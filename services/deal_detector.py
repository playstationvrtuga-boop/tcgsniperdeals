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
    PRICING_ENABLE_EBAY_HTML_FALLBACK,
)
from services.ebay_sold_client import (
    EbaySoldError,
    EbaySoldListing,
    EbaySoldRateLimitError,
    get_active_buy_now,
    get_recent_sales,
)
from services.ebay_api_client import (
    get_official_active_buy_now,
    get_official_recent_sales,
    official_ebay_api_configured,
)
from services import pokemon_title_parser as title_parser
from services.price_cache import price_cache


USD_TO_EUR_FALLBACK = 0.88
ETB_TERMS = ("etb", "elite trainer box")
BOOSTER_BOX_TERMS = ("booster box", "display")
GRADED_TERMS = ("psa", "bgs", "cgc", "beckett", "graded", "slab")
SEALED_TERMS = ("sealed", "booster bundle", "tin", "collection box")
GENERIC_TITLE_TERMS = {
    "pokemon", "pok", "mon", "tcg", "card", "cards", "carta", "cartas",
    "tarjeta", "tarjetas", "carte", "cartes", "karta", "kaarten",
    "english", "ingles", "inglês", "anglais", "francais", "français",
    "portugues", "português", "spanish", "espanol", "español",
    "near", "mint", "nm", "holo", "reverse", "rare", "ultra",
    "double", "seller", "feedback", "sealed", "box", "trainer", "elite",
    "novo", "nueva", "nuevo", "neuf", "neuve", "bon", "estado", "etat",
}

KNOWN_POKEMON_NAMES = {
    "absol", "aerodactyl", "alakazam", "arcanine", "articuno", "blastoise",
    "bulbasaur", "charizard", "charmander", "charmeleon", "dragonite",
    "eevee", "espeon", "flareon", "gengar", "greninja", "gyarados",
    "ivysaur", "jigglypuff", "jolteon", "lapras", "lucario", "lugia",
    "machamp", "mew", "mewtwo", "moltres", "pikachu", "psyduck", "raichu",
    "rayquaza", "snorlax", "squirtle", "sylveon", "umbreon", "venusaur",
    "vaporeon", "zapdos", "zeraora",
}

SET_HINT_TERMS = {
    "base", "jungle", "fossil", "rocket", "evolving", "skies", "fusion",
    "strike", "brilliant", "stars", "astral", "radiance", "lost", "origin",
    "silver", "tempest", "crown", "zenith", "paldea", "evolved", "obsidian",
    "flames", "paradox", "rift", "temporal", "forces", "twilight",
    "masquerade", "stellar", "crown", "surging", "sparks", "prismatic",
    "evolutions", "celebrations", "champions", "path", "hidden", "fates",
    "shining", "destinies", "scarlet", "violet", "sword", "shield",
    "flammes", "fantasmagoriques", "crepuscolo", "mascherato", "ascended",
    "heroes",
}

