"""Audio extraction (yt-dlp) and MP3 conversion (FFmpeg)."""

from __future__ import annotations

import asyncio
import logging
import math
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yt_dlp
from yt_dlp.utils import DownloadError, ExtractorError

from config import Settings
from utils.errors import FileTooLargeError, PermanentError, TransientError
from utils.text import safe_filename
from youtube_service import VideoInfo, YouTubeService, classify_ytdlp_error

log = logging.getLogger(__name__)

FFMPEG_TIMEOUT = 60 * 60  # 1 hour safety net for very long audio
SOURCE_MAX_BYTES = 2 * 1024 * 1024 * 1024  # never download more than 2 GB


@dataclass(frozen=True)
class AudioResult:
    path: Path
    filename: str
    size: int
    duration: int | None
    bitrate_kbps: int
    thumbnail: Path | None


def ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None


async def run_process(*args: str, timeout: float = FFMPEG_TIMEOUT) -> tuple[int, str]:
    proc = await asyncio.create_subprocess_exec(
        *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        raise TransientError(f"{args[0]} timed out")
    except asyncio.CancelledError:
        proc.kill()
        await proc.wait()
        raise
    output = (stdout or b"").decode(errors="replace") + (stderr or b"").decode(errors="replace")
    return proc.returncode or 0, output


async def probe_duration(path: Path) -> float | None:
    code, out = await run_process(
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1", str(path), timeout=60,
    )
    if code != 0:
        return None
    try:
        return float(out.strip().splitlines()[0])
    except (ValueError, IndexError):
        return None


async def convert_to_mp3(
    source: Path,
    target: Path,
    *,
    bitrate_kbps: int = 192,
    title: str | None = None,
    artist: str | None = None,
    comment: str | None = None,
    cover: Path | None = None,
) -> Path:
    """Convert any audio/video file to a CBR MP3 using FFmpeg."""
    if not source.exists():
        raise TransientError("source file is missing")
    args = ["ffmpeg", "-hide_banner", "-nostdin", "-y", "-i", str(source)]
    if cover is not None and cover.exists():
        args += ["-i", str(cover), "-map", "0:a:0", "-map", "1:v:0", "-c:v", "mjpeg",
                 "-disposition:v:0", "attached_pic",
                 "-metadata:s:v", "title=Album cover", "-metadata:s:v", "comment=Cover (front)"]
    else:
        args += ["-map", "0:a:0", "-vn"]
    args += ["-c:a", "libmp3lame", "-b:a", f"{bitrate_kbps}k", "-ar", "44100", "-id3v2_version", "3"]
    for key, value in (("title", title), ("artist", artist), ("comment", comment)):
        if value:
            args += ["-metadata", f"{key}={value[:250]}"]
    args.append(str(target))
    code, output = await run_process(*args)
    if code != 0 or not target.exists() or target.stat().st_size == 0:
        log.warning("ffmpeg failed (%s): %s", code, output[-800:])
        if cover is not None:
            # Retry without cover art - a broken thumbnail must not block the audio.
            return await convert_to_mp3(
                source, target, bitrate_kbps=bitrate_kbps, title=title, artist=artist, comment=comment
            )
        raise TransientError("MP3 conversion failed")
    return target


async def make_telegram_thumbnail(source: Path, target: Path) -> Path | None:
    """Telegram wants a JPEG <= 320px and < 200 KB as audio thumbnail."""
    code, _ = await run_process(
        "ffmpeg", "-hide_banner", "-nostdin", "-y", "-i", str(source),
        "-vf", "scale=320:320:force_original_aspect_ratio=increase,crop=320:320",
        "-q:v", "5", "-frames:v", "1", str(target), timeout=60,
    )
    if code == 0 and target.exists() and 0 < target.stat().st_size < 200 * 1024:
        return target
    return None


def fitting_bitrate(duration: float | None, limit_bytes: int, preferred: int, minimum: int) -> int | None:
    """Return the highest bitrate (kbps) whose MP3 fits ``limit_bytes``."""
    if not duration:
        return preferred
    # 3% headroom for ID3 tags / cover art.
    max_kbps = math.floor(limit_bytes * 0.97 * 8 / duration / 1000)
    if max_kbps >= preferred:
        return preferred
    for candidate in (160, 128, 112, 96, 80, 64, 48, 32):
        if candidate < minimum:
            break
        if candidate <= max_kbps:
            return candidate
    return None


class AudioService:
    def __init__(self, settings: Settings, youtube: YouTubeService) -> None:
        self.settings = settings
        self.youtube = youtube

    def _download_source_sync(self, raw_info: dict[str, Any], workdir: Path) -> Path:
        opts = self.youtube.base_opts() | {
            "format": "bestaudio/best",
            "outtmpl": {"default": str(workdir / "source.%(ext)s")},
            "max_filesize": SOURCE_MAX_BYTES,
            "postprocessors": [],
            "writethumbnail": False,
        }
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                result = ydl.process_ie_result(ydl.sanitize_info(raw_info, remove_private_keys=True), download=True)
        except (DownloadError, ExtractorError) as exc:
            raise classify_ytdlp_error(exc) from exc
        for item in (result or {}).get("requested_downloads") or []:
            path = Path(item.get("filepath") or "")
            if path.is_file():
                return path
        candidates = sorted(p for p in workdir.glob("source.*") if p.suffix != ".part")
        if not candidates:
            raise TransientError("downloaded audio file not found")
        return candidates[0]

    async def create_mp3(
        self, info: VideoInfo, raw_info: dict[str, Any], workdir: Path, *, max_duration_minutes: int
    ) -> AudioResult:
        if info.duration and info.duration > max_duration_minutes * 60:
            raise PermanentError(
                f"video too long ({info.duration}s)",
                user_message=f"Video juda uzun (maksimal {max_duration_minutes} daqiqa).",
            )
        workdir.mkdir(parents=True, exist_ok=True)
        source = await asyncio.to_thread(self._download_source_sync, raw_info, workdir)

        duration = float(info.duration) if info.duration else await probe_duration(source)
        limit = self.settings.upload_limit_bytes
        bitrate = fitting_bitrate(
            duration, limit, self.settings.audio_bitrate_kbps, self.settings.min_audio_bitrate_kbps
        )
        if bitrate is None:
            raise FileTooLargeError(f"audio would exceed {self.settings.upload_limit_mb} MB")

        cover_src = workdir / "cover_src.jpg"
        cover = cover_src if await self.youtube.download_thumbnail(info.video_id, cover_src) else None
        thumb = await make_telegram_thumbnail(cover, workdir / "thumb.jpg") if cover else None

        filename = safe_filename(info.title, "mp3")
        target = workdir / filename
        await convert_to_mp3(
            source, target, bitrate_kbps=bitrate, title=info.title,
            artist=info.uploader, comment=info.url, cover=cover,
        )
        size = target.stat().st_size
        if size > limit:
            # Cover art or VBR overhead pushed us over the limit: retry lower once.
            lower = fitting_bitrate(duration, int(limit * 0.9), bitrate - 32, self.settings.min_audio_bitrate_kbps)
            if lower is None or lower >= bitrate:
                raise FileTooLargeError("mp3 exceeds Telegram upload limit")
            await convert_to_mp3(
                source, target, bitrate_kbps=lower, title=info.title,
                artist=info.uploader, comment=info.url, cover=None,
            )
            bitrate, size = lower, target.stat().st_size
            if size > limit:
                raise FileTooLargeError("mp3 exceeds Telegram upload limit")
        source.unlink(missing_ok=True)
        return AudioResult(
            path=target,
            filename=filename,
            size=size,
            duration=int(duration) if duration else None,
            bitrate_kbps=bitrate,
            thumbnail=thumb,
        )
