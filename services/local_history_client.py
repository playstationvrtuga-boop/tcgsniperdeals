from __future__ import annotations

import re

from vip_app.app.models import Listing


def _normalize_title(value: str) -> str:
    text = (value or "").lower()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _token_set(value: str) -> set[str]:
    stop_terms = {
        "pokemon", "pok", "mon", "tcg", "card", "cards", "carta", "cartas",
        "english", "mint", "near", "rare", "holo", "reverse",
    }
    return {token for token in _normalize_title(value).split() if len(token) > 1 and token not in stop_terms}


def _parse_price_eur(price_display: str) -> float | None:
    if not price_display:
        return None

    euro_match = re.search(r"([\d.,]+)\s*(?:€|EUR|â‚¬)", price_display, flags=re.IGNORECASE)
    if euro_match:
        raw = euro_match.group(1)
        if "," in raw and "." in raw:
            raw = raw.replace(".", "").replace(",", ".")
        elif "," in raw:
            raw = raw.replace(",", ".")
        try:
            return round(float(raw), 2)
        except ValueError:
            return None

    usd_match = re.search(r"(?:US\s*)?\$\s*([\d.,]+)", price_display, flags=re.IGNORECASE)
    if usd_match:
        try:
            return round(float(usd_match.group(1).replace(",", "")) * 0.88, 2)
        except ValueError:
            return None

    return None


def get_product_prices(product_name: str, limit: int = 12) -> list[float]:
    target_tokens = _token_set(product_name)
    if not target_tokens:
        return []

    candidates = (
        Listing.query.filter(Listing.title.isnot(None))
        .order_by(Listing.detected_at.desc(), Listing.id.desc())
        .limit(120)
        .all()
    )

    scored: list[tuple[int, float]] = []
    for listing in candidates:
        listing_tokens = _token_set(listing.title or "")
        if not listing_tokens:
            continue

        overlap = len(target_tokens & listing_tokens)
        if overlap < 2:
            continue

        price_value = _parse_price_eur(listing.price_display or "")
        if price_value is None or price_value <= 0:
            continue

        scored.append((overlap, price_value))

    scored.sort(key=lambda item: item[0], reverse=True)
    return [price for _, price in scored[:limit]]
