"""Recovery after restart: persistent queue and offline catch-up."""

from database import PROCESSING, PUBLISHED, QUEUED, SKIPPED, Database
from monitor import ChannelMonitor
from queue_worker import QueueWorker
from tests.conftest import CHANNEL_ID, FakeAudio, FakePublisher, FakeYouTube, make_entry

import asyncio


async def test_interrupted_job_is_requeued_after_restart(settings):
    db = Database(settings.database_path)
    await db.connect()
    await db.add_video("AAAAAAAAAAA", url="https://www.youtube.com/watch?v=AAAAAAAAAAA")
    claimed = await db.claim_next_video()
    assert claimed.status == PROCESSING
    await db.create_job("AAAAAAAAAAA", "channel_mp3")
    await db.close()  # simulated crash / reboot

    db = Database(settings.database_path)
    await db.connect()
    pub = FakePublisher()
    worker = QueueWorker(settings, db, FakeYouTube(), FakeAudio(), pub, asyncio.Semaphore(1))
    await worker.start()
    try:
        for _ in range(100):
            if pub.published:
                break
            await asyncio.sleep(0.02)
    finally:
        await worker.stop()
    assert len(pub.published) == 1
    assert (await db.get_video("AAAAAAAAAAA")).status == PUBLISHED
    assert await db.count_running_jobs() == 0
    await db.close()


async def test_videos_published_while_offline_are_caught_up(settings):
    db = Database(settings.database_path)
    await db.connect()
    await db.set_active_source(CHANNEL_ID, "Test", None)
    yt = FakeYouTube([make_entry("AAAAAAAAAAA", 100)])
    await ChannelMonitor(settings, db, yt).check_now()  # baseline before going offline
    await db.close()

    # Bot was offline; three uploads happened meanwhile.
    yt.entries = [
        make_entry("BBBBBBBBBBB", 2),    # within 48h lookback
        make_entry("CCCCCCCCCCC", 20),   # within lookback
        make_entry("DDDDDDDDDDD", 72),   # older than lookback -> skipped
        make_entry("AAAAAAAAAAA", 100),  # already known
    ]
    db = Database(settings.database_path)
    await db.connect()
    result = await ChannelMonitor(settings, db, yt).check_now()
    assert result.baseline is False
    assert sorted(result.queued) == ["BBBBBBBBBBB", "CCCCCCCCCCC"]
    assert result.skipped_old == ["DDDDDDDDDDD"]
    assert result.duplicates == 1
    assert (await db.get_video("DDDDDDDDDDD")).status == SKIPPED
    assert (await db.video_status_counts())[QUEUED] == 2
    await db.close()


async def test_published_videos_survive_restart(settings):
    db = Database(settings.database_path)
    await db.connect()
    await db.set_active_source(CHANNEL_ID, "Test", None)
    await db.set_setting(f"baseline_done:{CHANNEL_ID}", "x")
    await db.add_video("AAAAAAAAAAA", url="u", status=PUBLISHED)
    await db.add_channel_post("AAAAAAAAAAA", "@c", 1)
    await db.close()

    db = Database(settings.database_path)
    await db.connect()
    yt = FakeYouTube([make_entry("AAAAAAAAAAA", 1)])
    result = await ChannelMonitor(settings, db, yt).check_now()
    assert result.queued == [] and result.duplicates == 1
    await db.close()
