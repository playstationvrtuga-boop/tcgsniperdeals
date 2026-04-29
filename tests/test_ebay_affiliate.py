import os
import unittest
from urllib.parse import parse_qs, urlsplit

from services.ebay_affiliate import build_ebay_affiliate_url


EPN_ENV_KEYS = [
    "EBAY_EPN_ENABLED",
    "EBAY_EPN_APP_CAMPAIGN_ID",
    "EBAY_EPN_WEBSITE_CAMPAIGN_ID",
    "EBAY_EPN_VIP_CAMPAIGN_ID",
    "EBAY_EPN_TELEGRAM_CAMPAIGN_ID",
]


class EbayAffiliateTests(unittest.TestCase):
    def build(self, url, source, listing_id=123, env=None):
        saved = {key: os.environ.get(key) for key in EPN_ENV_KEYS}
        try:
            for key in EPN_ENV_KEYS:
                os.environ.pop(key, None)
            os.environ.update(env or {})
            return build_ebay_affiliate_url(url, source, listing_id=listing_id)
        finally:
            for key in EPN_ENV_KEYS:
                os.environ.pop(key, None)
                if saved[key] is not None:
                    os.environ[key] = saved[key]

    def query(self, url):
        return parse_qs(urlsplit(url).query)

    def test_converts_ebay_com(self):
        url = self.build("https://www.ebay.com/itm/1234567890", "app", listing_id=42)
        query = self.query(url)

        self.assertEqual(query["campid"], ["5339151558"])
        self.assertEqual(query["customid"], ["tcg_app_42"])
        self.assertEqual(query["mkrid"], ["711-53200-19255-0"])
        self.assertEqual(query["mkevt"], ["1"])
        self.assertEqual(query["mkcid"], ["1"])

    def test_converts_ebay_es(self):
        url = self.build("https://www.ebay.es/itm/1234567890?hash=abc", "website", listing_id=99)
        query = self.query(url)

        self.assertEqual(query["campid"], ["5339151557"])
        self.assertEqual(query["customid"], ["tcg_web_99"])
        self.assertEqual(query["mkrid"], ["1185-53479-19255-0"])
        self.assertEqual(query["hash"], ["abc"])

    def test_does_not_convert_vinted(self):
        url = "https://www.vinted.pt/items/123-card"
        self.assertEqual(self.build(url, "vip"), url)

    def test_does_not_convert_olx(self):
        url = "https://www.olx.pt/d/anuncio/card-IDabc.html"
        self.assertEqual(self.build(url, "telegram_free"), url)

    def test_does_not_duplicate_already_tracked_link(self):
        url = "https://www.ebay.com/itm/123?campid=5339000000&customid=old"
        self.assertEqual(self.build(url, "app"), url)

    def test_uses_campaign_id_by_source(self):
        cases = {
            "app": "5339151558",
            "website": "5339151557",
            "vip": "5339151556",
            "telegram_free": "5339151554",
        }
        for source, campaign_id in cases.items():
            with self.subTest(source=source):
                query = self.query(self.build("https://www.ebay.com/itm/1", source))
                self.assertEqual(query["campid"], [campaign_id])

    def test_generates_custom_id_by_source(self):
        self.assertEqual(
            self.query(self.build("https://www.ebay.com/itm/1", "telegram_free", listing_id="abc 123"))["customid"],
            ["tcg_tg_free_abc_123"],
        )

    def test_disabled_returns_original_url(self):
        url = "https://www.ebay.com/itm/1234567890"
        self.assertEqual(self.build(url, "app", env={"EBAY_EPN_ENABLED": "false"}), url)


if __name__ == "__main__":
    unittest.main()
