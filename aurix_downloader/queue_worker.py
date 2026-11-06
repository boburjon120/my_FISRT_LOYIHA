"""Persistent processing queue: YouTube video -> MP3 -> Telegram channel.

The queue lives in SQLite (``processed_videos`` with status ``queued``), so
jobs survive restarts. One worker publishes videos in chronological order;
the shared download semaphore limits simultaneous downloads bot-wide.
"""

from __future__ import annotations

import asyncio
import logging
import shutil
from dataclasses import dataclass
from datetime import timedelta

from audio_service import AudioService
from config import Settings
from database import Database, VideoRecord
from telegram_service import TelegramPublisher
from utils.errors import (
    AurixError,
    DestinationError,
    NotReadyError,
    PermanentError,
)
from utils.text import esc
from utils.timeutils import from_iso, utcnow
from youtube_service import YouTubeService

log = logging.getLogger(__name__)

DESTINATION_KEY = "destination_channel"
NOT_READY_DELAY = 15 * 60
NOT_READY_GIVE_UP = timedelta(days=3)
DESTINATION_RETRY_DELAY = 5 * 60
MAX_BACKOFF = 6 * 60 * 60
IDLE_WAIT = 60


@dataclass
class WorkerStatus:
    running: bool = False
    current_video: str | None = None
    current_title: str | None = None
    processed_since_start: int = 0
    failed_since_start: int = 0
    last_error: str | None = None


async def get_destination(db: Database, settings: Settings) -> str:
    return (await db.get_setting(DESTINATION_KEY)) or settings.telegram_channel_id


