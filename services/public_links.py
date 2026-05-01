from __future__ import annotations

from config import PUBLIC_SITE_URL


def build_free_public_listing_url(listing_id) -> str:
    base_url = (PUBLIC_SITE_URL or "").rstrip("/")

    try:
        numeric_id = int(listing_id)
    except (TypeError, ValueError):
        numeric_id = None

    if numeric_id is None:
        return f"{base_url}/"

    return f"{base_url}/share/{numeric_id}"
