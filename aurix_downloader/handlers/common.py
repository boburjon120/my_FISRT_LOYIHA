"""/start, /help, main menu buttons."""

from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import Message

from config import Settings
from database import Database
from keyboards import BTN_ABOUT, BTN_MP3, BTN_STATUS, BTN_VIDEO, main_menu_kb
from monitor import ChannelMonitor
from queue_worker import get_destination
from utils.reports import LINE, public_status_text
from utils.text import esc

router = Router(name="common")

WELCOME = (
    "⚡ <b>AURIX Downloader</b>ga xush kelibsiz, {name}!\n"
    f"{LINE}\n"
    "🎵 YouTube videolarini <b>MP3</b> qilib yuklab oling\n"
    "🎬 Videolarni <b>MP4</b> formatda oling\n"
    "📡 Kanalimizga yangi treklar <b>avtomatik</b> joylanadi\n"
    f"{LINE}\n"
    "👇 Boshlash uchun YouTube havolasini yuboring yoki menyudan tanlang."
)

USER_HELP = (
    "❓ <b>Qanday foydalaniladi?</b>\n"
    f"{LINE}\n"
    "1️⃣ YouTube'dan video havolasini nusxalang\n"
    "2️⃣ Havolani shu yerga yuboring\n"
    "3️⃣ 🎵 MP3 yoki 🎬 MP4 tugmasini bosing\n\n"
    "📌 Qo'llab-quvvatlanadi: youtube.com/watch, youtu.be, shorts\n"
    "📌 Faqat ochiq (public) videolar yuklanadi\n"
    "📌 Telegram limiti: {limit} MB"
)

ADMIN_HELP = (
    "\n\n🛠 <b>Admin buyruqlari</b>\n"
    "/admin — boshqaruv paneli\n"
    "/set_source_channel — YouTube manba kanalni o'rnatish\n"
    "/set_destination_channel — Telegram kanalni o'rnatish\n"
    "/channel_status — monitoring holati\n"
    "/check_now — kanalni hozir tekshirish\n"
    "/queue — navbat holati\n"
    "/failed — xatolik bilan tugagan videolar\n"
    "/retry ID|all — xatolarni qayta navbatga qo'yish\n"
    "/stats — statistika\n"
    "/restart_monitor — monitorni qayta ishga tushirish"
)

ABOUT = (
    "💠 <b>AURIX Downloader</b>\n"
    f"{LINE}\n"
    "Zamonaviy YouTube → Telegram audio platformasi.\n\n"
    "🛰 YouTube kanalini 24/7 kuzatadi\n"
    "🎧 Yangi videolarni 192 kbps MP3 ga aylantiradi\n"
    "📢 Telegram kanalga avtomatik joylaydi\n"
    "🔒 Faqat ochiq va ruxsat berilgan kontent bilan ishlaydi\n"
    f"{LINE}\n"
    "⚡ <i>Powered by AURIX Downloader</i>"
)


@router.message(CommandStart())
async def cmd_start(message: Message, settings: Settings) -> None:
    name = esc(message.from_user.first_name if message.from_user else "do'st")
    text = WELCOME.format(name=name)
    if message.from_user and settings.is_admin(message.from_user.id):
        text += "\n\n🛠 Siz adminsiz: /admin"
    await message.answer(text, reply_markup=main_menu_kb())


@router.message(Command("help"))
async def cmd_help(message: Message, settings: Settings) -> None:
    text = USER_HELP.format(limit=settings.upload_limit_mb)
    if message.from_user and settings.is_admin(message.from_user.id):
        text += ADMIN_HELP
    await message.answer(text, reply_markup=main_menu_kb())


@router.message(F.text == BTN_MP3)
async def btn_mp3(message: Message) -> None:
    await message.answer(
        "🎵 <b>YouTube → MP3</b>\n\nVideo havolasini yuboring, so'ng «🎵 MP3 yuklab olish» tugmasini bosing.\n"
        "Masalan: <code>https://youtu.be/xxxxxxxxxxx</code>"
    )


@router.message(F.text == BTN_VIDEO)
async def btn_video(message: Message) -> None:
    await message.answer(
        "🎬 <b>YouTube → MP4</b>\n\nVideo havolasini yuboring, so'ng «🎬 MP4 yuklab olish» tugmasini bosing.\n"
        "Katta videolar Telegram limitiga sig'ishi uchun sifati avtomatik tanlanadi."
    )


@router.message(F.text == BTN_STATUS)
async def btn_status(message: Message, db: Database, monitor: ChannelMonitor, settings: Settings) -> None:
    destination = await get_destination(db, settings)
    await message.answer(await public_status_text(db, monitor, destination))


@router.message(F.text == BTN_ABOUT)
async def btn_about(message: Message) -> None:
    await message.answer(ABOUT)
