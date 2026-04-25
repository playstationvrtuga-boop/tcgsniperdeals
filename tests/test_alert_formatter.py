import unittest
from datetime import datetime, timezone

from services.alert_formatter import (
    format_free_alert_text,
    format_telegram_listing_message,
    format_vip_alert,
    listing_age_details,
    make_partial_product_name,
)


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
                "share_link": "https://example.com/share/123",
                "free_message_variant": "full",
            }
        )
        self.assertIn("https://example.com/share/123", text)
        self.assertIn("Listing Price", text)
        self.assertIn("Pikachu VMAX", text)
        self.assertNotIn("VIP listing", text)
        self.assertNotIn("Real-time listing", text)
        self.assertNotIn("vinted.pt/items", text.lower())

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
        self.assertNotIn("Real-time listing", text)

    def test_telegram_listing_message_has_card_spacing_and_age(self):
        text = format_telegram_listing_message(
            {
                "title": "Cartes Pokemon gradees Collect Aura 9.5 Mewtwo ex Team Rocket + Zeraora V JP",
                "source": "vinted",
                "price": "22.99",
                "seller_rating": "+7",
                "url": "https://www.vinted.pt/items/example",
                "detected_at": "2026-04-25T18:00:00+00:00",
            },
            now=datetime(2026, 4, 25, 18, 0, 12, tzinfo=timezone.utc),
        )
        self.assertIn("Pokemon Sniper Deals", text)
        self.assertIn("12s ago", text)
        self.assertIn("🎴 Pokémon TCG", text)
        self.assertIn("🛒 Vinted", text)
        self.assertIn("💰 Price: €22.99", text)
        self.assertIn("📊 Seller rating: +7", text)
        self.assertIn("🔗 View listing:", text)
        self.assertTrue(text.endswith("━━━━━━━━━━━━━━━━━━━━━━━\n\n"))

    def test_listing_age_uses_created_at_fallback(self):
        details = listing_age_details(
            {"created_at": "2026-04-25T18:00:00+00:00"},
            now=datetime(2026, 4, 25, 18, 2, 5, tzinfo=timezone.utc),
        )
        self.assertEqual(details["age_text"], "2m")
        self.assertTrue(details["used_created_at_fallback"])


if __name__ == "__main__":
    unittest.main()
