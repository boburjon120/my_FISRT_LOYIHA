"""UTC time helpers. All timestamps are stored as ISO-8601 UTC strings."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta


def utcnow() -> datetime:
    return datetime.now(UTC)


def to_iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC).isoformat(timespec="seconds")


def from_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def in_seconds(seconds: float) -> str:
    return to_iso(utcnow() + timedelta(seconds=seconds))  # type: ignore[return-value]


# Uzbekistan time (UTC+5, no DST) for human readable dates.
UZ_OFFSET = timedelta(hours=5)


def human_date(dt: datetime | str | None) -> str:
    if isinstance(dt, str):
        dt = from_iso(dt)
    if dt is None:
        return "—"
    local = dt.astimezone(UTC) + UZ_OFFSET
    return local.strftime("%d.%m.%Y %H:%M")
