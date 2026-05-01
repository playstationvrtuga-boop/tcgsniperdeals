import os
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path

from vip_app.app import create_app
from vip_app.app.config import Config
from vip_app.app.extensions import db
from vip_app.app.models import Listing, User, utcnow


class FeedPerformanceTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        db_path = Path(self.tmpdir.name) / "feed_performance.db"
        test_db_uri = f"sqlite:///{db_path.as_posix()}"
        os.environ["DATABASE_URL"] = test_db_uri
        os.environ["RUN_DB_CREATE_ALL"] = "true"
        os.environ["RUN_STARTUP_SCHEMA_CHECK"] = "false"
        os.environ["BOT_API_KEY"] = "test-key"
        Config.SQLALCHEMY_DATABASE_URI = test_db_uri
        Config.SQLALCHEMY_ENGINE_OPTIONS = {}
        self.app = create_app()
        self.app.config.update(
            TESTING=True,
            WTF_CSRF_ENABLED=False,
            FEED_PAGE_SIZE=2,
            FEED_PAGE_MAX_SIZE=4,
            FEED_CACHE_TTL_SECONDS=5,
            FEED_HTTP_CACHE_SECONDS=3,
            BOT_API_KEY="test-key",
        )
        self.ctx = self.app.app_context()
        self.ctx.push()
        db.drop_all()
        db.create_all()
        self.client = self.app.test_client()

        user = User(email="vip@example.com", is_vip=True)
        user.set_password("password123")
        user.apply_paid_plan("monthly")
        db.session.add(user)
        db.session.commit()
        self.client.post("/login", data={"email": "vip@example.com", "password": "password123"})

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        db.engine.dispose()
        self.ctx.pop()
        self.tmpdir.cleanup()

    def _listing(self, index, **overrides):
        detected_at = utcnow() - timedelta(minutes=index)
        values = {
            "source": "vinted",
            "external_id": f"perf-{index}",
            "external_url": f"https://example.com/listing-{index}",
            "normalized_url": f"https://example.com/listing-{index}",
            "image_url": "https://example.com/image.jpg",
            "title": f"Pokemon deal {index}",
            "price_display": "10,00 EUR",
            "platform": "Vinted",
            "badge_label": "Fresh",
            "detected_at": detected_at,
            "posted_at": detected_at,
            "raw_payload": "x" * 2000,
        }
        values.update(overrides)
        listing = Listing(**values)
        db.session.add(listing)
        db.session.commit()
        return listing

    def test_deals_uses_real_pagination(self):
        for index in range(3):
            self._listing(index)

        first_page = self.client.get("/deals?per_page=2")
        second_page = self.client.get("/deals?page=2&per_page=2")

        first_body = first_page.get_data(as_text=True)
        second_body = second_page.get_data(as_text=True)
        self.assertEqual(first_page.status_code, 200)
        self.assertEqual(first_body.count('class="listing-card '), 2)
        self.assertIn("Load older deals", first_body)
        self.assertEqual(second_body.count('class="listing-card '), 1)

    def test_feed_updates_has_short_cache_and_conditional_headers(self):
        newest = self._listing(0)
        response = self.client.get("/feed/updates?limit=1")

        self.assertEqual(response.status_code, 200)
        self.assertIn("private, max-age=3", response.headers["Cache-Control"])
        self.assertIn("ETag", response.headers)
        self.assertIn("Last-Modified", response.headers)
        self.assertEqual(response.get_json()["items"][0]["id"], newest.id)

    def test_api_listings_payload_is_reduced_and_paginated(self):
        self._listing(0)
        expected = self._listing(1)

        response = self.client.get("/api/listings?limit=1&page=2", headers={"X-API-Key": "test-key"})
        data = response.get_json()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(data["page"], 2)
        self.assertEqual(data["limit"], 1)
        self.assertEqual(data["listings"][0]["id"], expected.id)
        self.assertNotIn("raw_payload", data["listings"][0])
        self.assertNotIn("pricing_reason", data["listings"][0])

    def test_filters_still_apply_to_feed(self):
        expected = self._listing(0, title="Charizard PFL", set_code="PFL", card_language="en", listing_type="raw_card")
        self._listing(1, title="Pikachu BRS", set_code="BRS", card_language="jp", listing_type="sealed_product")

        response = self.client.get("/deals?set=PFL&language=en&market_type=raw_card&per_page=4")
        body = response.get_data(as_text=True)

        self.assertEqual(response.status_code, 200)
        self.assertIn(expected.title, body)
        self.assertNotIn("Pikachu BRS", body)


class PublicLiveViewTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        db_path = Path(self.tmpdir.name) / "public_live_view.db"
        test_db_uri = f"sqlite:///{db_path.as_posix()}"
        os.environ["DATABASE_URL"] = test_db_uri
        os.environ["RUN_DB_CREATE_ALL"] = "true"
        os.environ["RUN_STARTUP_SCHEMA_CHECK"] = "false"
        Config.SQLALCHEMY_DATABASE_URI = test_db_uri
        Config.SQLALCHEMY_ENGINE_OPTIONS = {}
        self.app = create_app()
        self.app.config.update(TESTING=True, WTF_CSRF_ENABLED=False)
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

    def test_live_view_is_public_and_cached_briefly(self):
        response = self.client.get("/live-view")
        body = response.get_data(as_text=True)

        self.assertEqual(response.status_code, 200)
        self.assertIn("TCG Sniper Deals", body)
        self.assertIn("public, max-age=60", response.headers["Cache-Control"])


if __name__ == "__main__":
    unittest.main()
