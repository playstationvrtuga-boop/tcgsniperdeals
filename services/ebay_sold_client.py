from __future__ import annotations

import re
from dataclasses import dataclass
from html import unescape
from urllib.parse import quote_plus

import requests


class EbaySoldError(Exception):
    """Base exception for lightweight eBay sold price lookup."""


class EbaySoldRateLimitError(EbaySoldError):
    """Raised when eBay refuses or rate-limits the request."""


EBAY_SOLD_SEARCH_URL = (
    "https://www.ebay.com/sch/i.html"
    "?_nkw={query}&LH_Sold=1&LH_Complete=1&_ipg=25&LH_BIN=1"
)

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

TYPE_KEYWORDS = {
    "single_card": {"single_card", "card", "raw"},
    "etb": {"etb", "elite trainer box"},
    "booster_box": {"booster box", "display"},
    "graded_card": {"psa", "bgs", "cgc", "beckett", "graded", "slab"},
    "sealed_product": {"sealed", "booster bundle", "tin", "collection box"},
}


@dataclass
class EbaySoldListing:
    title: str
    price_eur: float


def _clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", unescape(value or "")).strip()


def _normalize_title(value: str) -> str:
    text = _clean_text(value).lower()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _parse_price_to_eur(price_text: str) -> float | None:
    text = _clean_text(price_text)
    if not text:
        return None

    euro_match = re.search(r"EUR\s*([\d.,]+)|([\d.,]+)\s*(?:€|EUR|â‚¬)", text, flags=re.IGNORECASE)
    if euro_match:
        raw = euro_match.group(1) or euro_match.group(2)
        try:
            return round(float(raw.replace(",", "")), 2)
        except ValueError:
            return None

    usd_match = re.search(r"(?:US\s*)?\$\s*([\d.,]+)", text, flags=re.IGNORECASE)
    if usd_match:
        try:
            usd_value = float(usd_match.group(1).replace(",", ""))
        except ValueError:
            return None
        return round(usd_value * 0.88, 2)

    return None


def _extract_item_blocks(html: str) -> list[str]:
    return re.findall(r'(<li[^>]+class="s-item[^"]*"[\s\S]*?</li>)', html, flags=re.IGNORECASE)


def _extract_title(block: str) -> str:
    match = re.search(r'<h3[^>]*class="s-item__title[^"]*"[^>]*>([\s\S]*?)</h3>', block, flags=re.IGNORECASE)
    return _clean_text(re.sub(r"<[^>]+>", " ", match.group(1))) if match else ""


def _extract_price(block: str) -> str:
    match = re.search(r'<span[^>]*class="s-item__price[^"]*"[^>]*>([\s\S]*?)</span>', block, flags=re.IGNORECASE)
    return _clean_text(re.sub(r"<[^>]+>", " ", match.group(1))) if match else ""


def _title_overlap_score(query: str, candidate: str) -> int:
    query_tokens = set(_normalize_title(query).split())
    candidate_tokens = set(_normalize_title(candidate).split())
    if not query_tokens or not candidate_tokens:
        return 0
    overlap = len(query_tokens & candidate_tokens)
    exact_bonus = 4 if _normalize_title(query) == _normalize_title(candidate) else 0
    return overlap + exact_bonus


def _query_from_title(title: str, listing_kind: str | None = None) -> str:
    normalized = _normalize_title(title)
    stop_terms = {
        "pokemon", "pok", "mon", "tcg", "card", "cards", "carta", "cartas",
        "english", "near", "mint", "nm", "holo", "reverse", "rare",
        "ultra", "double", "seller", "feedback",
    }
    tokens = [token for token in normalized.split() if token not in stop_terms and len(token) > 1]

    extra = []
    if listing_kind == "etb":
        extra = ["etb"]
    elif listing_kind == "booster_box":
        extra = ["booster", "box"]
    elif listing_kind == "graded_card":
        extra = ["psa", "graded"]

    query_tokens = (tokens[:6] + extra)[:8]
    if not query_tokens:
        query_tokens = normalized.split()[:8]
    return " ".join(query_tokens).strip()


def _matches_listing_kind(title: str, listing_kind: str | None) -> bool:
    if not listing_kind:
        return True

    normalized = _normalize_title(title)
    if listing_kind == "single_card":
        return not any(keyword in normalized for keyword in TYPE_KEYWORDS["etb"] | TYPE_KEYWORDS["booster_box"] | TYPE_KEYWORDS["graded_card"])
    if listing_kind == "etb":
        return any(keyword in normalized for keyword in TYPE_KEYWORDS["etb"])
    if listing_kind == "booster_box":
        return any(keyword in normalized for keyword in TYPE_KEYWORDS["booster_box"])
    if listing_kind == "graded_card":
        return any(keyword in normalized for keyword in TYPE_KEYWORDS["graded_card"])
    if listing_kind == "sealed_product":
        return any(
            keyword in normalized
            for keyword in TYPE_KEYWORDS["sealed_product"] | TYPE_KEYWORDS["etb"] | TYPE_KEYWORDS["booster_box"]
        )
    return True


class EbaySoldClient:
    def __init__(self, timeout: float = 15):
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update(DEFAULT_HEADERS)

    def fetch_recent_sales(
        self,
        product_name: str,
        max_results: int = 3,
        listing_kind: str | None = None,
    ) -> list[EbaySoldListing]:
        query = _query_from_title(product_name, listing_kind=listing_kind)
        if not query:
            return []

        url = EBAY_SOLD_SEARCH_URL.format(query=quote_plus(query))
        try:
            response = self.session.get(url, timeout=self.timeout)
        except requests.Timeout as error:
            raise EbaySoldError("eBay sold request timed out.") from error
        except requests.RequestException as error:
            raise EbaySoldError(f"eBay sold request failed: {error}") from error

        if response.status_code in {403, 429}:
            raise EbaySoldRateLimitError(f"eBay sold lookup refused with HTTP {response.status_code}.")
        if response.status_code >= 400:
            raise EbaySoldError(f"eBay sold lookup failed with HTTP {response.status_code}.")

        listings: list[EbaySoldListing] = []
        for block in _extract_item_blocks(response.text):
            title = _extract_title(block)
            if not title or "shop on ebay" in title.lower():
                continue
            if not _matches_listing_kind(title, listing_kind):
                continue

            score = _title_overlap_score(product_name, title)
            if score < 2:
                continue

            price_text = _extract_price(block)
            price_eur = _parse_price_to_eur(price_text)
            if price_eur is None or price_eur <= 0:
                continue

            listings.append(EbaySoldListing(title=title, price_eur=price_eur))
            if len(listings) >= max_results:
                break

        return listings


ebay_sold_client = EbaySoldClient()


def get_recent_sales(product_name: str, max_results: int = 3, listing_kind: str | None = None) -> list[EbaySoldListing]:
    return ebay_sold_client.fetch_recent_sales(product_name, max_results=max_results, listing_kind=listing_kind)
