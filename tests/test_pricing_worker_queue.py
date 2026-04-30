import importlib
import os
import sys
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path

from vip_app.app.config import Config
from vip_app.app.extensions import db
from vip_app.app.models import Listing, utcnow


class PricingWorkerQueueTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        db_path = Path(self.tmpdir.name) / "pricing_worker_queue.db"
        test_db_uri = f"sqlite:///{db_path.as_posix()}"
        os.environ["DATABASE_URL"] = test_db_uri
        os.environ["RUN_DB_CREATE_ALL"] = "true"
        os.environ["RUN_STARTUP_SCHEMA_CHECK"] = "false"
        Config.SQLALCHEMY_DATABASE_URI = test_db_uri
        Config.SQLALCHEMY_ENGINE_OPTIONS = {}
        if "pricing_worker" in sys.modules:
            self.pricing_worker = importlib.reload(sys.modules["pricing_worker"])
        else:
            self.pricing_worker = importlib.import_module("pricing_worker")
        self.ctx = self.pricing_worker.app.app_context()
        self.ctx.push()
        db.drop_all()
        db.create_all()

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
            "external_id": f"queue-{now.timestamp()}-{len(overrides)}",
            "external_url": "https://example.com/listing",
            "title": "Charizard PFL 125/094 Pokemon",
            "price_display": "70,00 EUR",
            "platform": "Vinted",
            "pricing_status": "pending",
            "pricing_checked_at": None,
            "detected_at": now,
            "created_at": now,
        }
        values.update(overrides)
        listing = Listing(**values)
        db.session.add(listing)
        db.session.commit()
        return listing

    def test_incomplete_analyzed_listing_is_retried_after_retry_window(self):
        old = utcnow() - timedelta(hours=2)
        expected = self._listing(
            pricing_status="analyzed",
            pricing_checked_at=old,
            pricing_basis=None,
            pricing_reason=None,
            detected_at=old,
            created_at=old,
        )

        result = self.pricing_worker.fetch_next_pending_listing()

        self.assertEqual(result.id, expected.id)

    def test_complete_analyzed_listing_is_not_retried(self):
        old = utcnow() - timedelta(hours=2)
        self._listing(
            pricing_status="analyzed",
            pricing_checked_at=old,
            pricing_basis="sold",
            pricing_reason="source=sold; identity=strong; note=PRICING_STRONG_ID",
            detected_at=old,
            created_at=old,
        )

        self.assertIsNone(self.pricing_worker.fetch_next_pending_listing())


if __name__ == "__main__":
    unittest.main()
