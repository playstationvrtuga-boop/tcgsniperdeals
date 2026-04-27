from types import SimpleNamespace
import unittest

import services.deal_detector as deal_detector
from services.ebay_sold_client import EbaySoldListing
from services.price_cache import price_cache


class RawVsGradedPricingTests(unittest.TestCase):
    def setUp(self):
        price_cache.clear()
        self.original_recent = deal_detector.fetch_recent_comparables
        self.original_buy_now = deal_detector.fetch_active_buy_now_comparables

    def tearDown(self):
        deal_detector.fetch_recent_comparables = self.original_recent
        deal_detector.fetch_active_buy_now_comparables = self.original_buy_now
        price_cache.clear()

    def listing(self, title: str, price: str = "10,00 EUR"):
        return SimpleNamespace(title=title, price_display=price)

    def graded_only(self, title_prefix: str):
        return [
            EbaySoldListing(f"PSA 10 {title_prefix}", 220.0),
            EbaySoldListing(f"BGS 9.5 {title_prefix}", 210.0),
            EbaySoldListing(f"CGC 10 {title_prefix}", 200.0),
        ]

    def assert_raw_rejects_graded_market(self, title: str, comparable_prefix: str) -> None:
        deal_detector.fetch_recent_comparables = lambda *_args, **_kwargs: self.graded_only(comparable_prefix)
        deal_detector.fetch_active_buy_now_comparables = lambda *_args, **_kwargs: self.graded_only(comparable_prefix)

        result = deal_detector.evaluate_listing(self.listing(title))

        self.assertEqual(result.listing_type, "raw_card")
        self.assertEqual(result.status, "insufficient_comparables")
        self.assertIsNone(result.reference_price)
        self.assertIsNone(result.estimated_fair_value)
        self.assertEqual(result.comparable_count, 0)
        self.assertEqual(result.buy_now_count, 0)
        self.assertIn("PRICE_COMPARE_INSUFFICIENT_RAW_COMPARABLES", result.reason)

    def test_zapdos_fossil_raw_cannot_use_graded_comparables(self):
        self.assert_raw_rejects_graded_market(
            "Zapdos Fossil Pokemon raw holo 15/62",
            "Zapdos Fossil 15/62",
        )

    def test_lugia_ex_raw_cannot_use_graded_comparables(self):
        self.assert_raw_rejects_graded_market(
            "Lugia EX 94/98 Pokemon",
            "Lugia EX 94/98",
        )

    def test_mega_lucario_ex_raw_cannot_use_graded_comparables(self):
        self.assert_raw_rejects_graded_market(
            "Mega Lucario ex 123/456 Pokemon",
            "Mega Lucario ex 123/456",
        )

    def test_psa_10_compares_only_with_same_or_near_grade_graded_cards(self):
        deal_detector.fetch_recent_comparables = lambda *_args, **_kwargs: []
        deal_detector.fetch_active_buy_now_comparables = lambda *_args, **_kwargs: [
            EbaySoldListing("PSA 10 Charizard 4/102", 800.0),
            EbaySoldListing("PSA 9 Charizard 4/102", 300.0),
            EbaySoldListing("Charizard 4/102 raw card", 120.0),
        ]

        result = deal_detector.evaluate_listing(self.listing("PSA 10 Charizard 4/102 Pokemon", "500,00 EUR"))

        self.assertEqual(result.listing_type, "graded_card")
        self.assertEqual(result.pricing_basis, "buy_now")
        self.assertEqual(result.buy_now_count, 1)
        self.assertEqual(result.market_buy_now_median, 800.0)

    def test_booster_pack_does_not_compare_with_booster_box(self):
        deal_detector.fetch_recent_comparables = lambda *_args, **_kwargs: [
            EbaySoldListing("Pokemon Evolving Skies booster box sealed", 650.0),
        ]
        deal_detector.fetch_active_buy_now_comparables = lambda *_args, **_kwargs: [
            EbaySoldListing("Pokemon Evolving Skies booster box sealed", 700.0),
        ]

        result = deal_detector.evaluate_listing(
            self.listing("Pokemon Evolving Skies booster pack sealed", "8,00 EUR")
        )

        self.assertEqual(result.listing_type, "sealed_product")
        self.assertEqual(result.status, "needs_review")
        self.assertEqual(result.comparable_count, 0)
        self.assertEqual(result.buy_now_count, 0)

    def test_normal_etb_does_not_compare_with_pokemon_center_etb(self):
        deal_detector.fetch_recent_comparables = lambda *_args, **_kwargs: [
            EbaySoldListing("Pokemon Center Evolving Skies ETB", 300.0),
        ]
        deal_detector.fetch_active_buy_now_comparables = lambda *_args, **_kwargs: [
            EbaySoldListing("Pokemon Center Evolving Skies ETB", 320.0),
        ]

        result = deal_detector.evaluate_listing(
            self.listing("Pokemon Evolving Skies ETB Elite Trainer Box", "80,00 EUR")
        )

        self.assertEqual(result.listing_type, "sealed_product")
        self.assertEqual(result.status, "needs_review")
        self.assertEqual(result.comparable_count, 0)
        self.assertEqual(result.buy_now_count, 0)


if __name__ == "__main__":
    unittest.main()
