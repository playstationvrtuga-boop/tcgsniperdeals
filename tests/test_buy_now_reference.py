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

    def test_sold_reference_has_priority_over_lower_buy_now(self):
        deal_detector.fetch_recent_comparables = lambda *_args, **_kwargs: [
            EbaySoldListing("Charizard PFL 125/094 sold one", 100.0),
            EbaySoldListing("Charizard PFL 125/094 sold two", 110.0),
            EbaySoldListing("Charizard PFL 125/094 sold three", 120.0),
        ]
        deal_detector.fetch_active_buy_now_comparables = lambda *_args, **_kwargs: [
            EbaySoldListing("Charizard PFL 125/094 active one", 80.0),
            EbaySoldListing("Charizard PFL 125/094 active two", 85.0),
            EbaySoldListing("Charizard PFL 125/094 active three", 90.0),
        ]

        result = deal_detector.evaluate_listing(self.listing())

        self.assertEqual(result.status, "deal")
        self.assertEqual(result.price_source, "sold")
        self.assertEqual(result.pricing_basis, "sold")
        self.assertEqual(result.reference_price, 110.0)
        self.assertEqual(result.estimated_fair_value, 110.0)
        self.assertEqual(result.sold_median_price, 110.0)
        self.assertEqual(result.market_buy_now_median, 85.0)
        self.assertEqual(result.last_2_sales, [100.0, 110.0])
        self.assertEqual(result.buy_now_count, 3)
        self.assertEqual(result.comparable_count, 3)

    def test_one_recent_sale_sets_medium_confidence_fair_value(self):
        deal_detector.fetch_recent_comparables = lambda *_args, **_kwargs: [
            EbaySoldListing("Charizard PFL 125/094 sold one", 100.0),
        ]
        deal_detector.fetch_active_buy_now_comparables = lambda *_args, **_kwargs: [
            EbaySoldListing("Charizard PFL 125/094 active one", 130.0),
            EbaySoldListing("Charizard PFL 125/094 active two", 140.0),
            EbaySoldListing("Charizard PFL 125/094 active three", 150.0),
        ]

        result = deal_detector.evaluate_listing(self.listing())

        self.assertEqual(result.pricing_basis, "sold")
        self.assertEqual(result.estimated_fair_value, 100.0)
        self.assertEqual(result.confidence_score, 72)

    def test_buy_now_can_price_listing_when_recent_sales_are_missing(self):
        deal_detector.fetch_recent_comparables = lambda *_args, **_kwargs: []
        deal_detector.fetch_active_buy_now_comparables = lambda *_args, **_kwargs: [
            EbaySoldListing("Charizard PFL 125/094 active one", 100.0),
            EbaySoldListing("Charizard PFL 125/094 active two", 110.0),
            EbaySoldListing("Charizard PFL 125/094 active three", 120.0),
        ]

        result = deal_detector.evaluate_listing(self.listing())

        self.assertEqual(result.status, "deal")
        self.assertEqual(result.price_source, "buy_now")
        self.assertEqual(result.pricing_basis, "buy_now")
        self.assertEqual(result.reference_price, 110.0)
        self.assertEqual(result.buy_now_reference_price, 110.0)
        self.assertEqual(result.buy_now_count, 3)

    def test_limited_buy_now_comparables_still_price_with_lower_confidence(self):
        deal_detector.fetch_recent_comparables = lambda *_args, **_kwargs: []
        deal_detector.fetch_active_buy_now_comparables = lambda *_args, **_kwargs: [
            EbaySoldListing("Charizard PFL 125/094 active one", 100.0),
            EbaySoldListing("Charizard PFL 125/094 active two", 110.0),
        ]

        result = deal_detector.evaluate_listing(self.listing(price="80,00 EUR"))

        self.assertEqual(result.status, "priced")
        self.assertEqual(result.price_source, "buy_now")
        self.assertEqual(result.pricing_basis, "buy_now")
        self.assertEqual(result.reference_price, 105.0)
        self.assertEqual(result.buy_now_reference_price, 105.0)
        self.assertEqual(result.buy_now_count, 2)
        self.assertLess(result.confidence_score, 60)

    def test_usd_listing_price_keeps_decimal_point(self):
        self.assertEqual(deal_detector.extract_listing_price_eur("US $16.95"), 14.92)
        self.assertEqual(deal_detector.extract_listing_price_eur("$1,234.56"), 1086.41)

    def test_buy_now_still_runs_when_recent_sales_are_blocked(self):
        def blocked_recent(*_args, **_kwargs):
            raise EbaySoldRateLimitError("eBay sold lookup returned an anti-bot interruption page.")

        deal_detector.fetch_recent_comparables = blocked_recent
        deal_detector.fetch_active_buy_now_comparables = lambda *_args, **_kwargs: [
            EbaySoldListing("Charizard PFL 125/094 active one", 100.0),
            EbaySoldListing("Charizard PFL 125/094 active two", 110.0),
            EbaySoldListing("Charizard PFL 125/094 active three", 120.0),
        ]

        result = deal_detector.evaluate_listing(self.listing())

        self.assertEqual(result.status, "deal")
        self.assertEqual(result.price_source, "buy_now")
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

        self.assertEqual(result.status, "insufficient_comparables")
        self.assertIn("DEAL_REJECTED_NO_REFERENCE", result.reason)
        self.assertIn("SOLD_BLOCKED", result.reason)
        self.assertIn("SEARCH_FAILED", result.reason)


if __name__ == "__main__":
    unittest.main()
