import os
import json
import re
import tempfile
import unittest
from datetime import datetime, timezone
from html import escape
from pathlib import Path
from xml.etree import ElementTree

from vip_app.app import create_app
from vip_app.app.config import Config
from vip_app.app.extensions import db
from vip_app.app.models import Listing
from vip_app.app.seo_content import DYNAMIC_SEO_PAGES, SEO_PAGES


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
        self.assertIn("Last updated", body)
        self.assertIn("Live deals tracked", body)
        self.assertIn("Platforms tracked", body)
        self.assertIn("Related Pok&eacute;mon Deal Pages", body)
        self.assertIn("Charizard ex Pokemon card under 100", body)
        self.assertNotIn("Charizard PSA 10 premium listing", body)
        self.assertIn("Where to find cheap Pok\u00e9mon cards in Europe?", body)
        self.assertIn('"@type": "FAQPage"', body)
        self.assertIn("Is Vinted good for Pok\\u00e9mon cards?", body)
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
        self.assertIn("Explore Live Pok\u00e9mon Deals", body)
        self.assertIn('href="/pokemon-deals"', body)
        self.assertIn('href="/pokemon-deals-today"', body)
        self.assertIn('href="/best-pokemon-deals-today"', body)
        self.assertIn('href="/top-pokemon-deals-eu"', body)
        self.assertIn('href="/charizard-deals-under-100"', body)
        self.assertIn('href="/cheap-pokemon-cards-eu"', body)
        self.assertIn('href="/etb-deals"', body)
        self.assertIn('href="/booster-box-deals"', body)

    def test_seo_pages_include_related_internal_links(self):
        response = self.client.get("/top-pokemon-deals-eu")
        body = response.get_data(as_text=True)

        self.assertEqual(response.status_code, 200)
        self.assertIn("Related Pok&eacute;mon Deal Pages", body)
        self.assertIn('href="/"', body)
        self.assertIn('href="/pokemon-deals"', body)
        self.assertIn('href="/pokemon-deals-today"', body)
        self.assertIn('href="/charizard-deals-under-100"', body)
        self.assertIn('href="/cheap-pokemon-cards-eu"', body)
        self.assertIn('href="/top-pokemon-deals-eu"', body)

    def test_pokemon_deals_anchor_page_is_strong_and_dynamic(self):
        self._listing(title="Pokemon booster box deal", price_display="75,00 EUR", listing_type="sealed_product")

        response = self.client.get("/pokemon-deals")
        body = response.get_data(as_text=True)
        visible_text = re.sub(r"<[^>]+>", " ", body)

        self.assertEqual(response.status_code, 200)
        self.assertIn("Pok\u00e9mon Deals EU \u2013 Live Pok\u00e9mon Card Deals, Booster Boxes &amp; Charizard Finds", body)
        self.assertIn(f'<link rel="canonical" href="{OFFICIAL_URL}/pokemon-deals">', body)
        self.assertIn(escape(SEO_PAGES["pokemon-deals"]["title"]), body)
        self.assertIn(escape(SEO_PAGES["pokemon-deals"]["meta_description"]), body)
        self.assertGreaterEqual(len(re.findall(r"\b\w+\b", visible_text)), 800)
        for path in (
            "/pokemon-deals-today",
            "/best-pokemon-deals-today",
            "/top-pokemon-deals-eu",
            "/charizard-deals-under-100",
            "/cheap-pokemon-cards-eu",
            "/ebay-pokemon-deals",
            "/vinted-pokemon-deals",
        ):
            self.assertIn(f'href="{path}"', body)
        self.assertIn("Pokemon booster box deal", body)
        self.assertIn("Last updated", body)
        self.assertIn("Live deals tracked", body)

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

    def test_dynamic_seo_pages_include_valid_faq_schema(self):
        response = self.client.get("/pokemon-deals-today")
        body = response.get_data(as_text=True)
        match = re.search(r'<script type="application/ld\+json">(.*?)</script>', body, re.S)

        self.assertEqual(response.status_code, 200)
        self.assertIsNotNone(match)
        schema = json.loads(match.group(1))
        visible_questions = re.findall(r"<h3>(.*?)</h3>", body)

        self.assertEqual(schema["@type"], "FAQPage")
        self.assertGreaterEqual(len(schema["mainEntity"]), 6)
        self.assertIn("Where to find cheap Pok\u00e9mon cards in Europe?", visible_questions)
        self.assertEqual(
            schema["mainEntity"][0]["name"],
            "Where to find cheap Pok\u00e9mon cards in Europe?",
        )
        self.assertEqual(
            schema["mainEntity"][0]["acceptedAnswer"]["text"],
            re.search(r"<h3>Where to find cheap Pok\u00e9mon cards in Europe\?</h3>\s*<p>(.*?)</p>", body, re.S).group(1),
        )

    def test_priority_seo_pages_have_strategic_headings_and_single_h1(self):
        target_paths = (
            "/pokemon-deals",
            "/pokemon-deals-today",
            "/best-pokemon-deals-today",
            "/top-pokemon-deals-eu",
            "/charizard-deals-under-100",
            "/cheap-pokemon-cards-eu",
        )
        required_h2s = (
            "Best Pok\u00e9mon Deals in Europe",
            "Cheap Pok\u00e9mon Cards Under \u20ac50",
            "Live Charizard Deals",
        )

        for path in target_paths:
            with self.subTest(path=path):
                response = self.client.get(path)
                body = response.get_data(as_text=True)
                h2s = re.findall(r"<h2(?: [^>]*)?>(.*?)</h2>", body)

                self.assertEqual(response.status_code, 200)
                self.assertEqual(len(re.findall(r"<h1(?: [^>]*)?>", body)), 1)
                self.assertTrue(any("Pok\u00e9mon Deals" in h2 for h2 in h2s))
                for heading in required_h2s:
                    self.assertIn(f"<h2>{heading}</h2>", body)
                    match = re.search(rf"<h2>{re.escape(heading)}</h2>\s*<p>(.*?)</p>", body, re.S)
                    self.assertIsNotNone(match)
                    paragraph = re.sub(r"<[^>]+>", " ", match.group(1))
                    words = re.findall(r"\b\w+\b", paragraph)
                    paragraph_lower = paragraph.lower()

                    self.assertGreaterEqual(len(words), 80)
                    self.assertLessEqual(len(words), 150)
                    for term in ("pokemon cards", "deals", "eu", "cheap", "vinted", "ebay", "real-time"):
                        self.assertIn(term, paragraph_lower)

    def test_ai_answer_pages_render_direct_answers_article_schema_and_examples(self):
        answer_pages = {
            "/where-to-find-cheap-pokemon-cards": "Where to find cheap Pok\u00e9mon cards in Europe?",
            "/are-pokemon-cards-worth-buying": "Are Pok\u00e9mon cards worth buying?",
            "/best-place-to-buy-pokemon-cards-eu": "What is the best place to buy Pok\u00e9mon cards in the EU?",
            "/how-to-find-pokemon-deals": "How do you find Pok\u00e9mon deals?",
        }

        for path, h1 in answer_pages.items():
            with self.subTest(path=path):
                response = self.client.get(path)
                body = response.get_data(as_text=True)
                schema_blocks = [
                    json.loads(match)
                    for match in re.findall(r'<script type="application/ld\+json">(.*?)</script>', body, re.S)
                ]
                main_copy = " ".join(
                    re.findall(r'<p class="seo-direct-answer">(.*?)</p>', body, re.S)
                    + re.findall(r'<p class="seo-intro">(.*?)</p>', body, re.S)
                    + re.findall(r'<article class="seo-section-card">.*?</article>', body, re.S)
                )
                visible_words = re.findall(r"\b\w+\b", re.sub(r"<[^>]+>", " ", main_copy))

                self.assertEqual(response.status_code, 200)
                self.assertIn(f"<h1>{h1}</h1>", body)
                self.assertEqual(len(re.findall(r"<h1(?: [^>]*)?>", body)), 1)
                self.assertIn(f'<link rel="canonical" href="{OFFICIAL_URL}{path}">', body)
                self.assertIn('class="seo-direct-answer"', body)
                self.assertIn("<ul", body)
                self.assertIn("<ol", body)
                self.assertIn("seo-comparison-row", body)
                self.assertIn("Real", body)
                self.assertGreaterEqual(len(visible_words), 500)
                self.assertLessEqual(len(visible_words), 800)
                self.assertTrue(any(schema.get("@type") == "FAQPage" for schema in schema_blocks))
                self.assertTrue(any(schema.get("@type") == "Article" for schema in schema_blocks))

    def test_new_dynamic_category_routes_render_canonical_and_seo_copy(self):
        new_routes = {
            "/pokemon-deals-europe": "Pokemon Deals Europe",
            "/pokemon-booster-box-deals-eu": "Pokemon Booster Box Deals EU",
            "/pokemon-etb-deals-eu": "Pokemon ETB Deals EU",
            "/pokemon-card-lot-deals": "Pokemon Card Lot Deals",
            "/pokemon-graded-card-deals": "Pokemon Graded Card Deals",
        }

        for path, h1 in new_routes.items():
            with self.subTest(path=path):
                response = self.client.get(path)
                body = response.get_data(as_text=True)
                copy_parts = re.findall(r'<p class="seo-intro">(.*?)</p>', body, re.S)
                copy_parts.extend(re.findall(r'<article class="seo-section-card">.*?<p>(.*?)</p>', body, re.S))
                copy_parts.extend(re.findall(r'<article class="seo-faq-item">.*?<p>(.*?)</p>', body, re.S))
                visible_text = re.sub(r"<[^>]+>", " ", " ".join(copy_parts))

                self.assertEqual(response.status_code, 200)
                self.assertIn(f"<h1>{h1}</h1>", body)
                self.assertIn(f'<link rel="canonical" href="{OFFICIAL_URL}{path}">', body)
                self.assertIn('href="/"', body)
                self.assertIn("Related Pok&eacute;mon Deal Pages", body)
                word_count = len(re.findall(r"\b\w+\b", visible_text))
                self.assertGreaterEqual(word_count, 500)

    def test_new_dynamic_category_pages_filter_real_listings_and_limit_to_20(self):
        for index in range(22):
            self._listing(
                source="vinted",
                external_id=f"seo-booster-{index}",
                external_url=f"https://example.com/booster-{index}",
                normalized_url=f"https://example.com/booster-{index}",
                title=f"Pokemon booster box display EU deal {index}",
                platform="Vinted",
                listing_type="sealed_product",
            )
        self._listing(
            source="vinted",
            external_id="seo-booster-unrelated",
            external_url="https://example.com/raw-card",
            normalized_url="https://example.com/raw-card",
            title="Pokemon raw card deal not sealed booster",
            platform="Vinted",
            listing_type="raw_card",
        )

        response = self.client.get("/pokemon-booster-box-deals-eu")
        body = response.get_data(as_text=True)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(body.count('class="listing-card '), 20)
        self.assertIn("Pokemon booster box display EU deal", body)
        self.assertNotIn("Pokemon raw card deal not sealed booster", body)

    def test_sitemap_includes_new_dynamic_seo_routes(self):
        response = self.client.get("/sitemap.xml")
        root = ElementTree.fromstring(response.get_data(as_text=True))
        locs = {
            node.find("sm:loc", SITEMAP_NS).text
            for node in root.findall("sm:url", SITEMAP_NS)
        }

        for path in (
            "/pokemon-deals-europe",
            "/pokemon-booster-box-deals-eu",
            "/pokemon-etb-deals-eu",
            "/pokemon-card-lot-deals",
            "/pokemon-graded-card-deals",
            "/where-to-find-cheap-pokemon-cards",
            "/are-pokemon-cards-worth-buying",
            "/best-place-to-buy-pokemon-cards-eu",
            "/how-to-find-pokemon-deals",
        ):
            self.assertIn(f"{OFFICIAL_URL}{path}", locs)


if __name__ == "__main__":
    unittest.main()
