import os
import tempfile
import unittest
from pathlib import Path

from vip_app.app import create_app
from vip_app.app.config import Config
from vip_app.app.extensions import db
from vip_app.app.main import apply_listing_filters, parse_set_filter
from vip_app.app.models import Listing, utcnow


class FeedSetFilterTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        db_path = Path(self.tmpdir.name) / "feed_set_filters.db"
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

    def _listing(self, title, set_code, language):
        listing = Listing(
            source="test",
            external_id=f"test-{title}",
            external_url=f"https://example.com/{title.replace(' ', '-')}",
            normalized_url=f"https://example.com/{title.replace(' ', '-')}",
            title=title,
            price_display="10,00 EUR",
            platform="Vinted",
            badge_label="Fresh",
            detected_at=utcnow(),
            posted_at=utcnow(),
            card_language=language,
            set_code=set_code,
            set_name="Phantasmal Flames" if set_code == "PFL" else "Brilliant Stars",
        )
        db.session.add(listing)
        db.session.commit()
        return listing

    def test_parse_set_filter_accepts_comma_separated_codes(self):
        self.assertEqual(parse_set_filter("pfl,MEG,bad"), ["PFL", "MEG"])

    def test_set_and_language_filters_use_and_logic(self):
        english_pfl = self._listing("Charizard PFL 125 English", "PFL", "en")
        self._listing("PFL Dracaufeu francais", "PFL", "fr")
        self._listing("Charizard BRS Japanese", "BRS", "jp")

        results = apply_listing_filters(Listing.query, "", "", "", ["en", "jp"], ["PFL"]).all()

        self.assertEqual([listing.id for listing in results], [english_pfl.id])


if __name__ == "__main__":
    unittest.main()
