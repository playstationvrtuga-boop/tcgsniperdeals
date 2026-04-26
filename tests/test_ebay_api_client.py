import unittest

import services.ebay_api_client as ebay_api_client
from services.ebay_api_client import EbayApiClient


class FakeResponse:
    status_code = 200

    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


class FakeSession:
    def __init__(self, payload):
        self.payload = payload
        self.last_params = None

    def get(self, _url, headers=None, params=None, timeout=None):
        self.last_params = params
        return FakeResponse(self.payload)


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
        client._get_access_token = lambda: "token"

        listings = client.fetch_active_buy_now("Charizard PFL 125/094", max_results=5, listing_kind="single_card")

        self.assertEqual([listing.price_eur for listing in listings], [88.0, 95.0])
        self.assertEqual(session.last_params["filter"], "buyingOptions:{FIXED_PRICE}")


if __name__ == "__main__":
    unittest.main()
