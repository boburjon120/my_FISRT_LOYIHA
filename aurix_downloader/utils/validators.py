"""Strict YouTube URL / ID validation.

Only canonical URLs rebuilt from a validated video ID are ever passed to
yt-dlp, so user input can never make the server request an arbitrary host
(SSRF protection).
"""

from __future__ import annotations

import re
from urllib.parse import parse_qs, urlsplit

VIDEO_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")
CHANNEL_ID_RE = re.compile(r"^UC[A-Za-z0-9_-]{22}$")
HANDLE_RE = re.compile(r"^@[A-Za-z0-9._-]{3,30}$")
TELEGRAM_CHAT_RE = re.compile(r"^(-100\d{5,15}|-?\d{5,15}|@[A-Za-z][A-Za-z0-9_]{3,31})$")

YOUTUBE_HOSTS = frozenset(
    {
        "youtube.com",
        "www.youtube.com",
        "m.youtube.com",
        "music.youtube.com",
        "youtube-nocookie.com",
        "www.youtube-nocookie.com",
    }
)
SHORT_HOSTS = frozenset({"youtu.be", "www.youtu.be"})
MAX_URL_LENGTH = 300


def is_valid_video_id(value: str | None) -> bool:
    return bool(value) and bool(VIDEO_ID_RE.match(value))  # type: ignore[arg-type]


def canonical_video_url(video_id: str) -> str:
    if not is_valid_video_id(video_id):
        raise ValueError("invalid video id")
    return f"https://www.youtube.com/watch?v={video_id}"


def thumbnail_url(video_id: str) -> str:
    if not is_valid_video_id(video_id):
        raise ValueError("invalid video id")
    return f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg"


def _split(url: str):
    url = url.strip()
    if not url or len(url) > MAX_URL_LENGTH or any(c.isspace() for c in url):
        return None
    if "://" not in url:
        url = "https://" + url
    try:
        parts = urlsplit(url)
        port = parts.port  # raises ValueError on garbage ports
    except ValueError:
        return None
    if parts.scheme not in {"http", "https"}:
        return None
    if parts.username or parts.password or port not in {None, 80, 443}:
        return None
    return parts


def extract_video_id(url: str | None) -> str | None:
    """Return the 11-char video ID for a YouTube video URL, else ``None``."""
    if not url:
        return None
    parts = _split(url)
    if parts is None:
        return None
    host = (parts.hostname or "").lower()
    path = parts.path

    candidate: str | None = None
    if host in SHORT_HOSTS:
        candidate = path.lstrip("/").split("/")[0]
    elif host in YOUTUBE_HOSTS:
        if path in {"/watch", "/watch/"}:
            candidate = (parse_qs(parts.query).get("v") or [None])[0]
        else:
            segments = [s for s in path.split("/") if s]
            if len(segments) >= 2 and segments[0] in {"shorts", "embed", "live", "v", "e"}:
                candidate = segments[1]
    return candidate if is_valid_video_id(candidate) else None


def find_youtube_url(text: str | None) -> str | None:
    """Find the first YouTube video ID in free text."""
    if not text:
        return None
    for token in text.split():
        video_id = extract_video_id(token.strip("<>()[]{}\"',"))
        if video_id:
            return video_id
    return None


def parse_channel_input(value: str) -> tuple[str, str] | None:
    """Classify admin input for the source channel.

    Returns ``("id", "UC...")`` when the channel ID is known directly, or
    ``("url", canonical_url)`` when it must be resolved (handle, /c/, /user/).
    """
    value = (value or "").strip()
    if CHANNEL_ID_RE.match(value):
        return ("id", value)
    if HANDLE_RE.match(value):
        return ("url", f"https://www.youtube.com/{value}")
    parts = _split(value)
    if parts is None or (parts.hostname or "").lower() not in YOUTUBE_HOSTS:
        return None
    segments = [s for s in parts.path.split("/") if s]
    if not segments:
        return None
    first = segments[0]
    if first == "channel" and len(segments) >= 2 and CHANNEL_ID_RE.match(segments[1]):
        return ("id", segments[1])
    if HANDLE_RE.match(first):
        return ("url", f"https://www.youtube.com/{first}")
    if first in {"c", "user"} and len(segments) >= 2 and re.match(r"^[A-Za-z0-9._-]{1,100}$", segments[1]):
        return ("url", f"https://www.youtube.com/{first}/{segments[1]}")
    return None


def normalize_telegram_chat(value: str) -> str | None:
    value = (value or "").strip()
    if value.startswith("https://t.me/") or value.startswith("t.me/"):
        name = value.split("t.me/", 1)[1].strip("/")
        value = f"@{name}"
    return value if TELEGRAM_CHAT_RE.match(value) else None
