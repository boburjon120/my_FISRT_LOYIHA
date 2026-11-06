"""SQLite storage (aiosqlite).

The database is the single source of truth for the processing queue, so
nothing is lost when the bot restarts: queued videos stay ``queued`` and
videos that were ``processing`` during a crash are put back in the queue.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import aiosqlite

from utils.timeutils import in_seconds, to_iso, utcnow

log = logging.getLogger(__name__)

# Video statuses
QUEUED = "queued"
PROCESSING = "processing"
PUBLISHED = "published"
FAILED = "failed"
SKIPPED = "skipped"

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    user_id         INTEGER PRIMARY KEY,
    username        TEXT,
    full_name       TEXT,
    language_code   TEXT,
    is_blocked      INTEGER NOT NULL DEFAULT 0,
    downloads_count INTEGER NOT NULL DEFAULT 0,
    created_at      TEXT NOT NULL,
    last_seen_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS source_channels (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    channel_id      TEXT NOT NULL UNIQUE,
    title           TEXT,
    url             TEXT,
    is_active       INTEGER NOT NULL DEFAULT 1,
    added_by        INTEGER,
    created_at      TEXT NOT NULL,
    last_checked_at TEXT,
    last_success_at TEXT,
    last_error      TEXT
);

CREATE TABLE IF NOT EXISTS processed_videos (
    video_id        TEXT PRIMARY KEY,
    channel_id      TEXT,
    title           TEXT,
    url             TEXT NOT NULL,
    thumbnail_url   TEXT,
    published_at    TEXT,
    status          TEXT NOT NULL,
    attempts        INTEGER NOT NULL DEFAULT 0,
    last_error      TEXT,
    next_attempt_at TEXT,
    detected_at     TEXT NOT NULL,
    updated_at      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_videos_status ON processed_videos(status, next_attempt_at);

CREATE TABLE IF NOT EXISTS download_jobs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    video_id    TEXT NOT NULL,
    kind        TEXT NOT NULL,          -- channel_mp3 | user_mp3 | user_mp4
    user_id     INTEGER,
    status      TEXT NOT NULL,          -- running | done | failed | interrupted
    error       TEXT,
    file_size   INTEGER,
    created_at  TEXT NOT NULL,
    finished_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_jobs_status ON download_jobs(status);

CREATE TABLE IF NOT EXISTS channel_posts (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    video_id    TEXT NOT NULL UNIQUE,
    chat_id     TEXT NOT NULL,
    message_id  INTEGER NOT NULL,
    posted_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS bot_statistics (
    key         TEXT PRIMARY KEY,
    value       INTEGER NOT NULL DEFAULT 0,
    updated_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS settings (
    key         TEXT PRIMARY KEY,
    value       TEXT,
    updated_at  TEXT NOT NULL
);
"""


@dataclass(frozen=True)
class SourceChannel:
    channel_id: str
    title: str | None
    url: str | None
    created_at: str
    last_checked_at: str | None
    last_success_at: str | None
    last_error: str | None


@dataclass(frozen=True)
class VideoRecord:
    video_id: str
    channel_id: str | None
    title: str | None
    url: str
    thumbnail_url: str | None
    published_at: str | None
    status: str
    attempts: int
    last_error: str | None
    next_attempt_at: str | None
    detected_at: str


