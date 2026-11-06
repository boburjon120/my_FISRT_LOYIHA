"""Admin-only commands and control panel.

Only Telegram user IDs listed in ``ADMIN_IDS`` can use these commands.
"""

from __future__ import annotations

import logging

from aiogram import Bot, F, Router
from aiogram.enums import ChatMemberStatus, ChatType
from aiogram.filters import BaseFilter, Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, ChatMemberUpdated, Message, TelegramObject

from config import Settings
from database import Database
from keyboards import admin_panel_kb, destination_pick_kb
from monitor import ChannelMonitor
from queue_worker import DESTINATION_KEY, QueueWorker, get_destination
from telegram_service import TelegramPublisher
from utils.errors import AurixError
from utils.reports import LINE, admin_status_text, failed_text, queue_text, stats_text
from utils.text import esc
from utils.validators import is_valid_video_id, normalize_telegram_chat
from youtube_service import YouTubeService

log = logging.getLogger(__name__)

ADMIN_COMMANDS = (
    "admin",
    "set_source_channel",
    "set_destination_channel",
    "channel_status",
    "check_now",
    "queue",
    "failed",
    "retry",
    "stats",
    "restart_monitor",
)


class IsAdmin(BaseFilter):
    """Passes only for users listed in ADMIN_IDS."""

    async def __call__(self, event: TelegramObject, settings: Settings) -> bool:
        user = getattr(event, "from_user", None)
        return settings.is_admin(user.id if user else None)


class AdminStates(StatesGroup):
    waiting_source = State()
    waiting_destination = State()


# Order matters: protected admin handlers first, then the "access denied"
# fallback for everyone else.
router = Router(name="admin")
admin = Router(name="admin-protected")
admin.message.filter(IsAdmin())
admin.callback_query.filter(IsAdmin())
channel_events = Router(name="admin-channel-events")
denied = Router(name="admin-denied")
router.include_routers(admin, channel_events, denied)


# ------------------------------------------------------------------ helpers
async def apply_source(
    value: str, *, user_id: int, db: Database, youtube: YouTubeService, monitor: ChannelMonitor,
    settings: Settings,
) -> str:
    channel_id, title = await youtube.resolve_channel(value)
    await db.set_active_source(channel_id, title, f"https://www.youtube.com/channel/{channel_id}", user_id)
    result = await monitor.check_now()
    backfill = (
        f"🆕 Navbatga qo'shildi: <b>{len(result.queued)}</b> ta so'nggi video\n"
        if result and result.queued else ""
    )
    baseline = (
        f"📌 Mavjud {len(result.skipped_old)} ta video belgilandi (ular qayta joylanmaydi).\n"
        if result and result.baseline and result.skipped_old else ""
    )
    log.info("Admin %s set source channel %s (%s)", user_id, channel_id, title)
    return (
        "✅ <b>YouTube manba kanal o'rnatildi</b>\n"
        f"{LINE}\n"
        f"▶️ {esc(title)}\n"
        f"🆔 <code>{esc(channel_id)}</code>\n"
        f"{baseline}{backfill}"
        f"⏱ Har {settings.check_interval_seconds // 60} daqiqada yangi videolar tekshiriladi."
    )


async def apply_destination(
    value: str, *, user_id: int, db: Database, publisher: TelegramPublisher, worker: QueueWorker
) -> str:
    chat = normalize_telegram_chat(value)
    if chat is None:
        return (
            "⚠️ Kanal noto'g'ri ko'rsatildi.\n"
            "Masalan: <code>@aurix_music</code> yoki <code>-1001234567890</code>"
        )
    try:
        title = await publisher.check_destination(chat)
    except AurixError as exc:
        return (
            f"❌ {esc(exc.user_message)}\n\n"
            "1) Botni kanalga <b>administrator</b> qilib qo'shing\n"
            "2) «Post messages / Xabar joylash» huquqini yoqing\n"
            "3) Buyruqni qayta yuboring"
        )
    await db.set_setting(DESTINATION_KEY, chat)
    worker.wake()
    log.info("Admin %s set destination channel %s", user_id, chat)
    return f"✅ <b>Telegram kanal o'rnatildi</b>\n📢 {esc(title)}\n🆔 <code>{esc(chat)}</code>"


# ----------------------------------------------------------------- commands
@admin.message(Command("admin"))
async def cmd_admin(
    message: Message, settings: Settings, db: Database, monitor: ChannelMonitor, worker: QueueWorker
) -> None:
    destination = await get_destination(db, settings)
    await message.answer(
        await admin_status_text(settings, db, monitor, worker, destination), reply_markup=admin_panel_kb()
    )


