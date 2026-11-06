"""Per-user download limiter: one active download per user + cooldown."""

from __future__ import annotations

import time


class UserLimiter:
    def __init__(self, cooldown_seconds: float) -> None:
        self.cooldown = cooldown_seconds
        self._active: set[int] = set()
        self._last: dict[int, float] = {}

    def try_acquire(self, user_id: int, *, bypass_cooldown: bool = False) -> tuple[bool, float]:
        """Return (ok, seconds_to_wait)."""
        if user_id in self._active:
            return False, 0.0
        now = time.monotonic()
        wait = self.cooldown - (now - self._last.get(user_id, -1e9))
        if wait > 0 and not bypass_cooldown:
            return False, wait
        self._active.add(user_id)
        self._last[user_id] = now
        return True, 0.0

    def release(self, user_id: int) -> None:
        self._active.discard(user_id)

    @property
    def active_count(self) -> int:
        return len(self._active)
