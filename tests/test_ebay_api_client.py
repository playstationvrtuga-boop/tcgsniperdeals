import base64
import time
import unittest

import services.ebay_api_client as ebay_api_client
from services.ebay_api_client import EBAY_TOKEN_FAILURE_COOLDOWN_SECONDS, EBAY_TOKEN_REQUEST_TIMEOUT, EbayApiClient


class FakeResponse:
    def __init__(self, payload, status_code=200, text=""):
        self._payload = payload
        self.status_code = status_code
        self.text = text

    def json(self):
        return self._payload


class FakeSession:
    def __init__(self, payload, status_code=200, text=""):
        self.payload = payload
        self.status_code = status_code
        self.text = text
        self.last_params = None
        self.last_post_url = None
        self.last_post_headers = None
        self.last_post_data = None
        self.last_post_timeout = None
        self.post_count = 0

    def get(self, _url, headers=None, params=None, timeout=None):
        self.last_params = params
        return FakeResponse(self.payload, status_code=self.status_code, text=self.text)

    def post(self, _url, headers=None, data=None, timeout=None):
        self.post_count += 1
        self.last_post_url = _url
        self.last_post_headers = headers or {}
        self.last_post_data = data or {}
        self.last_post_timeout = timeout
        return FakeResponse(self.payload, status_code=self.status_code, text=self.text)


class EbayApiClientTests(unittest.TestCase):
    def setUp(self):
        self.original_enabled = ebay_api_client.EBAY_ENABLE_OFFICIAL_API
        self.original_client_id = ebay_api_client.EBAY_CLIENT_ID
        self.original_client_secret = ebay_api_client.EBAY_CLIENT_SECRET
        ebay_api_client.EBAY_ENABLE_OFFICIAL_API = True
        ebay_api_client.EBAY_CLIENT_ID = "client-id"
        ebay_api_client.EBAY_CLIENT_SECRET = "client-secret"

    def tearDown(self):
        ebay_api_client.EBAY_ENABLE_OFFICIAL_API = self.original_enabled
        ebay_api_client.EBAY_CLIENT_ID = self.original_client_id
        ebay_api_client.EBAY_CLIENT_SECRET = self.original_client_secret

    def test_fetch_active_buy_now_returns_filtered_price_references(self):
        session = FakeSession(
            {
                "itemSummaries": [
                    {
                        "title": "Charizard PFL 125/094 Pokemon Card",
                        "buyingOptions": ["FIXED_PRICE"],
                        "price": {"value": "100.00", "currency": "USD"},
                    },
                    {
                        "title": "Pokemon Elite Trainer Box unrelated",
                        "buyingOptions": ["FIXED_PRICE"],
                        "price": {"value": "40.00", "currency": "USD"},
                    },
                    {
                        "title": "Charizard PFL 125/094 Pokemon Card EU",
                        "buyingOptions": ["FIXED_PRICE"],
                        "price": {"value": "95.00", "currency": "EUR"},
                    },
                ]
            }
        )
        client = EbayApiClient()
        client.session = session
        client._get_access_token = lambda **_kwargs: "token"

        listings = client.fetch_active_buy_now("Charizard PFL 125/094", max_results=5, listing_kind="single_card")

        self.assertEqual([listing.price_eur for listing in listings], [88.0, 95.0])
        self.assertEqual(session.last_params["filter"], "buyingOptions:{FIXED_PRICE}")
        self.assertEqual(session.last_params["limit"], "20")
        self.assertEqual(session.last_params["sort"], "price")

    def test_missing_api_keys_report_clear_status(self):
        ebay_api_client.EBAY_ENABLE_OFFICIAL_API = True
        ebay_api_client.EBAY_CLIENT_ID = ""
        ebay_api_client.EBAY_CLIENT_SECRET = ""
        client = EbayApiClient()

        self.assertEqual(client.config_status(), "API_KEYS_MISSING")
        self.assertEqual(client.fetch_active_buy_now("pokemon charizard"), [])

    def test_token_failure_reports_token_failed(self):
        client = EbayApiClient()
        client.session = FakeSession({"error": "invalid_client"}, status_code=401, text="invalid_client")

        with self.assertRaisesRegex(Exception, "TOKEN_FAILED"):
            client._get_access_token()

    def test_token_failure_enters_short_cooldown(self):
        session = FakeSession({"error": "invalid_client"}, status_code=401, text="invalid_client")
        client = EbayApiClient()
        client.session = session

        with self.assertRaisesRegex(Exception, "TOKEN_FAILED"):
            client._get_access_token()
        with self.assertRaisesRegex(Exception, "cooldown"):
            client._get_access_token()

        self.assertEqual(session.post_count, 1)
        self.assertGreater(client._token_failure_until, 0)
        self.assertLessEqual(client._token_failure_until - time.time(), EBAY_TOKEN_FAILURE_COOLDOWN_SECONDS)

    def test_token_request_uses_basic_auth_form_data_and_timeout(self):
        session = FakeSession({"access_token": "access-token", "expires_in": 7200})
        client = EbayApiClient()
        client.session = session

        token = client._get_access_token(force_refresh=True)

        expected_basic = base64.b64encode(b"client-id:client-secret").decode("ascii")
        self.assertEqual(token, "access-token")
        self.assertEqual(session.last_post_headers["Authorization"], f"Basic {expected_basic}")
        self.assertEqual(session.last_post_headers["Content-Type"], "application/x-www-form-urlencoded")
        self.assertEqual(session.last_post_data["grant_type"], "client_credentials")
        self.assertEqual(session.last_post_data["scope"], "https://api.ebay.com/oauth/api_scope")
        self.assertEqual(session.last_post_timeout, EBAY_TOKEN_REQUEST_TIMEOUT)
        self.assertEqual(session.last_post_url, "https://api.ebay.com/identity/v1/oauth2/token")

    def test_zero_results_return_empty_after_query_variants(self):
        client = EbayApiClient()
        client.session = FakeSession({"itemSummaries": []})
        client._get_access_token = lambda **_kwargs: "token"

        listings = client.fetch_active_buy_now("No Such Pokemon Query", max_results=5)

        self.assertEqual(listings, [])

    def test_startup_check_reports_ok_with_sample_items(self):
        session = FakeSession(
            {
                "itemSummaries": [
                    {
                        "title": "Pokemon Charizard Card",
                        "buyingOptions": ["FIXED_PRICE"],
                        "price": {"value": "99.99", "currency": "USD"},
                    }
                ]
            }
        )
        client = EbayApiClient()
        client.session = session
        client._get_access_token = lambda **_kwargs: "token"

        result = client.startup_check(log=False)

        self.assertEqual(result["token_status"], "OK")
        self.assertEqual(result["search_status"], "OK")
        self.assertEqual(result["results_count"], 1)
        self.assertEqual(result["sample_items"][0]["title"], "Pokemon Charizard Card")


if __name__ == "__main__":
    unittest.main()
