from aiogram.types import KeyboardButton, ReplyKeyboardMarkup

BTN_MP3 = "🎵 YouTube MP3"
BTN_VIDEO = "🎬 YouTube Video"
BTN_STATUS = "📡 Kanal holati"
BTN_ABOUT = "ℹ️ Bot haqida"


def main_menu_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=BTN_MP3), KeyboardButton(text=BTN_VIDEO)],
            [KeyboardButton(text=BTN_STATUS), KeyboardButton(text=BTN_ABOUT)],
        ],
        resize_keyboard=True,
        input_field_placeholder="YouTube havolasini yuboring…",
    )
