import unittest

from services.listing_availability import UNKNOWN_CHECK_FAILED_STATUS, check_listing_availability


class FakeResponse:
    def __init__(self, status_code=200, body=""):
        self.status_code = status_code
        self.body = body.encode("utf-8")
        self.encoding = "utf-8"

    def iter_content(self, chunk_size=16384):
        yield self.body


class FakeSession:
    def __init__(self, response):
        self.response = response

    def get(self, *args, **kwargs):
        return self.response


class ListingAvailabilityTests(unittest.TestCase):
    def test_404_marks_removed(self):
        result = check_listing_availability(
            "https://www.vinted.pt/items/1-test",
            platform="Vinted",
            session=FakeSession(FakeResponse(status_code=404)),
        )
        self.assertTrue(result.is_gone)
        self.assertEqual(result.status, "removed")

    def test_vinted_sold_text_marks_sold(self):
        result = check_listing_availability(
            "https://www.vinted.pt/items/1-test",
            platform="Vinted",
            session=FakeSession(FakeResponse(body="This item is no longer available. Item sold.")),
        )
        self.assertTrue(result.is_gone)
        self.assertEqual(result.status, "sold")

    def test_vinted_active_actions_keep_listing_available(self):
        result = check_listing_availability(
            "https://www.vinted.pt/items/1-test",
            platform="Vinted",
            session=FakeSession(
                FakeResponse(
                    body=(
                        "<html><body>Pokemon card listing "
                        "Buy now Make an offer Ask seller "
                        "sold items you might like</body></html>"
                    )
                )
            ),
        )
        self.assertFalse(result.is_gone)
        self.assertEqual(result.status, "available")
        self.assertIn("vinted_active_action", result.reason)

    def test_vinted_plain_200_is_unknown_not_gone(self):
        result = check_listing_availability(
            "https://www.vinted.pt/items/1-test",
            platform="Vinted",
            session=FakeSession(FakeResponse(body="<html><title>Pokemon card listing</title></html>")),
        )
        self.assertFalse(result.is_gone)
        self.assertEqual(result.status, UNKNOWN_CHECK_FAILED_STATUS)

    def test_rate_limit_does_not_mark_gone(self):
        result = check_listing_availability(
            "https://www.ebay.com/itm/123",
            platform="eBay",
            session=FakeSession(FakeResponse(status_code=429)),
        )
        self.assertFalse(result.is_gone)
        self.assertEqual(result.status, UNKNOWN_CHECK_FAILED_STATUS)

    def test_plain_200_stays_available(self):
        result = check_listing_availability(
            "https://www.ebay.com/itm/123",
            platform="eBay",
            session=FakeSession(FakeResponse(body="<html><title>Pokemon card listing</title></html>")),
        )
        self.assertFalse(result.is_gone)
        self.assertEqual(result.status, "available")


if __name__ == "__main__":
    unittest.main()
