"""Admin authorization, tested through a real aiogram Dispatcher with a mocked Telegram API."""

import asyncio
from datetime import datetime
from types import SimpleNamespace

import pytest
from aiogram import Bot, Dispatcher
from aiogram.client.session.base import BaseSession
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.methods import AnswerCallbackQuery, EditMessageText, SendMessage, TelegramMethod
from aiogram.types import CallbackQuery, Chat, Message, Update, User

import admin
from bot import setup_dispatcher
from admin import IsAdmin
from handlers import common, download
from monitor import ChannelMonitor
from queue_worker import DESTINATION_KEY, QueueWorker
from tests.conftest import ADMIN_ID, USER_ID, FakeAudio, FakePublisher, FakeYouTube, make_entry
from utils.limiter import UserLimiter


class RecordingSession(BaseSession):
    """Fake Telegram Bot API: records every request, never touches the network."""

    def __init__(self):
        super().__init__()
        self.requests: list[TelegramMethod] = []

    async def make_request(self, bot, method, timeout=None):
        self.requests.append(method)
        if isinstance(method, (SendMessage, EditMessageText)):
            return Message(
                message_id=len(self.requests),
                date=datetime.now(),
                chat=Chat(id=getattr(method, "chat_id", None) or 1, type="private"),
                text=method.text,
            ).as_(bot)
        return True

    async def close(self):
        pass

    async def stream_content(self, *args, **kwargs):  # pragma: no cover
        yield b""

    def texts(self) -> list[str]:
        return [m.text for m in self.requests if isinstance(m, (SendMessage, EditMessageText))]


@pytest.fixture
async def app(settings, db):
    session = RecordingSession()
    bot = Bot("123456:TEST_TOKEN_NOT_REAL_xxxxxxxxxxxxxxxxxxxxxxxx", session=session)
    yt = FakeYouTube([make_entry("AAAAAAAAAAA", 1)])
    pub = FakePublisher()
    worker = QueueWorker(settings, db, yt, FakeAudio(), pub, asyncio.Semaphore(1))
    monitor = ChannelMonitor(settings, db, yt, on_new_videos=worker.wake)
    dp = Dispatcher(
        storage=MemoryStorage(), settings=settings, db=db, youtube=yt, publisher=pub, worker=worker,
        monitor=monitor, audio=None, video=None, download_semaphore=asyncio.Semaphore(1),
        user_limiter=UserLimiter(0),
    )
    # Routers are module-level singletons: detach them from any previous dispatcher.
    for r in (admin.router, common.router, download.router):
        r._parent_router = None
    setup_dispatcher(dp, db)
    yield SimpleNamespace(bot=bot, dp=dp, session=session, db=db, monitor=monitor, worker=worker)
    await monitor.stop()
    await worker.stop()


_update_id = 0


def message_update(user_id: int, text: str) -> Update:
    global _update_id
    _update_id += 1
    user = User(id=user_id, is_bot=False, first_name="Test")
    entities = None
    if text.startswith("/"):
        entities = [{"type": "bot_command", "offset": 0, "length": len(text.split()[0])}]
    msg = Message(
        message_id=_update_id, date=datetime.now(), chat=Chat(id=user_id, type="private"),
        from_user=user, text=text, entities=entities,
    )
    return Update(update_id=_update_id, message=msg)


def callback_update(user_id: int, data: str) -> Update:
    global _update_id
    _update_id += 1
    user = User(id=user_id, is_bot=False, first_name="Test")
    msg = Message(message_id=1, date=datetime.now(), chat=Chat(id=user_id, type="private"), text="x")
    return Update(
        update_id=_update_id,
        callback_query=CallbackQuery(id=str(_update_id), from_user=user, chat_instance="1", data=data, message=msg),
    )


async def feed(app, update):
    await app.dp.feed_update(app.bot, update)


async def test_is_admin_filter(settings):
    f = IsAdmin()
    assert await f(SimpleNamespace(from_user=SimpleNamespace(id=ADMIN_ID)), settings) is True
    assert await f(SimpleNamespace(from_user=SimpleNamespace(id=USER_ID)), settings) is False
    assert await f(SimpleNamespace(from_user=None), settings) is False


@pytest.mark.parametrize("command", [
    "/admin", "/set_source_channel @x", "/set_destination_channel @x", "/channel_status",
    "/check_now", "/queue", "/stats", "/restart_monitor", "/failed", "/retry all",
])
async def test_regular_user_is_denied(app, command):
    await feed(app, message_update(USER_ID, command))
    texts = app.session.texts()
    assert len(texts) == 1 and texts[0].startswith("⛔")
    assert await app.db.get_active_source() is None
    assert await app.db.get_setting(DESTINATION_KEY) is None


async def test_regular_user_cannot_press_admin_buttons(app):
    await feed(app, callback_update(USER_ID, "adm:setdest:-100123"))
    answers = [m for m in app.session.requests if isinstance(m, AnswerCallbackQuery)]
    assert answers and answers[0].text.startswith("⛔")
    assert await app.db.get_setting(DESTINATION_KEY) is None


async def test_admin_can_open_panel_and_stats(app):
    await feed(app, message_update(ADMIN_ID, "/admin"))
    await feed(app, message_update(ADMIN_ID, "/stats"))
    texts = app.session.texts()
    assert "AURIX — tizim holati" in texts[0]
    assert "AURIX statistikasi" in texts[1]


async def test_admin_sets_source_and_destination(app):
    await feed(app, message_update(ADMIN_ID, "/set_source_channel https://www.youtube.com/@TestChannel"))
    source = await app.db.get_active_source()
    assert source.channel_id == "UC_x5XG1OV2P6uZZ5FSM9Ttw"
    assert any("manba kanal o'rnatildi" in t for t in app.session.texts())

    await feed(app, message_update(ADMIN_ID, "/set_destination_channel @aurix_music"))
    assert await app.db.get_setting(DESTINATION_KEY) == "@aurix_music"

    await feed(app, message_update(ADMIN_ID, "/set_destination_channel not valid!!"))
    assert await app.db.get_setting(DESTINATION_KEY) == "@aurix_music"


async def test_admin_source_via_conversation(app):
    await feed(app, message_update(ADMIN_ID, "/set_source_channel"))
    await feed(app, message_update(ADMIN_ID, "UC_x5XG1OV2P6uZZ5FSM9Ttw"))
    assert (await app.db.get_active_source()).channel_id == "UC_x5XG1OV2P6uZZ5FSM9Ttw"


async def test_admin_check_now_and_queue(app):
    await app.db.set_active_source("UC_x5XG1OV2P6uZZ5FSM9Ttw", "Test", None)
    await feed(app, message_update(ADMIN_ID, "/check_now"))
    await feed(app, message_update(ADMIN_ID, "/queue"))
    texts = app.session.texts()
    assert any("Tekshiruv tugadi" in t for t in texts)
    assert any("Navbat" in t for t in texts)


async def test_user_start_and_menu(app):
    await feed(app, message_update(USER_ID, "/start"))
    await feed(app, message_update(USER_ID, "📡 Kanal holati"))
    texts = app.session.texts()
    assert "AURIX Downloader" in texts[0] and "/admin" not in texts[0]
    assert "kanal holati" in texts[1].lower()
    assert await app.db.count_users() == 1


async def test_non_youtube_link_rejected(app):
    await feed(app, message_update(USER_ID, "http://169.254.169.254/latest/meta-data"))
    assert "YouTube video havolasi emas" in app.session.texts()[0]
