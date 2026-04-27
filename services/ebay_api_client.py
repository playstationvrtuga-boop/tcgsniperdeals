from __future__ import annotations

import base64
import os
import re
import sys
import time
from dataclasses import dataclass
from typing import Any

import requests

from config import (
    EBAY_API_ENVIRONMENT,
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
from services.pokemon_title_parser import clean_pricing_query, is_valid_query


if EBAY_API_ENVIRONMENT == "SANDBOX":
    TOKEN_URL = "https://api.sandbox.ebay.com/identity/v1/oauth2/token"
    BROWSE_SEARCH_URL = "https://api.sandbox.ebay.com/buy/browse/v1/item_summary/search"
else:
    TOKEN_URL = "https://api.ebay.com/identity/v1/oauth2/token"
    BROWSE_SEARCH_URL = "https://api.ebay.com/buy/browse/v1/item_summary/search"

FX_TO_EUR = {
    "EUR": 1.0,
    "USD": 0.88,
    "GBP": 1.17,
}
EBAY_TOKEN_REQUEST_TIMEOUT = 20
EBAY_TOKEN_MAX_ATTEMPTS = 2

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
    return "present" if value else "missing"


def _env_setting(name: str, fallback: str = "") -> str:
    value = os.environ.get(name)
    if value is None:
        return str(fallback or "")
    return str(value).strip()


def _env_flag(name: str, fallback: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return bool(fallback)
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _runtime_enabled() -> bool:
    return _env_flag("EBAY_ENABLE_OFFICIAL_API", EBAY_ENABLE_OFFICIAL_API)


def _runtime_client_id() -> str:
    return _env_setting("EBAY_CLIENT_ID", EBAY_CLIENT_ID)


def _runtime_client_secret() -> str:
    return _env_setting("EBAY_CLIENT_SECRET", EBAY_CLIENT_SECRET)


def _runtime_marketplace() -> str:
    return _env_setting("EBAY_MARKETPLACE_ID", EBAY_MARKETPLACE_ID) or "EBAY_US"


def _runtime_environment() -> str:
    environment = _env_setting("EBAY_API_ENVIRONMENT", EBAY_API_ENVIRONMENT).upper()
    return "SANDBOX" if environment == "SANDBOX" else "PRODUCTION"


def _runtime_token_url() -> str:
    if _runtime_environment() == "SANDBOX":
        return "https://api.sandbox.ebay.com/identity/v1/oauth2/token"
    return "https://api.ebay.com/identity/v1/oauth2/token"


def _runtime_browse_search_url() -> str:
    if _runtime_environment() == "SANDBOX":
        return "https://api.sandbox.ebay.com/buy/browse/v1/item_summary/search"
    return "https://api.ebay.com/buy/browse/v1/item_summary/search"


def _log(message: str) -> None:
    print(f"[ebay_api] {message}", flush=True)


def _status_reason(status_code: int) -> str:
    if status_code in {400, 401}:
        return "TOKEN_INVALID_OR_EXPIRED"
    if status_code == 403:
        return "PERMISSION_DENIED"
    if status_code == 429:
        return "RATE_LIMIT"
    if status_code >= 400:
        return "SEARCH_FAILED"
    return "OK"


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

    variants = [cleaned_title, base_query, simplified]

    title_tokens = simplified.split()
    if title_tokens:
        variants.append("pokemon " + " ".join(title_tokens[:4]))
        variants.append(" ".join(title_tokens[:5]))

    seen = set()
    unique = []
    for variant in variants:
        clean = clean_pricing_query(variant)
        if not is_valid_query(clean):
            continue
        if clean and clean not in seen:
            seen.add(clean)
            unique.append(clean)
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
        return bool(_runtime_enabled() and _runtime_client_id() and _runtime_client_secret())

    def config_status(self) -> str:
        if not _runtime_enabled():
            return "API_DISABLED"
        if not _runtime_client_id() or not _runtime_client_secret():
            return "API_KEYS_MISSING"
        return "API_READY"

    def log_config_status(self, *, log: bool = True) -> None:
        if not log:
            return
        client_id = _runtime_client_id()
        client_secret = _runtime_client_secret()
        _log(
            "config "
            f"enabled={_runtime_enabled()} "
            f"client_id={_mask_secret(client_id)} "
            f"client_secret={_mask_secret(client_secret)} "
            f"marketplace={_runtime_marketplace()}"
        )
        if client_id and client_secret:
            print("[config] environment variables loaded successfully", flush=True)
        else:
            print("[config] required environment variables not found", flush=True)
            print("[config] check deployment environment configuration", flush=True)
        _log(f"environment={_runtime_environment()}")
        _log(f"endpoint={_runtime_browse_search_url()}")
        status = self.config_status()
        if status != "API_READY":
            _log(status)
        if status == "API_KEYS_MISSING":
            _log(
                "Add EBAY_CLIENT_ID and EBAY_CLIENT_SECRET to Render service "
                "tcg-sniper-deals-worker Environment Variables"
            )

    def _get_access_token(self, *, force_refresh: bool = False) -> str:
        if not self.is_configured():
            raise EbaySoldError(self.config_status())

        now = time.time()
        if not force_refresh and self._access_token and now < self._access_token_expires_at:
            return self._access_token

        raw_credentials = f"{_runtime_client_id()}:{_runtime_client_secret()}".encode("utf-8")
        basic_token = base64.b64encode(raw_credentials).decode("ascii")
        headers = {
            "Authorization": f"Basic {basic_token}",
            "Content-Type": "application/x-www-form-urlencoded",
        }
        data = {
            "grant_type": "client_credentials",
            "scope": EBAY_OAUTH_SCOPE,
        }

        last_error: Exception | None = None
        for attempt in range(1, EBAY_TOKEN_MAX_ATTEMPTS + 1):
            _log("oauth_request_start")
            try:
                response = self.session.post(
                    _runtime_token_url(),
                    headers=headers,
                    data=data,
                    timeout=EBAY_TOKEN_REQUEST_TIMEOUT,
                )
            except requests.Timeout as error:
                last_error = error
                _log(f"token FAILED reason=request_timeout attempt={attempt}")
                if attempt < EBAY_TOKEN_MAX_ATTEMPTS:
                    continue
                raise EbaySoldError("TOKEN_FAILED: official eBay token request timed out.") from error
            except requests.RequestException as error:
                last_error = error
                _log(f"token FAILED reason=request_exception attempt={attempt} error={error}")
                if attempt < EBAY_TOKEN_MAX_ATTEMPTS:
                    continue
                raise EbaySoldError(f"TOKEN_FAILED: official eBay token request failed: {error}") from error
            break
        else:
            raise EbaySoldError(f"TOKEN_FAILED: official eBay token request failed: {last_error}")

        _log(f"oauth_response_status={response.status_code}")
        _log(f"token endpoint={_runtime_token_url()} status={response.status_code}")
        if response.status_code in {400, 401}:
            _log("token FAILED reason=TOKEN_INVALID_OR_EXPIRED")
            raise EbaySoldError(f"TOKEN_FAILED: TOKEN_INVALID_OR_EXPIRED: official eBay token request failed with HTTP {response.status_code}: {response.text[:240]}")
        if response.status_code == 403:
            _log("token FAILED reason=PERMISSION_DENIED")
            raise EbaySoldError(f"TOKEN_FAILED: PERMISSION_DENIED: official eBay API credentials or scopes were rejected: {response.text[:240]}")
        if response.status_code == 429:
            _log("token FAILED reason=RATE_LIMIT")
            raise EbaySoldRateLimitError(f"TOKEN_FAILED: RATE_LIMIT: official eBay token request was rate-limited: {response.text[:240]}")
        if response.status_code >= 400:
            _log(f"token FAILED reason=HTTP_{response.status_code}")
            raise EbaySoldError(f"TOKEN_FAILED: official eBay token request failed with HTTP {response.status_code}: {response.text[:240]}")

        payload = self._json_response(response, "Official eBay token response was invalid.")
        token = str(payload.get("access_token") or "")
        if not token:
            _log("token FAILED reason=missing_access_token")
            raise EbaySoldError("TOKEN_FAILED: official eBay token response did not include an access token.")

        expires_in = int(payload.get("expires_in") or 7200)
        self._access_token = token
        self._access_token_expires_at = now + max(60, expires_in - 60)
        _log("token OK")
        return token

    def _api_headers(self, *, force_token_refresh: bool = False) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._get_access_token(force_refresh=force_token_refresh)}",
            "Accept": "application/json",
            "X-EBAY-C-MARKETPLACE-ID": _runtime_marketplace(),
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

    def _search_active_raw(self, query: str, limit: int = 20, *, force_token_refresh: bool = False) -> list[dict[str, Any]]:
        params = {
            "q": query,
            "limit": str(limit),
            "filter": "buyingOptions:{FIXED_PRICE}",
            "sort": "price",
        }
        _log(
            f"buy_now search endpoint={_runtime_browse_search_url()} "
            f"marketplace={_runtime_marketplace()} query={query!r} params={params}"
        )
        try:
            response = self.session.get(
                _runtime_browse_search_url(),
                headers=self._api_headers(force_token_refresh=force_token_refresh),
                params=params,
                timeout=self.timeout,
            )
        except requests.Timeout as error:
            raise EbaySoldError("SEARCH_FAILED: official eBay Buy Now request timed out.") from error
        except requests.RequestException as error:
            raise EbaySoldError(f"SEARCH_FAILED: official eBay Buy Now request failed: {error}") from error

        _log(f"buy_now status={response.status_code} query={query!r}")
        if response.status_code == 429:
            raise EbaySoldRateLimitError(f"RATE_LIMIT: official eBay Buy Now lookup refused with HTTP 429: {response.text[:240]}")
        if response.status_code == 403:
            raise EbaySoldError(f"PERMISSION_DENIED: official eBay Buy Now lookup failed with HTTP 403: {response.text[:240]}")
        if response.status_code in {400, 401}:
            raise EbaySoldError(f"TOKEN_INVALID_OR_EXPIRED: official eBay Buy Now lookup failed with HTTP {response.status_code}: {response.text[:240]}")
        if response.status_code >= 400:
            raise EbaySoldError(f"SEARCH_FAILED: official eBay Buy Now lookup failed with HTTP {response.status_code}: {response.text[:240]}")

        payload = self._json_response(response, "SEARCH_FAILED: official eBay Buy Now response was invalid.")
        summaries = payload.get("itemSummaries") or []
        if not isinstance(summaries, list):
            return []
        _log(f"buy_now raw_results={len(summaries)} query={query!r}")
        return [item for item in summaries if isinstance(item, dict)]

    def startup_check(self, query: str = "pokemon", limit: int = 20, *, log: bool = True) -> dict[str, Any]:
        def emit(message: str) -> None:
            if log:
                _log(message)

        result: dict[str, Any] = {
            "enabled": bool(_runtime_enabled()),
            "keys_present": bool(_runtime_client_id() and _runtime_client_secret()),
            "environment": _runtime_environment(),
            "marketplace": _runtime_marketplace(),
            "token_status": "FAILED",
            "search_status": "NOT_RUN",
            "results_count": 0,
            "sample_items": [],
            "error": None,
        }

        emit("STARTUP_CHECK")
        self.log_config_status(log=log)
        if not _runtime_enabled():
            result["error"] = "API_DISABLED"
            return result
        if not result["keys_present"]:
            result["error"] = "API_KEYS_MISSING"
            return result

        token_error = None
        for attempt in range(2):
            try:
                self._get_access_token(force_refresh=attempt > 0)
                result["token_status"] = "OK"
                emit("token OK")
                emit("auth_header_format=Bearer")
                break
            except Exception as error:
                token_error = error
                emit(f"TOKEN_FAILED attempt={attempt + 1} error={error}")
                self._access_token = None
                self._access_token_expires_at = 0.0

        if result["token_status"] != "OK":
            result["error"] = f"TOKEN_FAILED: {token_error}"
            return result

        try:
            items = self._search_active_raw(query, limit=limit)
        except EbaySoldError as error:
            message = str(error)
            if "TOKEN_INVALID_OR_EXPIRED" in message:
                emit(f"TOKEN_INVALID_OR_EXPIRED retrying search once error={message}")
                try:
                    items = self._search_active_raw(query, limit=limit, force_token_refresh=True)
                except Exception as retry_error:
                    result["search_status"] = "FAILED"
                    result["error"] = str(retry_error)
                    emit(f"SEARCH_FAILED error={retry_error}")
                    return result
            else:
                result["search_status"] = "FAILED"
                result["error"] = message
                emit(f"SEARCH_FAILED error={message}")
                return result
        except Exception as error:
            result["search_status"] = "FAILED"
            result["error"] = str(error)
            emit(f"SEARCH_FAILED error={error}")
            return result

        result["search_status"] = "OK"
        result["results_count"] = len(items)
        result["sample_items"] = [
            {
                "title": str(item.get("title") or ""),
                "price": str((item.get("price") or {}).get("value") or ""),
                "currency": str((item.get("price") or {}).get("currency") or ""),
                "buyingOptions": list(item.get("buyingOptions") or []),
            }
            for item in items[:3]
        ]

        emit("search OK")
        emit(f"results_count={result['results_count']}")
        if result["results_count"] == 0:
            result["error"] = "ZERO_RESULTS"
            emit("ZERO_RESULTS")
            return result

        first = result["sample_items"][0]
        emit(f"first_item_title={first['title'][:120]}")
        emit(f"first_item_price={first['price']} {first['currency']}")
        return result

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
    token_only = "--token-test" in argv
    query_args = [arg for arg in argv if arg != "--token-test"]
    query = " ".join(query_args).strip() or "pokemon charizard"
    client = EbayApiClient()
    if token_only:
        client.log_config_status(log=True)
        try:
            client._get_access_token(force_refresh=True)
        except Exception as error:
            print(f"token FAILED: {error}")
            return 1
        print("token OK")
        return 0

    result = client.startup_check(query=query, limit=20, log=True)
    print(f"token {result['token_status']}")
    print(f"search {result['search_status']}")
    print(f"total results: {result['results_count']}")
    for idx, item in enumerate(result["sample_items"][:3], start=1):
        print(
            f"{idx}. {item['title']}\n"
            f"   price: {item['price']} {item['currency']}\n"
            f"   buyingOptions: {', '.join(item['buyingOptions']) or 'n/a'}"
        )
    if result["token_status"] != "OK" or result["search_status"] != "OK":
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(_run_manual_test(sys.argv[1:]))
