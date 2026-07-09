from __future__ import annotations

import copy
import threading
import time
from collections.abc import Callable, Hashable
from typing import Any


class ReadResponseCache:
    def __init__(self, *, default_ttl_seconds: float = 10.0, max_entries: int = 256):
        self.default_ttl_seconds = default_ttl_seconds
        self.max_entries = max_entries
        self._lock = threading.RLock()
        self._key_locks: dict[tuple[Hashable, ...], threading.Lock] = {}
        self._entries: dict[tuple[Hashable, ...], tuple[float, Any]] = {}

    def get_or_set(
        self,
        key: tuple[Hashable, ...],
        factory: Callable[[], Any],
        *,
        ttl_seconds: float | None = None,
    ) -> Any:
        now = time.monotonic()
        ttl = self.default_ttl_seconds if ttl_seconds is None else ttl_seconds
        with self._lock:
            entry = self._entries.get(key)
            if entry is not None and entry[0] > now:
                return copy.deepcopy(entry[1])
            key_lock = self._key_locks.setdefault(key, threading.Lock())

        with key_lock:
            now = time.monotonic()
            with self._lock:
                entry = self._entries.get(key)
                if entry is not None and entry[0] > now:
                    return copy.deepcopy(entry[1])

            value = factory()
            expires_at = time.monotonic() + ttl
            with self._lock:
                if len(self._entries) >= self.max_entries:
                    self._evict_expired(now)
                if len(self._entries) >= self.max_entries:
                    oldest_key = min(self._entries, key=lambda item: self._entries[item][0])
                    self._entries.pop(oldest_key, None)
                    self._key_locks.pop(oldest_key, None)
                self._entries[key] = (expires_at, copy.deepcopy(value))
            return value

    def clear_prefix(self, prefix: tuple[Hashable, ...]) -> None:
        with self._lock:
            for key in list(self._entries):
                if key[: len(prefix)] == prefix:
                    self._entries.pop(key, None)
                    self._key_locks.pop(key, None)

    def clear_all(self) -> None:
        with self._lock:
            self._entries.clear()
            self._key_locks.clear()

    def _evict_expired(self, now: float) -> None:
        for key, (expires_at, _) in list(self._entries.items()):
            if expires_at <= now:
                self._entries.pop(key, None)
                self._key_locks.pop(key, None)


read_response_cache = ReadResponseCache()
