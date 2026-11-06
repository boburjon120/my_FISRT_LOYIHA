"""Application configuration loaded from environment variables (.env)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent

# Telegram Bot API (cloud) limit for files uploaded by bots.
DEFAULT_UPLOAD_LIMIT_MB = 50


class ConfigError(RuntimeError):
    """Raised when required configuration is missing or invalid."""


def _int(name: str, default: int, minimum: int | None = None) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ConfigError(f"{name} butun son bo'lishi kerak (hozir: {raw!r})") from exc
    if minimum is not None and value < minimum:
        raise ConfigError(f"{name} kamida {minimum} bo'lishi kerak")
    return value


def _bool(name: str, default: bool) -> bool:
    raw = os.getenv(name, "").strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on", "ha"}


def _path(name: str, default: Path) -> Path:
    raw = os.getenv(name, "").strip()
    path = Path(raw) if raw else default
    if not path.is_absolute():
        path = BASE_DIR / path
    return path


def _admin_ids(raw: str) -> frozenset[int]:
    ids: set[int] = set()
    for part in raw.replace(";", ",").split(","):
        part = part.strip()
        if not part:
            continue
        try:
            ids.add(int(part))
        except ValueError as exc:
            raise ConfigError(f"ADMIN_IDS ichida noto'g'ri ID: {part!r}") from exc
    return frozenset(ids)


@dataclass(frozen=True)
class Settings:
    bot_token: str
    admin_ids: frozenset[int]
    telegram_channel_id: str = ""
    youtube_channel: str = ""

    check_interval_seconds: int = 300
    lookback_hours: int = 48
    initial_backfill_count: int = 0

    audio_bitrate_kbps: int = 192
    min_audio_bitrate_kbps: int = 64
    max_concurrent_downloads: int = 2
    max_retries: int = 5
    retry_base_delay_seconds: int = 60
    channel_max_duration_minutes: int = 240
    user_max_duration_minutes: int = 120
    user_rate_limit_seconds: int = 20

    upload_limit_mb: int = DEFAULT_UPLOAD_LIMIT_MB
    telegram_api_url: str = ""
    ytdlp_cookies_file: str = ""
    notify_admins_on_failure: bool = True

    database_path: Path = field(default_factory=lambda: BASE_DIR / "data" / "aurix.db")
    download_dir: Path = field(default_factory=lambda: BASE_DIR / "downloads")
    log_dir: Path = field(default_factory=lambda: BASE_DIR / "logs")
    log_level: str = "INFO"
    http_port: int = 0  # >0 starts the /health web server (Render sets PORT)

    @property
    def upload_limit_bytes(self) -> int:
        return self.upload_limit_mb * 1024 * 1024

    def is_admin(self, user_id: int | None) -> bool:
        return user_id is not None and user_id in self.admin_ids


def load_settings(env_file: str | os.PathLike[str] | None = None) -> Settings:
    """Read settings from the environment (and optional .env file)."""
    load_dotenv(env_file or BASE_DIR / ".env", override=False)

    token = os.getenv("BOT_TOKEN", "").strip()
    if not token or token.startswith("PUT_"):
        raise ConfigError(
            "BOT_TOKEN topilmadi. .env.example faylini .env nomi bilan nusxalang "
            "va @BotFather bergan tokenni yozing."
        )
    admins = _admin_ids(os.getenv("ADMIN_IDS", ""))
    if not admins:
        raise ConfigError("ADMIN_IDS bo'sh. Kamida bitta admin Telegram ID kiriting.")

    telegram_api_url = os.getenv("TELEGRAM_API_URL", "").strip()
    default_limit = 2000 if telegram_api_url else DEFAULT_UPLOAD_LIMIT_MB

    return Settings(
        bot_token=token,
        admin_ids=admins,
        telegram_channel_id=os.getenv("TELEGRAM_CHANNEL_ID", "").strip(),
        youtube_channel=os.getenv("YOUTUBE_CHANNEL", "").strip(),
        check_interval_seconds=_int("CHECK_INTERVAL_SECONDS", 300, minimum=60),
        lookback_hours=_int("LOOKBACK_HOURS", 48, minimum=1),
        initial_backfill_count=_int("INITIAL_BACKFILL_COUNT", 0, minimum=0),
        audio_bitrate_kbps=_int("AUDIO_BITRATE_KBPS", 192, minimum=32),
        min_audio_bitrate_kbps=_int("MIN_AUDIO_BITRATE_KBPS", 64, minimum=32),
        max_concurrent_downloads=_int("MAX_CONCURRENT_DOWNLOADS", 2, minimum=1),
        max_retries=_int("MAX_RETRIES", 5, minimum=1),
        retry_base_delay_seconds=_int("RETRY_BASE_DELAY_SECONDS", 60, minimum=1),
        channel_max_duration_minutes=_int("CHANNEL_MAX_DURATION_MINUTES", 240, minimum=1),
        user_max_duration_minutes=_int("USER_MAX_DURATION_MINUTES", 120, minimum=1),
        user_rate_limit_seconds=_int("USER_RATE_LIMIT_SECONDS", 20, minimum=0),
        upload_limit_mb=_int("UPLOAD_LIMIT_MB", default_limit, minimum=1),
        telegram_api_url=telegram_api_url,
        ytdlp_cookies_file=os.getenv("YTDLP_COOKIES_FILE", "").strip(),
        notify_admins_on_failure=_bool("NOTIFY_ADMINS_ON_FAILURE", True),
        database_path=_path("DATABASE_PATH", BASE_DIR / "data" / "aurix.db"),
        download_dir=_path("DOWNLOAD_DIR", BASE_DIR / "downloads"),
        log_dir=_path("LOG_DIR", BASE_DIR / "logs"),
        log_level=os.getenv("LOG_LEVEL", "INFO").strip().upper() or "INFO",
        http_port=_int("PORT", 0, minimum=0),
    )
