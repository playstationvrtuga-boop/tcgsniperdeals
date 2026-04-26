from __future__ import annotations

from urllib.parse import urlsplit, urlunsplit


def app_live_deals_url(app_url: str | None) -> str:
    """Return the VIP live-feed entry URL without exposing secrets or changing domains."""
    raw_url = str(app_url or "").strip()
    if not raw_url:
        return ""

    parts = urlsplit(raw_url)
    if not parts.scheme or not parts.netloc:
        return raw_url

    path = (parts.path or "").rstrip("/")
    if path in {"", "/"}:
        path = "/live-deals"

    return urlunsplit((parts.scheme, parts.netloc, path, parts.query, parts.fragment))
