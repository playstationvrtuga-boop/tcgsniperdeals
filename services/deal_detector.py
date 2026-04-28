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
GRADED_TERMS = (
    "psa", "bgs", "beckett", "cgc", "ace", "sgc", "tag", "aura", "rpa",
    "graded", "grade", "graad", "graduada", "graduado", "slab",
    "encapsulated", "gem mint", "mint 10", "cert", "certificate",
    "certificado",
)
SEALED_TERMS = ("sealed", "booster bundle", "tin", "collection box")
ACCESSORY_TERMS = ("binder", "sleeves", "deck box", "toploader", "top loader", "album")
POKEMON_CENTER_TERMS = ("pokemon center", "pc etb", "center etb")
BOOSTER_PACK_TERMS = ("booster pack", "pack", "sobre")
RAW_COMPARABLE_MINIMUM = 2
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
LANGUAGE_TERMS = {
    "japanese": ("japanese", "japonais", "japones", "japan", " jp "),
    "english": ("english", "ingles", "anglais", " eng "),
    "portuguese": ("portuguese", "portugues", "português", " pt "),
    "french": ("french", "francais", "français", "fr "),
    "spanish": ("spanish", "espanol", "español", "es "),
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
    listing_type: str | None = None
    comparable_count: int = 0
    buy_now_prices: list[float] = field(default_factory=list)
    buy_now_titles: list[str] = field(default_factory=list)
    buy_now_count: int = 0
    buy_now_reference_price: float | None = None
    parser_confidence: str | None = None
    parser_query: str | None = None
    parser_queries: list[str] = field(default_factory=list)
    parser_name: str | None = None
    market_buy_now_min: float | None = None
    market_buy_now_avg: float | None = None
    market_buy_now_median: float | None = None
    last_sold_prices: list[float] = field(default_factory=list)
    last_2_sales: list[float] = field(default_factory=list)
    sold_avg_price: float | None = None
    sold_median_price: float | None = None
    estimated_fair_value: float | None = None
    pricing_basis: str | None = None
    confidence_score: int = 0


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


def _compare_text(value: str) -> str:
    return f" {title_parser.normalize_title(value or '')} "


def _has_graded_signal(value: str) -> bool:
    text = _compare_text(value)
    if any(f" {term} " in text for term in GRADED_TERMS if " " not in term):
        return True
    if any(term in text for term in GRADED_TERMS if " " in term):
        return True
    return bool(
        re.search(
            r"\b(?:gem\s+mint|mint|grade|graded|graad|graduada|graduado)\s*"
            r"(10|9\.5|9|8\.5|8)\b",
            text,
        )
    )


def _extract_grading_company(value: str) -> str | None:
    text = _compare_text(value)
    aliases = {
        "psa": "PSA",
        "bgs": "BGS",
        "beckett": "BGS",
        "cgc": "CGC",
        "ace": "ACE",
        "sgc": "SGC",
        "tag": "TAG",
        "aura": "AURA",
        "rpa": "RPA",
    }
    for alias, company in aliases.items():
        if f" {alias} " in text:
            return company
    return None


def _extract_grade(value: str) -> float | None:
    text = _compare_text(value).replace(",", ".")
    match = re.search(
        r"\b(?:psa|bgs|beckett|cgc|ace|sgc|tag|aura|rpa|grade|graded|graad|graduada|graduado)\s*"
        r"(10|[1-9](?:\.\d)?)\b",
        text,
    )
    if not match and _has_graded_signal(text):
        match = re.search(r"\b(10|[1-9]\.5|[1-9])\b", text)
    if not match:
        return None
    try:
        return float(match.group(1))
    except ValueError:
        return None


def _sealed_subtype(value: str) -> str | None:
    text = _compare_text(value)
    if any(term in text for term in POKEMON_CENTER_TERMS):
        return "pokemon_center_etb"
    if any(term in text for term in ETB_TERMS):
        return "etb"
    if any(term in text for term in BOOSTER_BOX_TERMS):
        return "booster_box"
    if any(term in text for term in BOOSTER_PACK_TERMS):
        return "booster_pack"
    if any(term in text for term in SEALED_TERMS):
        return "sealed_product"
    return None


def classify_listing_type(title: str, listing_kind: str | None = None) -> str:
    text = _compare_text(title)
    if _has_graded_signal(title):
        print("[pricing] LISTING_TYPE_DETECTED_GRADED", flush=True)
        return "graded_card"
    if _sealed_subtype(title):
        return "sealed_product"
    if any(term in text for term in ACCESSORY_TERMS):
        return "accessory"
    if listing_kind == "lot_bundle" or " lot " in text or " lote " in text or " bundle " in text:
        return "lot_bundle"
    if listing_kind in {"single_card", "unknown_pokemon"} or _is_pokemon_related(title) or _has_card_number_pattern(title):
        print("[pricing] LISTING_TYPE_DETECTED_RAW", flush=True)
        return "raw_card"
    return "unknown"


def _same_card_identity(original_title: str, candidate_title: str) -> bool:
    original = title_parser.extract_card_signals(original_title)
    candidate = title_parser.extract_card_signals(candidate_title)
    original_name = original.pokemon_name or original.keyword_name
    candidate_name = candidate.pokemon_name or candidate.keyword_name
    if original_name and candidate_name and original_name != candidate_name:
        return False
    original_number = original.full_number or original.card_number
    candidate_number = candidate.full_number or candidate.card_number
    if original_number and candidate_number and original_number != candidate_number:
        return False
    original_set = original.set_code or original.set_name
    candidate_set = candidate.set_code or candidate.set_name
    if original_set and candidate_set and original_set != candidate_set:
        return False
    return True


def is_comparable_listing(
    original_title: str,
    comparable_title: str,
    listing_type: str,
    listing_kind: str | None = None,
) -> tuple[bool, str]:
    if not comparable_title:
        return False, "missing_title"

    comparable_is_graded = _has_graded_signal(comparable_title)
    if listing_type == "raw_card" and comparable_is_graded:
        return False, "COMPARABLE_REJECTED_GRADED_FOR_RAW"
    if listing_type == "graded_card" and not comparable_is_graded:
        return False, "COMPARABLE_REJECTED_RAW_FOR_GRADED"

    if listing_type == "graded_card":
        original_company = _extract_grading_company(original_title)
        candidate_company = _extract_grading_company(comparable_title)
        if original_company and candidate_company and original_company != candidate_company:
            return False, "grading_company_mismatch"
        original_grade = _extract_grade(original_title)
        candidate_grade = _extract_grade(comparable_title)
        if original_grade is not None and candidate_grade is not None and abs(original_grade - candidate_grade) > 0.5:
            return False, "grade_mismatch"
    elif listing_type == "sealed_product":
        original_subtype = _sealed_subtype(original_title)
        candidate_subtype = _sealed_subtype(comparable_title)
        if original_subtype and candidate_subtype and original_subtype != candidate_subtype:
            return False, "sealed_subtype_mismatch"
        if original_subtype and not candidate_subtype:
            return False, "sealed_subtype_missing"
    elif listing_type == "lot_bundle":
        text = _compare_text(comparable_title)
        if not (" lot " in text or " lote " in text or " bundle " in text):
            return False, "single_reference_for_bundle"

    if listing_type in {"raw_card", "graded_card"} and not _same_card_identity(original_title, comparable_title):
        return False, "identity_mismatch"

    return True, "accepted"


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


def _parse_price_number(value: str, *, decimal_style: str = "auto") -> float | None:
    raw = (value or "").strip()
    if not raw:
        return None
    raw = re.sub(r"[^\d.,]", "", raw)
    if not raw:
        return None

    if decimal_style == "us":
        if "," in raw and "." in raw:
            raw = raw.replace(",", "")
        elif "," in raw and "." not in raw:
            raw = raw.replace(",", ".")
    elif decimal_style == "eu":
        raw = raw.replace(".", "").replace(",", ".")
    else:
        last_comma = raw.rfind(",")
        last_dot = raw.rfind(".")
        if last_comma >= 0 and last_dot >= 0:
            if last_dot > last_comma:
                raw = raw.replace(",", "")
            else:
                raw = raw.replace(".", "").replace(",", ".")
        elif "," in raw:
            raw = raw.replace(",", ".")
        elif "." in raw:
            parts = raw.split(".")
            if len(parts[-1]) == 3 and all(part.isdigit() for part in parts):
                raw = raw.replace(".", "")

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
        value = _parse_price_number(preferred, decimal_style="eu")
        if value is not None:
            return round(value, 2)

    usd_match = re.search(r"(?:US?\$|\$)\s*(\d[\d.,]*)", text, flags=re.IGNORECASE)
    if usd_match:
        usd_value = _parse_price_number(usd_match.group(1), decimal_style="us")
        if usd_value is not None:
            return round(usd_value * USD_TO_EUR_FALLBACK, 2)

    bare_match = re.search(r"(\d[\d.,]*)", text)
    if bare_match:
        value = _parse_price_number(bare_match.group(1))
        if value is not None:
            return round(value, 2)

    return None


def fetch_recent_comparables(product_name: str, listing_kind: str | None) -> list[EbaySoldListing]:
    cache_key = f"recent-sales-strict-v3::{listing_kind or 'unknown'}::{_clean_text(product_name).lower()}"
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


def _buy_now_min_comparables(listing_kind: str | None) -> int:
    if listing_kind == "graded_card":
        return 1
    return PRICING_BUY_NOW_MIN_COMPARABLES


def fetch_active_buy_now_comparables(product_name: str, listing_kind: str | None) -> list[EbaySoldListing]:
    if not PRICING_ENABLE_BUY_NOW_REFERENCE:
        return []

    cache_key = f"active-buy-now-strict-v3::{listing_kind or 'unknown'}::{_clean_text(product_name).lower()}"
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


def _clean_price_values(listings: list[EbaySoldListing]) -> list[float]:
    prices = [float(listing.price_eur) for listing in listings if listing.price_eur and listing.price_eur > 0]
    if len(prices) < 3:
        return prices
    center = float(median(prices))
    if center <= 0:
        return prices
    # Keep obvious bad matches from dominating tiny samples without being too aggressive.
    filtered = [price for price in prices if center * 0.35 <= price <= center * 2.75]
    return filtered or prices


def _price_stats(listings: list[EbaySoldListing]) -> tuple[float | None, float | None, float | None, list[float]]:
    prices = _clean_price_values(listings)
    if not prices:
        return None, None, None, []
    return (
        round(min(prices), 2),
        round(sum(prices) / len(prices), 2),
        round(float(median(prices)), 2),
        [round(price, 2) for price in prices],
    )


def _pricing_basis_and_confidence(
    *,
    sold_prices: list[float],
    buy_now_prices: list[float],
    sold_median_price: float | None,
    buy_now_median_price: float | None,
    parser_confidence: str | None,
) -> tuple[float | None, str | None, int]:
    if len(sold_prices) >= 2 and sold_median_price is not None:
        fair_value = sold_median_price
        basis = "sold"
        confidence = 88
    elif len(sold_prices) == 1:
        fair_value = sold_prices[0]
        basis = "sold"
        confidence = 72
    elif buy_now_prices and buy_now_median_price is not None:
        fair_value = buy_now_median_price
        basis = "buy_now"
        confidence = 58 if len(buy_now_prices) >= 3 else 48
    else:
        return None, None, 0

    if sold_prices and buy_now_prices:
        basis = "sold"

    parser_confidence = (parser_confidence or "").upper()
    if parser_confidence == "MEDIUM":
        confidence -= 6
    elif parser_confidence == "LOW":
        confidence -= 14

    if sold_prices and buy_now_median_price is not None and fair_value:
        spread = abs(buy_now_median_price - fair_value) / fair_value
        if spread > 0.75:
            confidence -= 12
        elif spread > 0.4:
            confidence -= 6

    return round(fair_value, 2), basis, max(0, min(100, int(round(confidence))))


def _detect_language_hint(value: str) -> str | None:
    normalized = f" {_normalize_title(value)} "
    for language, terms in LANGUAGE_TERMS.items():
        if any(term.strip() in normalized for term in terms):
            return language
    return None


def _language_confidence_penalty(expected_language: str | None, listings: list[EbaySoldListing]) -> int:
    if not expected_language:
        return 0
    for listing in listings:
        candidate_language = _detect_language_hint(listing.title)
        if candidate_language and candidate_language != expected_language:
            return 8
    return 0


def _grading_confidence_penalty(original_title: str, listings: list[EbaySoldListing], listing_type: str) -> int:
    if listing_type != "graded_card":
        return 0
    original_grade = _extract_grade(original_title)
    if original_grade is None:
        return 8
    for listing in listings:
        candidate_grade = _extract_grade(listing.title)
        if candidate_grade is not None and abs(candidate_grade - original_grade) > 0.25:
            return 10
    return 0


def _filter_comparables(
    *,
    original_title: str,
    listings: list[EbaySoldListing],
    listing_type: str,
    listing_kind: str | None,
    source: str,
) -> list[EbaySoldListing]:
    accepted: list[EbaySoldListing] = []
    for listing in listings:
        is_valid, reason = is_comparable_listing(
            original_title,
            listing.title,
            listing_type,
            listing_kind=listing_kind,
        )
        if not is_valid:
            print(f"[pricing] {reason} source={source} title={listing.title[:100]}", flush=True)
            continue
        if listing_type == "raw_card":
            print(f"[pricing] COMPARABLE_ACCEPTED_RAW source={source} title={listing.title[:100]}", flush=True)
        elif listing_type == "graded_card":
            print(f"[pricing] COMPARABLE_ACCEPTED_GRADED source={source} title={listing.title[:100]}", flush=True)
        accepted.append(listing)
    return accepted


def _log_pricing_attempt(source: str, attempt: int, query: str) -> None:
    print(f"[pricing] query_attempt={attempt} source={source} query=\"{query}\"", flush=True)


def _log_pricing_results(results_count: int, success: bool) -> None:
    print(f"[pricing] results={results_count}", flush=True)
    if success:
        print("[pricing] SUCCESS", flush=True)
    else:
        print("[pricing] fallback_next_query=true", flush=True)


def _prepare_pricing_queries(raw_queries: list[str]) -> list[str]:
    cleaned_queries: list[str] = []
    for raw_query in raw_queries:
        cleaned_query = title_parser.clean_pricing_query(raw_query)
        valid = title_parser.is_valid_query(cleaned_query)
        print(f"[pricing] raw_query={raw_query}", flush=True)
        print(f"[pricing] cleaned_query={cleaned_query}", flush=True)
        print(f"[pricing] valid={str(valid).lower()}", flush=True)
        if not valid:
            print("[pricing] skipped_invalid_query=true", flush=True)
            continue
        if cleaned_query not in cleaned_queries:
            cleaned_queries.append(cleaned_query)
    if not cleaned_queries:
        print("[pricing] no_valid_queries=true", flush=True)
    return cleaned_queries


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
    required_comparables = _buy_now_min_comparables(listing_kind)
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
        success = len(listings) >= required_comparables
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
    listing_type = classify_listing_type(title, listing_kind)
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
            listing_type=listing_type,
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
            listing_type=listing_type,
            parser_confidence=identity.confidence,
            parser_query=pricing_query,
            parser_queries=pricing_queries,
            parser_name=identity.extracted_name,
        )

    pricing_queries = _prepare_pricing_queries(pricing_queries)
    pricing_query = pricing_queries[0] if pricing_queries else pricing_query
    signals = getattr(identity, "signals", None)
    expected_language = getattr(signals, "language", None)

    comparable_sales: list[EbaySoldListing] = []
    recent_sales_error: str | None = None
    recent_sales_exception: EbaySoldError | None = None
    try:
        comparable_sales = _fetch_best_recent_for_queries(pricing_queries, listing_kind=listing_kind)
    except EbaySoldError as error:
        recent_sales_error = str(error)
        recent_sales_exception = error
    comparable_sales = _filter_comparables(
        original_title=title,
        listings=comparable_sales,
        listing_type=listing_type,
        listing_kind=listing_kind,
        source="sold",
    )

    buy_now_listings: list[EbaySoldListing] = []
    buy_now_error: str | None = None
    buy_now_exception: EbaySoldError | None = None
    try:
        buy_now_listings = _fetch_best_buy_now_for_queries(pricing_queries, listing_kind=listing_kind)
    except EbaySoldError as error:
        buy_now_error = str(error)
        buy_now_exception = error
    buy_now_listings = _filter_comparables(
        original_title=title,
        listings=buy_now_listings,
        listing_type=listing_type,
        listing_kind=listing_kind,
        source="buy_now",
    )

    required_buy_now_count = _buy_now_min_comparables(listing_kind)
    _sold_min, sold_avg_price, sold_median_price, sold_prices = _price_stats(comparable_sales[:3])
    market_buy_now_min, market_buy_now_avg, market_buy_now_median, buy_now_prices_all = _price_stats(
        buy_now_listings[:PRICING_BUY_NOW_MAX_RESULTS]
    )
    buy_now_reference_price = market_buy_now_median if buy_now_prices_all else None
    if buy_now_prices_all and len(buy_now_prices_all) < required_buy_now_count:
        print(
            "[pricing] PRICING_LOW_CONFIDENCE "
            f"reason=limited_buy_now_comparables count={len(buy_now_prices_all)} "
            f"required={required_buy_now_count}",
            flush=True,
        )
    estimated_fair_value, pricing_basis, confidence_score = _pricing_basis_and_confidence(
        sold_prices=sold_prices,
        buy_now_prices=buy_now_prices_all,
        sold_median_price=sold_median_price,
        buy_now_median_price=buy_now_reference_price,
        parser_confidence=identity.confidence,
    )
    language_penalty = _language_confidence_penalty(
        expected_language,
        comparable_sales[:3] if sold_prices else buy_now_listings[:PRICING_BUY_NOW_MAX_RESULTS],
    )
    if language_penalty:
        confidence_score = max(0, confidence_score - language_penalty)
        print(
            "[pricing] PRICING_LOW_CONFIDENCE "
            f"reason=language_mismatch expected={expected_language} penalty={language_penalty}",
            flush=True,
        )
    grading_penalty = _grading_confidence_penalty(
        title,
        comparable_sales[:3] if sold_prices else buy_now_listings[:PRICING_BUY_NOW_MAX_RESULTS],
        listing_type,
    )
    if grading_penalty:
        confidence_score = max(0, confidence_score - grading_penalty)
        print(
            "[pricing] PRICING_LOW_CONFIDENCE "
            f"reason=grade_near_match penalty={grading_penalty}",
            flush=True,
        )

    if buy_now_prices_all:
        print(
            "[pricing] PRICING_BUY_NOW_FOUND "
            f"count={len(buy_now_prices_all)} min={market_buy_now_min} median={market_buy_now_median} avg={market_buy_now_avg}",
            flush=True,
        )
    if sold_prices:
        print(
            "[pricing] PRICING_SOLD_FOUND "
            f"count={len(sold_prices)} last_2={sold_prices[:2]} median={sold_median_price} avg={sold_avg_price}",
            flush=True,
        )
    if pricing_basis == "sold":
        print(f"[pricing] PRICING_FAIR_VALUE_FROM_SOLD value={estimated_fair_value}", flush=True)
    elif pricing_basis == "buy_now":
        print(f"[pricing] PRICING_FAIR_VALUE_FROM_BUY_NOW value={estimated_fair_value}", flush=True)
    if confidence_score < 60:
        print(f"[pricing] PRICING_LOW_CONFIDENCE score={confidence_score}", flush=True)

    if estimated_fair_value is None:
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
        if listing_type == "raw_card":
            reason_parts.append("PRICE_COMPARE_INSUFFICIENT_RAW_COMPARABLES")
            print("[pricing] PRICE_COMPARE_INSUFFICIENT_RAW_COMPARABLES", flush=True)

        return DealResult(
            status="insufficient_comparables" if listing_type == "raw_card" else "needs_review",
            listing_price=listing_price,
            reason="; ".join(reason_parts),
            price_source="ebay_sold+buy_now",
            listing_kind=listing_kind,
            listing_type=listing_type,
            comparable_count=len(comparable_sales),
            buy_now_count=len(buy_now_listings),
            buy_now_prices=buy_now_prices_all,
            comparable_prices=sold_prices,
            last_sold_prices=sold_prices,
            last_2_sales=sold_prices[:2],
            sold_avg_price=sold_avg_price,
            sold_median_price=sold_median_price,
            market_buy_now_min=market_buy_now_min,
            market_buy_now_avg=market_buy_now_avg,
            market_buy_now_median=market_buy_now_median,
            buy_now_reference_price=buy_now_reference_price,
            estimated_fair_value=estimated_fair_value,
            pricing_basis=pricing_basis,
            confidence_score=confidence_score,
            parser_confidence=identity.confidence,
            parser_query=pricing_query,
            parser_queries=pricing_queries,
            parser_name=identity.extracted_name,
        )

    comparable_prices = sold_prices
    comparable_titles = [sale.title for sale in comparable_sales[:3]]
    buy_now_prices = buy_now_prices_all
    buy_now_titles = [listing.title for listing in buy_now_listings[:PRICING_BUY_NOW_MAX_RESULTS]]
    reference_price = estimated_fair_value
    price_source = pricing_basis

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
            listing_type=listing_type,
            comparable_count=len(comparable_prices),
            buy_now_count=len(buy_now_prices),
            buy_now_reference_price=buy_now_reference_price,
            market_buy_now_min=market_buy_now_min,
            market_buy_now_avg=market_buy_now_avg,
            market_buy_now_median=market_buy_now_median,
            last_sold_prices=comparable_prices,
            last_2_sales=comparable_prices[:2],
            sold_avg_price=sold_avg_price,
            sold_median_price=sold_median_price,
            estimated_fair_value=estimated_fair_value,
            pricing_basis=pricing_basis,
            confidence_score=confidence_score,
            parser_confidence=identity.confidence,
            parser_query=pricing_query,
            parser_queries=pricing_queries,
            parser_name=identity.extracted_name,
        )

    gross_margin = round(reference_price - listing_price, 2)
    discount_percent = round((gross_margin / reference_price) * 100, 2)
    score = calculate_score(discount_percent, gross_margin)
    if pricing_basis == "buy_now":
        score = max(0, score - 10)
    if confidence_score < 60:
        score = max(0, score - 8)
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
    if sold_prices:
        result_reason = f"{result_reason}; PRICING_SOLD_FOUND"
    result_reason = f"{result_reason}; pricing_basis={pricing_basis}; confidence_score={confidence_score}"
    if recent_sales_error:
        result_reason = f"{result_reason}; SOLD_BLOCKED" if isinstance(recent_sales_exception, EbaySoldRateLimitError) else f"{result_reason}; SOLD_FAILED"
    result_reason = f"{result_reason}; confidence={identity.confidence}; query={pricing_query}"
    if is_deal:
        print("[pricing] PRICING_ACCEPTED", flush=True)
    print(
        "[pricing] PRICE_COMPARE_FINAL "
        f"listing_type={listing_type} basis={pricing_basis} fair_value={reference_price} "
        f"sold_count={len(comparable_prices)} buy_now_count={len(buy_now_prices)} "
        f"confidence={confidence_score} status={'deal' if is_deal else 'priced'}",
        flush=True,
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
        listing_type=listing_type,
        comparable_count=len(comparable_prices),
        buy_now_prices=buy_now_prices,
        buy_now_titles=buy_now_titles,
        buy_now_count=len(buy_now_prices),
        buy_now_reference_price=buy_now_reference_price,
        market_buy_now_min=market_buy_now_min,
        market_buy_now_avg=market_buy_now_avg,
        market_buy_now_median=market_buy_now_median,
        last_sold_prices=comparable_prices,
        last_2_sales=comparable_prices[:2],
        sold_avg_price=sold_avg_price,
        sold_median_price=sold_median_price,
        estimated_fair_value=estimated_fair_value,
        pricing_basis=pricing_basis,
        confidence_score=confidence_score,
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
    "classify_listing_type",
    "is_comparable_listing",
    "is_precisely_identified_listing",
    "parse_listing_identity",
]
