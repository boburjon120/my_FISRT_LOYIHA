import sys
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from audio_service import AudioResult  # noqa: E402
from config import Settings  # noqa: E402
from database import Database  # noqa: E402
from utils.timeutils import utcnow  # noqa: E402
from youtube_service import Feed, FeedEntry, VideoInfo  # noqa: E402

CHANNEL_ID = "UC_x5XG1OV2P6uZZ5FSM9Ttw"
ADMIN_ID = 111111
USER_ID = 222222


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        bot_token="123456:TEST_TOKEN_NOT_REAL_xxxxxxxxxxxxxxxxxxxxxxxx",
        admin_ids=frozenset({ADMIN_ID}),
        telegram_channel_id="@aurix_test",
        check_interval_seconds=300,
        lookback_hours=48,
        max_retries=3,
        retry_base_delay_seconds=60,
        database_path=tmp_path / "data" / "aurix.db",
        download_dir=tmp_path / "downloads",
        log_dir=tmp_path / "logs",
    )


@pytest.fixture
async def db(settings: Settings):
    database = Database(settings.database_path)
    await database.connect()
    yield database
    await database.close()


def make_entry(video_id: str, hours_ago: float, title: str | None = None) -> FeedEntry:
    return FeedEntry(
        video_id=video_id,
        title=title or f"Video {video_id}",
        url=f"https://www.youtube.com/watch?v={video_id}",
        published_at=utcnow() - timedelta(hours=hours_ago),
        thumbnail_url=f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg",
        channel_id=CHANNEL_ID,
    )


class FakeYouTube:
    """Mocked YouTube: no network access."""

    def __init__(self, entries=None, errors=None):
        self.entries = list(entries or [])
        self.feed_error: Exception | None = None
        self.info_errors: dict[str, Exception] = dict(errors or {})
        self.feed_calls = 0
        self.info_calls: list[str] = []

    async def fetch_feed(self, channel_id: str) -> Feed:
        self.feed_calls += 1
        if self.feed_error:
            raise self.feed_error
        return Feed(channel_id=channel_id, title="Test Channel", entries=list(self.entries))

    async def resolve_channel(self, value: str):
        return CHANNEL_ID, "Test Channel"

    async def get_video_info(self, video_id: str):
        self.info_calls.append(video_id)
        if video_id in self.info_errors:
            raise self.info_errors[video_id]
        info = VideoInfo(
            video_id=video_id,
            title=f"Song {video_id}",
            url=f"https://www.youtube.com/watch?v={video_id}",
            duration=180,
            thumbnail_url=f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg",
            uploader="Test Channel",
            upload_date=utcnow(),
        )
        return info, {"id": video_id}

    async def download_thumbnail(self, video_id, dest) -> bool:
        return False

    def base_opts(self) -> dict:
        return {}


class FakeInstagram(FakeYouTube):
    async def get_video_info(self, code: str):
        self.info_calls.append(code)
        if code in self.info_errors:
            raise self.info_errors[code]
        info = VideoInfo(
            video_id=code,
            title=f"Reel {code}",
            url=f"https://www.instagram.com/p/{code}/",
            duration=15,
            thumbnail_url="",
            uploader="test_user",
            upload_date=utcnow(),
            platform="instagram",
        )
        return info, {"id": code}


class FakeAudio:
    def __init__(self):
        self.calls: list[str] = []
        self.error: Exception | None = None

    async def create_mp3(self, info, raw, workdir, *, max_duration_minutes):
        self.calls.append(info.video_id)
        if self.error:
            raise self.error
        workdir.mkdir(parents=True, exist_ok=True)
        path = workdir / f"{info.title}.mp3"
        path.write_bytes(b"ID3fake-mp3")
        return AudioResult(path, path.name, path.stat().st_size, info.duration, 192, None)


class FakePublisher:
    def __init__(self):
        self.published: list[dict] = []
        self.notifications: list[str] = []
        self.error: Exception | None = None
        self._next_id = 100

    async def publish_audio(self, chat_id, **kwargs):
        if self.error:
            raise self.error
        assert kwargs["audio_path"].exists(), "file must exist while uploading"
        self._next_id += 1
        self.published.append({"chat_id": chat_id, **kwargs})
        return SimpleNamespace(message_id=self._next_id)

    async def notify(self, chat_ids, text):
        self.notifications.append(text)

    async def check_destination(self, chat_id):
        return "Test Destination"
