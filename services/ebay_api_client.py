from __future__ import annotations

import base64
import re
import sys
import time
from dataclasses import dataclass
from typing import Any

import requests

from config import (
    EBAY_API_TIMEOUT,
    EBAY_CLIENT_ID,
    EBAY_CLIENT_SECRET,
    EBAY_ENABLE_MARKETPLACE_INSIGHTS,
    EBAY_ENABLE_OFFICIAL_API,
    EBAY_MARKETPLACE_ID,
    EBAY_MARKETPLACE_INSIGHTS_SEARCH_URL,
    EBAY_OAUTH_SCOPE,
)
from services.ebay_sold_client import (
    EbaySoldError,
    EbaySoldListing,
    EbaySoldRateLimitError,
    _matches_listing_kind,
    _query_from_title,
    _title_overlap_score,
)


TOKEN_URL = "https://api.ebay.com/identity/v1/oauth2/token"
BROWSE_SEARCH_URL = "https://api.ebay.com/buy/browse/v1/item_summary/search"

FX_TO_EUR = {
    "EUR": 1.0,
    "USD": 0.88,
    "GBP": 1.17,
}

NOISY_QUERY_TERMS = {
    "psa", "graded", "grade", "slab", "bgs", "cgc", "beckett",
    "lot", "bundle", "rare", "ultra", "near", "mint", "nm",
    "holo", "reverse", "english", "japanese", "sealed",
}


@dataclass
class EbayApiRawItem:
    title: str
    price_value: str
    price_currency: str
    item_url: str
    buying_options: list[str]


def _mask_secret(value: str) -> str:
    if not value:
        return "missing"
    if len(value) <= 6:
        return "present-short"
    return f"present:{value[:3]}...{value[-3:]}"


def _log(message: str) -> None:
    print(f"[ebay_api] {message}")


def _clean_query_text(value: str) -> str:
    text = re.sub(r"[^A-Za-z0-9/ -]+", " ", value or "")
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _without_noisy_terms(query: str) -> str:
    tokens = []
    for token in _clean_query_text(query).split():
        normalized = re.sub(r"[^a-z0-9]+", "", token.lower())
        if normalized and normalized not in NOISY_QUERY_TERMS:
            tokens.append(token)
    return " ".join(tokens).strip()


def build_query_variants(product_name: str, listing_kind: str | None = None) -> list[str]:
    base_query = _query_from_title(product_name, listing_kind=listing_kind)
    cleaned_title = _clean_query_text(product_name)
    simplified = _without_noisy_terms(cleaned_title)

    variants = [base_query, cleaned_title, simplified]

    title_tokens = simplified.split()
    if title_tokens:
        variants.append("pokemon " + " ".join(title_tokens[:4]))
        variants.append(" ".join(title_tokens[:5]))

    if listing_kind == "etb":
        variants.extend(["pokemon etb", "pokemon elite trainer box"])
    elif listing_kind == "booster_box":
        variants.extend(["pokemon booster box", "pokemon booster display"])
    elif listing_kind == "sealed_product":
        variants.extend(["pokemon sealed product", "pokemon collection box"])
    else:
        variants.extend(["pokemon card", "pokemon tcg card"])

    seen = set()
    unique = []
    for variant in variants:
        clean = _clean_query_text(variant).lower()
        if clean and clean not in seen:
            seen.add(clean)
            unique.append(_clean_query_text(variant))
    return unique

