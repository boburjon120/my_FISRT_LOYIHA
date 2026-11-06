"""Tiny in-memory TTL cache (video metadata for inline button callbacks)."""

from __future__ import annotations

import time
from collections import OrderedDict
from typing import Generic, TypeVar

V = TypeVar("V")


class TTLCache(Generic[V]):
    def __init__(self, ttl: float = 600, max_items: int = 256) -> None:
        self.ttl = ttl
        self.max_items = max_items
        self._data: OrderedDict[str, tuple[float, V]] = OrderedDict()

    def get(self, key: str) -> V | None:
        item = self._data.get(key)
        if item is None:
            return None
        stamp, value = item
        if time.monotonic() - stamp > self.ttl:
            self._data.pop(key, None)
            return None
        return value

    def set(self, key: str, value: V) -> None:
        self._data[key] = (time.monotonic(), value)
        self._data.move_to_end(key)
        while len(self._data) > self.max_items:
            self._data.popitem(last=False)
