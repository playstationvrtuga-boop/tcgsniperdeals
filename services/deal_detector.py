from __future__ import annotations

import re
from dataclasses import dataclass, field
from statistics import median

from config import (
    PRICING_BUY_NOW_MAX_RESULTS,
    PRICING_BUY_NOW_MIN_COMPARABLES,
    PRICING_DEAL_MIN_DISCOUNT,
    PRICING_DEAL_MIN_MARGIN,
    PRICING_DEAL_MIN_SCORE,
    PRICING_ENABLE_BUY_NOW_REFERENCE,
)
from services.ebay_sold_client import (
    EbaySoldError,
    EbaySoldListing,
    EbaySoldRateLimitError,
    get_active_buy_now,
    get_recent_sales,
)
from services.price_cache import price_cache


USD_TO_EUR_FALLBACK = 0.88
ETB_TERMS = ("etb", "elite trainer box")
BOOSTER_BOX_TERMS = ("booster box", "display")
GRADED_TERMS = ("psa", "bgs", "cgc", "beckett", "graded", "slab")
SEALED_TERMS = ("sealed", "booster bundle", "tin", "collection box")
GENERIC_TITLE_TERMS = {
    "pokemon", "pok", "mon", "tcg", "card", "cards", "carta", "cartas",
    "english", "near", "mint", "nm", "holo", "reverse", "rare", "ultra",
    "double", "seller", "feedback", "sealed", "box", "trainer", "elite",
}


@dataclass
class DealResult:
    status: str
    reference_price: float | None = None
    discount_percent: float | None = None
    gross_margin: float | None = None
    score: int = 0
    is_deal: bool = False
    comparable_prices: list[float] = field(default_factory=list)
    comparable_titles: list[str] = field(default_factory=list)
    listing_price: float | None = None
    reason: str | None = None
    price_source: str | None = None
    listing_kind: str | None = None
    comparable_count: int = 0
    buy_now_prices: list[float] = field(default_factory=list)
    buy_now_titles: list[str] = field(default_factory=list)
    buy_now_count: int = 0
    buy_now_reference_price: float | None = None


def _clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", (value or "").strip())


def _normalize_title(value: str) -> str:
    text = _clean_text(value).lower()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _meaningful_tokens(value: str) -> list[str]:
    return [
        token for token in _normalize_title(value).split()
        if len(token) > 1 and token not in GENERIC_TITLE_TERMS
    ]


def _has_card_number_pattern(title: str) -> bool:
    normalized = _normalize_title(title)
    if re.search(r"\b\d{1,3}\s*/\s*\d{1,3}\b", normalized):
        return True
    if re.search(r"\b[a-z]{2,5}\d?[a-z]?\s*[- ]\s*\d{1,3}[a-z]?\b", normalized):
        return True
    if re.search(r"\b[a-z]{2,5}\d{2,4}[a-z]?\b", normalized):
        return True
    if re.search(r"\b[a-z]{2,5}\s+\d{1,3}\s*/\s*\d{1,3}\b", normalized):
        return True
    return False


def detect_listing_kind(title: str) -> str | None:
    normalized = _normalize_title(title)

    if any(term in normalized for term in GRADED_TERMS):
        return "graded_card"
    if any(term in normalized for term in ETB_TERMS):
        return "etb"
    if any(term in normalized for term in BOOSTER_BOX_TERMS):
        return "booster_box"
    if any(term in normalized for term in SEALED_TERMS):
        return "sealed_product"
    if _has_card_number_pattern(title):
        return "single_card"
    return None


def _is_precisely_identified_card(title: str) -> bool:
    if not _has_card_number_pattern(title):
        return False
    return len(_meaningful_tokens(title)) >= 2


def _is_precisely_identified_etb(title: str) -> bool:
    normalized = _normalize_title(title)
    if not any(term in normalized for term in ETB_TERMS):
        return False
    remaining = [
        token for token in _meaningful_tokens(title)
        if token not in {"etb", "elite", "trainer", "box"}
    ]
    return len(remaining) >= 2


def _is_precisely_identified_booster_box(title: str) -> bool:
    normalized = _normalize_title(title)
    if not any(term in normalized for term in BOOSTER_BOX_TERMS):
        return False
    remaining = [
        token for token in _meaningful_tokens(title)
        if token not in {"booster", "box", "display"}
    ]
    return len(remaining) >= 2


