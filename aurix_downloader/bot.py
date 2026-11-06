"""AURIX Downloader — entry point.

Starts the Telegram bot (long polling), the YouTube channel monitor and the
persistent publishing queue. Everything starts automatically on boot.
"""

from __future__ import annotations

import asyncio
import logging
import shutil
import sys

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.client.telegram import TelegramAPIServer
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramUnauthorizedError
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand, BotCommandScopeChat, BotCommandScopeDefault, LinkPreviewOptions

import admin
from audio_service import AudioService, ffmpeg_available
from config import ConfigError, Settings, load_settings
from database import Database
from handlers import common, download
from instagram_service import InstagramService
from monitor import ChannelMonitor
from queue_worker import QueueWorker
from telegram_service import TelegramPublisher
from utils.limiter import UserLimiter
from utils.logging_setup import setup_logging
from utils.middlewares import UserTrackingMiddleware
from video_service import VideoService
from web_server import HealthServer
from youtube_service import YouTubeService

log = logging.getLogger("aurix")

USER_COMMANDS = [
    BotCommand(command="start", description="Botni ishga tushirish"),
    BotCommand(command="help", description="Yordam"),
]
ADMIN_COMMANDS = USER_COMMANDS + [
    BotCommand(command="admin", description="Admin panel"),
    BotCommand(command="set_source_channel", description="YouTube manba kanal"),
    BotCommand(command="set_destination_channel", description="Telegram kanal"),
    BotCommand(command="channel_status", description="Monitoring holati"),
    BotCommand(command="check_now", description="Hozir tekshirish"),
    BotCommand(command="queue", description="Navbat"),
    BotCommand(command="failed", description="Xatoliklar"),
    BotCommand(command="stats", description="Statistika"),
    BotCommand(command="restart_monitor", description="Monitorni qayta ishga tushirish"),
]


def create_bot(settings: Settings) -> Bot:
    session = None
    if settings.telegram_api_url:
        session = AiohttpSession(api=TelegramAPIServer.from_base(settings.telegram_api_url, is_local=True))
    return Bot(
        token=settings.bot_token,
        session=session,
        default=DefaultBotProperties(
            parse_mode=ParseMode.HTML, link_preview=LinkPreviewOptions(is_disabled=True)
        ),
    )


def setup_dispatcher(dp: Dispatcher, db: Database) -> Dispatcher:
    """Register middlewares and routers (order matters: admin first)."""
    tracker = UserTrackingMiddleware(db)
    dp.message.outer_middleware(tracker)
    dp.callback_query.outer_middleware(tracker)
    dp.include_routers(admin.router, common.router, download.router)
    return dp


def clean_download_dir(settings: Settings) -> None:
    """Remove temporary files left behind by a crash."""
    settings.download_dir.mkdir(parents=True, exist_ok=True)
    for item in settings.download_dir.iterdir():
        if item.name.startswith("."):
            continue
        if item.is_dir():
            shutil.rmtree(item, ignore_errors=True)
        else:
            item.unlink(missing_ok=True)


async def set_commands(bot: Bot, settings: Settings) -> None:
    await bot.set_my_commands(USER_COMMANDS, scope=BotCommandScopeDefault())
    for admin_id in settings.admin_ids:
        try:
            await bot.set_my_commands(ADMIN_COMMANDS, scope=BotCommandScopeChat(chat_id=admin_id))
        except Exception as exc:  # noqa: BLE001 - admin may not have started the bot yet
            log.info("Cannot set admin commands for %s yet: %s", admin_id, exc)


async def run(settings: Settings) -> None:
    if not ffmpeg_available():
        log.critical("FFmpeg topilmadi! O'rnating: sudo apt install ffmpeg")
        sys.exit(1)

    clean_download_dir(settings)
    db = Database(settings.database_path)
    await db.connect()

    bot = create_bot(settings)
    youtube = YouTubeService(settings)
    instagram = InstagramService(settings)
    audio = AudioService(settings, youtube, instagram)
    video = VideoService(settings, youtube, instagram)
    publisher = TelegramPublisher(bot)
    semaphore = asyncio.Semaphore(settings.max_concurrent_downloads)
    worker = QueueWorker(settings, db, youtube, audio, publisher, semaphore)
    monitor = ChannelMonitor(settings, db, youtube, on_new_videos=worker.wake)

    dp = Dispatcher(
        storage=MemoryStorage(),
        settings=settings,
        db=db,
        youtube=youtube,
        instagram=instagram,
        audio=audio,
        video=video,
        publisher=publisher,
        worker=worker,
        monitor=monitor,
        download_semaphore=semaphore,
        user_limiter=UserLimiter(settings.user_rate_limit_seconds),
    )
    setup_dispatcher(dp, db)

    async def on_startup() -> None:
        me = await bot.get_me()
        log.info("Bot @%s started", me.username)
        await set_commands(bot, settings)
        await worker.start()
        monitor.start()

    async def on_shutdown() -> None:
        log.info("Shutting down…")
        await monitor.stop()
        await worker.stop()

    dp.startup.register(on_startup)
    dp.shutdown.register(on_shutdown)

    # Optional /health web server (needed on Render-like hosts that set $PORT).
    health = HealthServer(monitor, worker, settings.http_port) if settings.http_port else None
    if health:
        await health.start()

    try:
        await bot.delete_webhook(drop_pending_updates=False)
        await dp.start_polling(
            bot,
            allowed_updates=dp.resolve_used_update_types(),
            handle_signals=True,
        )
    except TelegramUnauthorizedError:
        log.critical("BOT_TOKEN noto'g'ri (Telegram: Unauthorized). .env faylini tekshiring.")
        raise SystemExit(3) from None
    finally:
        if health:
            await health.stop()
        await monitor.stop()
        await worker.stop()
        await youtube.close()
        await instagram.close()
        await db.close()
        await bot.session.close()


def main() -> None:
    try:
        settings = load_settings()
    except ConfigError as exc:
        print(f"❌ Sozlama xatosi: {exc}", file=sys.stderr)
        sys.exit(2)
    setup_logging(settings.log_dir, settings.log_level)
    log.info("AURIX Downloader is starting")
    try:
        asyncio.run(run(settings))
    except KeyboardInterrupt:
        pass
    log.info("AURIX Downloader stopped")


if __name__ == "__main__":
    main()
