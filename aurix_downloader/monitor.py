"""Background YouTube channel monitor (RSS based).

Every ``CHECK_INTERVAL_SECONDS`` (default 5 minutes) the active source
channel's RSS feed is fetched. Unknown videos published within the lookback
window are added to the persistent queue; known video IDs are ignored, so a
video is never processed twice.
"""

from __future__ import annotations

import asyncio
import logging
import random
from dataclasses import dataclass, field
from datetime import timedelta

from config import Settings
from database import QUEUED, SKIPPED, Database, SourceChannel
from utils.errors import PermanentError, TransientError
from utils.timeutils import to_iso, utcnow
from youtube_service import Feed, YouTubeService

log = logging.getLogger(__name__)

BASELINE_KEY = "baseline_done:{channel_id}"


@dataclass
class CheckResult:
    channel_id: str
    channel_title: str
    total_entries: int = 0
    queued: list[str] = field(default_factory=list)
    skipped_old: list[str] = field(default_factory=list)
    duplicates: int = 0
    baseline: bool = False


@dataclass
class MonitorStatus:
    running: bool = False
    last_check_at: str | None = None
    last_success_at: str | None = None
    last_error: str | None = None
    next_check_at: str | None = None
    checks: int = 0
    consecutive_failures: int = 0


class ChannelMonitor:
    def __init__(self, settings: Settings, db: Database, youtube: YouTubeService, on_new_videos=None) -> None:
        self.settings = settings
        self.db = db
        self.youtube = youtube
        self.on_new_videos = on_new_videos  # callable() -> None, e.g. QueueWorker.wake
        self.status = MonitorStatus()
        self._task: asyncio.Task | None = None
        self._trigger = asyncio.Event()
        self._check_lock = asyncio.Lock()
        self._stopping = False

    # -------------------------------------------------------------- lifecycle
    def start(self) -> None:
        if self.is_running:
            return
        self._stopping = False
        self._task = asyncio.create_task(self._run(), name="aurix-channel-monitor")
        self._task.add_done_callback(self._on_done)

    def _on_done(self, task: asyncio.Task) -> None:
        self.status.running = False
        if self._stopping or task.cancelled():
            return
        log.error("Monitor stopped unexpectedly (%r); restarting in 10s", task.exception())
        asyncio.get_running_loop().call_later(10, self._restart_if_needed)

    def _restart_if_needed(self) -> None:
        if not self._stopping and not self.is_running:
            self.start()

    async def stop(self) -> None:
        self._stopping = True
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
        self.status.running = False

    async def restart(self) -> None:
        await self.stop()
        self.start()

    @property
    def is_running(self) -> bool:
        return self._task is not None and not self._task.done()

    def trigger(self) -> None:
        """Ask the loop to check immediately."""
        self._trigger.set()

    # ------------------------------------------------------------------- loop
    async def _run(self) -> None:
        self.status.running = True
        log.info("Channel monitor started (interval %ss)", self.settings.check_interval_seconds)
        while True:
            try:
                await self.check_now()
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 - monitoring must never die
                log.exception("Unexpected monitor error")
            delay = self._next_delay()
            self.status.next_check_at = to_iso(utcnow() + timedelta(seconds=delay))
            self._write_heartbeat()
            self._trigger.clear()
            try:
                await asyncio.wait_for(self._trigger.wait(), timeout=delay)
            except asyncio.TimeoutError:
                pass

    def _next_delay(self) -> float:
        base = self.settings.check_interval_seconds
        failures = self.status.consecutive_failures
        if failures:
            # Network trouble: retry sooner first, then back off (max = interval * 3).
            base = min(base * 3, 30 * (2 ** min(failures, 6)))
        return base + random.uniform(0, min(20, base * 0.1))

    def _write_heartbeat(self) -> None:
        try:
            path = self.settings.database_path.parent / "heartbeat"
            path.write_text(to_iso(utcnow()) or "")
        except OSError:
            pass

    # ----------------------------------------------------------------- checks
    async def check_now(self) -> CheckResult | None:
        """Fetch the feed of the active source and enqueue new videos."""
        async with self._check_lock:
            source = await self.db.get_active_source()
            self.status.last_check_at = to_iso(utcnow())
            self.status.checks += 1
            if source is None and self.settings.youtube_channel:
                source = await self._source_from_env()
            if source is None:
                self.status.last_error = "Manba YouTube kanal sozlanmagan"
                return None
            try:
                feed = await self.youtube.fetch_feed(source.channel_id)
            except (TransientError, PermanentError) as exc:
                self.status.consecutive_failures += 1
                self.status.last_error = str(exc)
                await self.db.update_source_check(source.channel_id, error=str(exc))
                log.warning("Feed check failed for %s: %s", source.channel_id, exc)
                return None
            result = await self.process_feed(source, feed)
            self.status.consecutive_failures = 0
            self.status.last_error = None
            self.status.last_success_at = to_iso(utcnow())
            await self.db.update_source_check(source.channel_id, error=None, title=feed.title or None)
            if result.queued:
                log.info("Queued %s new video(s) from %s: %s", len(result.queued), source.channel_id, result.queued)
                await self.db.incr_stat("videos_detected", len(result.queued))
                if self.on_new_videos:
                    self.on_new_videos()
            return result

    async def _source_from_env(self) -> SourceChannel | None:
        """Use YOUTUBE_CHANNEL from .env when no channel was set via /set_source_channel."""
        try:
            channel_id, title = await self.youtube.resolve_channel(self.settings.youtube_channel)
        except (TransientError, PermanentError) as exc:
            self.status.consecutive_failures += 1
            self.status.last_error = f"YOUTUBE_CHANNEL aniqlanmadi: {exc}"
            log.warning("Cannot resolve YOUTUBE_CHANNEL=%r: %s", self.settings.youtube_channel, exc)
            return None
        await self.db.set_active_source(channel_id, title, f"https://www.youtube.com/channel/{channel_id}")
        log.info("Source channel from .env: %s (%s)", channel_id, title)
        return await self.db.get_active_source()

    async def process_feed(self, source: SourceChannel, feed: Feed) -> CheckResult:
        result = CheckResult(
            channel_id=source.channel_id,
            channel_title=feed.title or source.title or source.channel_id,
            total_entries=len(feed.entries),
        )
        cutoff = utcnow() - timedelta(hours=self.settings.lookback_hours)
        baseline_key = BASELINE_KEY.format(channel_id=source.channel_id)
        first_run = await self.db.get_setting(baseline_key) is None
        result.baseline = first_run
        backfill_left = self.settings.initial_backfill_count if first_run else 0

        # Newest first so the initial backfill takes the most recent uploads.
        entries = sorted(
            feed.entries, key=lambda e: e.published_at or utcnow(), reverse=True
        )
        for entry in entries:
            if await self.db.video_exists(entry.video_id):
                result.duplicates += 1
                continue
            too_old = entry.published_at is not None and entry.published_at < cutoff
            if first_run:
                enqueue = backfill_left > 0 and not too_old
                if enqueue:
                    backfill_left -= 1
                reason = "kanal qo'shilganda mavjud bo'lgan video"
            else:
                enqueue = not too_old
                reason = f"{self.settings.lookback_hours} soatlik limitdan eski"
            inserted = await self.db.add_video(
                entry.video_id,
                url=entry.url,
                status=QUEUED if enqueue else SKIPPED,
                channel_id=source.channel_id,
                title=entry.title,
                thumbnail_url=entry.thumbnail_url,
                published_at=to_iso(entry.published_at),
                last_error=None if enqueue else reason,
            )
            if not inserted:
                result.duplicates += 1
            elif enqueue:
                result.queued.append(entry.video_id)
            else:
                result.skipped_old.append(entry.video_id)
        if first_run:
            await self.db.set_setting(baseline_key, to_iso(utcnow()))
        return result
