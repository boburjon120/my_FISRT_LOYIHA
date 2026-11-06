"""aiogram middlewares."""

from __future__ import annotations

import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, User

from database import Database

log = logging.getLogger(__name__)


class UserTrackingMiddleware(BaseMiddleware):
    """Save/update users in the database (at most once per minute per user)."""

    def __init__(self, db: Database) -> None:
        self.db = db
        self._seen: dict[int, float] = {}

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user: User | None = data.get("event_from_user")
        if user is not None and not user.is_bot:
            now = time.monotonic()
            if now - self._seen.get(user.id, 0) > 60:
                self._seen[user.id] = now
                try:
                    await self.db.upsert_user(user.id, user.username, user.full_name, user.language_code)
                except Exception:  # noqa: BLE001 - never block the update
                    log.exception("failed to save user %s", user.id)
        return await handler(event, data)
