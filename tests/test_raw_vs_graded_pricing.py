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
        self.original_prepare_queries = deal_detector._prepare_pricing_queries

    def tearDown(self):
        deal_detector.fetch_recent_comparables = self.original_recent
        deal_detector.fetch_active_buy_now_comparables = self.original_buy_now
        deal_detector._prepare_pricing_queries = self.original_prepare_queries
        price_cache.clear()

    def listing(self, title: str, price: str = "10,00 EUR"):
        return SimpleNamespace(title=title, price_display=price)

    def graded_only(self, title_prefix: str):
        return [
            EbaySoldListing(f"PSA 10 {title_prefix}", 220.0),
            EbaySoldListing(f"BGS 9.5 {title_prefix}", 210.0),
            EbaySoldListing(f"CGC 10 {title_prefix}", 200.0),
        ]

    def test_detects_raw_individual_cards_without_grading_signals(self):
        self.assertEqual(deal_detector.detect_listing_market_type("Mewtwo 56/165 Expedition"), "raw_card")
        self.assertEqual(deal_detector.detect_listing_market_type("Alakazam Star 99/100"), "raw_card")
        self.assertEqual(deal_detector.detect_listing_market_type("Charizard ex 199/165"), "raw_card")

    def test_detects_graded_card_and_grade(self):
        title = "Charizard brs 174 PSA 10"

        self.assertEqual(deal_detector.detect_listing_market_type(title), "graded_card")
        self.assertEqual(deal_detector._extract_grading_company(title), "PSA")
        self.assertEqual(deal_detector._extract_grade(title), 10.0)

    def test_detects_french_graded_gradee_ten(self):
        title = "Chinchidou 082/071 Ultra rare Pokemon - Gradée 10"

        self.assertEqual(deal_detector.detect_listing_market_type(title), "graded_card")
        self.assertEqual(deal_detector._extract_grade(title), 10.0)

    def test_detects_additional_real_market_types(self):
        self.assertEqual(
            deal_detector.detect_listing_market_type(
                "Dragonite V 192/203 Evoluzioni Eteree Italiano Aigrading 9 mint"
            ),
            "graded_card",
        )
        self.assertEqual(deal_detector._extract_grade("Dragonite Aigrading 9 mint"), 9.0)
        self.assertEqual(
            deal_detector.detect_listing_market_type(
                "Ditto 132/165 Cosmos Holo Prize Pack Stamped Series 6 Pokemon TCG 151 Mew"
            ),
            "raw_card",
        )
        self.assertEqual(deal_detector.detect_listing_market_type("pokémon cartes"), "lot_bundle")

    def test_raw_comparable_filter_rejects_graded_titles(self):
        for ebay_title in ("PSA 10 Mewtwo 56/165", "CGC 9 Mewtwo 56/165", "Mewtwo slab", "Mewtwo graded"):
            with self.subTest(ebay_title=ebay_title):
                self.assertFalse(
                    deal_detector.is_comparable_ebay_result("raw_card", None, ebay_title)
                )

    def test_graded_comparable_filter_rejects_raw_titles(self):
        for ebay_title in ("Charizard 4/102 raw card", "Charizard 4/102 ungraded"):
            with self.subTest(ebay_title=ebay_title):
                self.assertFalse(
                    deal_detector.is_comparable_ebay_result("graded_card", 10.0, ebay_title)
                )

    def test_raw_comparable_accepts_same_full_number_with_localized_set_text(self):
        result = deal_detector.is_comparable_listing(
            "Rayquaza Vmax - EB7 217/203 - Evolution Celeste - Carte Pokemon",
            "RAYQUAZA VMAX RAINBOW - POKEMON 217/203 EB7 CELESTIAL EVOLUTION NEW FR",
            "raw_card",
        )

        self.assertEqual(result, (True, "accepted"))

    def test_psa_10_leading_grade_does_not_become_card_number(self):
        listing_type = deal_detector.detect_listing_market_type("Charizard BRS 174 PSA 10")

        self.assertEqual(listing_type, "graded_card")
        self.assertEqual(
            deal_detector.is_comparable_listing(
                "Charizard BRS 174 PSA 10",
                "PSA 10 Charizard BRS 174",
                listing_type,
            ),
            (True, "accepted"),
        )
        self.assertEqual(
            deal_detector.is_comparable_listing(
                "Charizard BRS 174 PSA 10",
                "PSA 9 Charizard BRS 174",
                listing_type,
            ),
            (False, "grade_mismatch"),
        )

    def assert_raw_rejects_graded_market(self, title: str, comparable_prefix: str) -> None:
        deal_detector.fetch_recent_comparables = lambda *_args, **_kwargs: self.graded_only(comparable_prefix)
        deal_detector.fetch_active_buy_now_comparables = lambda *_args, **_kwargs: self.graded_only(comparable_prefix)

        result = deal_detector.evaluate_listing(self.listing(title))

        self.assertEqual(result.listing_type, "raw_card")
        self.assertEqual(result.status, "needs_review")
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

    def test_query_reduction_does_not_chase_fallback_after_graded_results_for_raw_card(self):
        deal_detector._prepare_pricing_queries = lambda _queries: ["bad graded query", "good raw query"]
        deal_detector.fetch_recent_comparables = lambda *_args, **_kwargs: []
        calls = []

        def buy_now(query, *_args, **_kwargs):
            calls.append(query)
            if query == "bad graded query":
                return self.graded_only("Zapdos Fossil 15/62")
            return [
                EbaySoldListing("Zapdos Fossil 15/62 raw holo Pokemon", 42.0),
                EbaySoldListing("Pokemon Zapdos Fossil 15/62 raw card", 45.0),
                EbaySoldListing("Zapdos 15/62 Fossil Pokemon card raw", 48.0),
            ]

        deal_detector.fetch_active_buy_now_comparables = buy_now

        result = deal_detector.evaluate_listing(
            self.listing("Zapdos Fossil Pokemon raw holo 15/62", "20,00 EUR")
        )

        self.assertEqual(result.listing_type, "raw_card")
        self.assertEqual(result.status, "needs_review")
        self.assertIsNone(result.pricing_basis)
        self.assertEqual(result.buy_now_count, 0)
        self.assertEqual(calls, ["bad graded query"])

    def test_raw_buy_now_only_cannot_become_high_confidence_deal(self):
        deal_detector.fetch_recent_comparables = lambda *_args, **_kwargs: []
        deal_detector.fetch_active_buy_now_comparables = lambda *_args, **_kwargs: [
            EbaySoldListing("Charizard PFL 125/094 raw Pokemon", 100.0),
            EbaySoldListing("Pokemon Charizard PFL 125/094 raw", 110.0),
            EbaySoldListing("Charizard 125/094 PFL Pokemon card", 120.0),
        ]

        result = deal_detector.evaluate_listing(
            self.listing("Charizard PFL 125/094 Pokemon", "70,00 EUR")
        )

        self.assertEqual(result.pricing_basis, "buy_now")
        self.assertEqual(result.status, "priced")
        self.assertFalse(result.is_deal)
        self.assertLess(result.confidence_score, 70)
        self.assertLessEqual(result.score, 69)

    def test_absurd_raw_profit_without_sold_comparable_needs_review(self):
        deal_detector.fetch_recent_comparables = lambda *_args, **_kwargs: []
        deal_detector.fetch_active_buy_now_comparables = lambda *_args, **_kwargs: [
            EbaySoldListing("Alakazam Star 99/100 raw Pokemon card", 220.0),
            EbaySoldListing("Pokemon Alakazam Star 99/100 raw", 230.0),
            EbaySoldListing("Alakazam Star 99/100 Pokemon card raw", 240.0),
        ]

        result = deal_detector.evaluate_listing(
            self.listing("Alakazam Star 99/100", "20,00 EUR")
        )

        self.assertEqual(result.status, "needs_review")
        self.assertFalse(result.is_deal)
        self.assertEqual(result.score, 0)
        self.assertIn("profit_too_high_without_sold", result.reason)


if __name__ == "__main__":
    unittest.main()
