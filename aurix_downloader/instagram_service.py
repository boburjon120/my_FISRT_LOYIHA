"""Instagram (public posts / reels / IGTV) metadata via yt-dlp.

Only public content is supported. Private accounts, stories and anything
that requires login are rejected unless the operator configured cookies of
their own account (INSTAGRAM_COOKIES_FILE); even then private content of
accounts the operator does not follow is not accessible.
"""

from __future__ import annotations

import asyncio
import logging
import re
from datetime import UTC, datetime
from typing import Any

import yt_dlp
from yt_dlp.utils import DownloadError, ExtractorError

from utils.errors import PermanentError, TransientError
from utils.text import truncate
from utils.validators import canonical_instagram_url, is_valid_instagram_code
from youtube_service import VideoInfo, YouTubeService

log = logging.getLogger(__name__)

_LOGIN_PATTERNS = (
    "login required", "log in", "login_required", "private", "checkpoint",
    "not available", "restricted", "unable to extract shared data",
)
_RATE_PATTERNS = ("rate-limit", "rate limit", "429", "too many requests", "please wait a few minutes")


def classify_instagram_error(exc: BaseException) -> Exception:
    text = str(exc)
    lower = text.lower()
    short = re.sub(r"\s+", " ", re.sub(r"^ERROR:\s*", "", text)).strip()[:300]
    if any(p in lower for p in _RATE_PATTERNS):
        return TransientError(short, user_message="Instagram vaqtincha so'rovlarni chekladi. Keyinroq urinib ko'ring.")
    if any(p in lower for p in _LOGIN_PATTERNS):
        return PermanentError(
            short,
            user_message="Bu post yopiq, o'chirilgan yoki Instagram kirishni (login) talab qilyapti — yuklab bo'lmaydi.",
        )
    if "no video formats" in lower or "there is no video" in lower:
        return PermanentError(short, user_message="Bu postda video yo'q (faqat rasm).")
    return TransientError(short, user_message="Instagram'dan ma'lumot olib bo'lmadi. Keyinroq urinib ko'ring.")


def _is_video(entry: dict[str, Any]) -> bool:
    if entry.get("vcodec") not in (None, "none"):
        return True
    return any(f.get("vcodec") not in (None, "none") for f in entry.get("formats") or [])


def pick_video_entry(info: dict[str, Any]) -> dict[str, Any]:
    """Carousel posts are playlists: take the first video in them."""
    if info.get("_type") in {"playlist", "multi_video"}:
        for entry in info.get("entries") or []:
            if entry and _is_video(entry):
                merged = dict(entry)
                for key in ("uploader", "channel", "description", "timestamp", "title"):
                    merged.setdefault(key, info.get(key))
                return merged
        raise PermanentError("carousel without video", user_message="Bu postda video yo'q (faqat rasm).")
    if not _is_video(info) and info.get("formats") is not None:
        raise PermanentError("no video", user_message="Bu postda video yo'q (faqat rasm).")
    return info


def _title(info: dict[str, Any], code: str) -> str:
    description = (info.get("description") or "").strip()
    title = (info.get("title") or "").strip()
    generic = not title or title.lower().startswith(("video by", "post by")) or title == code
    if generic and description:
        first = description.splitlines()[0].strip()
        if first:
            return truncate(first, 80)
    if title:
        return truncate(title, 80)
    uploader = info.get("uploader") or info.get("channel")
    return f"Instagram — {uploader}" if uploader else f"Instagram {code}"


class InstagramService(YouTubeService):
    """Reuses the yt-dlp option handling of YouTubeService with Instagram cookies."""

    cookies_setting = "instagram_cookies_file"
    cookies_runtime_name = "instagram_cookies.runtime.txt"

    def extract_info_sync(self, code: str) -> dict[str, Any]:  # type: ignore[override]
        url = canonical_instagram_url(code)
        opts = self.base_opts() | {"noplaylist": False}
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=False)
        except (DownloadError, ExtractorError) as exc:
            raise classify_instagram_error(exc) from exc
        if not info:
            raise TransientError("empty metadata from yt-dlp")
        info = pick_video_entry(info)
        if info.get("is_live") or info.get("live_status") in {"is_live", "is_upcoming"}:
            raise PermanentError("live", user_message="Jonli efirlarni yuklab bo'lmaydi.")
        return info

    @staticmethod
    def to_video_info(info: dict[str, Any], code: str) -> VideoInfo:  # type: ignore[override]
        ts = info.get("timestamp")
        thumb = info.get("thumbnail") or ""
        return VideoInfo(
            video_id=code,
            title=_title(info, code),
            url=canonical_instagram_url(code),
            duration=int(info["duration"]) if info.get("duration") else None,
            # Only passed to Telegram as a photo URL; the server never fetches it.
            thumbnail_url=thumb if thumb.startswith("https://") else "",
            uploader=info.get("uploader") or info.get("channel") or info.get("uploader_id"),
            upload_date=datetime.fromtimestamp(int(ts), tz=UTC) if ts else None,
            view_count=info.get("view_count"),
            platform="instagram",
        )

    async def get_video_info(self, code: str) -> tuple[VideoInfo, dict[str, Any]]:  # type: ignore[override]
        if not is_valid_instagram_code(code):
            raise PermanentError("invalid code", user_message="Instagram havolasi noto'g'ri.")
        raw = await asyncio.to_thread(self.extract_info_sync, code)
        return self.to_video_info(raw, code), raw

    async def download_thumbnail(self, video_id, dest) -> bool:
        return False
