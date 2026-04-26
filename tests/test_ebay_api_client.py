import unittest

import services.ebay_api_client as ebay_api_client
from services.ebay_api_client import EbayApiClient


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

    def get(self, _url, headers=None, params=None, timeout=None):
        self.last_params = params
        return FakeResponse(self.payload, status_code=self.status_code, text=self.text)

    def post(self, _url, headers=None, data=None, timeout=None):
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
