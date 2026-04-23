import unittest

from services.alert_formatter import classify_deal_level, format_free_alert_text


class DealLevelTests(unittest.TestCase):
    def test_elite_level(self):
        result = classify_deal_level(26, 8)
        self.assertEqual(result["deal_level"], "elite")
        self.assertEqual(result["badge"], "HOT DEAL")

    def test_strong_level(self):
        result = classify_deal_level(16, 7)
        self.assertEqual(result["deal_level"], "strong")
        self.assertEqual(result["badge"], "EASY FLIP")

    def test_good_level(self):
        result = classify_deal_level(10, 5)
        self.assertEqual(result["deal_level"], "good")
        self.assertEqual(result["badge"], "VALUE DEAL")

    def test_below_threshold(self):
        result = classify_deal_level(8, 4)
        self.assertIsNone(result)

    def test_short_variant_contains_fomo(self):
        text = format_free_alert_text(
            {
                "title": "Charizard EX PFL125 Near Mint",
                "listing_price": 12,
                "listing_price_text": "12.00 EUR",
                "market_price": 25,
                "discount_percent": 52,
                "free_message_variant": "short",
            }
        )
        self.assertIn("Real-time listing", text)
        self.assertIn("Listing Price", text)


if __name__ == "__main__":
    unittest.main()