class Database:
    def __init__(self, path: Path | str) -> None:
        self.path = Path(path) if str(path) != ":memory:" else path
        self._conn: aiosqlite.Connection | None = None

    # ------------------------------------------------------------------ setup
    async def connect(self) -> None:
        if isinstance(self.path, Path):
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = await aiosqlite.connect(str(self.path))
        self._conn.row_factory = aiosqlite.Row
        await self._conn.execute("PRAGMA journal_mode=WAL")
        await self._conn.execute("PRAGMA busy_timeout=5000")
        await self._conn.executescript(SCHEMA)
        await self._conn.commit()

    async def close(self) -> None:
        if self._conn is not None:
            await self._conn.close()
            self._conn = None

    @property
    def conn(self) -> aiosqlite.Connection:
        if self._conn is None:
            raise RuntimeError("Database is not connected")
        return self._conn

    async def _exec(self, sql: str, params: tuple[Any, ...] = ()) -> int:
        cur = await self.conn.execute(sql, params)
        await self.conn.commit()
        return cur.rowcount

    async def _one(self, sql: str, params: tuple[Any, ...] = ()) -> aiosqlite.Row | None:
        async with self.conn.execute(sql, params) as cur:
            return await cur.fetchone()

    async def _all(self, sql: str, params: tuple[Any, ...] = ()) -> list[aiosqlite.Row]:
        async with self.conn.execute(sql, params) as cur:
            return list(await cur.fetchall())

    # ------------------------------------------------------------------ users
    async def upsert_user(
        self, user_id: int, username: str | None, full_name: str | None, language_code: str | None
    ) -> None:
        now = to_iso(utcnow())
        await self._exec(
            """
            INSERT INTO users (user_id, username, full_name, language_code, created_at, last_seen_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                username=excluded.username, full_name=excluded.full_name,
                language_code=excluded.language_code, last_seen_at=excluded.last_seen_at
            """,
            (user_id, username, full_name, language_code, now, now),
        )

    async def increment_user_downloads(self, user_id: int) -> None:
        await self._exec(
            "UPDATE users SET downloads_count = downloads_count + 1 WHERE user_id = ?", (user_id,)
        )

    async def count_users(self) -> int:
        row = await self._one("SELECT COUNT(*) AS c FROM users")
        return int(row["c"]) if row else 0

    # --------------------------------------------------------------- settings
    async def get_setting(self, key: str, default: str | None = None) -> str | None:
        row = await self._one("SELECT value FROM settings WHERE key = ?", (key,))
        return row["value"] if row and row["value"] is not None else default

    async def set_setting(self, key: str, value: str | None) -> None:
        await self._exec(
            """
            INSERT INTO settings (key, value, updated_at) VALUES (?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at
            """,
            (key, value, to_iso(utcnow())),
        )

    # -------------------------------------------------------- source channels
    async def set_active_source(
        self, channel_id: str, title: str | None, url: str | None, added_by: int | None = None
    ) -> bool:
        """Make ``channel_id`` the only active source. Returns True if it is new."""
        existed = await self._one(
            "SELECT 1 FROM source_channels WHERE channel_id = ?", (channel_id,)
        )
        now = to_iso(utcnow())
        await self.conn.execute("UPDATE source_channels SET is_active = 0")
        await self.conn.execute(
            """
            INSERT INTO source_channels (channel_id, title, url, is_active, added_by, created_at)
            VALUES (?, ?, ?, 1, ?, ?)
            ON CONFLICT(channel_id) DO UPDATE SET
                title=COALESCE(excluded.title, source_channels.title),
                url=COALESCE(excluded.url, source_channels.url),
                is_active=1
            """,
            (channel_id, title, url, added_by, now),
        )
        await self.conn.commit()
        return existed is None

    async def get_active_source(self) -> SourceChannel | None:
        row = await self._one(
            """
            SELECT channel_id, title, url, created_at, last_checked_at, last_success_at, last_error
            FROM source_channels WHERE is_active = 1 ORDER BY id DESC LIMIT 1
            """
        )
        return SourceChannel(**dict(row)) if row else None

    async def update_source_check(
        self, channel_id: str, *, error: str | None, title: str | None = None
    ) -> None:
        now = to_iso(utcnow())
        if error is None:
            await self._exec(
                """
                UPDATE source_channels SET last_checked_at=?, last_success_at=?, last_error=NULL,
                    title=COALESCE(?, title)
                WHERE channel_id=?
                """,
                (now, now, title, channel_id),
            )
        else:
            await self._exec(
                "UPDATE source_channels SET last_checked_at=?, last_error=? WHERE channel_id=?",
                (now, error[:500], channel_id),
            )

    # ----------------------------------------------------------------- videos
    async def video_exists(self, video_id: str) -> bool:
        row = await self._one("SELECT 1 FROM processed_videos WHERE video_id = ?", (video_id,))
        return row is not None

    async def add_video(
        self,
        video_id: str,
        *,
        url: str,
        status: str = QUEUED,
        channel_id: str | None = None,
        title: str | None = None,
        thumbnail_url: str | None = None,
        published_at: str | None = None,
        last_error: str | None = None,
    ) -> bool:
        """Insert a video once. Returns False if the video ID is already known."""
        now = to_iso(utcnow())
        count = await self._exec(
            """
            INSERT OR IGNORE INTO processed_videos
                (video_id, channel_id, title, url, thumbnail_url, published_at, status,
                 last_error, next_attempt_at, detected_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                video_id, channel_id, title, url, thumbnail_url, published_at, status,
                last_error, now, now, now,
            ),
        )
        return count == 1

    async def get_video(self, video_id: str) -> VideoRecord | None:
        row = await self._one(
            """
            SELECT video_id, channel_id, title, url, thumbnail_url, published_at, status,
                   attempts, last_error, next_attempt_at, detected_at
            FROM processed_videos WHERE video_id = ?
            """,
            (video_id,),
        )
        return VideoRecord(**dict(row)) if row else None

    async def claim_next_video(self) -> VideoRecord | None:
        """Atomically move the oldest due queued video to ``processing``."""
        now = to_iso(utcnow())
        rows = await self._all(
            """
            SELECT video_id FROM processed_videos
            WHERE status = ? AND (next_attempt_at IS NULL OR next_attempt_at <= ?)
            ORDER BY COALESCE(published_at, detected_at) ASC
            LIMIT 5
            """,
            (QUEUED, now),
        )
        for row in rows:
            changed = await self._exec(
                "UPDATE processed_videos SET status=?, updated_at=? WHERE video_id=? AND status=?",
                (PROCESSING, now, row["video_id"], QUEUED),
            )
            if changed == 1:
                return await self.get_video(row["video_id"])
        return None

    async def next_due_time(self) -> str | None:
        row = await self._one(
            "SELECT MIN(next_attempt_at) AS t FROM processed_videos WHERE status = ?", (QUEUED,)
        )
        return row["t"] if row else None

    async def update_video_meta(
        self, video_id: str, *, title: str | None = None, published_at: str | None = None
    ) -> None:
        await self._exec(
            """
            UPDATE processed_videos SET title=COALESCE(?, title),
                published_at=COALESCE(published_at, ?), updated_at=? WHERE video_id=?
            """,
            (title, published_at, to_iso(utcnow()), video_id),
        )

    async def mark_video_published(self, video_id: str) -> None:
        await self._exec(
            "UPDATE processed_videos SET status=?, last_error=NULL, updated_at=? WHERE video_id=?",
            (PUBLISHED, to_iso(utcnow()), video_id),
        )

    async def mark_video_failed(self, video_id: str, error: str, *, count_attempt: bool = True) -> None:
        await self._exec(
            """
            UPDATE processed_videos SET status=?, last_error=?,
                attempts = attempts + ?, updated_at=? WHERE video_id=?
            """,
            (FAILED, error[:500], 1 if count_attempt else 0, to_iso(utcnow()), video_id),
        )

    async def reschedule_video(
        self, video_id: str, delay_seconds: float, error: str, *, count_attempt: bool = True
    ) -> None:
        await self._exec(
            """
            UPDATE processed_videos SET status=?, last_error=?, attempts = attempts + ?,
                next_attempt_at=?, updated_at=? WHERE video_id=?
            """,
            (
                QUEUED, error[:500], 1 if count_attempt else 0, in_seconds(delay_seconds),
                to_iso(utcnow()), video_id,
            ),
        )

    async def requeue_failed(self, video_id: str | None = None) -> int:
        now = to_iso(utcnow())
        if video_id:
            return await self._exec(
                """
                UPDATE processed_videos SET status=?, attempts=0, next_attempt_at=?, updated_at=?
                WHERE video_id=? AND status IN (?, ?)
                """,
                (QUEUED, now, now, video_id, FAILED, SKIPPED),
            )
        return await self._exec(
            "UPDATE processed_videos SET status=?, attempts=0, next_attempt_at=?, updated_at=? WHERE status=?",
            (QUEUED, now, now, FAILED),
        )

    async def recover_interrupted(self) -> int:
        """Called on startup: anything left ``processing`` is queued again."""
        now = to_iso(utcnow())
        count = await self._exec(
            "UPDATE processed_videos SET status=?, next_attempt_at=?, updated_at=? WHERE status=?",
            (QUEUED, now, now, PROCESSING),
        )
        await self._exec(
            "UPDATE download_jobs SET status='interrupted', finished_at=? WHERE status='running'",
            (now,),
        )
        return count

    async def video_status_counts(self) -> dict[str, int]:
        rows = await self._all(
            "SELECT status, COUNT(*) AS c FROM processed_videos GROUP BY status"
        )
        counts = {QUEUED: 0, PROCESSING: 0, PUBLISHED: 0, FAILED: 0, SKIPPED: 0}
        counts.update({row["status"]: int(row["c"]) for row in rows})
        return counts

    async def list_videos(self, statuses: tuple[str, ...], limit: int = 10) -> list[VideoRecord]:
        placeholders = ",".join("?" for _ in statuses)
        rows = await self._all(
            f"""
            SELECT video_id, channel_id, title, url, thumbnail_url, published_at, status,
                   attempts, last_error, next_attempt_at, detected_at
            FROM processed_videos WHERE status IN ({placeholders})
            ORDER BY updated_at DESC LIMIT ?
            """,
            (*statuses, limit),
        )
        return [VideoRecord(**dict(row)) for row in rows]

    # ------------------------------------------------------------------- jobs
    async def create_job(self, video_id: str, kind: str, user_id: int | None = None) -> int:
        cur = await self.conn.execute(
            "INSERT INTO download_jobs (video_id, kind, user_id, status, created_at) VALUES (?, ?, ?, 'running', ?)",
            (video_id, kind, user_id, to_iso(utcnow())),
        )
        await self.conn.commit()
        return int(cur.lastrowid or 0)

    async def finish_job(
        self, job_id: int, status: str, error: str | None = None, file_size: int | None = None
    ) -> None:
        await self._exec(
            "UPDATE download_jobs SET status=?, error=?, file_size=?, finished_at=? WHERE id=?",
            (status, (error or None) and error[:500], file_size, to_iso(utcnow()), job_id),
        )

    async def count_running_jobs(self) -> int:
        row = await self._one("SELECT COUNT(*) AS c FROM download_jobs WHERE status='running'")
        return int(row["c"]) if row else 0

    async def list_failed_jobs(self, limit: int = 10) -> list[aiosqlite.Row]:
        return await self._all(
            "SELECT id, video_id, kind, user_id, error, finished_at FROM download_jobs "
            "WHERE status='failed' ORDER BY id DESC LIMIT ?",
            (limit,),
        )

    # ---------------------------------------------------------- channel posts
    async def get_channel_post(self, video_id: str) -> aiosqlite.Row | None:
        return await self._one(
            "SELECT video_id, chat_id, message_id, posted_at FROM channel_posts WHERE video_id=?",
            (video_id,),
        )

    async def add_channel_post(self, video_id: str, chat_id: str, message_id: int) -> bool:
        count = await self._exec(
            "INSERT OR IGNORE INTO channel_posts (video_id, chat_id, message_id, posted_at) VALUES (?, ?, ?, ?)",
            (video_id, str(chat_id), message_id, to_iso(utcnow())),
        )
        return count == 1

    async def count_channel_posts(self) -> int:
        row = await self._one("SELECT COUNT(*) AS c FROM channel_posts")
        return int(row["c"]) if row else 0

    # ------------------------------------------------------------- statistics
    async def incr_stat(self, key: str, amount: int = 1) -> None:
        await self._exec(
            """
            INSERT INTO bot_statistics (key, value, updated_at) VALUES (?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET value = value + excluded.value, updated_at = excluded.updated_at
            """,
            (key, amount, to_iso(utcnow())),
        )

    async def get_stats(self) -> dict[str, int]:
        rows = await self._all("SELECT key, value FROM bot_statistics")
        return {row["key"]: int(row["value"]) for row in rows}
