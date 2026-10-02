"""Session-local preview caches; never used to authorize payment posting."""

from dataclasses import dataclass
from time import monotonic
from typing import Generic, Hashable, TypeVar

T = TypeVar("T")


@dataclass
class _Entry(Generic[T]):
    expires_at: float
    value: T


class PreviewCache(Generic[T]):
    def __init__(self) -> None:
        self._entries: dict[Hashable, _Entry[T]] = {}

    def get(self, key: Hashable) -> T | None:
        entry = self._entries.get(key)
        if entry is None:
            return None
        if entry.expires_at <= monotonic():
            del self._entries[key]
            return None
        return entry.value

    def put(self, key: Hashable, value: T, ttl: float) -> None:
        now = monotonic()
        self._entries = {
            k: entry for k, entry in self._entries.items() if entry.expires_at > now
        }
        if ttl > 0:
            self._entries[key] = _Entry(now + ttl, value)

    def clear(self) -> None:
        self._entries.clear()