@admin.message(Command("channel_status"))
async def cmd_status(
    message: Message, settings: Settings, db: Database, monitor: ChannelMonitor, worker: QueueWorker
) -> None:
    destination = await get_destination(db, settings)
    await message.answer(await admin_status_text(settings, db, monitor, worker, destination))


@admin.message(Command("set_source_channel"))
async def cmd_set_source(
    message: Message, command: CommandObject, state: FSMContext, settings: Settings,
    db: Database, youtube: YouTubeService, monitor: ChannelMonitor,
) -> None:
    if not command.args:
        await state.set_state(AdminStates.waiting_source)
        await message.answer(
            "▶️ Kuzatiladigan YouTube kanal havolasini yuboring:\n"
            "• <code>https://www.youtube.com/@kanal_nomi</code>\n"
            "• <code>https://www.youtube.com/channel/UC...</code>\n"
            "• yoki kanal ID: <code>UCxxxxxxxxxxxxxxxxxxxxxx</code>\n\n"
            "Bekor qilish: /cancel"
        )
        return
    await _set_source(message, command.args, settings, db, youtube, monitor)


@admin.message(AdminStates.waiting_source, F.text & ~F.text.startswith("/"))
async def state_source(
    message: Message, state: FSMContext, settings: Settings, db: Database,
    youtube: YouTubeService, monitor: ChannelMonitor,
) -> None:
    await state.clear()
    await _set_source(message, message.text or "", settings, db, youtube, monitor)


async def _set_source(message, value, settings, db, youtube, monitor) -> None:
    wait = await message.answer("🔎 Kanal tekshirilmoqda…")
    try:
        text = await apply_source(
            value.strip(), user_id=message.from_user.id, db=db, youtube=youtube, monitor=monitor,
            settings=settings,
        )
    except AurixError as exc:
        text = f"❌ {esc(exc.user_message)}\n<i>{esc(str(exc)[:200])}</i>"
    await wait.edit_text(text)


@admin.message(Command("set_destination_channel"))
async def cmd_set_destination(
    message: Message, command: CommandObject, state: FSMContext, db: Database,
    publisher: TelegramPublisher, worker: QueueWorker,
) -> None:
    if not command.args:
        await state.set_state(AdminStates.waiting_destination)
        await message.answer(
            "📢 Telegram kanal username yoki ID sini yuboring:\n"
            "• <code>@kanal_nomi</code>\n"
            "• <code>-1001234567890</code>\n\n"
            "💡 Maslahat: botni kanalga admin qilib qo'shsangiz, men sizga kanal ID sini "
            "o'zim yuboraman.\nBekor qilish: /cancel"
        )
        return
    text = await apply_destination(
        command.args, user_id=message.from_user.id, db=db, publisher=publisher, worker=worker
    )
    await message.answer(text)


@admin.message(AdminStates.waiting_destination, F.text & ~F.text.startswith("/"))
async def state_destination(
    message: Message, state: FSMContext, db: Database, publisher: TelegramPublisher, worker: QueueWorker
) -> None:
    await state.clear()
    text = await apply_destination(
        message.text or "", user_id=message.from_user.id, db=db, publisher=publisher, worker=worker
    )
    await message.answer(text)


@admin.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("❎ Bekor qilindi.")


@admin.message(Command("check_now"))
async def cmd_check_now(message: Message, monitor: ChannelMonitor) -> None:
    wait = await message.answer("🔄 Kanal tekshirilmoqda…")
    await wait.edit_text(await _check_now_text(monitor))


async def _check_now_text(monitor: ChannelMonitor) -> str:
    result = await monitor.check_now()
    if result is None:
        return f"⚠️ Tekshirib bo'lmadi: {esc(monitor.status.last_error or 'nomaʼlum xato')}"
    return (
        f"✅ <b>Tekshiruv tugadi</b> — {esc(result.channel_title)}\n"
        f"📄 RSS'dagi videolar: {result.total_entries}\n"
        f"🆕 Navbatga qo'shildi: <b>{len(result.queued)}</b>\n"
        f"♻️ Avval qayta ishlangan: {result.duplicates}\n"
        f"⏭ Eski (o'tkazildi): {len(result.skipped_old)}"
    )


@admin.message(Command("queue"))
async def cmd_queue(message: Message, db: Database, worker: QueueWorker) -> None:
    await message.answer(await queue_text(db, worker))


