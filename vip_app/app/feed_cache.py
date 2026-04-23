from threading import RLock
from time import monotonic


_CACHE: dict[str, dict] = {}
_LOCK = RLock()


def get_or_set(key: str, ttl_seconds: int, builder):
    now = monotonic()
    with _LOCK:
        entry = _CACHE.get(key)
        if entry and entry["expires_at"] > now:
            return entry["value"], True

    value = builder()
    with _LOCK:
        _CACHE[key] = {"expires_at": monotonic() + ttl_seconds, "value": value}
    return value, False


def invalidate(prefix: str | None = None) -> None:
    with _LOCK:
        if prefix is None:
            _CACHE.clear()
            return

        for key in list(_CACHE):
            if key.startswith(prefix):
                _CACHE.pop(key, None)
