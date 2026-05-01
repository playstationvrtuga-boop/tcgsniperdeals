import os
import tempfile
import unittest
from pathlib import Path

from vip_app.app import create_app
from vip_app.app.config import Config
from vip_app.app.extensions import db
from vip_app.app.models import Listing


class EbayIngestTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        db_path = Path(self.tmpdir.name) / "ebay_ingest.db"
        test_db_uri = f"sqlite:///{db_path.as_posix()}"
        self.original_env = {
            "DATABASE_URL": os.environ.get("DATABASE_URL"),
            "RUN_DB_CREATE_ALL": os.environ.get("RUN_DB_CREATE_ALL"),
            "RUN_STARTUP_SCHEMA_CHECK": os.environ.get("RUN_STARTUP_SCHEMA_CHECK"),
            "BOT_API_KEY": os.environ.get("BOT_API_KEY"),
        }
        self.original_config = {
            "SQLALCHEMY_DATABASE_URI": Config.SQLALCHEMY_DATABASE_URI,
            "SQLALCHEMY_ENGINE_OPTIONS": dict(Config.SQLALCHEMY_ENGINE_OPTIONS),
            "BOT_API_KEY": Config.BOT_API_KEY,
        }
        os.environ["DATABASE_URL"] = test_db_uri
        os.environ["RUN_DB_CREATE_ALL"] = "true"
        os.environ["RUN_STARTUP_SCHEMA_CHECK"] = "false"
        os.environ["BOT_API_KEY"] = "test-key"
        Config.SQLALCHEMY_DATABASE_URI = test_db_uri
        Config.SQLALCHEMY_ENGINE_OPTIONS = {}
        Config.BOT_API_KEY = "test-key"
        self.app = create_app()
        self.app.config.update(TESTING=True, WTF_CSRF_ENABLED=False, BOT_API_KEY="test-key")
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
        for key, value in self.original_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        for key, value in self.original_config.items():
            setattr(Config, key, value)
        self.tmpdir.cleanup()

    def _post_listing(self, detected_at, **overrides):
        payload = {
            "source": "ebay",
            "platform": "ebay",
            "external_id": "ebay_123456789012",
            "external_url": "https://www.ebay.com/itm/123456789012",
            "title": "Pokemon White Flare Elite Trainer Box",
            "price": "US $159.99",
            "image_url": "https://i.ebayimg.com/images/example.jpg",
            "detected_at": detected_at,
        }
        payload.update(overrides)
        return self.client.post("/api/listings", json=payload, headers={"X-API-Key": "test-key"})

    def test_duplicate_ebay_ingest_preserves_original_detected_at(self):
        first_detected = "2026-05-01T18:00:00+00:00"
        second_detected = "2026-05-01T20:00:00+00:00"

        first = self._post_listing(first_detected)
        second = self._post_listing(second_detected, price="US $149.99")
        listing = Listing.query.filter_by(external_id="ebay_123456789012").one()

        self.assertEqual(first.status_code, 201)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(second.get_json()["status"], "duplicate")
        self.assertEqual(listing.detected_at_iso, "2026-05-01T18:00:00+00:00")
        self.assertEqual(listing.price_display, "US $149.99")
        self.assertEqual(Listing.query.count(), 1)


if __name__ == "__main__":
    unittest.main()
