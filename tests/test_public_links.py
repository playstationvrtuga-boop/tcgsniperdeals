import unittest

from services.public_links import build_free_public_listing_url


class PublicLinksTests(unittest.TestCase):
    def test_free_public_listing_url_uses_app_share_route(self):
        url = build_free_public_listing_url(123)
        self.assertIn("/share/123", url)


if __name__ == "__main__":
    unittest.main()
