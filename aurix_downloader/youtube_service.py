"""YouTube access: RSS feed monitoring, channel resolution and video metadata.

Access-control policy: the bot only processes public videos. Private,
members-only, premium, age-gated (sign-in required) and DRM protected
videos are rejected and never downloaded.
"""

from __future__ import annotations

import asyncio
import logging
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import aiohttp
import yt_dlp
from yt_dlp.utils import DownloadError, ExtractorError

from config import Settings
from utils.errors import NotReadyError, PermanentError, TransientError
from utils.timeutils import from_iso
from utils.validators import (
    CHANNEL_ID_RE,
    canonical_video_url,
    is_valid_video_id,
    parse_channel_input,
    thumbnail_url,
)

log = logging.getLogger(__name__)

FEED_URL = "https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"
NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "yt": "http://www.youtube.com/xml/schemas/2015",
    "media": "http://search.yahoo.com/mrss/",
}
HTTP_TIMEOUT = aiohttp.ClientTimeout(total=30, connect=10)
USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"
MAX_FEED_BYTES = 2 * 1024 * 1024

RESTRICTED_AVAILABILITY = {"private", "premium_only", "subscriber_only", "needs_auth"}

_PERMANENT_PATTERNS = (
    "private video",
    "video is private",
    "video unavailable",
    "has been removed",
    "account associated with this video has been terminated",
    "copyright",
    "not available in your country",
    "confirm your age",
    "age-restricted",
    "members-only",
    "join this channel",
    "requires payment",
    "drm",
    "unsupported url",
    "is not a valid url",
)
_NOT_READY_PATTERNS = (
    "premieres in",
    "live event will begin",
    "this live event",
    "is_upcoming",
    "will begin in",
)


@dataclass(frozen=True)
class FeedEntry:
    video_id: str
    title: str
    url: str
    published_at: datetime | None
    thumbnail_url: str
    channel_id: str


@dataclass(frozen=True)
class Feed:
    channel_id: str
    title: str
    entries: list[FeedEntry]


@dataclass(frozen=True)
class VideoInfo:
    video_id: str
    title: str
    url: str
    duration: int | None
    thumbnail_url: str
    uploader: str | None
    upload_date: datetime | None
    view_count: int | None = None


