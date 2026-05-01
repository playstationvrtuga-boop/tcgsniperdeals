import os
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path

from vip_app.app import create_app
from vip_app.app.config import Config
from vip_app.app.extensions import db
from vip_app.app.models import Listing, User, utcnow


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

        self.user = User(
            email="vip@example.com",
            is_vip=True,
            vip_expires_at=utcnow() + timedelta(days=1),
        )
        self.user.set_password("password123")
        db.session.add(self.user)
        db.session.commit()

        with self.client.session_transaction() as session:
            session["_user_id"] = str(self.user.id)
            session["_fresh"] = True

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
            "external_url": "https://example.com/live",
            "normalized_url": "https://example.com/live",
            "image_url": "https://example.com/card.jpg",
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

    def test_live_view_renders_standalone_stream_shell(self):
        self._listing()

        response = self.client.get("/live-view")
        body = response.get_data(as_text=True)

        self.assertEqual(response.status_code, 200)
        self.assertIn("window.__LIVE_VIEW_LISTINGS__", body)
        self.assertIn("Charizard ex live alert", body)
        self.assertIn("data-live-view-card", body)
        self.assertIn("grid-template-rows: 70svh 30svh", body)
        self.assertNotIn("topbar", body)
        self.assertNotIn("bottom-nav", body)

    def test_live_view_json_returns_latest_available_listing(self):
        older = self._listing(title="Older live listing", detected_at=utcnow() - timedelta(minutes=3))
        newest = self._listing(title="Newest live listing", platform="eBay", score_level="INSANE")
        self._listing(title="Gone live listing", status="gone", available_status="gone")

        response = self.client.get("/live-view/listings")
        payload = response.get_json()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["count"], 2)
        self.assertEqual(payload["listings"][0]["id"], newest.id)
        self.assertEqual(payload["listings"][0]["platform"], "eBay")
        self.assertEqual(payload["listings"][0]["deal_level"], "INSANE")
        self.assertTrue(payload["listings"][0]["is_hot"])
        self.assertEqual(payload["listings"][1]["id"], older.id)


if __name__ == "__main__":
    unittest.main()
