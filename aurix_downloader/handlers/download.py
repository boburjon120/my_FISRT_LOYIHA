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
from instagram_service import InstagramService
from keyboards import video_actions_kb
from keyboards.inline import OPEN_TEXT
from telegram_service import build_user_caption, call_with_retry, youtube_button
from utils.cache import TTLCache
from utils.errors import AurixError
from utils.limiter import UserLimiter
from utils.reports import LINE
from utils.text import esc, format_duration, format_size, truncate
from utils.timeutils import human_date
from utils.validators import find_media, is_valid_instagram_code, is_valid_video_id
from video_service import VideoService
from youtube_service import VideoInfo, YouTubeService

log = logging.getLogger(__name__)
router = Router(name="download")

info_cache: TTLCache[tuple[VideoInfo, dict[str, Any]]] = TTLCache(ttl=600, max_items=200)


PLATFORM_BY_CODE = {"yt": "youtube", "ig": "instagram"}


async def get_info_cached(
    service: YouTubeService, video_id: str, platform: str = "youtube"
) -> tuple[VideoInfo, dict[str, Any]]:
    key = f"{platform}:{video_id}"
    cached = info_cache.get(key)
    if cached is not None:
        return cached
    result = await service.get_video_info(video_id)
    info_cache.set(key, result)
    return result


def video_card(info: VideoInfo) -> str:
    if info.platform == "instagram":
        header, who = "📸 <b>Instagram</b>\n", "👤 Muallif"
    else:
        header, who = "", "👤 Kanal"
    return (
        f"{header}🎬 <b>{esc(truncate(info.title, 200))}</b>\n"
        f"{LINE}\n"
        f"{who}: {esc(info.uploader or '—')}\n"
        f"⏱ Davomiyligi: {format_duration(info.duration)}\n"
        f"📅 Sana: {human_date(info.upload_date)}\n"
        f"{LINE}\n"
        "👇 Formatni tanlang:"
    )


@router.message(F.text & ~F.text.startswith("/"))
async def on_text(message: Message, youtube: YouTubeService, instagram: InstagramService) -> None:
    text = message.text or ""
    media = find_media(text)
    if media is None:
        if "http" in text or "www." in text or ".com" in text or ".be/" in text:
            await message.answer(
                "⚠️ Bu havolani qo'llab-quvvatlamayman.\n"
                "Qabul qilinadi: <b>YouTube</b> (youtube.com, youtu.be) va "
                "<b>Instagram</b> post / reels (instagram.com/p/…, /reel/…)."
            )
        else:
            await message.answer("🔗 YouTube yoki Instagram video havolasini yuboring. Yordam: /help")
        return

    platform, video_id = media
    service = instagram if platform == "instagram" else youtube
    status = await message.answer("🔎 Video ma'lumotlari olinmoqda…")
    try:
        info, _ = await get_info_cached(service, video_id, platform)
    except AurixError as exc:
        log.info("info failed for %s:%s: %s", platform, video_id, exc)
        await status.edit_text(f"❌ {esc(exc.user_message)}")
        return
    except Exception:  # noqa: BLE001
        log.exception("unexpected info error for %s:%s", platform, video_id)
        await status.edit_text("❌ Kutilmagan xatolik. Keyinroq urinib ko'ring.")
        return

    keyboard = video_actions_kb(info.video_id, info.url, info.platform)
    sent = False
    if info.thumbnail_url:
        try:
            await message.answer_photo(info.thumbnail_url, caption=video_card(info), reply_markup=keyboard)
            sent = True
        except TelegramBadRequest:
            pass
    if not sent:
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
    instagram: InstagramService,
    audio: AudioService,
    video: VideoService,
    download_semaphore: asyncio.Semaphore,
    user_limiter: UserLimiter,
) -> None:
    parts = (callback.data or "").split(":")
    if len(parts) == 3:  # old buttons: dl:mp3:VIDEO_ID (YouTube)
        parts = [parts[0], parts[1], "yt", parts[2]]
    platform = PLATFORM_BY_CODE.get(parts[2]) if len(parts) == 4 else None
    valid_id = (
        is_valid_instagram_code(parts[3]) if platform == "instagram"
        else platform == "youtube" and is_valid_video_id(parts[3])
    ) if platform else False
    if len(parts) != 4 or parts[1] not in {"mp3", "mp4"} or not valid_id:
        await callback.answer("Noto'g'ri so'rov", show_alert=True)
        return
    kind, video_id = parts[1], parts[3]
    service = instagram if platform == "instagram" else youtube
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
    job_id = await db.create_job(video_id, f"user_{kind}" if platform == "youtube" else f"ig_{kind}", user_id)
    workdir = settings.download_dir / f"user_{user_id}_{job_id}"
    try:
        info, raw = await get_info_cached(service, video_id, platform)
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
            caption = build_user_caption(
                info.title, info.url, f"🎚 {result.bitrate_kbps} kbps • {format_size(result.size)}\n", info.platform
            )
            async with ChatActionSender(bot=bot, chat_id=chat_id, action=ChatAction.UPLOAD_VOICE):
                await call_with_retry(lambda: bot.send_audio(
                    chat_id,
                    FSInputFile(result.path, filename=result.filename),
                    caption=caption,
                    title=truncate(info.title, 64),
                    performer=truncate(info.uploader or "AURIX", 64),
                    duration=result.duration,
                    thumbnail=FSInputFile(result.thumbnail) if result.thumbnail else None,
                    reply_markup=youtube_button(info.url, OPEN_TEXT[info.platform]),
                    request_timeout=600,
                ))
        else:
            quality = f"{result.width}×{result.video_height}" if result.width else f"{result.height}p"
            caption = build_user_caption(
                info.title, info.url, f"📺 {quality} • {format_size(result.size)}\n", info.platform
            )
            async with ChatActionSender(bot=bot, chat_id=chat_id, action=ChatAction.UPLOAD_VIDEO):
                await call_with_retry(lambda: bot.send_video(
                    chat_id,
                    FSInputFile(result.path, filename=result.filename),
                    caption=caption,
                    duration=result.duration,
                    width=result.width,
                    height=result.video_height,
                    supports_streaming=True,
                    reply_markup=youtube_button(info.url, OPEN_TEXT[info.platform]),
                    request_timeout=900,
                ))
        await db.finish_job(job_id, "done", file_size=result.size)
        await db.incr_stat(f"user_{kind}" if platform == "youtube" else f"instagram_{kind}")
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
