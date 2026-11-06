"""Persistent queue processing with mocked YouTube / audio / Telegram."""

import asyncio
from dataclasses import replace

from database import FAILED, PUBLISHED, QUEUED
from queue_worker import DESTINATION_KEY, QueueWorker
from tests.conftest import FakeAudio, FakePublisher, FakeYouTube
from utils.errors import DestinationError, NotReadyError, PermanentError, TransientError
from utils.timeutils import from_iso, utcnow


def make_worker(settings, db, yt=None, audio=None, pub=None):
    yt = yt or FakeYouTube()
    audio = audio or FakeAudio()
    pub = pub or FakePublisher()
    worker = QueueWorker(settings, db, yt, audio, pub, asyncio.Semaphore(1))
    return worker, yt, audio, pub


async def enqueue(db, video_id, published="2026-11-05T10:00:00+00:00"):
    await db.add_video(video_id, url=f"https://www.youtube.com/watch?v={video_id}",
                       title=f"T {video_id}", published_at=published)


async def test_successful_publish(settings, db):
    worker, _, audio, pub = make_worker(settings, db)
    await enqueue(db, "AAAAAAAAAAA")
    assert await worker.run_once() is True
    assert pub.published[0]["chat_id"] == "@aurix_test"
    assert pub.published[0]["title"] == "Song AAAAAAAAAAA"
    assert pub.published[0]["url"] == "https://www.youtube.com/watch?v=AAAAAAAAAAA"
    assert (await db.get_video("AAAAAAAAAAA")).status == PUBLISHED
    post = await db.get_channel_post("AAAAAAAAAAA")
    assert post["message_id"] == 101 and post["chat_id"] == "@aurix_test"
    # temp files are removed after upload
    assert list(settings.download_dir.glob("*")) == []
    assert await worker.run_once() is False


async def test_queue_processes_in_publication_order(settings, db):
    worker, _, _, pub = make_worker(settings, db)
    await enqueue(db, "CCCCCCCCCCC", "2026-11-05T12:00:00+00:00")
    await enqueue(db, "AAAAAAAAAAA", "2026-11-05T08:00:00+00:00")
    await enqueue(db, "BBBBBBBBBBB", "2026-11-05T10:00:00+00:00")
    while await worker.run_once():
        pass
    assert [p["url"][-11:] for p in pub.published] == ["AAAAAAAAAAA", "BBBBBBBBBBB", "CCCCCCCCCCC"]


async def test_already_posted_video_is_not_published_again(settings, db):
    worker, _, audio, pub = make_worker(settings, db)
    await enqueue(db, "AAAAAAAAAAA")
    await db.add_channel_post("AAAAAAAAAAA", "@aurix_test", 5)
    await worker.run_once()
    assert pub.published == [] and audio.calls == []
    assert (await db.get_video("AAAAAAAAAAA")).status == PUBLISHED


async def test_transient_error_is_retried_with_backoff(settings, db):
    worker, yt, audio, pub = make_worker(settings, db)
    audio.error = TransientError("network down")
    await enqueue(db, "AAAAAAAAAAA")
    await worker.run_once()
    video = await db.get_video("AAAAAAAAAAA")
    assert video.status == QUEUED and video.attempts == 1
    assert from_iso(video.next_attempt_at) > utcnow()
    # not due yet -> nothing to do
    assert await worker.run_once() is False
    assert list(settings.download_dir.glob("*")) == []


async def test_gives_up_after_max_retries(settings, db):
    worker, _, audio, pub = make_worker(settings, db)
    audio.error = TransientError("still down")
    await enqueue(db, "AAAAAAAAAAA")
    for _ in range(settings.max_retries):
        await db._exec("UPDATE processed_videos SET next_attempt_at=NULL")
        await worker.run_once()
    video = await db.get_video("AAAAAAAAAAA")
    assert video.status == FAILED
    assert "gave up" in video.last_error
    assert pub.notifications and "AAAAAAAAAAA" in pub.notifications[0]


async def test_permanent_error_fails_immediately(settings, db):
    yt = FakeYouTube(errors={"AAAAAAAAAAA": PermanentError("Private video")})
    worker, _, audio, pub = make_worker(settings, db, yt=yt)
    await enqueue(db, "AAAAAAAAAAA")
    await worker.run_once()
    assert (await db.get_video("AAAAAAAAAAA")).status == FAILED
    assert audio.calls == [] and pub.published == []
    assert (await db.get_stats())["channel_failed"] == 1


async def test_upcoming_premiere_waits_without_using_attempts(settings, db):
    yt = FakeYouTube(errors={"AAAAAAAAAAA": NotReadyError("Premieres in 2 hours")})
    worker, *_ = make_worker(settings, db, yt=yt)
    await enqueue(db, "AAAAAAAAAAA")
    await worker.run_once()
    video = await db.get_video("AAAAAAAAAAA")
    assert video.status == QUEUED and video.attempts == 0


async def test_missing_destination_waits(settings, db):
    settings = replace(settings, telegram_channel_id="")
    worker, _, audio, pub = make_worker(settings, db)
    await enqueue(db, "AAAAAAAAAAA")
    await worker.run_once()
    video = await db.get_video("AAAAAAAAAAA")
    assert video.status == QUEUED and video.attempts == 0
    assert audio.calls == []
    assert pub.notifications  # admins are told to configure the channel

    await db.set_setting(DESTINATION_KEY, "@from_admin")
    await db._exec("UPDATE processed_videos SET next_attempt_at=NULL")
    await worker.run_once()
    assert pub.published[0]["chat_id"] == "@from_admin"


async def test_publish_rejected_by_telegram_does_not_create_post(settings, db):
    worker, _, _, pub = make_worker(settings, db)
    pub.error = DestinationError("bot is not admin")
    await enqueue(db, "AAAAAAAAAAA")
    await worker.run_once()
    assert await db.get_channel_post("AAAAAAAAAAA") is None
    assert (await db.get_video("AAAAAAAAAAA")).status == QUEUED


async def test_background_worker_wakes_up_on_new_video(settings, db):
    worker, _, _, pub = make_worker(settings, db)
    await worker.start()
    try:
        await asyncio.sleep(0.05)
        await enqueue(db, "AAAAAAAAAAA")
        worker.wake()
        for _ in range(100):
            if pub.published:
                break
            await asyncio.sleep(0.02)
        assert len(pub.published) == 1
    finally:
        await worker.stop()
    assert not worker.is_running


async def test_retry_failed(settings, db):
    await enqueue(db, "AAAAAAAAAAA")
    await db.mark_video_failed("AAAAAAAAAAA", "boom")
    assert await db.requeue_failed("AAAAAAAAAAA") == 1
    video = await db.get_video("AAAAAAAAAAA")
    assert video.status == QUEUED and video.attempts == 0
