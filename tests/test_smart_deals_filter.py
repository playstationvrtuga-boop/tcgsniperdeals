import os
import tempfile
import unittest
from pathlib import Path

from vip_app.app import create_app
from vip_app.app.config import Config
from vip_app.app.extensions import db
from vip_app.app.main import build_smart_deals_query
from vip_app.app.models import Listing, utcnow


class SmartDealsFilterTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        db_path = Path(self.tmpdir.name) / "smart_deals_filter.db"
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

    def _listing(self, **overrides):
        values = {
            "source": "vinted",
            "external_id": f"smart-{len(overrides)}-{utcnow().timestamp()}",
            "external_url": "https://example.com/listing",
            "title": "Dragonite Expedition 56/165 Pokemon",
            "price_display": "45,00 EUR",
            "platform": "Vinted",
            "pricing_status": "analyzed",
            "pricing_basis": "sold",
            "listing_type": "raw_card",
            "estimated_fair_value": 55.0,
            "reference_price": 55.0,
            "confidence_score": 70,
            "is_deal": True,
            "score_level": "LOW",
            "estimated_profit": 10.0,
            "discount_percent": 18.18,
            "last_2_sales_json": "[55.0]",
            "pricing_reason": (
                "source=sold; sold_refs=1; buy_now_refs=0; comparable_results=1; "
                "identity=strong; confidence=MEDIUM; basis=sold; listing_type=raw_card; "
                "note=PRICING_STRONG_ID; DEAL_ACCEPTED; SIMPLE_SOLD_AVG_OPPORTUNITY"
            ),
        }
        values.update(overrides)
        listing = Listing(**values)
        db.session.add(listing)
        db.session.commit()
        return listing

    def test_one_sold_strong_identity_opportunity_is_visible(self):
        expected = self._listing()

        results = build_smart_deals_query().all()

        self.assertEqual([listing.id for listing in results], [expected.id])

    def test_weak_false_positive_risk_is_not_visible(self):
        self._listing(
            title="Charizard 56/165 lot bundle",
            listing_type="raw_card",
            pricing_reason=(
                "source=sold; sold_refs=3; comparable_results=3; identity=strong; "
                "false_positive_risk=true; note=PRICING_SKIPPED_SNIPER_FALSE_POSITIVE_RISK"
            ),
        )

        self.assertEqual(build_smart_deals_query().count(), 0)

    def test_strong_buy_now_market_signal_is_visible(self):
        expected = self._listing(
            pricing_basis="buy_now",
            confidence_score=58,
            is_deal=False,
            score_level="MEDIUM",
            estimated_profit=30.0,
            discount_percent=25.0,
            last_2_sales_json="[]",
            pricing_reason=(
                "source=buy_now; sold_refs=0; buy_now_refs=3; comparable_results=3; "
                "identity=strong; confidence=HIGH; basis=buy_now; listing_type=raw_card; "
                "note=PRICING_STRONG_ID; BUY_NOW_REFERENCE_FOUND; PRICING_LOW_CONFIDENCE_BUY_NOW_ONLY"
            ),
        )

        results = build_smart_deals_query().all()

        self.assertEqual([listing.id for listing in results], [expected.id])

    def test_buy_now_without_market_edge_is_not_visible(self):
        self._listing(
            pricing_basis="buy_now",
            confidence_score=58,
            is_deal=False,
            score_level="LOW",
            estimated_profit=4.0,
            discount_percent=4.0,
            last_2_sales_json="[]",
            pricing_reason=(
                "source=buy_now; sold_refs=0; buy_now_refs=3; comparable_results=3; "
                "identity=strong; confidence=HIGH; basis=buy_now; listing_type=raw_card; "
                "note=PRICING_STRONG_ID; BUY_NOW_REFERENCE_FOUND; PRICING_LOW_CONFIDENCE_BUY_NOW_ONLY"
            ),
        )

        self.assertEqual(build_smart_deals_query().count(), 0)


if __name__ == "__main__":
    unittest.main()