def _is_precisely_identified_graded(title: str) -> bool:
    normalized = _normalize_title(title)
    if not any(term in normalized for term in GRADED_TERMS):
        return False
    return _has_card_number_pattern(title) or len(_meaningful_tokens(title)) >= 3


def is_precisely_identified_listing(title: str) -> bool:
    return any(
        (
            _is_precisely_identified_card(title),
            _is_precisely_identified_etb(title),
            _is_precisely_identified_booster_box(title),
            _is_precisely_identified_graded(title),
        )
    )


def _parse_decimal(value: str) -> float | None:
    raw = (value or "").strip()
    if not raw:
        return None
    raw = raw.replace(".", "").replace(",", ".")
    try:
        return float(raw)
    except ValueError:
        return None


def extract_listing_price_eur(price_display: str) -> float | None:
    text = _clean_text(price_display)
    if not text:
        return None

    euro_matches = re.findall(r"(\d[\d.,]*)\s*(?:€|EUR|â‚¬)", text, flags=re.IGNORECASE)
    if euro_matches:
        preferred = euro_matches[-1] if any(marker in text for marker in ("≈", "~", "about")) else euro_matches[0]
        value = _parse_decimal(preferred)
        if value is not None:
            return round(value, 2)

    usd_match = re.search(r"(?:US?\$|\$)\s*(\d[\d.,]*)", text, flags=re.IGNORECASE)
    if usd_match:
        usd_value = _parse_decimal(usd_match.group(1))
        if usd_value is not None:
            return round(usd_value * USD_TO_EUR_FALLBACK, 2)

    bare_match = re.search(r"(\d[\d.,]*)", text)
    if bare_match:
        value = _parse_decimal(bare_match.group(1))
        if value is not None:
            return round(value, 2)

    return None


def fetch_recent_comparables(product_name: str, listing_kind: str | None) -> list[EbaySoldListing]:
    cache_key = f"recent-sales::{listing_kind or 'unknown'}::{_clean_text(product_name).lower()}"
    cached = price_cache.get(cache_key)
    if cached is not None:
        return [
            EbaySoldListing(title=f"cached-{idx + 1}", price_eur=float(price))
            for idx, price in enumerate(cached[:3])
        ]

    sales = get_recent_sales(product_name, max_results=3, listing_kind=listing_kind)
    if sales:
        price_cache.set(cache_key, [sale.price_eur for sale in sales])
    return sales


def fetch_active_buy_now_comparables(product_name: str, listing_kind: str | None) -> list[EbaySoldListing]:
    if not PRICING_ENABLE_BUY_NOW_REFERENCE:
        return []

    cache_key = f"active-buy-now::{listing_kind or 'unknown'}::{_clean_text(product_name).lower()}"
    cached = price_cache.get(cache_key)
    if cached is not None:
        return [
            EbaySoldListing(title=f"cached-buy-now-{idx + 1}", price_eur=float(price))
            for idx, price in enumerate(cached[:PRICING_BUY_NOW_MAX_RESULTS])
        ]

    listings = get_active_buy_now(
        product_name,
        max_results=PRICING_BUY_NOW_MAX_RESULTS,
        listing_kind=listing_kind,
    )
    if listings:
        price_cache.set(cache_key, [listing.price_eur for listing in listings])
    return listings


def calculate_score(discount_percent: float, gross_margin: float) -> int:
    score = 0

    if discount_percent >= 35:
        score += 60
    elif discount_percent >= 25:
        score += 46
    elif discount_percent >= 15:
        score += 32
    elif discount_percent >= 8:
        score += 18

    if gross_margin >= 40:
        score += 20
    elif gross_margin >= 20:
        score += 12
    elif gross_margin >= 5:
        score += 6

    return max(0, min(100, int(round(score))))


def _median_price(listings: list[EbaySoldListing]) -> float | None:
    prices = [listing.price_eur for listing in listings if listing.price_eur and listing.price_eur > 0]
    if not prices:
        return None
    return round(float(median(prices)), 2)


