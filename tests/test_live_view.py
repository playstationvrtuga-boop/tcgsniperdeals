import os
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path

from vip_app.app import create_app
from vip_app.app.config import Config
from vip_app.app.extensions import db
from vip_app.app.models import Listing, utcnow


SAFE_MARKET_STATUS_MESSAGES = (
    "New listing detected",
    "Market watch active",
    "Tracking live listings",
    "Price movement spotted",
    "Fresh item in the feed",
)

FORBIDDEN_TEMPLATE_WORDS = (
    "buy",
    "deal",
    "profit",
    "cheap",
    "under market",
    "flip",
    "snipe",
)


class LiveViewTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        db_path = Path(self.tmpdir.name) / "live_view.db"
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

    def _listing(self, **overrides):
        now = utcnow()
        values = {
            "source": "vinted",
            "external_id": f"live-{now.timestamp()}-{len(overrides)}",
            "external_url": "https://seller.example/listing/live-buy-now",
            "normalized_url": "https://seller.example/listing/live-buy-now",
            "image_url": "https://cdn.example.com/card.jpg",
            "title": "Charizard ex live alert",
            "price_display": "49,00 EUR",
            "platform": "Vinted",
            "badge_label": "Strong",
            "score_level": "HIGH",
            "is_deal": True,
            "available_status": "available",
            "status": "available",
            "detected_at": now,
            "posted_at": now,
        }
        values.update(overrides)
        listing = Listing(**values)
        db.session.add(listing)
        db.session.commit()
        return listing

    def test_live_view_returns_200_without_login_and_has_no_buy_links(self):
        self._listing()

        response = self.client.get("/live-view")
        body = response.get_data(as_text=True)

        self.assertEqual(response.status_code, 200)
        self.assertIn("window.__LIVE_VIEW_LISTINGS__", body)
        self.assertIn("Charizard ex live alert", body)
        self.assertIn("data-live-view-card", body)
        self.assertIn("grid-template-rows: 70svh 30svh", body)
        self.assertIn("image-slow-drift", body)
        self.assertIn("price-soft-pulse", body)
        self.assertIn("live-indicator", body)
        self.assertIn("data-market-status", body)
        self.assertIn("compactAgo", body)
        self.assertIn("https://cdn.example.com/card.jpg", body)
        self.assertNotIn("https://seller.example/listing/live-buy-now", body)
        self.assertNotIn("external_url", body)
        self.assertNotIn('"url"', body)
        self.assertNotIn("href=", body)
        self.assertNotIn("topbar", body)
        self.assertNotIn("bottom-nav", body)

    def test_live_view_template_contains_safe_motion_copy_only(self):
        self._listing()

        response = self.client.get("/live-view")
        body = response.get_data(as_text=True)
        normalized_body = body.lower()

        self.assertEqual(response.status_code, 200)
        for message in SAFE_MARKET_STATUS_MESSAGES:
            self.assertIn(message, body)

        for word in FORBIDDEN_TEMPLATE_WORDS:
            self.assertNotIn(word, normalized_body)

    def test_live_view_json_returns_safe_latest_available_listing_without_login(self):
        older = self._listing(title="Older live listing", detected_at=utcnow() - timedelta(minutes=3))
        newest = self._listing(title="Newest live listing", platform="eBay", score_level="INSANE")
        self._listing(title="Gone live listing", status="gone", available_status="gone")

        response = self.client.get("/live-view/listings")
        payload = response.get_json()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["count"], 2)
        self.assertEqual(payload["listings"][0]["title"], newest.title)
        self.assertEqual(payload["listings"][0]["platform"], "eBay")
        self.assertEqual(payload["listings"][0]["score_label"], "INSANE")
        self.assertEqual(payload["listings"][1]["title"], older.title)
        self.assertEqual(
            set(payload["listings"][0].keys()),
            {"image_url", "title", "price", "platform", "detected_at", "score_label"},
        )
        self.assertNotIn("url", payload["listings"][0])
        self.assertNotIn("external_url", payload["listings"][0])

    def test_vip_routes_still_require_login(self):
        for path in ("/feed", "/smart-deals", "/missed-deals", "/ai-market-intel"):
            with self.subTest(path=path):
                response = self.client.get(path, follow_redirects=False)

                self.assertEqual(response.status_code, 302)
                self.assertIn("/login", response.headers["Location"])


if __name__ == "__main__":
    unittest.main()