class QueueWorker:
    def __init__(
        self,
        settings: Settings,
        db: Database,
        youtube: YouTubeService,
        audio: AudioService,
        publisher: TelegramPublisher,
        download_semaphore: asyncio.Semaphore,
    ) -> None:
        self.settings = settings
        self.db = db
        self.youtube = youtube
        self.audio = audio
        self.publisher = publisher
        self.semaphore = download_semaphore
        self.status = WorkerStatus()
        self._wake = asyncio.Event()
        self._task: asyncio.Task | None = None
        self._stopping = False
        self._last_notice: dict[str, float] = {}

    # -------------------------------------------------------------- lifecycle
    async def start(self) -> None:
        recovered = await self.db.recover_interrupted()
        if recovered:
            log.info("Recovered %s interrupted video(s) back into the queue", recovered)
        self._stopping = False
        self._spawn()

    def _spawn(self) -> None:
        self._task = asyncio.create_task(self._run(), name="aurix-queue-worker")
        self._task.add_done_callback(self._on_done)

    def _on_done(self, task: asyncio.Task) -> None:
        self.status.running = False
        if self._stopping or task.cancelled():
            return
        exc = task.exception()
        log.error("Queue worker stopped unexpectedly (%r); restarting in 5s", exc)
        asyncio.get_running_loop().call_later(5, self._restart_if_needed)

    def _restart_if_needed(self) -> None:
        if not self._stopping and (self._task is None or self._task.done()):
            self._spawn()

    async def stop(self) -> None:
        self._stopping = True
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
        self.status.running = False

    def wake(self) -> None:
        self._wake.set()

    @property
    def is_running(self) -> bool:
        return self._task is not None and not self._task.done()

    # ------------------------------------------------------------------- loop
    async def _run(self) -> None:
        self.status.running = True
        log.info("Queue worker started")
        while True:
            try:
                processed = await self.run_once()
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 - keep the worker alive
                log.exception("Unexpected queue worker error")
                processed = False
                await asyncio.sleep(10)
            if not processed:
                await self._sleep_until_due()

    async def _sleep_until_due(self) -> None:
        timeout = IDLE_WAIT
        due = from_iso(await self.db.next_due_time())
        if due is not None:
            timeout = max(1.0, min(IDLE_WAIT, (due - utcnow()).total_seconds()))
        self._wake.clear()
        try:
            await asyncio.wait_for(self._wake.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            pass

    async def run_once(self) -> bool:
        """Process one due video. Returns False when nothing was due."""
        video = await self.db.claim_next_video()
        if video is None:
            return False
        await self.process(video)
        return True

    # ------------------------------------------------------------- processing
    def _backoff(self, attempts: int) -> float:
        return min(MAX_BACKOFF, self.settings.retry_base_delay_seconds * (2 ** attempts))

    async def process(self, video: VideoRecord) -> None:
        self.status.current_video = video.video_id
        self.status.current_title = video.title
        job_id = await self.db.create_job(video.video_id, "channel_mp3")
        workdir = self.settings.download_dir / f"channel_{video.video_id}_{job_id}"
        try:
            await self._process(video, job_id, workdir)
        except DestinationError as exc:
            log.warning("Destination problem for %s: %s", video.video_id, exc)
            await self.db.reschedule_video(video.video_id, DESTINATION_RETRY_DELAY, str(exc), count_attempt=False)
            await self.db.finish_job(job_id, "failed", str(exc))
            await self._notify_once("destination", f"⚠️ <b>Kanalga joylab bo'lmadi</b>\n{esc(exc)}\n\n"
                                    "Botni kanalga admin qiling yoki /set_destination_channel ni tekshiring.")
        except NotReadyError as exc:
            detected = from_iso(video.detected_at) or utcnow()
            if utcnow() - detected > NOT_READY_GIVE_UP:
                await self._fail(video, job_id, f"not ready for too long: {exc}")
            else:
                log.info("%s not ready yet (%s); retry in %ss", video.video_id, exc, NOT_READY_DELAY)
                await self.db.reschedule_video(video.video_id, NOT_READY_DELAY, str(exc), count_attempt=False)
                await self.db.finish_job(job_id, "failed", str(exc))
        except PermanentError as exc:
            await self._fail(video, job_id, str(exc))
        except asyncio.CancelledError:
            await self.db.finish_job(job_id, "interrupted", "cancelled")
            raise
        except Exception as exc:  # noqa: BLE001 - TransientError and unexpected errors
            if not isinstance(exc, AurixError):
                log.exception("Unexpected error while processing %s", video.video_id)
            attempts = video.attempts + 1
            if attempts >= self.settings.max_retries:
                await self._fail(video, job_id, f"gave up after {attempts} attempts: {exc}")
            else:
                delay = self._backoff(video.attempts)
                log.warning("Transient error for %s (%s); retry %s/%s in %.0fs",
                            video.video_id, exc, attempts, self.settings.max_retries, delay)
                await self.db.reschedule_video(video.video_id, delay, str(exc))
                await self.db.finish_job(job_id, "failed", str(exc))
                self.status.last_error = str(exc)
        finally:
            shutil.rmtree(workdir, ignore_errors=True)
            self.status.current_video = None
            self.status.current_title = None

    async def _process(self, video: VideoRecord, job_id: int, workdir) -> None:
        # Duplicate guard: if a post was recorded, never publish again.
        if await self.db.get_channel_post(video.video_id):
            log.info("%s already posted, marking published", video.video_id)
            await self.db.mark_video_published(video.video_id)
            await self.db.finish_job(job_id, "done", "already posted")
            return

        destination = await get_destination(self.db, self.settings)
        if not destination:
            raise DestinationError("TELEGRAM_CHANNEL_ID is not configured")

        info, raw = await self.youtube.get_video_info(video.video_id)
        await self.db.update_video_meta(video.video_id, title=info.title)

        async with self.semaphore:
            log.info("Downloading %s - %s", video.video_id, info.title)
            result = await self.audio.create_mp3(
                info, raw, workdir, max_duration_minutes=self.settings.channel_max_duration_minutes
            )

        published_at = video.published_at or info.upload_date
        message = await self.publisher.publish_audio(
            destination,
            audio_path=result.path,
            filename=result.filename,
            title=info.title,
            performer=info.uploader,
            url=info.url,
            published_at=published_at,
            duration=result.duration,
            thumbnail=result.thumbnail,
        )
        # Record the post immediately so it can never be published twice.
        await self.db.add_channel_post(video.video_id, destination, message.message_id)
        await self.db.mark_video_published(video.video_id)
        await self.db.finish_job(job_id, "done", file_size=result.size)
        await self.db.incr_stat("channel_published")
        await self.db.incr_stat("bytes_published", result.size)
        self.status.processed_since_start += 1
        log.info("Published %s to %s (message %s)", video.video_id, destination, message.message_id)

    async def _fail(self, video: VideoRecord, job_id: int, error: str) -> None:
        log.error("Video %s failed permanently: %s", video.video_id, error)
        await self.db.mark_video_failed(video.video_id, error)
        await self.db.finish_job(job_id, "failed", error)
        await self.db.incr_stat("channel_failed")
        self.status.failed_since_start += 1
        self.status.last_error = error
        if self.settings.notify_admins_on_failure:
            await self.publisher.notify(
                self.settings.admin_ids,
                "❌ <b>AURIX: video qayta ishlanmadi</b>\n\n"
                f"🎬 {esc(video.title or video.video_id)}\n"
                f"🔗 {esc(video.url)}\n"
                f"⚠️ {esc(error[:300])}\n\n"
                f"Qayta urinish: <code>/retry {esc(video.video_id)}</code>",
            )

    async def _notify_once(self, key: str, text: str, every: float = 3600) -> None:
        loop = asyncio.get_running_loop()
        last = self._last_notice.get(key, 0.0)
        if loop.time() - last < every and last:
            return
        self._last_notice[key] = loop.time()
        await self.publisher.notify(self.settings.admin_ids, text)
