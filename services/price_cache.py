from __future__ import annotations

import time


class TTLPriceCache:
    def __init__(self, ttl_seconds: int = 1800, max_items: int = 256):
        self.ttl_seconds = max(60, int(ttl_seconds))
        self.max_items = max(32, int(max_items))
        self._store: dict[str, tuple[float, list[float]]] = {}

    def _expired(self, expires_at: float) -> bool:
        return expires_at <= time.time()

    def _trim(self) -> None:
        expired_keys = [
            key for key, (expires_at, _) in self._store.items()
            if self._expired(expires_at)
        ]
        for key in expired_keys:
            self._store.pop(key, None)

        if len(self._store) <= self.max_items:
            return

        oldest_keys = sorted(
            self._store.items(),
            key=lambda item: item[1][0],
        )
        for key, _ in oldest_keys[: len(self._store) - self.max_items]:
            self._store.pop(key, None)

    def get(self, key: str) -> list[float] | None:
        if not key:
            return None

        cached = self._store.get(key)
        if not cached:
            return None

        expires_at, value = cached
        if self._expired(expires_at):
            self._store.pop(key, None)
            return None

        return list(value)

    def set(self, key: str, prices: list[float]) -> list[float]:
        cleaned = [float(price) for price in prices if price is not None]
        self._store[key] = (time.time() + self.ttl_seconds, cleaned)
        self._trim()
        return list(cleaned)

    def clear(self) -> None:
        self._store.clear()


price_cache = TTLPriceCache(ttl_seconds=1800, max_items=256)
