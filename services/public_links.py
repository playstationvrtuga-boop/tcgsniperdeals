from __future__ import annotations

from config import SITE_URL


def build_free_public_listing_url(listing_id) -> str:
    base_url = (SITE_URL or "").rstrip("/")
    if not base_url:
        base_url = "http://127.0.0.1:5000"

    try:
        numeric_id = int(listing_id)
    except (TypeError, ValueError):
        numeric_id = None

    if numeric_id is None:
        return f"{base_url}/"

    return f"{base_url}/share/{numeric_id}"
