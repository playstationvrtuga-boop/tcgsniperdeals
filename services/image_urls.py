from __future__ import annotations

import re


EBAY_IMAGE_SIZE = 1600


def high_resolution_ebay_image_url(url: str | None, *, size: int = EBAY_IMAGE_SIZE) -> str | None:
    """Return the larger eBay CDN variant when the URL exposes a size segment."""
    if not url:
        return None

    text = str(url).strip()
    if not text or "i.ebayimg.com" not in text.lower():
        return text

    target_size = max(500, min(int(size or EBAY_IMAGE_SIZE), 1600))
    upgraded = re.sub(
        r"(?i)(/s-l)\d+(\.(?:jpg|jpeg|png|webp)(?:[?#].*)?)$",
        rf"\g<1>{target_size}\2",
        text,
    )
    if upgraded != text:
        return upgraded

    return re.sub(
        r"(?i)(/s-l)\d+(/)",
        rf"\g<1>{target_size}\2",
        text,
    )


def high_resolution_listing_image_url(url: str | None) -> str | None:
    return high_resolution_ebay_image_url(url)
