"""Formatting helpers for Telegram messages and file names."""

from __future__ import annotations

import html
import re
import unicodedata

CAPTION_LIMIT = 1024
_FORBIDDEN_FS_CHARS = re.compile(r'[\\/:*?"<>|\x00-\x1f\x7f]')


def esc(value: object) -> str:
    return html.escape(str(value or ""), quote=True)


def truncate(value: str, limit: int) -> str:
    value = value.strip()
    return value if len(value) <= limit else value[: max(0, limit - 1)].rstrip() + "…"


def format_duration(seconds: int | float | None) -> str:
    if not seconds:
        return "—"
    seconds = int(seconds)
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes}:{secs:02d}"


def format_size(num_bytes: int | None) -> str:
    if not num_bytes:
        return "—"
    size = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.1f} {unit}" if unit != "B" else f"{int(size)} B"
        size /= 1024
    return f"{size:.1f} GB"


def safe_filename(title: str, ext: str, max_length: int = 120) -> str:
    """Keep the original title readable but safe for every filesystem."""
    name = unicodedata.normalize("NFC", title or "")
    name = _FORBIDDEN_FS_CHARS.sub(" ", name)
    name = re.sub(r"\s+", " ", name).strip(" .")
    if not name:
        name = "audio"
    name = name[:max_length].rstrip(" .")
    return f"{name}.{ext.lstrip('.')}"
