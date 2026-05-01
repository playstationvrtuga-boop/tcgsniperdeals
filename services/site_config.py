from __future__ import annotations

from urllib.parse import urlsplit, urlunsplit


DEFAULT_PUBLIC_SITE_URL = "https://tcgsniperdeals.com"
OLD_PUBLIC_SITE_HOST = "tcg-sniper-deals.onrender.com"
NEW_PUBLIC_SITE_HOST = "tcgsniperdeals.com"


def normalize_public_site_url(value: str | None, *, default: str = DEFAULT_PUBLIC_SITE_URL) -> str:
    raw_url = str(value or "").strip() or default
    raw_url = raw_url.rstrip("/")

    parts = urlsplit(raw_url)
    if not parts.scheme or not parts.netloc:
        parts = urlsplit(default)

    if parts.netloc.lower() == OLD_PUBLIC_SITE_HOST:
        return urlunsplit(("https", NEW_PUBLIC_SITE_HOST, parts.path.rstrip("/"), parts.query, parts.fragment)).rstrip("/")

    return urlunsplit(("https", parts.netloc, parts.path.rstrip("/"), parts.query, parts.fragment)).rstrip("/")


def public_site_url_from(getter) -> str:
    return normalize_public_site_url(getter("PUBLIC_SITE_URL"))


def normalize_known_public_url(value: str | None, *, default: str | None = None) -> str:
    fallback = default if default is not None else ""
    if not value:
        return fallback

    parts = urlsplit(str(value).strip())
    if parts.netloc.lower() == OLD_PUBLIC_SITE_HOST:
        return normalize_public_site_url(value)

    return str(value).strip().rstrip("/")
