import unittest

from services.app_links import app_live_deals_url


class AppLinksTests(unittest.TestCase):
    def test_root_app_url_points_to_live_deals(self):
        self.assertEqual(
            app_live_deals_url("https://tcg-sniper-deals.onrender.com/"),
            "https://tcg-sniper-deals.onrender.com/live-deals",
        )

    def test_existing_path_is_preserved(self):
        self.assertEqual(
            app_live_deals_url("https://tcg-sniper-deals.onrender.com/billing"),
            "https://tcg-sniper-deals.onrender.com/billing",
        )

    def test_empty_url_stays_empty(self):
        self.assertEqual(app_live_deals_url(""), "")


if __name__ == "__main__":
    unittest.main()
