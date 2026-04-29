import os
import tempfile
import unittest
from pathlib import Path

from vip_app.app import create_app
from vip_app.app.config import Config
from vip_app.app.extensions import db
from vip_app.app.main import apply_listing_filters, parse_region_filter, parse_set_filter
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

    def _listing(self, title, set_code, language, platform="Vinted", listing_type="raw_card"):
        listing = Listing(
            source=platform.lower(),
            external_id=f"test-{platform}-{title}",
            external_url=f"https://example.com/{platform}/{title.replace(' ', '-')}",
            normalized_url=f"https://example.com/{platform}/{title.replace(' ', '-')}",
            title=title,
            price_display="10,00 EUR",
            platform=platform,
            badge_label="Fresh",
            detected_at=utcnow(),
            posted_at=utcnow(),
            card_language=language,
            set_code=set_code,
            set_name="Phantasmal Flames" if set_code == "PFL" else "Brilliant Stars",
            listing_type=listing_type,
        )
        db.session.add(listing)
        db.session.commit()
        return listing

    def test_parse_set_filter_accepts_comma_separated_codes(self):
        self.assertEqual(parse_set_filter("pfl,MEG,bad"), ["PFL", "MEG"])
        self.assertEqual(parse_region_filter("eu"), "eu")

    def test_set_and_language_filters_use_and_logic(self):
        english_pfl = self._listing("Charizard PFL 125 English", "PFL", "en")
        self._listing("PFL Dracaufeu francais", "PFL", "fr")
        self._listing("Charizard BRS Japanese", "BRS", "jp")

        results = apply_listing_filters(Listing.query, "", "", "", ["en", "jp"], ["PFL"]).all()

        self.assertEqual([listing.id for listing in results], [english_pfl.id])

    def test_eu_region_includes_vinted_and_wallapop_only(self):
        vinted = self._listing("Charizard PFL Vinted", "PFL", "en", platform="Vinted")
        wallapop = self._listing("Charizard PFL Wallapop", "PFL", "en", platform="Wallapop")
        self._listing("Charizard PFL eBay", "PFL", "en", platform="eBay")

        results = apply_listing_filters(Listing.query, "", "", "", [], [], region="eu").order_by(Listing.id).all()

        self.assertEqual([listing.id for listing in results], [vinted.id, wallapop.id])

    def test_ebay_region_includes_ebay_only(self):
        self._listing("Charizard PFL Vinted", "PFL", "en", platform="Vinted")
        ebay = self._listing("Charizard PFL eBay", "PFL", "en", platform="eBay")

        results = apply_listing_filters(Listing.query, "", "", "", [], [], region="ebay").all()

        self.assertEqual([listing.id for listing in results], [ebay.id])

    def test_region_set_language_and_market_type_are_and_filters(self):
        expected = self._listing("Charizard PFL English", "PFL", "en", platform="Wallapop", listing_type="sealed_product")
        self._listing("PFL Dracaufeu francais", "PFL", "fr", platform="Wallapop", listing_type="sealed_product")
        self._listing("Charizard PFL English raw", "PFL", "en", platform="Wallapop", listing_type="raw_card")
        self._listing("Charizard BRS English", "BRS", "en", platform="Wallapop", listing_type="sealed_product")

        results = apply_listing_filters(
            Listing.query,
            "",
            "wallapop",
            "",
            ["en", "jp"],
            ["PFL"],
            region="eu",
            market_types=["sealed_product"],
        ).all()

        self.assertEqual([listing.id for listing in results], [expected.id])


if __name__ == "__main__":
    unittest.main()
