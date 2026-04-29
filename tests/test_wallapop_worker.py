import io
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from vip_app.app import create_app
from vip_app.app.config import Config
from vip_app.app.extensions import db
from vip_app.app.models import Listing
from wallapop_worker import run_once


EMPTY_SCRAPE_STATS = {"accepted": 0, "rejected": 0, "duplicates": 0, "timeouts": 0, "query_errors": 0}


class WallapopWorkerTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        db_path = Path(self.tmpdir.name) / "wallapop_worker.db"
        test_db_uri = f"sqlite:///{db_path.as_posix()}"
        os.environ["DATABASE_URL"] = test_db_uri
        os.environ["RUN_DB_CREATE_ALL"] = "true"
        os.environ["RUN_STARTUP_SCHEMA_CHECK"] = "false"
        os.environ["ENABLE_WALLAPOP"] = "true"
        os.environ["WALLAPOP_MAX_ITEMS_PER_RUN"] = "2"
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
        os.environ.pop("ENABLE_WALLAPOP", None)
        os.environ.pop("WALLAPOP_MAX_ITEMS_PER_RUN", None)

    def test_run_once_inserts_wallapop_listing_into_db(self):
        item = {
            "id": "wallapop_charizard-1",
            "external_id": "wallapop_charizard-1",
            "source": "wallapop",
            "platform": "Wallapop",
            "title": "Pokemon TCG Charizard PFL 125 English",
            "price": "20 €",
            "url": "https://es.wallapop.com/item/charizard-1",
            "image_url": "",
            "detected_at": None,
            "raw_payload": {"location": "Madrid"},
        }

        output = io.StringIO()
        with patch("wallapop_worker.fetch_wallapop_listings", return_value=([item], dict(EMPTY_SCRAPE_STATS))) as fetch_mock:
            with redirect_stdout(output):
                print(f"[WALLAPOP_ACCEPTED] external_id={item['external_id']}")
                result = run_once(self.app)

        self.assertEqual(result["inserted"], 1)
        self.assertEqual(result["duplicates"], 0)
        fetch_mock.assert_called_once()
        logs = output.getvalue()
        self.assertIn("[WALLAPOP_ACCEPTED]", logs)
        self.assertIn("[WALLAPOP_DB_INSERTED]", logs)
        self.assertLess(logs.index("[WALLAPOP_ACCEPTED]"), logs.index("[WALLAPOP_DB_INSERTED]"))
        listing = Listing.query.filter_by(source="wallapop").one()
        self.assertEqual(listing.platform, "Wallapop")
        self.assertEqual(listing.external_id, "wallapop_charizard-1")

    def test_run_once_dedupes_existing_wallapop_listing(self):
        item = {
            "id": "wallapop_pikachu-1",
            "external_id": "wallapop_pikachu-1",
            "source": "wallapop",
            "platform": "Wallapop",
            "title": "Pokemon TCG Pikachu 25/25",
            "price": "12 €",
            "url": "https://es.wallapop.com/item/pikachu-1",
        }

        with patch("wallapop_worker.fetch_wallapop_listings", return_value=([item], dict(EMPTY_SCRAPE_STATS))):
            first = run_once(self.app)
            second = run_once(self.app)

        self.assertEqual(first["inserted"], 1)
        self.assertEqual(second["duplicates"], 1)
        self.assertEqual(Listing.query.filter_by(source="wallapop").count(), 1)

    def test_run_once_includes_scraper_duplicates_in_summary(self):
        scrape_stats = dict(EMPTY_SCRAPE_STATS)
        scrape_stats.update({"rejected": 1, "duplicates": 1})

        with patch("wallapop_worker.fetch_wallapop_listings", return_value=([], scrape_stats)):
            result = run_once(self.app)

        self.assertEqual(result["fetched"], 0)
        self.assertEqual(result["inserted"], 0)
        self.assertEqual(result["duplicates"], 1)
        self.assertEqual(result["errors"], 0)


if __name__ == "__main__":
    unittest.main()
