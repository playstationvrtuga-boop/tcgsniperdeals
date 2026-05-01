import unittest

from services.image_urls import high_resolution_ebay_image_url, high_resolution_listing_image_url


class ImageUrlTests(unittest.TestCase):
    def test_ebay_thumbnail_url_is_upgraded_to_large_image(self):
        url = "https://i.ebayimg.com/images/g/example/s-l225.jpg"

        self.assertEqual(
            high_resolution_ebay_image_url(url),
            "https://i.ebayimg.com/images/g/example/s-l1600.jpg",
        )

    def test_ebay_webp_url_keeps_extension_and_query(self):
        url = "https://i.ebayimg.com/images/g/example/s-l300.webp?set_id=880000500F"

        self.assertEqual(
            high_resolution_ebay_image_url(url),
            "https://i.ebayimg.com/images/g/example/s-l1600.webp?set_id=880000500F",
        )

    def test_non_ebay_image_url_is_unchanged(self):
        url = "https://example.com/image.jpg"

        self.assertEqual(high_resolution_listing_image_url(url), url)


if __name__ == "__main__":
    unittest.main()