NAME_ALIASES = {
    "dracaufeu": "charizard",
    "glurak": "charizard",
    "salameche": "charmander",
    "salamèche": "charmander",
    "pikachu": "pikachu",
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
    parser_confidence: str | None = None
    parser_query: str | None = None
    parser_queries: list[str] = field(default_factory=list)
    parser_name: str | None = None


@dataclass
class ParsedListingIdentity:
    confidence: str
    query: str
    listing_kind: str | None = None
    extracted_name: str | None = None
    extracted_number: str | None = None
    extracted_set: str | None = None
    fallback_query_used: bool = False
    is_pokemon_related: bool = False


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


def _extract_pokemon_name(title: str) -> str | None:
    normalized = _normalize_title(title)
    tokens = normalized.split()
    for token in tokens:
        if token in NAME_ALIASES:
            return NAME_ALIASES[token]
        if token in KNOWN_POKEMON_NAMES:
            return token
    return None


def _extract_card_number(title: str) -> str | None:
    text = _clean_text(title)
    patterns = (
        r"\b\d{1,3}\s*/\s*\d{1,3}\b",
        r"\bNo\.?\s*\d{1,4}\b",
        r"\bCard\s*\d{1,4}\b",
        r"\b[a-zA-Z]{2,5}\d?[a-zA-Z]?\s*[- ]?\s*\d{1,3}[a-zA-Z]?\b",
        r"\b[a-zA-Z]{2,5}\d{2,4}[a-zA-Z]?\b",
    )
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return re.sub(r"\s+", "", match.group(0)).strip()
    return None


def _extract_set_hint(title: str) -> str | None:
    tokens = _normalize_title(title).split()
    hits = [token for token in tokens if token in SET_HINT_TERMS]
    if not hits:
        return None
    return " ".join(hits[:3])


def _has_card_number_pattern(title: str) -> bool:
    return _extract_card_number(title) is not None


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


def _is_pokemon_related(title: str) -> bool:
    normalized = _normalize_title(title)
    return "pokemon" in normalized.split() or "pok mon" in normalized or _extract_pokemon_name(title) is not None


def parse_listing_identity(title: str) -> ParsedListingIdentity:
    return title_parser.parse_listing_identity(title)


def _log_parser(identity: ParsedListingIdentity) -> None:
    signals = getattr(identity, "signals", None)
    if signals is not None:
        print(f"[parser] raw_title={signals.raw_title}", flush=True)
        print(f"[parser] normalized_title={signals.normalized_title}", flush=True)
        print(f"[parser] kind={signals.kind}", flush=True)
        print(f"[parser] confidence={signals.confidence}", flush=True)
        print(f"[parser] pokemon_name={signals.pokemon_name or ''}", flush=True)
        print(f"[parser] card_number={signals.card_number or ''}", flush=True)
        print(f"[parser] full_number={signals.full_number or ''}", flush=True)
        print(f"[parser] set_code={signals.set_code or ''}", flush=True)
        print(f"[parser] variant={signals.variant or ''}", flush=True)
        print(f"[parser] generated_queries={signals.queries}", flush=True)
        print(f"[parser] decision={signals.decision}", flush=True)
        print(f"[parser] fallback_mode={str(identity.fallback_query_used).lower()}", flush=True)
        print(f"[parser] skip_reason={signals.skip_reason or ''}", flush=True)
        return

    print(
        "[parser] "
        f"confidence={identity.confidence} "
        f"extracted_name={identity.extracted_name or ''} "
        f"extracted_number={identity.extracted_number or ''} "
        f"extracted_set={identity.extracted_set or ''} "
        f"fallback_query_used={str(identity.fallback_query_used).lower()} "
        f"query={identity.query!r}",
        flush=True,
    )


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

    sales = []
    if official_ebay_api_configured():
        sales = get_official_recent_sales(product_name, max_results=3, listing_kind=listing_kind)
    if not sales and PRICING_ENABLE_EBAY_HTML_FALLBACK:
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

    listings = []
    if official_ebay_api_configured():
        listings = get_official_active_buy_now(
            product_name,
            max_results=PRICING_BUY_NOW_MAX_RESULTS,
            listing_kind=listing_kind,
        )
    if not listings and PRICING_ENABLE_EBAY_HTML_FALLBACK:
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


def _log_pricing_attempt(source: str, attempt: int, query: str) -> None:
    print(f"[pricing] query_attempt={attempt} source={source} query=\"{query}\"", flush=True)


def _log_pricing_results(results_count: int, success: bool) -> None:
    print(f"[pricing] results={results_count}", flush=True)
    if success:
        print("[pricing] SUCCESS", flush=True)
    else:
        print("[pricing] fallback_next_query=true", flush=True)


def _fetch_best_recent_for_queries(queries: list[str], listing_kind: str | None) -> list[EbaySoldListing]:
    best: list[EbaySoldListing] = []
    last_error: EbaySoldError | None = None
    for attempt, query in enumerate(queries, start=1):
        _log_pricing_attempt("sold", attempt, query)
        try:
            listings = fetch_recent_comparables(query, listing_kind=listing_kind)
        except EbaySoldError as error:
            last_error = error
            print(f"[pricing] source=sold query_error={error}", flush=True)
            _log_pricing_results(0, success=False)
            continue
        if len(listings) > len(best):
            best = listings
        success = len(listings) >= 3
        _log_pricing_results(len(listings), success=success)
        if success:
            return listings
    if best:
        return best
    if last_error is not None:
        raise last_error
    return best


def _fetch_best_buy_now_for_queries(queries: list[str], listing_kind: str | None) -> list[EbaySoldListing]:
    best: list[EbaySoldListing] = []
    last_error: EbaySoldError | None = None
    for attempt, query in enumerate(queries, start=1):
        _log_pricing_attempt("buy_now", attempt, query)
        try:
            listings = fetch_active_buy_now_comparables(query, listing_kind=listing_kind)
        except EbaySoldError as error:
            last_error = error
            print(f"[pricing] source=buy_now query_error={error}", flush=True)
            _log_pricing_results(0, success=False)
            continue
        if len(listings) > len(best):
            best = listings
        success = len(listings) >= PRICING_BUY_NOW_MIN_COMPARABLES
        _log_pricing_results(len(listings), success=success)
        if success:
            return listings
    if best:
        return best
    if last_error is not None:
        raise last_error
    return best


def evaluate_listing(listing) -> DealResult:
    title = _clean_text(getattr(listing, "title", "") or "")
    price_display = _clean_text(getattr(listing, "price_display", "") or "")
    identity = parse_listing_identity(title)
    listing_kind = identity.listing_kind
    parser_queries = list(getattr(getattr(identity, "signals", None), "queries", None) or [])
    pricing_query = identity.query or title
    pricing_queries = parser_queries or [pricing_query]

    if not title:
        return DealResult(status="skipped", reason="missing_title")

    _log_parser(identity)
    if identity.confidence == "UNKNOWN":
        return DealResult(
            status="skipped",
            reason="not_pokemon_related",
            listing_kind=listing_kind,
            parser_confidence=identity.confidence,
            parser_query=pricing_query,
            parser_queries=pricing_queries,
            parser_name=identity.extracted_name,
        )

    listing_price = extract_listing_price_eur(price_display)
    if listing_price is None:
        return DealResult(
            status="skipped",
            reason="invalid_listing_price",
            listing_kind=listing_kind,
            parser_confidence=identity.confidence,
            parser_query=pricing_query,
            parser_queries=pricing_queries,
            parser_name=identity.extracted_name,
        )

    comparable_sales: list[EbaySoldListing] = []
    recent_sales_error: str | None = None
    recent_sales_exception: EbaySoldError | None = None
    try:
        comparable_sales = _fetch_best_recent_for_queries(pricing_queries, listing_kind=listing_kind)
    except EbaySoldError as error:
        recent_sales_error = str(error)
        recent_sales_exception = error

    buy_now_listings: list[EbaySoldListing] = []
    buy_now_error: str | None = None
    buy_now_exception: EbaySoldError | None = None
    try:
        buy_now_listings = _fetch_best_buy_now_for_queries(pricing_queries, listing_kind=listing_kind)
    except EbaySoldError as error:
        buy_now_error = str(error)
        buy_now_exception = error

    sold_reference_price = _median_price(comparable_sales[:3]) if len(comparable_sales) >= 3 else None
    buy_now_reference_price = (
        _median_price(buy_now_listings[:PRICING_BUY_NOW_MIN_COMPARABLES])
        if len(buy_now_listings) >= PRICING_BUY_NOW_MIN_COMPARABLES
        else None
    )

    if sold_reference_price is None and buy_now_reference_price is None:
        reason_parts = ["DEAL_REJECTED_NO_REFERENCE"]
        if recent_sales_error:
            if isinstance(recent_sales_exception, EbaySoldRateLimitError):
                reason_parts.append("SOLD_BLOCKED")
            else:
                reason_parts.append("SOLD_FAILED")
        if buy_now_error:
            reason_parts.append("SEARCH_FAILED")
        if not buy_now_listings:
            reason_parts.append("ZERO_RESULTS")

        return DealResult(
            status="needs_review",
            listing_price=listing_price,
            reason="; ".join(reason_parts),
            price_source="ebay_sold+buy_now",
            listing_kind=listing_kind,
            comparable_count=len(comparable_sales),
            buy_now_count=len(buy_now_listings),
            parser_confidence=identity.confidence,
            parser_query=pricing_query,
            parser_queries=pricing_queries,
            parser_name=identity.extracted_name,
        )

    comparable_prices = [sale.price_eur for sale in comparable_sales[:3]]
    comparable_titles = [sale.title for sale in comparable_sales[:3]]
    buy_now_prices = [listing.price_eur for listing in buy_now_listings[:PRICING_BUY_NOW_MIN_COMPARABLES]]
    buy_now_titles = [listing.title for listing in buy_now_listings[:PRICING_BUY_NOW_MIN_COMPARABLES]]

    if buy_now_reference_price is not None:
        reference_price = buy_now_reference_price
        price_source = "ebay_buy_now_with_sold_reference" if sold_reference_price is not None else "ebay_buy_now"
    else:
        reference_price = sold_reference_price
        price_source = "ebay_sold"

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
            parser_confidence=identity.confidence,
            parser_query=pricing_query,
            parser_queries=pricing_queries,
            parser_name=identity.extracted_name,
        )

    gross_margin = round(reference_price - listing_price, 2)
    discount_percent = round((gross_margin / reference_price) * 100, 2)
    score = calculate_score(discount_percent, gross_margin)
    if price_source == "ebay_buy_now":
        score = max(0, score - 10)
    if identity.confidence == "MEDIUM":
        score = max(0, score - 3)
    elif identity.confidence == "LOW":
        score = max(0, score - 8)
    is_deal = (
        listing_price < reference_price
        and discount_percent >= PRICING_DEAL_MIN_DISCOUNT
        and gross_margin >= PRICING_DEAL_MIN_MARGIN
        and score >= PRICING_DEAL_MIN_SCORE
    )
    result_reason = "DEAL_ACCEPTED" if is_deal else "DEAL_REJECTED_THRESHOLDS"
    if buy_now_reference_price is not None:
        result_reason = f"{result_reason}; BUY_NOW_REFERENCE_FOUND"
    if recent_sales_error:
        result_reason = f"{result_reason}; SOLD_BLOCKED" if isinstance(recent_sales_exception, EbaySoldRateLimitError) else f"{result_reason}; SOLD_FAILED"
    result_reason = f"{result_reason}; confidence={identity.confidence}; query={pricing_query}"

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
        reason=result_reason,
        parser_confidence=identity.confidence,
        parser_query=pricing_query,
        parser_queries=pricing_queries,
        parser_name=identity.extracted_name,
    )


__all__ = [
    "DealResult",
    "EbaySoldError",
    "EbaySoldRateLimitError",
    "detect_listing_kind",
    "evaluate_listing",
    "is_precisely_identified_listing",
    "parse_listing_identity",
]
