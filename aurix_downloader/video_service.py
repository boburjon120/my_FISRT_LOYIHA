"""MP4 downloads for Telegram users (respecting the upload limit)."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yt_dlp
from yt_dlp.utils import DownloadError, ExtractorError

from audio_service import run_process
from config import Settings
from utils.errors import FileTooLargeError, PermanentError, TransientError
from utils.text import safe_filename
from youtube_service import VideoInfo, YouTubeService, classify_ytdlp_error

log = logging.getLogger(__name__)

HEIGHTS = (720, 480, 360, 240)


@dataclass(frozen=True)
class VideoResult:
    path: Path
    filename: str
    size: int
    height: int
    duration: int | None
    width: int | None = None
    video_height: int | None = None


async def probe_dimensions(path: Path) -> tuple[int | None, int | None]:
    code, out = await run_process(
        "ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height",
        "-of", "csv=s=x:p=0", str(path), timeout=60,
    )
    try:
        width, height = out.strip().splitlines()[0].split("x")[:2]
        return int(width), int(height)
    except (ValueError, IndexError):
        return None, None


def format_for_height(height: int) -> str:
    return (
        f"bv*[height<={height}][ext=mp4][vcodec^=avc1]+ba[ext=m4a]/"
        f"bv*[height<={height}][ext=mp4]+ba[ext=m4a]/"
        f"b[height<={height}][ext=mp4]/"
        f"bv*[height<={height}]+ba/b[height<={height}]"
    )


def _format_size(fmt: dict[str, Any], duration: float | None) -> float | None:
    size = fmt.get("filesize") or fmt.get("filesize_approx")
    if size:
        return float(size)
    if fmt.get("tbr") and duration:
        return float(fmt["tbr"]) * 1000 / 8 * duration
    return None


def estimate_size(formats: list[dict[str, Any]], height: int, duration: float | None) -> float | None:
    """Rough size estimate for the best mp4 video <= height plus best m4a audio."""
    videos = [
        f for f in formats
        if f.get("vcodec") not in (None, "none") and (f.get("height") or 0) <= height
        and f.get("ext") == "mp4" and not f.get("has_drm")
    ]
    audios = [
        f for f in formats
        if f.get("vcodec") == "none" and f.get("acodec") not in (None, "none") and f.get("ext") == "m4a"
    ]
    if not videos:
        return None
    video = max(videos, key=lambda f: ((f.get("height") or 0), f.get("tbr") or 0))
    vsize = _format_size(video, duration)
    if vsize is None:
        return None
    if video.get("acodec") not in (None, "none") or not audios:
        return vsize
    audio = max(audios, key=lambda f: f.get("abr") or f.get("tbr") or 0)
    return vsize + (_format_size(audio, duration) or 0)


class VideoService:
    def __init__(self, settings: Settings, youtube: YouTubeService) -> None:
        self.settings = settings
        self.youtube = youtube

    def _download_sync(self, raw_info: dict[str, Any], workdir: Path, height: int) -> Path:
        opts = self.youtube.base_opts() | {
            "format": format_for_height(height),
            "merge_output_format": "mp4",
            "outtmpl": {"default": str(workdir / f"video_{height}.%(ext)s")},
            "max_filesize": self.settings.upload_limit_bytes * 2,
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
        files = sorted(workdir.glob(f"video_{height}.*"))
        files = [f for f in files if f.suffix not in {".part", ".ytdl"}]
        if not files:
            raise TransientError("downloaded video not found")
        return files[0]

    async def create_mp4(
        self, info: VideoInfo, raw_info: dict[str, Any], workdir: Path, *, max_duration_minutes: int
    ) -> VideoResult:
        if info.duration and info.duration > max_duration_minutes * 60:
            raise PermanentError(
                "video too long", user_message=f"Video juda uzun (maksimal {max_duration_minutes} daqiqa)."
            )
        workdir.mkdir(parents=True, exist_ok=True)
        limit = self.settings.upload_limit_bytes
        formats = raw_info.get("formats") or []
        for height in HEIGHTS:
            estimate = estimate_size(formats, height, info.duration)
            if estimate is not None and estimate > limit * 1.05:
                log.info("skip %sp for %s: estimated %.1f MB", height, info.video_id, estimate / 1e6)
                continue
            path = await asyncio.to_thread(self._download_sync, raw_info, workdir, height)
            size = path.stat().st_size
            if size <= limit:
                final = workdir / safe_filename(info.title, "mp4")
                path.rename(final)
                w, h = await probe_dimensions(final)
                return VideoResult(final, final.name, size, height, info.duration, w, h)
            log.info("%sp for %s is %.1f MB > limit, trying lower", height, info.video_id, size / 1e6)
            path.unlink(missing_ok=True)
        raise FileTooLargeError(
            "video exceeds upload limit at every quality",
            user_message=f"Video {self.settings.upload_limit_mb} MB dan katta. "
            "MP3 variantini tanlab ko'ring.",
        )
