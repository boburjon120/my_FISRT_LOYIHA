"""Telegram publishing with a mocked Bot."""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiogram.enums import ChatMemberStatus
from aiogram.exceptions import TelegramBadRequest, TelegramNetworkError, TelegramRetryAfter
from aiogram.methods import SendAudio

import telegram_service
from telegram_service import TelegramPublisher, build_channel_caption, call_with_retry
from utils.errors import DestinationError, PermanentError, TransientError

URL = "https://www.youtube.com/watch?v=AAAAAAAAAAA"


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    sleeps = []

    async def fake_sleep(seconds):
        sleeps.append(seconds)

    monkeypatch.setattr(telegram_service.asyncio, "sleep", fake_sleep)
    return sleeps


def test_caption_format():
    caption = build_channel_caption("Yulduz <live> & band", URL, "2026-11-05T10:00:00+00:00")
    assert caption.startswith("🎵 <b>AURIX MUSIC</b>")
    assert "🎧 <b>Track:</b> Yulduz &lt;live&gt; &amp; band" in caption
    assert f"▶️ <b>Original YouTube:</b> {URL}" in caption
    assert "05.11.2026 15:00" in caption  # Tashkent time
    assert "Powered by AURIX Downloader" in caption


def test_caption_respects_telegram_limit():
    caption = build_channel_caption("x" * 3000, URL, None)
    assert len(caption) <= 1024
    assert URL in caption and "Powered by AURIX Downloader" in caption


async def test_publish_audio_uses_send_audio(tmp_path: Path):
    mp3 = tmp_path / "Song.mp3"
    mp3.write_bytes(b"ID3")
    bot = SimpleNamespace(send_audio=AsyncMock(return_value=SimpleNamespace(message_id=77)))
    publisher = TelegramPublisher(bot)
    msg = await publisher.publish_audio(
        "@aurix", audio_path=mp3, filename="Song.mp3", title="Song", performer="Artist",
        url=URL, published_at=None, duration=180,
    )
    assert msg.message_id == 77
    kwargs = bot.send_audio.await_args.kwargs
    assert kwargs["chat_id"] == "@aurix"
    assert kwargs["audio"].filename == "Song.mp3"
    assert kwargs["title"] == "Song" and kwargs["performer"] == "Artist"
    assert kwargs["duration"] == 180
    assert "AURIX MUSIC" in kwargs["caption"]
    assert kwargs["reply_markup"].inline_keyboard[0][0].url == URL


async def test_retry_after_and_network_errors_are_retried(no_sleep):
    method = SendAudio(chat_id=1, audio="x")
    action = AsyncMock(side_effect=[
        TelegramRetryAfter(method=method, message="flood", retry_after=5),
        TelegramNetworkError(method=method, message="timeout"),
        "ok",
    ])
    assert await call_with_retry(action) == "ok"
    assert action.await_count == 3
    assert no_sleep == [6, 6.0]


async def test_gives_up_after_attempts():
    method = SendAudio(chat_id=1, audio="x")
    action = AsyncMock(side_effect=TelegramNetworkError(method=method, message="down"))
    with pytest.raises(TransientError):
        await call_with_retry(action, attempts=3)
    assert action.await_count == 3


async def test_destination_errors_are_classified():
    method = SendAudio(chat_id=1, audio="x")
    action = AsyncMock(side_effect=TelegramBadRequest(method=method, message="Bad Request: chat not found"))
    with pytest.raises(DestinationError):
        await call_with_retry(action)
    action = AsyncMock(side_effect=TelegramBadRequest(method=method, message="Bad Request: wrong file"))
    with pytest.raises(PermanentError):
        await call_with_retry(action)


def _bot_with_member(status, can_post=True, chat_type="channel"):
    return SimpleNamespace(
        get_chat=AsyncMock(return_value=SimpleNamespace(id=-100123, title="AURIX Music", type=chat_type)),
        get_me=AsyncMock(return_value=SimpleNamespace(id=999)),
        get_chat_member=AsyncMock(return_value=SimpleNamespace(status=status, can_post_messages=can_post)),
    )


async def test_check_destination():
    ok = TelegramPublisher(_bot_with_member(ChatMemberStatus.ADMINISTRATOR))
    assert await ok.check_destination("@aurix") == "AURIX Music"
    with pytest.raises(DestinationError):
        await TelegramPublisher(_bot_with_member(ChatMemberStatus.MEMBER)).check_destination("@aurix")
    with pytest.raises(DestinationError):
        await TelegramPublisher(
            _bot_with_member(ChatMemberStatus.ADMINISTRATOR, can_post=False)
        ).check_destination("@aurix")