@admin.message(Command("failed"))
async def cmd_failed(message: Message, db: Database) -> None:
    await message.answer(await failed_text(db))


@admin.message(Command("retry"))
async def cmd_retry(message: Message, command: CommandObject, db: Database, worker: QueueWorker) -> None:
    arg = (command.args or "").strip()
    if arg == "all":
        count = await db.requeue_failed()
    elif is_valid_video_id(arg):
        count = await db.requeue_failed(arg)
    else:
        await message.answer("Foydalanish: <code>/retry VIDEO_ID</code> yoki <code>/retry all</code>")
        return
    worker.wake()
    await message.answer(f"♻️ Qayta navbatga qo'yildi: <b>{count}</b> ta video")


@admin.message(Command("stats"))
async def cmd_stats(message: Message, db: Database) -> None:
    await message.answer(await stats_text(db))


@admin.message(Command("restart_monitor"))
async def cmd_restart(message: Message, monitor: ChannelMonitor, worker: QueueWorker) -> None:
    await message.answer(await _restart(monitor, worker))


async def _restart(monitor: ChannelMonitor, worker: QueueWorker) -> str:
    await monitor.restart()
    if not worker.is_running:
        await worker.start()
    worker.wake()
    return "♻️ Monitoring qayta ishga tushirildi. Kanal hozir tekshirilmoqda."


# ----------------------------------------------------------- panel buttons
@admin.callback_query(F.data.startswith("adm:"))
async def on_admin_button(
    callback: CallbackQuery, settings: Settings, db: Database, monitor: ChannelMonitor,
    worker: QueueWorker, publisher: TelegramPublisher,
) -> None:
    action = (callback.data or "").split(":", 2)
    await callback.answer()
    name = action[1] if len(action) > 1 else ""
    destination = await get_destination(db, settings)
    if name == "status":
        text = await admin_status_text(settings, db, monitor, worker, destination)
    elif name == "check":
        text = await _check_now_text(monitor)
    elif name == "queue":
        text = await queue_text(db, worker)
    elif name == "stats":
        text = await stats_text(db)
    elif name == "failed":
        text = await failed_text(db)
    elif name == "restart":
        text = await _restart(monitor, worker)
    elif name == "setdest" and len(action) == 3:
        text = await apply_destination(
            action[2], user_id=callback.from_user.id, db=db, publisher=publisher, worker=worker
        )
    else:
        return
    if callback.message:
        await callback.message.answer(text)


# ----------------------------------------------- bot added to a channel
@channel_events.my_chat_member(F.chat.type == ChatType.CHANNEL)
async def on_bot_channel_membership(event: ChatMemberUpdated, bot: Bot, settings: Settings) -> None:
    status = event.new_chat_member.status
    title = esc(event.chat.title or event.chat.id)
    if status == ChatMemberStatus.ADMINISTRATOR:
        can_post = getattr(event.new_chat_member, "can_post_messages", False)
        text = (
            "📢 <b>Bot kanalga administrator qilindi</b>\n"
            f"{LINE}\n"
            f"Kanal: {title}\n"
            f"🆔 <code>{event.chat.id}</code>\n"
            f"✍️ Xabar joylash huquqi: {'✅ bor' if can_post else '❌ yoʻq — yoqib qoʻying!'}\n\n"
            "Shu kanalni manzil sifatida tanlash uchun tugmani bosing 👇"
        )
        markup = destination_pick_kb(event.chat.id)
    elif status in {ChatMemberStatus.LEFT, ChatMemberStatus.KICKED, ChatMemberStatus.MEMBER}:
        text = f"⚠️ Bot «{title}» kanalida endi administrator emas (<code>{event.chat.id}</code>)."
        markup = None
    else:
        return
    for admin_id in settings.admin_ids:
        try:
            await bot.send_message(admin_id, text, reply_markup=markup)
        except Exception as exc:  # noqa: BLE001
            log.warning("cannot notify admin %s: %s", admin_id, exc)


# ------------------------------------------- non-admins hitting admin cmds
@denied.message(Command(*ADMIN_COMMANDS))
async def not_admin(message: Message) -> None:
    await message.answer("⛔ Bu buyruq faqat AURIX administratorlari uchun.")


@denied.callback_query(F.data.startswith("adm:"))
async def not_admin_cb(callback: CallbackQuery) -> None:
    await callback.answer("⛔ Faqat adminlar uchun", show_alert=True)
