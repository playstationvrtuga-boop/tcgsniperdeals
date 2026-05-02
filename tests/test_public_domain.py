import json
import re
import unittest
from xml.etree import ElementTree

from vip_app.app import create_app
from services.site_config import OLD_PUBLIC_SITE_HOST


OFFICIAL_URL = "https://tcgsniperdeals.com"
LEGACY_HOST = OLD_PUBLIC_SITE_HOST
SITEMAP_NS = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}


def sitemap_locs(body: str) -> list[str]:
    root = ElementTree.fromstring(body)
    return [node.text or "" for node in root.findall("sm:url/sm:loc", SITEMAP_NS)]


class PublicDomainTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app(skip_db=True)
        self.app.config.update(TESTING=True, PUBLIC_SITE_URL=OFFICIAL_URL)
        self.client = self.app.test_client()

    def test_sitemap_uses_official_domain_only(self):
        response = self.client.get("/sitemap.xml")
        body = response.get_data(as_text=True)

        self.assertEqual(response.status_code, 200)
        self.assertIn(f"<loc>{OFFICIAL_URL}/</loc>", body)
        self.assertIn(f"<loc>{OFFICIAL_URL}/pokemon-deals</loc>", body)
        self.assertNotIn(LEGACY_HOST, body)
        self.assertNotIn("onrender.com", body)
        self.assertTrue(all(loc.startswith(OFFICIAL_URL) for loc in sitemap_locs(body)))

    def test_sitemap_normalizes_misconfigured_public_site_url(self):
        self.app.config["PUBLIC_SITE_URL"] = f"http://{LEGACY_HOST}"
        response = self.client.get("/sitemap.xml")
        body = response.get_data(as_text=True)

        self.assertEqual(response.status_code, 200)
        self.assertIn(f"<loc>{OFFICIAL_URL}/</loc>", body)
        self.assertIn(f"<loc>{OFFICIAL_URL}/charizard-deals</loc>", body)
        self.assertTrue(all(loc.startswith(OFFICIAL_URL) for loc in sitemap_locs(body)))
        self.assertNotIn("onrender.com", body)

    def test_robots_points_to_official_sitemap(self):
        response = self.client.get("/robots.txt")
        body = response.get_data(as_text=True)

        self.assertEqual(response.status_code, 200)
        self.assertIn("Allow: /", body)
        self.assertIn(f"Sitemap: {OFFICIAL_URL}/sitemap.xml", body)
        self.assertNotIn("Disallow: /deals", body)
        self.assertNotIn("Disallow: /live-deals", body)
        self.assertNotIn("Disallow: /smart-deals", body)
        self.assertNotIn("Disallow: /missed-deals", body)
        self.assertIn("Disallow: /api", body)
        self.assertIn("Disallow: /admin", body)
        self.assertIn("Disallow: /billing", body)
        self.assertIn("Disallow: /vip", body)
        self.assertIn("Disallow: /favorites", body)
        self.assertIn("Disallow: /profile", body)
        self.assertIn("Disallow: /push-info", body)
        self.assertIn("Disallow: /push-subscriptions", body)
        self.assertNotIn(LEGACY_HOST, body)

    def test_seo_page_canonical_and_social_urls_use_official_domain(self):
        response = self.client.get("/pokemon-deals")
        body = response.get_data(as_text=True)

        self.assertEqual(response.status_code, 200)
        self.assertIn(f'<link rel="canonical" href="{OFFICIAL_URL}/pokemon-deals">', body)
        self.assertIn(f'<meta property="og:url" content="{OFFICIAL_URL}/pokemon-deals">', body)
        self.assertIn(f'<meta name="twitter:url" content="{OFFICIAL_URL}/pokemon-deals">', body)
        self.assertNotIn(LEGACY_HOST, body)

    def test_pokemon_deals_public_page_has_visible_faq_and_schema(self):
        response = self.client.get("/pokemon-deals")
        body = response.get_data(as_text=True)
        match = re.search(r'<script type="application/ld\+json">(.*?)</script>', body, re.S)

        self.assertEqual(response.status_code, 200)
        self.assertIn("<h3>Where to find cheap Pok\u00e9mon cards in Europe?</h3>", body)
        self.assertIn("<h3>Are Pok\u00e9mon deals worth it?</h3>", body)
        self.assertIsNotNone(match)
        schema = json.loads(match.group(1))
        questions = [entry["name"] for entry in schema["mainEntity"]]

        self.assertEqual(schema["@type"], "FAQPage")
        self.assertIn("Where to find cheap Pok\u00e9mon cards in Europe?", questions)
        self.assertEqual(len(schema["mainEntity"]), 6)
        self.assertNotIn("login", response.request.path)

    def test_legacy_render_host_redirects_public_pages(self):
        response = self.client.get("/pokemon-deals?x=1", headers={"Host": LEGACY_HOST})

        self.assertEqual(response.status_code, 301)
        self.assertEqual(response.headers["Location"], f"{OFFICIAL_URL}/pokemon-deals?x=1")

    def test_legacy_render_host_redirects_eu_deals_and_preserves_query_string(self):
        response = self.client.get("/eu-deals?region=eu&page=2", headers={"Host": LEGACY_HOST})

        self.assertEqual(response.status_code, 301)
        self.assertEqual(response.headers["Location"], f"{OFFICIAL_URL}/eu-deals?region=eu&page=2")

    def test_legacy_render_host_redirect_uses_official_domain_even_if_config_is_old(self):
        self.app.config["PUBLIC_SITE_URL"] = f"https://{LEGACY_HOST}"
        response = self.client.get("/charizard-deals", headers={"Host": LEGACY_HOST})

        self.assertEqual(response.status_code, 301)
        self.assertEqual(response.headers["Location"], f"{OFFICIAL_URL}/charizard-deals")

    def test_legacy_render_forwarded_host_redirects_public_pages(self):
        response = self.client.get(
            "/download-app",
            headers={"Host": "tcgsniperdeals.com", "X-Forwarded-Host": LEGACY_HOST},
        )

        self.assertEqual(response.status_code, 301)
        self.assertEqual(response.headers["Location"], f"{OFFICIAL_URL}/download-app")

    def test_legacy_render_host_does_not_redirect_api(self):
        response = self.client.get("/api/listings", headers={"Host": LEGACY_HOST})

        self.assertNotEqual(response.status_code, 301)
        self.assertNotIn("Location", response.headers)

    def test_legacy_render_host_does_not_redirect_health_check(self):
        response = self.client.get("/health", headers={"Host": LEGACY_HOST})

        self.assertEqual(response.status_code, 200)


if __name__ == "__main__":
    unittest.main()
