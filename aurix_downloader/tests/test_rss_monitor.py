"""YouTube RSS parsing, new-video detection, duplicates and lookback."""

from database import QUEUED, SKIPPED
from monitor import ChannelMonitor
from tests.conftest import CHANNEL_ID, FakeYouTube, make_entry
from utils.errors import TransientError
from youtube_service import parse_feed

SAMPLE_FEED = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns:yt="http://www.youtube.com/xml/schemas/2015" xmlns:media="http://search.yahoo.com/mrss/" xmlns="http://www.w3.org/2005/Atom">
 <title>Test Channel</title>
 <entry>
  <id>yt:video:AAAAAAAAAAA</id>
  <yt:videoId>AAAAAAAAAAA</yt:videoId>
  <yt:channelId>UC_x5XG1OV2P6uZZ5FSM9Ttw</yt:channelId>
  <title>Newest &amp; best</title>
  <link rel="alternate" href="https://www.youtube.com/watch?v=AAAAAAAAAAA"/>
  <published>2026-11-05T10:00:00+00:00</published>
  <media:group><media:thumbnail url="https://i3.ytimg.com/vi/AAAAAAAAAAA/hqdefault.jpg"/></media:group>
 </entry>
 <entry>
  <yt:videoId>BBBBBBBBBBB</yt:videoId>
  <title>Older</title>
  <published>2026-11-01T10:00:00+00:00</published>
 </entry>
 <entry>
  <yt:videoId>bad id!</yt:videoId>
  <title>Broken</title>
 </entry>
</feed>"""


def test_parse_feed():
    feed = parse_feed(SAMPLE_FEED, CHANNEL_ID)
    assert feed.title == "Test Channel"
    assert [e.video_id for e in feed.entries] == ["AAAAAAAAAAA", "BBBBBBBBBBB"]
    first = feed.entries[0]
    assert first.title == "Newest & best"
    assert first.url == "https://www.youtube.com/watch?v=AAAAAAAAAAA"
    assert first.published_at.isoformat() == "2026-11-05T10:00:00+00:00"
    assert first.thumbnail_url == "https://i.ytimg.com/vi/AAAAAAAAAAA/hqdefault.jpg"


def test_parse_broken_feed_is_transient():
    try:
        parse_feed("<feed><entry>", CHANNEL_ID)
    except TransientError:
        pass
    else:
        raise AssertionError("expected TransientError")


async def _monitor(settings, db, yt):
    woken = []
    mon = ChannelMonitor(settings, db, yt, on_new_videos=lambda: woken.append(1))
    await db.set_active_source(CHANNEL_ID, "Test Channel", None)
    return mon, woken


async def test_first_check_creates_baseline_without_posting_old_videos(settings, db):
    yt = FakeYouTube([make_entry("AAAAAAAAAAA", 1), make_entry("BBBBBBBBBBB", 30)])
    mon, woken = await _monitor(settings, db, yt)
    result = await mon.check_now()
    assert result.baseline is True
    assert result.queued == []
    assert sorted(result.skipped_old) == ["AAAAAAAAAAA", "BBBBBBBBBBB"]
    assert (await db.get_video("AAAAAAAAAAA")).status == SKIPPED
    assert woken == []


async def test_initial_backfill(settings, db):
    from dataclasses import replace

    settings = replace(settings, initial_backfill_count=1)
    yt = FakeYouTube([make_entry("BBBBBBBBBBB", 30), make_entry("AAAAAAAAAAA", 1)])
    mon, _ = await _monitor(settings, db, yt)
    result = await mon.check_now()
    assert result.queued == ["AAAAAAAAAAA"]  # newest one only
    assert result.skipped_old == ["BBBBBBBBBBB"]


async def test_new_video_detection(settings, db):
    yt = FakeYouTube([make_entry("AAAAAAAAAAA", 5)])
    mon, woken = await _monitor(settings, db, yt)
    await mon.check_now()  # baseline

    yt.entries.insert(0, make_entry("CCCCCCCCCCC", 0.1, "Brand new"))
    result = await mon.check_now()
    assert result.queued == ["CCCCCCCCCCC"]
    video = await db.get_video("CCCCCCCCCCC")
    assert video.status == QUEUED
    assert video.title == "Brand new"
    assert video.url == "https://www.youtube.com/watch?v=CCCCCCCCCCC"
    assert woken == [1]
    stats = await db.get_stats()
    assert stats["videos_detected"] == 1


async def test_duplicates_are_never_queued_twice(settings, db):
    yt = FakeYouTube([])
    mon, _ = await _monitor(settings, db, yt)
    await mon.check_now()
    yt.entries = [make_entry("CCCCCCCCCCC", 0.1)]
    first = await mon.check_now()
    second = await mon.check_now()
    third = await mon.check_now()
    assert first.queued == ["CCCCCCCCCCC"]
    assert second.queued == [] and second.duplicates == 1
    assert third.queued == []
    assert (await db.video_status_counts())[QUEUED] == 1
    # Even if the DB insert races, INSERT OR IGNORE keeps one row.
    assert await db.add_video("CCCCCCCCCCC", url="x") is False


async def test_feed_network_error_is_handled(settings, db):
    yt = FakeYouTube([])
    mon, _ = await _monitor(settings, db, yt)
    yt.feed_error = TransientError("network error: timeout")
    assert await mon.check_now() is None
    assert mon.status.consecutive_failures == 1
    assert "timeout" in mon.status.last_error
    source = await db.get_active_source()
    assert "timeout" in source.last_error

    yt.feed_error = None
    assert await mon.check_now() is not None
    assert mon.status.consecutive_failures == 0
    assert (await db.get_active_source()).last_error is None


async def test_source_from_env(settings, db):
    from dataclasses import replace

    settings = replace(settings, youtube_channel="@TestChannel")
    yt = FakeYouTube([make_entry("AAAAAAAAAAA", 1)])
    mon = ChannelMonitor(settings, db, yt)
    result = await mon.check_now()
    assert result is not None
    assert (await db.get_active_source()).channel_id == CHANNEL_ID


async def test_no_source_configured(settings, db):
    mon = ChannelMonitor(settings, db, FakeYouTube([]))
    assert await mon.check_now() is None
    assert "sozlanmagan" in mon.status.last_error


async def test_monitor_loop_runs_in_background(settings, db):
    import asyncio

    yt = FakeYouTube([])
    mon, _ = await _monitor(settings, db, yt)
    mon.start()
    for _ in range(50):
        if yt.feed_calls:
            break
        await asyncio.sleep(0.02)
    assert mon.is_running and yt.feed_calls == 1
    mon.trigger()
    for _ in range(50):
        if yt.feed_calls == 2:
            break
        await asyncio.sleep(0.02)
    assert yt.feed_calls == 2
    await mon.restart()
    assert mon.is_running
    await mon.stop()
    assert not mon.is_running
