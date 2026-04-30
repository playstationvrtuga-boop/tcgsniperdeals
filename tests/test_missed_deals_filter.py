import os
import tempfile
import unittest
from pathlib import Path

from vip_app.app import create_app
from vip_app.app.config import Config
from vip_app.app.extensions import db
from vip_app.app.main import build_missed_deals_query
from vip_app.app.models import Listing, utcnow


class MissedDealsFilterTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        db_path = Path(self.tmpdir.name) / "missed_deals_filter.db"
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

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        db.engine.dispose()
        self.ctx.pop()
        self.tmpdir.cleanup()

    def _listing(self, *, status, available_status):
        listing = Listing(
            source="vinted",
            external_id=f"missed-{status}-{available_status}-{utcnow().timestamp()}",
            external_url="https://example.com/listing",
            title="Pikachu reverse 055/217 Pokemon",
            price_display="1,00 EUR",
            platform="Vinted",
            status=status,
            available_status=available_status,
        )
        db.session.add(listing)
        db.session.commit()
        return listing

    def test_legacy_sold_without_confirmation_is_hidden(self):
        self._listing(status="sold", available_status="sold")

        self.assertEqual(build_missed_deals_query().count(), 0)

    def test_confirmed_sold_is_visible(self):
        expected = self._listing(status="sold", available_status="gone_confirmed")

        results = build_missed_deals_query().all()

        self.assertEqual([listing.id for listing in results], [expected.id])


if __name__ == "__main__":
    unittest.main()
