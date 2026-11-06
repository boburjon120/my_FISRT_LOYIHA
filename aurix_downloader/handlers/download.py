"""User-facing YouTube link handling and MP3/MP4 downloads."""

from __future__ import annotations

import asyncio
import logging
import shutil
from typing import Any

from aiogram import Bot, F, Router
from aiogram.enums import ChatAction
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, FSInputFile, Message
from aiogram.utils.chat_action import ChatActionSender

from audio_service import AudioService
from config import Settings
from database import Database
from keyboards import video_actions_kb
from telegram_service import build_user_caption, call_with_retry, youtube_button
from utils.cache import TTLCache
from utils.errors import AurixError
from utils.limiter import UserLimiter
from utils.reports import LINE
from utils.text import esc, format_duration, format_size, truncate
from utils.timeutils import human_date
from utils.validators import find_youtube_url, is_valid_video_id
from video_service import VideoService
from youtube_service import VideoInfo, YouTubeService

log = logging.getLogger(__name__)
router = Router(name="download")

info_cache: TTLCache[tuple[VideoInfo, dict[str, Any]]] = TTLCache(ttl=600, max_items=200)


async def get_info_cached(youtube: YouTubeService, video_id: str) -> tuple[VideoInfo, dict[str, Any]]:
    cached = info_cache.get(video_id)
    if cached is not None:
        return cached
    result = await youtube.get_video_info(video_id)
    info_cache.set(video_id, result)
    return result


def video_card(info: VideoInfo) -> str:
    return (
        f"🎬 <b>{esc(truncate(info.title, 200))}</b>\n"
        f"{LINE}\n"
        f"👤 Kanal: {esc(info.uploader or '—')}\n"
        f"⏱ Davomiyligi: {format_duration(info.duration)}\n"
        f"📅 Sana: {human_date(info.upload_date)}\n"
        f"{LINE}\n"
        "👇 Formatni tanlang:"
    )


@router.message(F.text & ~F.text.startswith("/"))
async def on_text(message: Message, youtube: YouTubeService) -> None:
    text = message.text or ""
    video_id = find_youtube_url(text)
    if video_id is None:
        if "http" in text or "www." in text or ".com" in text or ".be/" in text:
            await message.answer(
                "⚠️ Bu YouTube video havolasi emas.\n"
                "Faqat <b>youtube.com</b> va <b>youtu.be</b> havolalari qabul qilinadi."
            )
        else:
            await message.answer("🔗 YouTube video havolasini yuboring. Yordam: /help")
        return

    status = await message.answer("🔎 Video ma'lumotlari olinmoqda…")
    try:
        info, _ = await get_info_cached(youtube, video_id)
    except AurixError as exc:
        log.info("info failed for %s: %s", video_id, exc)
        await status.edit_text(f"❌ {esc(exc.user_message)}")
        return
    except Exception:  # noqa: BLE001
        log.exception("unexpected info error for %s", video_id)
        await status.edit_text("❌ Kutilmagan xatolik. Keyinroq urinib ko'ring.")
        return

    keyboard = video_actions_kb(info.video_id, info.url)
    try:
        await message.answer_photo(info.thumbnail_url, caption=video_card(info), reply_markup=keyboard)
    except TelegramBadRequest:
        await message.answer(video_card(info), reply_markup=keyboard)
    try:
        await status.delete()
    except TelegramBadRequest:
        pass