class EbayApiClient:
    """Small official eBay API client for pricing references.

    This avoids relying on eBay HTML pages for active Buy Now comparables.
    Sold history is only attempted when Marketplace Insights is explicitly enabled.
    """

    def __init__(self, timeout: float = EBAY_API_TIMEOUT):
        self.timeout = timeout
        self.session = requests.Session()
        self._access_token: str | None = None
        self._access_token_expires_at = 0.0

    def is_configured(self) -> bool:
        return bool(EBAY_ENABLE_OFFICIAL_API and EBAY_CLIENT_ID and EBAY_CLIENT_SECRET)

    def config_status(self) -> str:
        if not EBAY_ENABLE_OFFICIAL_API:
            return "API_DISABLED"
        if not EBAY_CLIENT_ID or not EBAY_CLIENT_SECRET:
            return "API_KEYS_MISSING"
        return "API_READY"

    def log_config_status(self) -> None:
        _log(
            "config "
            f"enabled={EBAY_ENABLE_OFFICIAL_API} "
            f"client_id={_mask_secret(EBAY_CLIENT_ID)} "
            f"client_secret={_mask_secret(EBAY_CLIENT_SECRET)} "
            f"marketplace={EBAY_MARKETPLACE_ID} "
            f"endpoint={BROWSE_SEARCH_URL}"
        )

    def _get_access_token(self) -> str:
        if not self.is_configured():
            raise EbaySoldError(self.config_status())

        now = time.time()
        if self._access_token and now < self._access_token_expires_at:
            return self._access_token

        raw_credentials = f"{EBAY_CLIENT_ID}:{EBAY_CLIENT_SECRET}".encode("utf-8")
        basic_token = base64.b64encode(raw_credentials).decode("ascii")
        headers = {
            "Authorization": f"Basic {basic_token}",
            "Content-Type": "application/x-www-form-urlencoded",
        }
        data = {
            "grant_type": "client_credentials",
            "scope": EBAY_OAUTH_SCOPE,
        }

        try:
            response = self.session.post(TOKEN_URL, headers=headers, data=data, timeout=self.timeout)
        except requests.Timeout as error:
            raise EbaySoldError("TOKEN_FAILED: official eBay token request timed out.") from error
        except requests.RequestException as error:
            raise EbaySoldError(f"TOKEN_FAILED: official eBay token request failed: {error}") from error

        _log(f"token endpoint={TOKEN_URL} status={response.status_code}")
        if response.status_code in {401, 403}:
            raise EbaySoldError("TOKEN_FAILED: official eBay API credentials were rejected.")
        if response.status_code == 429:
            raise EbaySoldRateLimitError("TOKEN_FAILED: official eBay token request was rate-limited.")
        if response.status_code >= 400:
            raise EbaySoldError(f"TOKEN_FAILED: official eBay token request failed with HTTP {response.status_code}: {response.text[:240]}")

        payload = self._json_response(response, "Official eBay token response was invalid.")
        token = str(payload.get("access_token") or "")
        if not token:
            raise EbaySoldError("TOKEN_FAILED: official eBay token response did not include an access token.")

        expires_in = int(payload.get("expires_in") or 7200)
        self._access_token = token
        self._access_token_expires_at = now + max(60, expires_in - 60)
        _log("token OK")
        return token

    def _api_headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._get_access_token()}",
            "Accept": "application/json",
            "X-EBAY-C-MARKETPLACE-ID": EBAY_MARKETPLACE_ID,
        }

    @staticmethod
    def _json_response(response: requests.Response, error_message: str) -> dict[str, Any]:
        try:
            payload = response.json()
        except ValueError as error:
            raise EbaySoldError(error_message) from error
        if not isinstance(payload, dict):
            raise EbaySoldError(error_message)
        return payload

    @staticmethod
    def _price_to_eur(price: dict[str, Any] | None) -> float | None:
        if not isinstance(price, dict):
            return None
        currency = str(price.get("currency") or "").upper()
        try:
            value = float(price.get("value"))
        except (TypeError, ValueError):
            return None

        rate = FX_TO_EUR.get(currency)
        if rate is None:
            return None
        return round(value * rate, 2)

    def _search_active_raw(self, query: str, limit: int = 20) -> list[dict[str, Any]]:
        params = {
            "q": query,
            "limit": str(limit),
            "filter": "buyingOptions:{FIXED_PRICE}",
            "sort": "price",
        }
        _log(f"buy_now search endpoint={BROWSE_SEARCH_URL} marketplace={EBAY_MARKETPLACE_ID} query={query!r} params={params}")
        try:
            response = self.session.get(BROWSE_SEARCH_URL, headers=self._api_headers(), params=params, timeout=self.timeout)
        except requests.Timeout as error:
            raise EbaySoldError("SEARCH_FAILED: official eBay Buy Now request timed out.") from error
        except requests.RequestException as error:
            raise EbaySoldError(f"SEARCH_FAILED: official eBay Buy Now request failed: {error}") from error

        _log(f"buy_now status={response.status_code} query={query!r}")
        if response.status_code in {403, 429}:
            raise EbaySoldRateLimitError(f"SEARCH_FAILED: official eBay Buy Now lookup refused with HTTP {response.status_code}: {response.text[:240]}")
        if response.status_code >= 400:
            raise EbaySoldError(f"SEARCH_FAILED: official eBay Buy Now lookup failed with HTTP {response.status_code}: {response.text[:240]}")

        payload = self._json_response(response, "SEARCH_FAILED: official eBay Buy Now response was invalid.")
        summaries = payload.get("itemSummaries") or []
        if not isinstance(summaries, list):
            return []
        _log(f"buy_now raw_results={len(summaries)} query={query!r}")
        return [item for item in summaries if isinstance(item, dict)]

    def fetch_active_buy_now_raw(self, product_name: str, limit: int = 20, listing_kind: str | None = None) -> list[EbayApiRawItem]:
        if not self.is_configured():
            _log(f"buy_now skipped reason={self.config_status()}")
            return []

        for query in build_query_variants(product_name, listing_kind=listing_kind):
            items = self._search_active_raw(query, limit=limit)
            if not items:
                _log(f"buy_now ZERO_RESULTS query={query!r}")
                continue

            raw_items = []
            for item in items:
                price = item.get("price") or {}
                raw_items.append(
                    EbayApiRawItem(
                        title=str(item.get("title") or ""),
                        price_value=str(price.get("value") or ""),
                        price_currency=str(price.get("currency") or ""),
                        item_url=str(item.get("itemWebUrl") or item.get("itemHref") or ""),
                        buying_options=list(item.get("buyingOptions") or []),
                    )
                )
            return raw_items

        return []

    def fetch_active_buy_now(
        self,
        product_name: str,
        max_results: int = 5,
        listing_kind: str | None = None,
    ) -> list[EbaySoldListing]:
        if not self.is_configured():
            _log(f"buy_now skipped reason={self.config_status()}")
            return []

        limit = 20
        best_listings: list[EbaySoldListing] = []
        for query in build_query_variants(product_name, listing_kind=listing_kind):
            items = self._search_active_raw(query, limit=limit)
            if not items:
                _log(f"buy_now ZERO_RESULTS query={query!r}")
                continue

            listings: list[EbaySoldListing] = []
            preview = []
            for item in items:
                buying_options = item.get("buyingOptions") or []
                if buying_options and "FIXED_PRICE" not in buying_options:
                    continue

                title = str(item.get("title") or "").strip()
                price = item.get("price") or {}
                preview.append(
                    f"{title[:80]} | {price.get('value')} {price.get('currency')} | {','.join(buying_options)}"
                )
                if not title or not _matches_listing_kind(title, listing_kind):
                    continue
                if _title_overlap_score(product_name, title) < 2:
                    continue

                price_eur = self._price_to_eur(item.get("price"))
                if price_eur is None or price_eur <= 0:
                    continue

                listings.append(EbaySoldListing(title=title, price_eur=price_eur))
                if len(listings) >= max_results:
                    break

            for idx, line in enumerate(preview[:3], start=1):
                _log(f"buy_now preview#{idx} {line}")
            _log(f"buy_now filtered_results={len(listings)} query={query!r}")

            if listings:
                best_listings = listings
                break

        if best_listings:
            _log(f"BUY_NOW_REFERENCE_FOUND count={len(best_listings)}")
        else:
            _log("ZERO_RESULTS no usable Buy Now references after query variants")
        return best_listings


    def fetch_recent_sales(
        self,
        product_name: str,
        max_results: int = 3,
        listing_kind: str | None = None,
    ) -> list[EbaySoldListing]:
        if not (self.is_configured() and EBAY_ENABLE_MARKETPLACE_INSIGHTS and EBAY_MARKETPLACE_INSIGHTS_SEARCH_URL):
            return []

        query = _query_from_title(product_name, listing_kind=listing_kind)
        if not query:
            return []

        params = {"q": query, "limit": str(max(1, min(max_results * 3, 50)))}
        try:
            response = self.session.get(
                EBAY_MARKETPLACE_INSIGHTS_SEARCH_URL,
                headers=self._api_headers(),
                params=params,
                timeout=self.timeout,
            )
        except requests.Timeout as error:
            raise EbaySoldError("Official eBay sold request timed out.") from error
        except requests.RequestException as error:
            raise EbaySoldError(f"Official eBay sold request failed: {error}") from error

        if response.status_code in {403, 429}:
            raise EbaySoldRateLimitError(f"Official eBay sold lookup refused with HTTP {response.status_code}.")
        if response.status_code >= 400:
            raise EbaySoldError(f"Official eBay sold lookup failed with HTTP {response.status_code}.")

        payload = self._json_response(response, "Official eBay sold response was invalid.")
        items = payload.get("itemSales") or payload.get("itemSummaries") or []
        if not isinstance(items, list):
            return []

        listings: list[EbaySoldListing] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            title = str(item.get("title") or "").strip()
            if not title or not _matches_listing_kind(title, listing_kind):
                continue
            if _title_overlap_score(product_name, title) < 2:
                continue

            price_eur = self._price_to_eur(item.get("price") or item.get("lastSoldPrice"))
            if price_eur is None or price_eur <= 0:
                continue

            listings.append(EbaySoldListing(title=title, price_eur=price_eur))
            if len(listings) >= max_results:
                break

        return listings