def evaluate_listing(listing) -> DealResult:
    title = _clean_text(getattr(listing, "title", "") or "")
    price_display = _clean_text(getattr(listing, "price_display", "") or "")
    listing_kind = detect_listing_kind(title)

    if not title:
        return DealResult(status="skipped", reason="missing_title")

    if not is_precisely_identified_listing(title):
        return DealResult(status="skipped", reason="listing_not_precisely_identified", listing_kind=listing_kind)

    listing_price = extract_listing_price_eur(price_display)
    if listing_price is None:
        return DealResult(status="skipped", reason="invalid_listing_price", listing_kind=listing_kind)

    comparable_sales = fetch_recent_comparables(title, listing_kind=listing_kind)
    buy_now_listings: list[EbaySoldListing] = []
    buy_now_error: str | None = None
    try:
        buy_now_listings = fetch_active_buy_now_comparables(title, listing_kind=listing_kind)
    except EbaySoldError as error:
        buy_now_error = str(error)

    sold_reference_price = _median_price(comparable_sales[:3]) if len(comparable_sales) >= 3 else None
    buy_now_reference_price = (
        _median_price(buy_now_listings[:PRICING_BUY_NOW_MIN_COMPARABLES])
        if len(buy_now_listings) >= PRICING_BUY_NOW_MIN_COMPARABLES
        else None
    )

    if sold_reference_price is None and buy_now_reference_price is None:
        reason = "not_enough_price_references"
        if buy_now_error:
            reason = f"{reason}; buy_now_error"
        return DealResult(
            status="skipped",
            listing_price=listing_price,
            reason=reason,
            price_source="ebay_sold+buy_now",
            listing_kind=listing_kind,
            comparable_count=len(comparable_sales),
            buy_now_count=len(buy_now_listings),
        )

    comparable_prices = [sale.price_eur for sale in comparable_sales[:3]]
    comparable_titles = [sale.title for sale in comparable_sales[:3]]
    buy_now_prices = [listing.price_eur for listing in buy_now_listings[:PRICING_BUY_NOW_MIN_COMPARABLES]]
    buy_now_titles = [listing.title for listing in buy_now_listings[:PRICING_BUY_NOW_MIN_COMPARABLES]]

    if sold_reference_price is not None and buy_now_reference_price is not None:
        reference_price = min(sold_reference_price, buy_now_reference_price)
        price_source = (
            "ebay_sold_validated_by_buy_now"
            if reference_price == sold_reference_price
            else "ebay_sold_capped_by_buy_now"
        )
    elif sold_reference_price is not None:
        reference_price = sold_reference_price
        price_source = "ebay_sold"
    else:
        reference_price = buy_now_reference_price
        price_source = "ebay_buy_now"

    if reference_price <= 0:
        return DealResult(
            status="skipped",
            listing_price=listing_price,
            comparable_prices=comparable_prices,
            comparable_titles=comparable_titles,
            buy_now_prices=buy_now_prices,
            buy_now_titles=buy_now_titles,
            reason="invalid_reference_price",
            price_source=price_source,
            listing_kind=listing_kind,
            comparable_count=len(comparable_prices),
            buy_now_count=len(buy_now_prices),
            buy_now_reference_price=buy_now_reference_price,
        )

    gross_margin = round(reference_price - listing_price, 2)
    discount_percent = round((gross_margin / reference_price) * 100, 2)
    score = calculate_score(discount_percent, gross_margin)
    if price_source == "ebay_buy_now":
        score = max(0, score - 10)
    is_deal = (
        listing_price < reference_price
        and discount_percent >= PRICING_DEAL_MIN_DISCOUNT
        and gross_margin >= PRICING_DEAL_MIN_MARGIN
        and score >= PRICING_DEAL_MIN_SCORE
    )

    return DealResult(
        status="deal" if is_deal else "priced",
        reference_price=reference_price,
        discount_percent=discount_percent,
        gross_margin=gross_margin,
        score=score,
        is_deal=is_deal,
        comparable_prices=comparable_prices,
        comparable_titles=comparable_titles,
        listing_price=listing_price,
        price_source=price_source,
        listing_kind=listing_kind,
        comparable_count=len(comparable_prices),
        buy_now_prices=buy_now_prices,
        buy_now_titles=buy_now_titles,
        buy_now_count=len(buy_now_prices),
        buy_now_reference_price=buy_now_reference_price,
        reason="active_buy_now_error" if buy_now_error else None,
    )


__all__ = [
    "DealResult",
    "EbaySoldError",
    "EbaySoldRateLimitError",
    "detect_listing_kind",
    "evaluate_listing",
    "is_precisely_identified_listing",
]
