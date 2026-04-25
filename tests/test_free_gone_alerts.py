import unittest
from datetime import date

from services.alert_formatter import format_free_gone_alert_text
from services.free_gone_alerts import GONE_AVAILABLE_STATUSES, build_daily_plan, parse_windows


class FreeGoneAlertTests(unittest.TestCase):
    def test_gone_alert_text_is_english_and_link_free(self):
        text = format_free_gone_alert_text(
            {
                "title": "Charizard ex 223/197 Obsidian Flames",
                "platform": "Vinted",
                "listing_price_text": "75.00 EUR",
                "updated_at": "2026-04-23T10:15:00+01:00",
                "app_url": "https://tcg-sniper-deals.onrender.com",
            }
        )
        self.assertIn("GONE ALERT", text)
        self.assertIn("Last seen", text)
        self.assertIn("VIP", text)
        self.assertIn("https://tcg-sniper-deals.onrender.com", text)
        self.assertNotIn("Produto", text)
        self.assertNotIn("vinted.pt/items", text.lower())

    def test_daily_plan_spreads_counts_across_windows(self):
        windows = parse_windows("10:00-13:00,15:00-19:00,20:00-23:00")
        plan = build_daily_plan(date(2026, 4, 23), windows)
        self.assertGreaterEqual(plan["daily_target_count"], 3)
        self.assertLessEqual(plan["daily_target_count"], 5)
        self.assertEqual(sum(plan["window_plan"].values()), plan["daily_target_count"])
        self.assertEqual(sum(plan["window_posted"].values()), 0)
        self.assertEqual(set(plan["window_plan"].keys()), {window.key for window in windows})

    def test_gone_statuses_accept_portuguese_sold_terms(self):
        self.assertIn("vendido", GONE_AVAILABLE_STATUSES)
        self.assertIn("vendida", GONE_AVAILABLE_STATUSES)
        self.assertIn("indisponível", GONE_AVAILABLE_STATUSES)


if __name__ == "__main__":
    unittest.main()
