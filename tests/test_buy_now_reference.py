from types import SimpleNamespace
import unittest

import services.deal_detector as deal_detector
from services.ebay_sold_client import EbaySoldListing, EbaySoldRateLimitError
from services.price_cache import price_cache


class BuyNowReferenceTests(unittest.TestCase):
    def setUp(self):
        price_cache.clear()
        self.original_recent = deal_detector.fetch_recent_comparables
        self.original_buy_now = deal_detector.fetch_active_buy_now_comparables

    def tearDown(self):
        deal_detector.fetch_recent_comparables = self.original_recent
        deal_detector.fetch_active_buy_now_comparables = self.original_buy_now
        price_cache.clear()

    def listing(self, title="Charizard PFL 125/094", price="70,00 EUR"):
        return SimpleNamespace(title=title, price_display=price)

    def test_buy_now_caps_sold_reference_when_active_market_is_lower(self):
        deal_detector.fetch_recent_comparables = lambda *_args, **_kwargs: [
            EbaySoldListing("sold one", 100.0),
            EbaySoldListing("sold two", 110.0),
            EbaySoldListing("sold three", 120.0),
        ]
        deal_detector.fetch_active_buy_now_comparables = lambda *_args, **_kwargs: [
            EbaySoldListing("active one", 80.0),
            EbaySoldListing("active two", 85.0),
            EbaySoldListing("active three", 90.0),
        ]

        result = deal_detector.evaluate_listing(self.listing())

        self.assertEqual(result.status, "priced")
        self.assertEqual(result.price_source, "ebay_buy_now_with_sold_reference")
        self.assertEqual(result.reference_price, 85.0)
        self.assertEqual(result.buy_now_count, 3)
        self.assertEqual(result.comparable_count, 3)

    def test_buy_now_can_price_listing_when_recent_sales_are_missing(self):
        deal_detector.fetch_recent_comparables = lambda *_args, **_kwargs: []
        deal_detector.fetch_active_buy_now_comparables = lambda *_args, **_kwargs: [
            EbaySoldListing("active one", 100.0),
            EbaySoldListing("active two", 110.0),
            EbaySoldListing("active three", 120.0),
        ]

        result = deal_detector.evaluate_listing(self.listing())

        self.assertEqual(result.status, "deal")
        self.assertEqual(result.price_source, "ebay_buy_now")
        self.assertEqual(result.reference_price, 110.0)
        self.assertEqual(result.buy_now_reference_price, 110.0)
        self.assertEqual(result.buy_now_count, 3)

    def test_buy_now_still_runs_when_recent_sales_are_blocked(self):
        def blocked_recent(*_args, **_kwargs):
            raise EbaySoldRateLimitError("eBay sold lookup returned an anti-bot interruption page.")

        deal_detector.fetch_recent_comparables = blocked_recent
        deal_detector.fetch_active_buy_now_comparables = lambda *_args, **_kwargs: [
            EbaySoldListing("active one", 100.0),
            EbaySoldListing("active two", 110.0),
            EbaySoldListing("active three", 120.0),
        ]

        result = deal_detector.evaluate_listing(self.listing())

        self.assertEqual(result.status, "deal")
        self.assertEqual(result.price_source, "ebay_buy_now")
        self.assertEqual(result.reference_price, 110.0)
        self.assertIn("SOLD_BLOCKED", result.reason)

    def test_worker_style_result_needs_review_when_sold_and_buy_now_fail(self):
        def blocked_recent(*_args, **_kwargs):
            raise EbaySoldRateLimitError("SOLD_BLOCKED")

        def failed_buy_now(*_args, **_kwargs):
            raise EbaySoldRateLimitError("SEARCH_FAILED")

        deal_detector.fetch_recent_comparables = blocked_recent
        deal_detector.fetch_active_buy_now_comparables = failed_buy_now

        result = deal_detector.evaluate_listing(self.listing())

        self.assertEqual(result.status, "needs_review")
        self.assertIn("DEAL_REJECTED_NO_REFERENCE", result.reason)
        self.assertIn("SOLD_BLOCKED", result.reason)
        self.assertIn("SEARCH_FAILED", result.reason)


if __name__ == "__main__":
    unittest.main()
