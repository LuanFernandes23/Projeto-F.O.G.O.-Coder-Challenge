"""Cache em memória com expiração (TTL) e limite de entradas."""

import time
from collections import OrderedDict
from collections.abc import Callable


class TtlCache[K, V]:
    def __init__(
        self,
        ttl_seconds: float,
        max_entries: int,
        time_source: Callable[[], float] = time.monotonic,
    ) -> None:
        self._ttl = ttl_seconds
        self._max_entries = max_entries
        self._time = time_source
        self._entries: OrderedDict[K, tuple[float, V]] = OrderedDict()

    def get(self, key: K) -> V | None:
        entry = self._entries.get(key)
        if entry is None:
            return None
        expires_at, value = entry
        if expires_at <= self._time():
            del self._entries[key]
            return None
        self._entries.move_to_end(key)
        return value

    def set(self, key: K, value: V) -> None:
        self._entries[key] = (self._time() + self._ttl, value)
        self._entries.move_to_end(key)
        while len(self._entries) > self._max_entries:
            self._entries.popitem(last=False)
