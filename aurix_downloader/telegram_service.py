"""Telegram publishing: channel posts and file delivery with safe retries."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import datetime
from pathlib import Path
from typing import TypeVar

from aiogram import Bot
from aiogram.enums import ChatMemberStatus, ParseMode
from aiogram.exceptions import (
    TelegramBadRequest,
    TelegramEntityTooLarge,
    TelegramForbiddenError,
    TelegramNetworkError,
    TelegramNotFound,
    TelegramRetryAfter,
    TelegramServerError,
    TelegramUnauthorizedError,
)
from aiogram.types import (
    FSInputFile,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    LinkPreviewOptions,
    Message,
)

from utils.errors import DestinationError, FileTooLargeError, PermanentError, TransientError
from utils.text import CAPTION_LIMIT, esc, truncate
from utils.timeutils import human_date

log = logging.getLogger(__name__)

T = TypeVar("T")
BRAND = "AURIX Downloader"
UPLOAD_TIMEOUT = 600


def build_channel_caption(title: str, url: str, published_at: datetime | str | None) -> str:
    def render(t: str) -> str:
        return (
            "🎵 <b>AURIX MUSIC</b>\n\n"
            f"🎧 <b>Track:</b> {esc(t)}\n"
            f"📅 <b>Sana:</b> {esc(human_date(published_at))}\n"
            f"▶️ <b>Original YouTube:</b> {esc(url)}\n\n"
            f"⚡ <i>Powered by {BRAND}</i>"
        )

    caption = render(title)
    if len(caption) > CAPTION_LIMIT:
        overflow = len(caption) - CAPTION_LIMIT
        caption = render(truncate(title, max(10, len(title) - overflow - 5)))
    return caption


def build_user_caption(title: str, url: str, extra: str = "") -> str:
    caption = (
        f"🎧 <b>{esc(truncate(title, 200))}</b>\n"
        f"{extra}"
        f"▶️ <a href=\"{esc(url)}\">YouTube'da ochish</a>\n\n"
        f"⚡ <i>{BRAND}</i>"
    )
    return caption[:CAPTION_LIMIT]


def youtube_button(url: str, text: str = "▶️ YouTube'da tinglash / ko'rish") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=text, url=url)]])


async def call_with_retry(
    action: Callable[[], Awaitable[T]], *, attempts: int = 4, base_delay: float = 3.0
) -> T:
    """Run a Telegram API call, retrying flood-wait, network and 5xx errors."""
    last_exc: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            return await action()
        except TelegramRetryAfter as exc:
            last_exc = exc
            wait = min(float(exc.retry_after) + 1, 300)
            log.warning("Telegram flood control, sleeping %.0fs", wait)
            await asyncio.sleep(wait)
        except (TelegramNetworkError, TelegramServerError) as exc:
            last_exc = exc
            wait = base_delay * (2 ** (attempt - 1))
            log.warning("Telegram network/server error (%s), retry %s/%s in %.0fs", exc, attempt, attempts, wait)
            await asyncio.sleep(wait)
        except TelegramEntityTooLarge as exc:
            raise FileTooLargeError(str(exc)) from exc
        except (TelegramForbiddenError, TelegramUnauthorizedError, TelegramNotFound) as exc:
            raise DestinationError(f"Telegram rejected the request: {exc}") from exc
        except TelegramBadRequest as exc:
            text = str(exc).lower()
            if "chat not found" in text or "not enough rights" in text or "need administrator" in text:
                raise DestinationError(f"Telegram destination problem: {exc}") from exc
            if "too big" in text or "too large" in text:
                raise FileTooLargeError(str(exc)) from exc
            raise PermanentError(f"Telegram bad request: {exc}") from exc
    raise TransientError(f"Telegram request failed after {attempts} attempts: {last_exc}")


class TelegramPublisher:
    def __init__(self, bot: Bot) -> None:
        self.bot = bot

    async def check_destination(self, chat_id: str) -> str:
        """Verify the bot can post in ``chat_id``. Returns the chat title."""
        try:
            chat = await self.bot.get_chat(chat_id)
            me = await self.bot.get_me()
            member = await self.bot.get_chat_member(chat.id, me.id)
        except (TelegramBadRequest, TelegramForbiddenError, TelegramNotFound) as exc:
            raise DestinationError(
                f"cannot access chat {chat_id}: {exc}",
                user_message="Kanal topilmadi yoki bot kanalga qo'shilmagan.",
            ) from exc
        if member.status == ChatMemberStatus.CREATOR:
            return chat.title or str(chat.id)
        if member.status != ChatMemberStatus.ADMINISTRATOR:
            raise DestinationError(
                "bot is not an administrator", user_message="Bot bu kanalda administrator emas."
            )
        if chat.type == "channel" and not getattr(member, "can_post_messages", False):
            raise DestinationError(
                "bot cannot post messages",
                user_message="Botga «Xabar joylash» (Post messages) huquqi berilmagan.",
            )
        return chat.title or str(chat.id)

    async def publish_audio(
        self,
        chat_id: str,
        *,
        audio_path: Path,
        filename: str,
        title: str,
        performer: str | None,
        url: str,
        published_at: datetime | str | None,
        duration: int | None,
        thumbnail: Path | None = None,
    ) -> Message:
        caption = build_channel_caption(title, url, published_at)

        async def send() -> Message:
            return await self.bot.send_audio(
                chat_id=chat_id,
                audio=FSInputFile(audio_path, filename=filename),
                caption=caption,
                parse_mode=ParseMode.HTML,
                title=truncate(title, 64),
                performer=truncate(performer or "AURIX MUSIC", 64),
                duration=duration,
                thumbnail=FSInputFile(thumbnail, filename="thumb.jpg") if thumbnail else None,
                reply_markup=youtube_button(url, "▶️ YouTube'da ko'rish"),
                request_timeout=UPLOAD_TIMEOUT,
            )

        return await call_with_retry(send)

    async def notify(self, chat_ids, text: str) -> None:
        for chat_id in chat_ids:
            try:
                await call_with_retry(
                    lambda cid=chat_id: self.bot.send_message(
                        cid, text, parse_mode=ParseMode.HTML,
                        link_preview_options=LinkPreviewOptions(is_disabled=True),
                    ),
                    attempts=2,
                )
            except Exception as exc:  # noqa: BLE001 - notifications are best effort
                log.warning("admin notification to %s failed: %s", chat_id, exc)