ebay_api_client = EbayApiClient()


def official_ebay_api_configured() -> bool:
    return ebay_api_client.is_configured()


def get_official_active_buy_now(
    product_name: str,
    max_results: int = 5,
    listing_kind: str | None = None,
) -> list[EbaySoldListing]:
    return ebay_api_client.fetch_active_buy_now(product_name, max_results=max_results, listing_kind=listing_kind)


def get_official_recent_sales(
    product_name: str,
    max_results: int = 3,
    listing_kind: str | None = None,
) -> list[EbaySoldListing]:
    return ebay_api_client.fetch_recent_sales(product_name, max_results=max_results, listing_kind=listing_kind)


def _run_manual_test(argv: list[str]) -> int:
    query = " ".join(argv).strip() or "pokemon charizard"
    client = EbayApiClient()
    client.log_config_status()

    try:
        client._get_access_token()
        print("token OK")
    except Exception as error:
        print(f"token failed: {error}")
        return 1

    try:
        items = client.fetch_active_buy_now_raw(query, limit=20)
    except Exception as error:
        print(f"search failed: {error}")
        return 1

    print("search OK")
    print(f"total results: {len(items)}")
    for idx, item in enumerate(items[:10], start=1):
        print(
            f"{idx}. {item.title}\n"
            f"   price: {item.price_value} {item.price_currency}\n"
            f"   buyingOptions: {', '.join(item.buying_options) or 'n/a'}\n"
            f"   link: {item.item_url}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(_run_manual_test(sys.argv[1:]))
