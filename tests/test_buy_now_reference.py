from types import SimpleNamespace
import time
import unittest

import services.deal_detector as deal_detector
from services.ebay_sold_client import EbaySoldListing, EbaySoldRateLimitError
from services.price_cache import price_cache


class BuyNowReferenceTests(unittest.TestCase):
    def setUp(self):
        price_cache.clear()
        self.original_recent = deal_detector.fetch_recent_comparables
        self.original_buy_now = deal_detector.fetch_active_buy_now_comparables
        self.original_pause_until = deal_detector._EBAY_PAUSED_UNTIL
        self.original_rate_limit_strikes = deal_detector._EBAY_RATE_LIMIT_STRIKES

    def tearDown(self):
        deal_detector.fetch_recent_comparables = self.original_recent
        deal_detector.fetch_active_buy_now_comparables = self.original_buy_now
        deal_detector._EBAY_PAUSED_UNTIL = self.original_pause_until
        deal_detector._EBAY_RATE_LIMIT_STRIKES = self.original_rate_limit_strikes
        price_cache.clear()

    def listing(self, title="Charizard PFL 125/094", price="70,00 EUR", platform=None):
        return SimpleNamespace(title=title, price_display=price, platform=platform, source=platform)

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
        self.assertIsNone(result.market_buy_now_median)
        self.assertEqual(result.last_2_sales, [100.0, 110.0])
        self.assertEqual(result.buy_now_count, 0)
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

    def test_buy_now_can_price_listing_when_recent_sales_are_missing_without_sniper_deal(self):
        deal_detector.fetch_recent_comparables = lambda *_args, **_kwargs: []
        deal_detector.fetch_active_buy_now_comparables = lambda *_args, **_kwargs: [
            EbaySoldListing("Charizard PFL 125/094 active one", 100.0),
            EbaySoldListing("Charizard PFL 125/094 active two", 110.0),
            EbaySoldListing("Charizard PFL 125/094 active three", 120.0),
        ]

        result = deal_detector.evaluate_listing(self.listing())

        self.assertEqual(result.status, "priced")
        self.assertFalse(result.is_deal)
        self.assertLess(result.confidence_score, 70)
        self.assertEqual(result.price_source, "buy_now")
        self.assertEqual(result.pricing_basis, "buy_now")
        self.assertEqual(result.reference_price, 110.0)
        self.assertEqual(result.buy_now_reference_price, 110.0)
        self.assertEqual(result.buy_now_count, 3)

    def test_low_confidence_listing_stops_after_sold_zero_without_buy_now(self):
        sold_calls = []
        buy_now_calls = []

        def sold_zero(*_args, **_kwargs):
            sold_calls.append("sold")
            return []

        def buy_now_should_not_run(*_args, **_kwargs):
            buy_now_calls.append("buy_now")
            return [
                EbaySoldListing("Pokemon Dragonite active one", 100.0),
                EbaySoldListing("Pokemon Dragonite active two", 110.0),
            ]

        deal_detector.fetch_recent_comparables = sold_zero
        deal_detector.fetch_active_buy_now_comparables = buy_now_should_not_run

        result = deal_detector.evaluate_listing(self.listing("Pokemon Dragonite", "20,00 EUR"))

        self.assertEqual(result.status, "needs_review")
        self.assertEqual(result.parser_confidence, "LOW")
        self.assertLess(result.confidence_score, 60)
        self.assertEqual(result.buy_now_count, 0)
        self.assertEqual(sold_calls, [])
        self.assertEqual(buy_now_calls, [])
        self.assertIn("PRICING_WEAK_ID_NEEDS_REVIEW", result.reason)

    def test_generic_buy_now_query_is_blocked_even_with_medium_confidence(self):
        identity = SimpleNamespace(confidence="MEDIUM")
        signals = SimpleNamespace(full_number="56/165", card_number="56", set_code=None, variant=None)

        reason = deal_detector._buy_now_skip_reason(
            identity=identity,
            signals=signals,
            listing_price=20.0,
            pricing_queries=["pokemon dragonite"],
        )

        self.assertEqual(reason, "generic_or_low_confidence")

    def test_ebay_low_confidence_listing_can_fetch_buy_now_market_data(self):
        sold_calls = []
        buy_now_calls = []

        def sold_zero(*_args, **_kwargs):
            sold_calls.append("sold")
            return []

        def buy_now_refs(*_args, **_kwargs):
            buy_now_calls.append("buy_now")
            return [
                EbaySoldListing("Pokemon Mega Evolution #84", 5.0),
                EbaySoldListing("Pokemon Mega Evolution 84", 6.0),
                EbaySoldListing("Pokemon Mega Evolution card 84", 7.0),
            ]

        deal_detector.fetch_recent_comparables = sold_zero
        deal_detector.fetch_active_buy_now_comparables = buy_now_refs

        result = deal_detector.evaluate_listing(
            self.listing("Pokémon Mega Evolution #84", "US $1.00", platform="ebay")
        )

        self.assertTrue(sold_calls)
        self.assertTrue(buy_now_calls)
        self.assertEqual(result.pricing_basis, "buy_now")
        self.assertEqual(result.buy_now_count, 3)
        self.assertLess(result.confidence_score, 60)

    def test_ebay_graded_name_set_grade_can_fetch_buy_now_without_number(self):
        sold_calls = []
        buy_now_calls = []

        def sold_zero(*_args, **_kwargs):
            sold_calls.append("sold")
            return []

        def buy_now_refs(*_args, **_kwargs):
            buy_now_calls.append("buy_now")
            return [
                EbaySoldListing("Lance's Charizard Celebrations PSA 8", 30.0),
                EbaySoldListing("Pokemon Celebrations Lance's Charizard PSA 8", 32.0),
            ]

        deal_detector.fetch_recent_comparables = sold_zero
        deal_detector.fetch_active_buy_now_comparables = buy_now_refs

        result = deal_detector.evaluate_listing(
            self.listing("Pokemon Lance's Charizard Celebrations PSA 8", "US $12.00", platform="ebay")
        )

        self.assertTrue(sold_calls)
        self.assertTrue(buy_now_calls)
        self.assertEqual(result.pricing_basis, "buy_now")
        self.assertEqual(result.buy_now_count, 2)

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

    def test_buy_now_still_runs_when_recent_sales_are_blocked_without_sniper_deal(self):
        def blocked_recent(*_args, **_kwargs):
            raise EbaySoldRateLimitError("eBay sold lookup returned an anti-bot interruption page.")

        deal_detector.fetch_recent_comparables = blocked_recent
        deal_detector.fetch_active_buy_now_comparables = lambda *_args, **_kwargs: [
            EbaySoldListing("Charizard PFL 125/094 active one", 100.0),
            EbaySoldListing("Charizard PFL 125/094 active two", 110.0),
            EbaySoldListing("Charizard PFL 125/094 active three", 120.0),
        ]

        result = deal_detector.evaluate_listing(self.listing())

        self.assertEqual(result.status, "priced")
        self.assertFalse(result.is_deal)
        self.assertLess(result.confidence_score, 70)
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

        self.assertEqual(result.status, "needs_review")
        self.assertIn("DEAL_REJECTED_NO_REFERENCE", result.reason)
        self.assertIn("SOLD_BLOCKED", result.reason)
        self.assertIn("SEARCH_FAILED", result.reason)

    def test_recent_sold_average_marks_medium_confidence_opportunity(self):
        deal_detector.fetch_recent_comparables = lambda *_args, **_kwargs: [
            EbaySoldListing("Dragonite Expedition 56/165 sold one", 55.0),
        ]
        deal_detector.fetch_active_buy_now_comparables = lambda *_args, **_kwargs: []

        result = deal_detector.evaluate_listing(self.listing("Dragonite 56/165", "45,00 EUR"))

        self.assertEqual(result.status, "deal")
        self.assertTrue(result.is_deal)
        self.assertEqual(result.price_source, "sold")
        self.assertIn("SIMPLE_SOLD_AVG_OPPORTUNITY", result.reason)

    def test_pause_active_defers_listing_without_query_fallbacks(self):
        calls = []

        def should_not_query(*_args, **_kwargs):
            calls.append("called")
            return []

        deal_detector.fetch_recent_comparables = should_not_query
        deal_detector.fetch_active_buy_now_comparables = should_not_query
        deal_detector._EBAY_PAUSED_UNTIL = time.time() + 300

        result = deal_detector.evaluate_listing(self.listing())

        self.assertEqual(result.status, "retry_later")
        self.assertEqual(result.score, 0)
        self.assertFalse(result.is_deal)
        self.assertEqual(result.reason.split("; ")[0], "diagnostic_reason=EBAY_RATE_LIMIT")
        self.assertEqual(result.last_2_sales, [])
        self.assertEqual(calls, [])

    def test_global_pause_only_starts_for_explicit_rate_limit(self):
        deal_detector._EBAY_PAUSED_UNTIL = 0.0

        ignored = deal_detector._pause_ebay_calls(EbaySoldRateLimitError("Official eBay sold lookup refused with HTTP 403."))
        self.assertFalse(ignored)
        self.assertEqual(deal_detector.ebay_pause_remaining_seconds(), 0)

        triggered = deal_detector._pause_ebay_calls(EbaySoldRateLimitError("RATE_LIMIT: official lookup refused with HTTP 429."))
        self.assertTrue(triggered)
        self.assertGreater(deal_detector.ebay_pause_remaining_seconds(), 0)

    def test_rate_limit_backoff_caps_at_three_minutes(self):
        deal_detector._EBAY_PAUSED_UNTIL = 0.0
        deal_detector._EBAY_RATE_LIMIT_STRIKES = 0

        pauses = []
        for _ in range(4):
            deal_detector._pause_ebay_calls(EbaySoldRateLimitError("RATE_LIMIT: HTTP 429"))
            pauses.append(deal_detector.ebay_pause_remaining_seconds())
            deal_detector._EBAY_PAUSED_UNTIL = 0.0

        self.assertGreaterEqual(pauses[0], 59)
        self.assertGreaterEqual(pauses[1], 119)
        self.assertGreaterEqual(pauses[2], 179)
        self.assertGreaterEqual(pauses[3], 179)
        self.assertLessEqual(pauses[3], 180)


if __name__ == "__main__":
    unittest.main()