@router.callback_query(F.data.startswith("dl:"))
async def on_download(
    callback: CallbackQuery,
    bot: Bot,
    settings: Settings,
    db: Database,
    youtube: YouTubeService,
    audio: AudioService,
    video: VideoService,
    download_semaphore: asyncio.Semaphore,
    user_limiter: UserLimiter,
) -> None:
    parts = (callback.data or "").split(":")
    if len(parts) != 3 or parts[1] not in {"mp3", "mp4"} or not is_valid_video_id(parts[2]):
        await callback.answer("Noto'g'ri so'rov", show_alert=True)
        return
    kind, video_id = parts[1], parts[2]
    user_id = callback.from_user.id
    chat_id = callback.message.chat.id if callback.message else user_id

    ok, wait = user_limiter.try_acquire(user_id, bypass_cooldown=settings.is_admin(user_id))
    if not ok:
        msg = (
            "⏳ Avvalgi yuklash hali tugamadi, iltimos kuting."
            if wait == 0 else f"⏳ Juda tez! {int(wait) + 1} soniyadan so'ng urinib ko'ring."
        )
        await callback.answer(msg, show_alert=True)
        return

    await callback.answer("⏳ Boshlandi…")
    label = "MP3" if kind == "mp3" else "MP4"
    progress = await bot.send_message(chat_id, f"⏳ <b>{label}</b> tayyorlanmoqda…")
    job_id = await db.create_job(video_id, f"user_{kind}", user_id)
    workdir = settings.download_dir / f"user_{user_id}_{job_id}"
    try:
        info, raw = await get_info_cached(youtube, video_id)
        if download_semaphore.locked():
            await progress.edit_text("🕐 Navbatdasiz… Server band, birozdan so'ng boshlanadi.")
        async with download_semaphore:
            await progress.edit_text(f"⬇️ <b>{label}</b> yuklanmoqda va tayyorlanmoqda…")
            if kind == "mp3":
                result = await audio.create_mp3(
                    info, raw, workdir, max_duration_minutes=settings.user_max_duration_minutes
                )
            else:
                result = await video.create_mp4(
                    info, raw, workdir, max_duration_minutes=settings.user_max_duration_minutes
                )
        await progress.edit_text(f"📤 Telegram'ga yuborilmoqda… ({format_size(result.size)})")

        if kind == "mp3":
            caption = build_user_caption(info.title, info.url, f"🎚 {result.bitrate_kbps} kbps • {format_size(result.size)}\n")
            async with ChatActionSender(bot=bot, chat_id=chat_id, action=ChatAction.UPLOAD_VOICE):
                await call_with_retry(lambda: bot.send_audio(
                    chat_id,
                    FSInputFile(result.path, filename=result.filename),
                    caption=caption,
                    title=truncate(info.title, 64),
                    performer=truncate(info.uploader or "AURIX", 64),
                    duration=result.duration,
                    thumbnail=FSInputFile(result.thumbnail) if result.thumbnail else None,
                    reply_markup=youtube_button(info.url),
                    request_timeout=600,
                ))
        else:
            caption = build_user_caption(info.title, info.url, f"📺 {result.height}p • {format_size(result.size)}\n")
            async with ChatActionSender(bot=bot, chat_id=chat_id, action=ChatAction.UPLOAD_VIDEO):
                await call_with_retry(lambda: bot.send_video(
                    chat_id,
                    FSInputFile(result.path, filename=result.filename),
                    caption=caption,
                    duration=result.duration,
                    width=result.width,
                    height=result.video_height,
                    supports_streaming=True,
                    reply_markup=youtube_button(info.url),
                    request_timeout=900,
                ))
        await db.finish_job(job_id, "done", file_size=result.size)
        await db.incr_stat(f"user_{kind}")
        await db.increment_user_downloads(user_id)
        try:
            await progress.delete()
        except TelegramBadRequest:
            pass
    except AurixError as exc:
        log.info("user download %s/%s failed: %s", kind, video_id, exc)
        await db.finish_job(job_id, "failed", str(exc))
        await _safe_edit(progress, f"❌ {esc(exc.user_message)}")
    except Exception as exc:  # noqa: BLE001
        log.exception("unexpected user download error %s/%s", kind, video_id)
        await db.finish_job(job_id, "failed", f"unexpected: {exc}")
        await _safe_edit(progress, "❌ Kutilmagan xatolik yuz berdi. Keyinroq urinib ko'ring.")
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
        user_limiter.release(user_id)


async def _safe_edit(message: Message, text: str) -> None:
    try:
        await message.edit_text(text)
    except TelegramBadRequest:
        pass
