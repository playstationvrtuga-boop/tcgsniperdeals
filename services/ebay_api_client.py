from __future__ import annotations

import base64
import time
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

    def _get_access_token(self) -> str:
        if not self.is_configured():
            raise EbaySoldError("Official eBay API is not configured.")

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
            raise EbaySoldError("Official eBay token request timed out.") from error
        except requests.RequestException as error:
            raise EbaySoldError(f"Official eBay token request failed: {error}") from error

        if response.status_code in {401, 403}:
            raise EbaySoldError("Official eBay API credentials were rejected.")
        if response.status_code == 429:
            raise EbaySoldRateLimitError("Official eBay token request was rate-limited.")
        if response.status_code >= 400:
            raise EbaySoldError(f"Official eBay token request failed with HTTP {response.status_code}.")

        payload = self._json_response(response, "Official eBay token response was invalid.")
        token = str(payload.get("access_token") or "")
        if not token:
            raise EbaySoldError("Official eBay token response did not include an access token.")

        expires_in = int(payload.get("expires_in") or 7200)
        self._access_token = token
        self._access_token_expires_at = now + max(60, expires_in - 60)
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

    def fetch_active_buy_now(
        self,
        product_name: str,
        max_results: int = 5,
        listing_kind: str | None = None,
    ) -> list[EbaySoldListing]:
        query = _query_from_title(product_name, listing_kind=listing_kind)
        if not query or not self.is_configured():
            return []

        limit = max(1, min(max_results * 3, 50))
        params = {
            "q": query,
            "limit": str(limit),
            "filter": "buyingOptions:{FIXED_PRICE}",
        }

        try:
            response = self.session.get(BROWSE_SEARCH_URL, headers=self._api_headers(), params=params, timeout=self.timeout)
        except requests.Timeout as error:
            raise EbaySoldError("Official eBay Buy Now request timed out.") from error
        except requests.RequestException as error:
            raise EbaySoldError(f"Official eBay Buy Now request failed: {error}") from error

        if response.status_code in {403, 429}:
            raise EbaySoldRateLimitError(f"Official eBay Buy Now lookup refused with HTTP {response.status_code}.")
        if response.status_code >= 400:
            raise EbaySoldError(f"Official eBay Buy Now lookup failed with HTTP {response.status_code}.")

        payload = self._json_response(response, "Official eBay Buy Now response was invalid.")
        summaries = payload.get("itemSummaries") or []
        if not isinstance(summaries, list):
            return []

        listings: list[EbaySoldListing] = []
        for item in summaries:
            if not isinstance(item, dict):
                continue

            buying_options = item.get("buyingOptions") or []
            if buying_options and "FIXED_PRICE" not in buying_options:
                continue

            title = str(item.get("title") or "").strip()
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

        return listings

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
