import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from xml.etree import ElementTree

from vip_app.app import create_app
from vip_app.app.config import Config
from vip_app.app.extensions import db
from vip_app.app.models import Listing
from vip_app.app.seo_content import DYNAMIC_SEO_PAGES


OFFICIAL_URL = "https://tcgsniperdeals.com"
SITEMAP_NS = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}


class DynamicSeoPagesTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        db_path = Path(self.tmpdir.name) / "dynamic_seo_pages.db"
        test_db_uri = f"sqlite:///{db_path.as_posix()}"
        os.environ["DATABASE_URL"] = test_db_uri
        os.environ["RUN_DB_CREATE_ALL"] = "true"
        os.environ["RUN_STARTUP_SCHEMA_CHECK"] = "false"
        Config.SQLALCHEMY_DATABASE_URI = test_db_uri
        Config.SQLALCHEMY_ENGINE_OPTIONS = {}
        self.app = create_app()
        self.app.config.update(TESTING=True, WTF_CSRF_ENABLED=False, PUBLIC_SITE_URL=OFFICIAL_URL)
        self.ctx = self.app.app_context()
        self.ctx.push()
        db.drop_all()
        db.create_all()
        self.client = self.app.test_client()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        db.engine.dispose()
        self.ctx.pop()
        self.tmpdir.cleanup()

    def _listing(self, **overrides):
        values = {
            "source": "vinted",
            "external_id": f"seo-{len(overrides)}-{datetime.now(timezone.utc).timestamp()}",
            "external_url": "https://example.com/listing",
            "normalized_url": "https://example.com/listing",
            "image_url": "https://example.com/card.jpg",
            "title": "Charizard ex Pokemon card",
            "price_display": "89,00 EUR",
            "platform": "Vinted",
            "badge_label": "Strong",
            "tcg_type": "pokemon",
            "available_status": "available",
            "pricing_status": "analyzed",
            "pricing_basis": "sold",
            "listing_type": "raw_card",
            "estimated_fair_value": 130.0,
            "reference_price": 130.0,
            "confidence_score": 80,
            "estimated_profit": 41.0,
            "discount_percent": 31.5,
            "score_level": "HIGH",
            "is_deal": True,
            "detected_at": datetime(2026, 4, 30, 12, 0, tzinfo=timezone.utc),
            "posted_at": datetime(2026, 4, 30, 12, 0, tzinfo=timezone.utc),
            "pricing_reason": "identity=strong; sold_refs=2; DEAL_ACCEPTED",
        }
        values.update(overrides)
        listing = Listing(**values)
        db.session.add(listing)
        db.session.commit()
        return listing

    def test_dynamic_seo_page_renders_real_bot_listings_and_meta(self):
        self._listing(title="Charizard ex Pokemon card under 100", price_display="89,00 EUR")
        self._listing(title="Charizard PSA 10 premium listing", price_display="250,00 EUR")

        response = self.client.get("/charizard-deals-under-100")
        body = response.get_data(as_text=True)

        self.assertEqual(response.status_code, 200)
        self.assertIn("<h1>Charizard Deals Under 100</h1>", body)
        self.assertIn(f'<link rel="canonical" href="{OFFICIAL_URL}/charizard-deals-under-100">', body)
        self.assertIn(f'<meta property="og:url" content="{OFFICIAL_URL}/charizard-deals-under-100">', body)
        self.assertIn("Charizard ex Pokemon card under 100", body)
        self.assertNotIn("Charizard PSA 10 premium listing", body)
        self.assertIn("Where to find cheap Pokemon cards?", body)
        self.assertIn("Live Charizard listings under 100 EUR", body)
        self.assertNotIn("onrender.com", body)

    def test_sitemap_includes_dynamic_pages_with_listing_lastmod(self):
        self._listing(title="Charizard ex Pokemon card under 100", price_display="89,00 EUR")

        response = self.client.get("/sitemap.xml")
        root = ElementTree.fromstring(response.get_data(as_text=True))
        entries = {
            loc.text: lastmod.text
            for loc, lastmod in (
                (node.find("sm:loc", SITEMAP_NS), node.find("sm:lastmod", SITEMAP_NS))
                for node in root.findall("sm:url", SITEMAP_NS)
            )
        }

        self.assertEqual(response.status_code, 200)
        self.assertEqual(entries[f"{OFFICIAL_URL}/charizard-deals-under-100"], "2026-04-30")
        self.assertIn(f"{OFFICIAL_URL}/pokemon-deals-today", entries)
        self.assertIn(f"{OFFICIAL_URL}/best-pokemon-deals-today", entries)
        self.assertIn(f"{OFFICIAL_URL}/top-pokemon-deals-eu", entries)
        self.assertIn(f"{OFFICIAL_URL}/cheap-pokemon-cards-eu", entries)
        self.assertTrue(all("onrender.com" not in loc for loc in entries))

    def test_homepage_has_visible_links_to_priority_dynamic_seo_pages(self):
        response = self.client.get("/")
        body = response.get_data(as_text=True)

        self.assertEqual(response.status_code, 200)
        self.assertIn('href="/pokemon-deals-today"', body)
        self.assertIn('href="/charizard-deals-under-100"', body)
        self.assertIn('href="/cheap-pokemon-cards-eu"', body)

    def test_seo_pages_include_related_internal_links(self):
        response = self.client.get("/top-pokemon-deals-eu")
        body = response.get_data(as_text=True)

        self.assertEqual(response.status_code, 200)
        self.assertIn("Related Pokemon Deals", body)
        self.assertIn('href="/"', body)
        self.assertIn('href="/pokemon-deals"', body)
        self.assertIn('href="/charizard-deals"', body)
        self.assertIn('href="/cheap-pokemon-cards-eu"', body)

    def test_dynamic_seo_titles_and_meta_descriptions_are_ctr_ready(self):
        titles = [page["title"] for page in DYNAMIC_SEO_PAGES.values()]

        self.assertEqual(len(titles), len(set(titles)))
        for page in DYNAMIC_SEO_PAGES.values():
            title = page["title"].lower()
            description = page["meta_description"]
            searchable_text = f"{title} {description.lower()}"

            self.assertGreaterEqual(len(description), 140)
            self.assertLessEqual(len(description), 160)
            for keyword in ("pokemon", "deals", "cheap", "eu", "today"):
                self.assertIn(keyword, searchable_text)


if __name__ == "__main__":
    unittest.main()
