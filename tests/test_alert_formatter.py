import unittest

from services.alert_formatter import format_free_alert_text, format_vip_alert, make_partial_product_name


class AlertFormatterTests(unittest.TestCase):
    def test_partial_name_removes_searchable_codes(self):
        partial = make_partial_product_name("Charizard EX PFL125 Near Mint")
        self.assertIn("Charizard EX", partial)
        self.assertNotIn("PFL125", partial)
        self.assertNotIn("Near Mint", partial)

    def test_vip_alert_contains_full_structured_fields(self):
        data = format_vip_alert(
            {
                "title": "Pikachu VMAX TG17/TG30 NM English",
                "platform": "eBay",
                "listing_price": 12,
                "listing_price_text": "12.00 EUR",
                "market_price": 25,
                "discount_percent": 52,
                "potential_profit": 13,
                "score": 86,
                "detected_at": "2026-04-22T18:00:00+00:00",
                "direct_link": "https://example.com/item",
            }
        )
        self.assertEqual(data["marketplace"], "eBay")
        self.assertEqual(data["cta_primary"], "Open Listing")
        self.assertEqual(data["badge"], "HOT DEAL")
        self.assertIn("below market", data["push_body"])

    def test_free_alert_has_no_direct_link_and_has_vip_cta(self):
        text = format_free_alert_text(
            {
                "title": "Pikachu VMAX TG17/TG30 NM English",
                "listing_price": 12,
                "listing_price_text": "12.00 EUR",
                "market_price": 25,
                "discount_percent": 52,
                "free_message_variant": "full",
            }
        )
        self.assertNotIn("http", text.lower())
        self.assertIn("VIP APP", text)
        self.assertNotIn("TG17/TG30", text)

    def test_free_alert_is_english_only_for_main_labels(self):
        text = format_free_alert_text(
            {
                "title": "Charizard EX PFL125 Near Mint",
                "listing_price": 20,
                "listing_price_text": "20.00 EUR",
                "market_price": 40,
                "discount_percent": 50,
            }
        )
        self.assertNotIn("Produto", text)
        self.assertNotIn("Preco", text)
        self.assertIn("Listing Price", text)


if __name__ == "__main__":
    unittest.main()
