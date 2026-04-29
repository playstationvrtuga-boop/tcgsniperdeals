from types import SimpleNamespace
import unittest

import services.deal_detector as deal_detector
from services.ebay_sold_client import EbaySoldListing
from services.price_cache import price_cache


class ListingParserTests(unittest.TestCase):
    def setUp(self):
        price_cache.clear()
        self.original_recent = deal_detector.fetch_recent_comparables
        self.original_buy_now = deal_detector.fetch_active_buy_now_comparables

    def tearDown(self):
        deal_detector.fetch_recent_comparables = self.original_recent
        deal_detector.fetch_active_buy_now_comparables = self.original_buy_now
        price_cache.clear()

    def listing(self, title, price="10,00 EUR"):
        return SimpleNamespace(title=title, price_display=price)

    def test_high_confidence_name_number_and_set(self):
        identity = deal_detector.parse_listing_identity("Charizard PFL 125/094 Paldea Evolved")

        self.assertEqual(identity.confidence, "HIGH")
        self.assertEqual(identity.extracted_name, "charizard")
        self.assertTrue(identity.extracted_number)
        self.assertEqual(identity.extracted_set, "PFL")

    def test_medium_confidence_name_and_number_formats(self):
        samples = [
            "Pikachu 080/132",
            "Pikachu 080 / 132",
            "Pikachu No.080",
            "Pikachu Card 80",
        ]

        for title in samples:
            with self.subTest(title=title):
                identity = deal_detector.parse_listing_identity(title)
                self.assertEqual(identity.confidence, "HIGH" if "/" in title else "MEDIUM")
                self.assertEqual(identity.extracted_name, "pikachu")
                self.assertTrue(identity.extracted_number)

    def test_low_confidence_name_only_stops_after_sold_zero(self):
        buy_now_calls = []
        deal_detector.fetch_recent_comparables = lambda *_args, **_kwargs: []

        def buy_now(*_args, **_kwargs):
            buy_now_calls.append("buy_now")
            return [
                EbaySoldListing("Charizard Pokemon card", 100.0),
                EbaySoldListing("Charizard Pokemon card 2", 110.0),
                EbaySoldListing("Charizard Pokemon card 3", 120.0),
            ]

        deal_detector.fetch_active_buy_now_comparables = buy_now

        result = deal_detector.evaluate_listing(self.listing("Charizard", price="70,00 EUR"))

        self.assertNotEqual(result.reason, "listing_not_precisely_identified")
        self.assertEqual(result.parser_confidence, "LOW")
        self.assertEqual(result.parser_query, "pokemon charizard")
        self.assertEqual(result.status, "insufficient_comparables")
        self.assertIsNone(result.pricing_basis)
        self.assertEqual(result.buy_now_count, 0)
        self.assertEqual(buy_now_calls, [])

    def test_pokemon_without_known_name_is_low_confidence(self):
        identity = deal_detector.parse_listing_identity("Carta pokemon brilhante francesa")

        self.assertEqual(identity.confidence, "LOW")
        self.assertTrue(identity.fallback_query_used)
        self.assertIn("pokemon", identity.query)

    def test_non_pokemon_listing_is_only_rejected_case(self):
        result = deal_detector.evaluate_listing(self.listing("Vintage football shirt", price="12,00 EUR"))

        self.assertEqual(result.status, "skipped")
        self.assertEqual(result.reason, "not_pokemon_related")
        self.assertEqual(result.parser_confidence, "UNKNOWN")


if __name__ == "__main__":
    unittest.main()
