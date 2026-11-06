from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def video_actions_kb(video_id: str, url: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🎵 MP3 yuklab olish", callback_data=f"dl:mp3:{video_id}"),
                InlineKeyboardButton(text="🎬 MP4 yuklab olish", callback_data=f"dl:mp4:{video_id}"),
            ],
            [InlineKeyboardButton(text="▶️ YouTube'da tinglash / ko'rish", url=url)],
        ]
    )


def admin_panel_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="📡 Holat", callback_data="adm:status"),
                InlineKeyboardButton(text="🔄 Hozir tekshirish", callback_data="adm:check"),
            ],
            [
                InlineKeyboardButton(text="📥 Navbat", callback_data="adm:queue"),
                InlineKeyboardButton(text="📊 Statistika", callback_data="adm:stats"),
            ],
            [
                InlineKeyboardButton(text="❌ Xatolar", callback_data="adm:failed"),
                InlineKeyboardButton(text="♻️ Monitorni qayta ishga tushirish", callback_data="adm:restart"),
            ],
        ]
    )


def destination_pick_kb(chat_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✅ Shu kanalga joylash", callback_data=f"adm:setdest:{chat_id}")]
        ]
    )
