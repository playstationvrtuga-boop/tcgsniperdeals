import unittest

from services.app_links import app_live_deals_url
from services.site_config import OLD_PUBLIC_SITE_HOST


class AppLinksTests(unittest.TestCase):
    def test_root_app_url_points_to_live_deals(self):
        self.assertEqual(
            app_live_deals_url("https://tcgsniperdeals.com/"),
            "https://tcgsniperdeals.com/live-deals",
        )

    def test_existing_path_is_preserved(self):
        self.assertEqual(
            app_live_deals_url("https://tcgsniperdeals.com/billing"),
            "https://tcgsniperdeals.com/billing",
        )

    def test_legacy_render_host_is_normalized(self):
        self.assertEqual(
            app_live_deals_url(f"https://{OLD_PUBLIC_SITE_HOST}/"),
            "https://tcgsniperdeals.com/live-deals",
        )

    def test_empty_url_stays_empty(self):
        self.assertEqual(app_live_deals_url(""), "")


if __name__ == "__main__":
    unittest.main()
