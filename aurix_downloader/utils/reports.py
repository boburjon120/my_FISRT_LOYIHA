"""Uzbek-language status / statistics texts shared by user and admin handlers."""

from __future__ import annotations

from typing import TYPE_CHECKING

from database import FAILED, PROCESSING, QUEUED
from utils.text import esc, format_size, truncate
from utils.timeutils import human_date

if TYPE_CHECKING:
    from config import Settings
    from database import Database
    from monitor import ChannelMonitor
    from queue_worker import QueueWorker

LINE = "━━━━━━━━━━━━━━━━━━"


def _flag(ok: bool) -> str:
    return "🟢 ishlayapti" if ok else "🔴 to'xtagan"


async def public_status_text(db: "Database", monitor: "ChannelMonitor", destination: str) -> str:
    source = await db.get_active_source()
    posts = await db.count_channel_posts()
    if source is None:
        src = "sozlanmagan"
    else:
        src = f'<a href="https://www.youtube.com/channel/{esc(source.channel_id)}">{esc(source.title or source.channel_id)}</a>'
    dest = esc(destination) if destination.startswith("@") else ("sozlangan" if destination else "sozlanmagan")
    return (
        f"📡 <b>AURIX kanal holati</b>\n{LINE}\n"
        f"▶️ YouTube manba: {src}\n"
        f"📢 Telegram kanal: {dest}\n"
        f"🛰 Monitoring: {_flag(monitor.is_running)}\n"
        f"🕒 Oxirgi tekshiruv: {human_date(monitor.status.last_success_at)}\n"
        f"🎵 Joylangan treklar: <b>{posts}</b>"
    )


async def admin_status_text(
    settings: "Settings", db: "Database", monitor: "ChannelMonitor", worker: "QueueWorker", destination: str
) -> str:
    source = await db.get_active_source()
    counts = await db.video_status_counts()
    if source:
        src = (
            f"{esc(source.title or '—')}\n"
            f"   🆔 <code>{esc(source.channel_id)}</code>\n"
            f"   ⚠️ Oxirgi xato: {esc(truncate(source.last_error or 'yo‘q', 150))}"
        )
    else:
        src = "❗️ sozlanmagan — /set_source_channel"
    current = (
        f"⚙️ Hozir: {esc(truncate(worker.status.current_title or worker.status.current_video or '', 60))}\n"
        if worker.status.current_video else ""
    )
    return (
        f"🛠 <b>AURIX — tizim holati</b>\n{LINE}\n"
        f"▶️ <b>Manba:</b> {src}\n"
        f"📢 <b>Telegram kanal:</b> <code>{esc(destination or 'sozlanmagan')}</code>\n"
        f"{LINE}\n"
        f"🛰 Monitor: {_flag(monitor.is_running)}\n"
        f"🧵 Navbat ishchisi: {_flag(worker.is_running)}\n"
        f"🕒 Oxirgi tekshiruv: {human_date(monitor.status.last_check_at)}\n"
        f"✅ Oxirgi muvaffaqiyat: {human_date(monitor.status.last_success_at)}\n"
        f"⏭ Keyingi tekshiruv: {human_date(monitor.status.next_check_at)}\n"
        f"⏱ Interval: {settings.check_interval_seconds // 60} daqiqa\n"
        f"{current}"
        f"{LINE}\n"
        f"📥 Navbatda: <b>{counts[QUEUED]}</b> | ⚙️ Jarayonda: <b>{counts[PROCESSING]}</b>\n"
        f"✅ Joylangan: <b>{counts['published']}</b> | ❌ Xato: <b>{counts[FAILED]}</b>"
    )


async def queue_text(db: "Database", worker: "QueueWorker") -> str:
    items = await db.list_videos((QUEUED, PROCESSING), limit=15)
    counts = await db.video_status_counts()
    lines = [f"📥 <b>Navbat</b> ({counts[QUEUED]} navbatda, {counts[PROCESSING]} jarayonda)", LINE]
    if not items:
        lines.append("Navbat bo'sh ✨")
    for v in items:
        icon = "⚙️" if v.status == PROCESSING else "⏳"
        extra = f" — urinish {v.attempts}" if v.attempts else ""
        when = f" (keyingi: {human_date(v.next_attempt_at)})" if v.status == QUEUED and v.attempts else ""
        lines.append(f"{icon} {esc(truncate(v.title or v.video_id, 50))}{extra}{when}")
        if v.last_error:
            lines.append(f"     ↳ <i>{esc(truncate(v.last_error, 90))}</i>")
    return "\n".join(lines)


async def failed_text(db: "Database") -> str:
    items = await db.list_videos((FAILED,), limit=10)
    lines = ["❌ <b>Muvaffaqiyatsiz videolar</b>", LINE]
    if not items:
        lines.append("Xatolar yo'q ✅")
    for v in items:
        lines.append(
            f"• {esc(truncate(v.title or v.video_id, 50))}\n"
            f"  🆔 <code>{esc(v.video_id)}</code> | urinish: {v.attempts}\n"
            f"  ⚠️ <i>{esc(truncate(v.last_error or '', 120))}</i>"
        )
    jobs = await db.list_failed_jobs(limit=5)
    user_jobs = [j for j in jobs if j["kind"] != "channel_mp3"]
    if user_jobs:
        lines += ["", "👤 <b>Foydalanuvchi yuklashlaridagi so'nggi xatolar:</b>"]
        for j in user_jobs:
            lines.append(f"• {esc(j['kind'])} <code>{esc(j['video_id'])}</code>: {esc(truncate(j['error'] or '', 80))}")
    if items:
        lines += ["", "♻️ Qayta urinish: <code>/retry VIDEO_ID</code> yoki <code>/retry all</code>"]
    return "\n".join(lines)


async def stats_text(db: "Database") -> str:
    stats = await db.get_stats()
    counts = await db.video_status_counts()
    users = await db.count_users()
    return (
        f"📊 <b>AURIX statistikasi</b>\n{LINE}\n"
        f"👥 Foydalanuvchilar: <b>{users}</b>\n"
        f"🔎 Aniqlangan yangi videolar: <b>{stats.get('videos_detected', 0)}</b>\n"
        f"✅ Kanalga joylangan MP3: <b>{counts['published']}</b>\n"
        f"❌ Muvaffaqiyatsiz: <b>{counts[FAILED]}</b>\n"
        f"⏭ O'tkazib yuborilgan (eski): <b>{counts['skipped']}</b>\n"
        f"📥 Navbatda: <b>{counts[QUEUED]}</b>\n"
        f"{LINE}\n"
        f"🎵 Foydalanuvchi MP3: <b>{stats.get('user_mp3', 0)}</b>\n"
        f"🎬 Foydalanuvchi MP4: <b>{stats.get('user_mp4', 0)}</b>\n"
        f"📸 Instagram MP4 / MP3: <b>{stats.get('instagram_mp4', 0)}</b> / <b>{stats.get('instagram_mp3', 0)}</b>\n"
        f"💾 Kanalga yuborilgan hajm: <b>{format_size(stats.get('bytes_published', 0))}</b>"
    )