def parse_feed(xml_text: str | bytes, channel_id: str = "") -> Feed:
    """Parse a YouTube Atom feed into ``FeedEntry`` objects (newest first)."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        raise TransientError(f"RSS feed could not be parsed: {exc}") from exc
    feed_title = (root.findtext("atom:title", default="", namespaces=NS) or "").strip()
    entries: list[FeedEntry] = []
    for entry in root.findall("atom:entry", NS):
        video_id = (entry.findtext("yt:videoId", default="", namespaces=NS) or "").strip()
        if not is_valid_video_id(video_id):
            continue
        title = (entry.findtext("atom:title", default="", namespaces=NS) or "").strip()
        published = from_iso((entry.findtext("atom:published", default="", namespaces=NS) or "").strip())
        entry_channel = (entry.findtext("yt:channelId", default="", namespaces=NS) or "").strip()
        entries.append(
            FeedEntry(
                video_id=video_id,
                title=title or video_id,
                url=canonical_video_url(video_id),
                published_at=published,
                thumbnail_url=thumbnail_url(video_id),
                channel_id=entry_channel or channel_id,
            )
        )
    return Feed(channel_id=channel_id, title=feed_title, entries=entries)


def classify_ytdlp_error(exc: BaseException) -> Exception:
    """Map a yt-dlp exception to Permanent/NotReady/Transient errors."""
    text = str(exc)
    lower = text.lower()
    short = re.sub(r"\s+", " ", re.sub(r"^ERROR:\s*", "", text)).strip()[:300]
    if any(p in lower for p in _NOT_READY_PATTERNS):
        return NotReadyError(short)
    if "not a bot" in lower or "429" in lower or "too many requests" in lower:
        return TransientError(short, user_message="YouTube vaqtincha so'rovlarni chekladi. Keyinroq urinib ko'ring.")
    if any(p in lower for p in _PERMANENT_PATTERNS):
        return PermanentError(
            short, user_message="Bu video mavjud emas, yopiq yoki cheklangan — yuklab bo'lmaydi."
        )
    return TransientError(short)


class YouTubeService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._session: aiohttp.ClientSession | None = None

    # ------------------------------------------------------------- lifecycle
    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=HTTP_TIMEOUT,
                headers={"User-Agent": USER_AGENT, "Accept-Language": "en-US,en;q=0.8"},
                trust_env=True,
            )
        return self._session

    async def close(self) -> None:
        if self._session is not None and not self._session.closed:
            await self._session.close()

    # ------------------------------------------------------------------- HTTP
    async def _get_text(self, url: str, *, max_bytes: int = MAX_FEED_BYTES) -> tuple[int, str]:
        session = await self._get_session()
        try:
            async with session.get(url, allow_redirects=True, max_redirects=3) as resp:
                host = resp.url.host or ""
                if not (host == "youtube.com" or host.endswith(".youtube.com")):
                    raise TransientError(f"unexpected redirect to {host}")
                body = await resp.content.read(max_bytes + 1)
                if len(body) > max_bytes:
                    raise TransientError("response too large")
                return resp.status, body.decode("utf-8", errors="replace")
        except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
            raise TransientError(f"network error: {exc.__class__.__name__}: {exc}") from exc

    async def fetch_feed(self, channel_id: str) -> Feed:
        if not CHANNEL_ID_RE.match(channel_id):
            raise PermanentError(f"invalid channel id {channel_id!r}")
        status, text = await self._get_text(FEED_URL.format(channel_id=channel_id))
        if status == 404:
            raise PermanentError("RSS feed not found (404). Kanal ID sini tekshiring.")
        if status >= 500 or status == 429:
            raise TransientError(f"YouTube RSS HTTP {status}")
        if status != 200:
            raise TransientError(f"YouTube RSS HTTP {status}")
        return parse_feed(text, channel_id)

    async def resolve_channel(self, value: str) -> tuple[str, str]:
        """Return ``(channel_id, title)`` for a channel ID, URL or @handle."""
        parsed = parse_channel_input(value)
        if parsed is None:
            raise PermanentError(
                "invalid channel input",
                user_message="Kanal manzili noto'g'ri. Masalan: https://www.youtube.com/@kanal "
                "yoki UC... bilan boshlanadigan kanal ID.",
            )
        kind, data = parsed
        if kind == "id":
            channel_id = data
        else:
            status, html_text = await self._get_text(data)
            if status == 404:
                raise PermanentError("channel page 404", user_message="Bunday YouTube kanal topilmadi.")
            if status != 200:
                raise TransientError(f"channel page HTTP {status}")
            match = (
                re.search(r'"externalId":"(UC[A-Za-z0-9_-]{22})"', html_text)
                or re.search(r'<meta itemprop="identifier" content="(UC[A-Za-z0-9_-]{22})"', html_text)
                or re.search(r'rel="canonical" href="https://www\.youtube\.com/channel/(UC[A-Za-z0-9_-]{22})"', html_text)
            )
            if match:
                channel_id = match.group(1)
            else:
                channel_id = await asyncio.to_thread(self._resolve_with_ytdlp, data)
        feed = await self.fetch_feed(channel_id)
        return channel_id, feed.title or channel_id

    def _resolve_with_ytdlp(self, url: str) -> str:
        opts = self.base_opts() | {"extract_flat": True, "playlist_items": "1"}
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=False) or {}
        except (DownloadError, ExtractorError) as exc:
            raise classify_ytdlp_error(exc) from exc
        channel_id = info.get("channel_id") or info.get("uploader_id") or ""
        if not CHANNEL_ID_RE.match(channel_id):
            raise PermanentError("channel id not found", user_message="Kanal ID sini aniqlab bo'lmadi.")
        return channel_id

    # ----------------------------------------------------------------- yt-dlp
    def base_opts(self) -> dict[str, Any]:
        opts: dict[str, Any] = {
            "quiet": True,
            "no_warnings": True,
            "noplaylist": True,
            "socket_timeout": 30,
            "retries": 3,
            "fragment_retries": 3,
            "extractor_retries": 2,
            "noprogress": True,
            "logger": logging.getLogger("yt_dlp"),
            "allow_unplayable_formats": False,
            "check_formats": False,
        }
        if self.settings.ytdlp_cookies_file:
            opts["cookiefile"] = self.settings.ytdlp_cookies_file
        return opts

    def extract_info_sync(self, video_id: str) -> dict[str, Any]:
        url = canonical_video_url(video_id)
        try:
            with yt_dlp.YoutubeDL(self.base_opts()) as ydl:
                info = ydl.extract_info(url, download=False)
        except (DownloadError, ExtractorError) as exc:
            raise classify_ytdlp_error(exc) from exc
        if not info:
            raise TransientError("empty metadata from yt-dlp")
        self.ensure_allowed(info)
        return info

    @staticmethod
    def ensure_allowed(info: dict[str, Any]) -> None:
        """Enforce the access-control policy on yt-dlp metadata."""
        availability = info.get("availability")
        if availability in RESTRICTED_AVAILABILITY:
            raise PermanentError(
                f"video availability is {availability}",
                user_message="Bu video yopiq yoki faqat obunachilar uchun — yuklab bo'lmaydi.",
            )
        if (info.get("age_limit") or 0) >= 18:
            raise PermanentError(
                "age restricted video", user_message="Yosh cheklovi bor videolarni yuklab bo'lmaydi."
            )
        live_status = info.get("live_status")
        if live_status == "is_upcoming":
            raise NotReadyError("video is an upcoming premiere/live")
        if live_status in {"is_live", "post_live"} or info.get("is_live"):
            raise NotReadyError("live stream is still in progress")
        formats = info.get("formats") or []
        if formats and all(f.get("has_drm") for f in formats):
            raise PermanentError("DRM protected", user_message="Video DRM bilan himoyalangan.")

    @staticmethod
    def to_video_info(info: dict[str, Any]) -> VideoInfo:
        video_id = info.get("id") or ""
        upload_date = None
        raw_date = info.get("upload_date")
        ts = info.get("release_timestamp") or info.get("timestamp")
        if ts:
            upload_date = datetime.fromtimestamp(int(ts), tz=UTC)
        elif raw_date and len(raw_date) == 8:
            upload_date = from_iso(f"{raw_date[:4]}-{raw_date[4:6]}-{raw_date[6:]}T00:00:00+00:00")
        return VideoInfo(
            video_id=video_id,
            title=(info.get("title") or video_id).strip(),
            url=canonical_video_url(video_id),
            duration=int(info["duration"]) if info.get("duration") else None,
            thumbnail_url=thumbnail_url(video_id),
            uploader=info.get("uploader") or info.get("channel"),
            upload_date=upload_date,
            view_count=info.get("view_count"),
        )

    async def get_video_info(self, video_id: str) -> tuple[VideoInfo, dict[str, Any]]:
        if not is_valid_video_id(video_id):
            raise PermanentError("invalid video id", user_message="YouTube havolasi noto'g'ri.")
        raw = await asyncio.to_thread(self.extract_info_sync, video_id)
        return self.to_video_info(raw), raw

    async def download_thumbnail(self, video_id: str, dest) -> bool:
        """Download the video thumbnail from i.ytimg.com (fixed host)."""
        session = await self._get_session()
        for quality in ("maxresdefault", "hqdefault"):
            url = f"https://i.ytimg.com/vi/{video_id}/{quality}.jpg"
            try:
                async with session.get(url, allow_redirects=False) as resp:
                    if resp.status != 200:
                        continue
                    data = await resp.content.read(5 * 1024 * 1024 + 1)
                    if not data or len(data) > 5 * 1024 * 1024:
                        continue
                    dest.write_bytes(data)
                    return True
            except (aiohttp.ClientError, asyncio.TimeoutError, OSError) as exc:
                log.debug("thumbnail %s failed: %s", url, exc)
        return False
