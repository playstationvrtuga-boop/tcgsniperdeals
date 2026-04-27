import os
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path

from services.ai_market_intel import (
    ParsedTrend,
    apply_ai_market_intel_to_listing,
    build_ai_market_intel_payload,
    parse_cardmarket_trends,
    save_trends_snapshot,
    trend_matches_listing,
)
from vip_app.app import create_app
from vip_app.app.config import Config
from vip_app.app.extensions import db
from vip_app.app.models import CardmarketTrend, Listing, User, utcnow


SAMPLE_TRENDS_HTML = """
<section>
  <h2>Best Sellers</h2>
  <img src="/img/meowth.jpg">
  <a href="/en/Pokemon/Products/Singles/Phantasmal-Flames/Meowth-ex-POR062">Meowth ex (POR 062)</a>
  <span>5,90 €</span>
  <img src="/img/pad.jpg">
  <a href="/en/Pokemon/Products/Singles/Phantasmal-Flames/Poke-Pad-POR081">Poke Pad (POR 081)</a>
  <span>0,02 €</span>
  <h2>Best Bargains!</h2>
  <img src="/img/jigglypuff.jpg">
  <a href="/en/Pokemon/Products/Singles/MCD/Jigglypuff-MCD168">Jigglypuff (MCD16 8)</a>
  <span>0,40 €</span>
  <img src="/img/kyurem.jpg">
  <a href="/en/Pokemon/Products/Singles/BW/Kyurem-BW44">Kyurem (BW 44)</a>
  <span>0,98 €</span>
</section>
"""


class AiMarketIntelTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        db_path = Path(self.tmpdir.name) / "ai_market_intel_test.db"
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

    def _listing(self, title="Jigglypuff ex 091/080 Pokemon", score=90):
        listing = Listing(
            source="vinted",
            external_id=f"test-{title}",
            external_url="https://example.com/listing",
            normalized_url="https://example.com/listing",
            title=title,
            price_display="1,00 EUR",
            platform="Vinted",
            detected_at=utcnow(),
            pricing_status="analyzed",
            pricing_score=score,
            score=score,
            confidence_score=80,
            discount_percent=35,
            estimated_profit=20,
            listing_type="raw_card",
        )
        db.session.add(listing)
        db.session.commit()
        return listing

    def test_parse_best_sellers_and_best_bargains(self):
        trends = parse_cardmarket_trends(SAMPLE_TRENDS_HTML, max_items=10)
        categories = [trend.category for trend in trends]
        self.assertIn("best_sellers", categories)
        self.assertIn("best_bargains", categories)
        self.assertEqual(trends[0].product_name, "Meowth ex")
        self.assertEqual(trends[0].expansion, "POR")
        self.assertEqual(trends[0].card_number, "062")
        self.assertEqual(trends[0].price, 5.90)

    def test_save_daily_snapshot_replaces_same_day_duplicates(self):
        trends = [
            ParsedTrend(category="best_sellers", rank=1, product_name="Meowth ex", expansion="POR", card_number="062"),
            ParsedTrend(category="best_bargains", rank=1, product_name="Jigglypuff", expansion="MCD16", card_number="8"),
        ]
        self.assertEqual(save_trends_snapshot(trends), 2)
        self.assertEqual(save_trends_snapshot(trends), 2)
        self.assertEqual(CardmarketTrend.query.count(), 2)

    def test_api_payload_shape_uses_last_snapshot(self):
        save_trends_snapshot([
            ParsedTrend(category="best_sellers", rank=1, product_name="Meowth ex", expansion="POR", card_number="062"),
        ])
        payload = build_ai_market_intel_payload()
        self.assertIn("market_summary", payload)
        self.assertIn("best_sellers", payload)
        self.assertEqual(payload["best_sellers"][0]["product_name"], "Meowth ex")

    def test_stale_fallback_marks_payload_stale(self):
        old_time = utcnow() - timedelta(hours=31)
        save_trends_snapshot([
            ParsedTrend(category="best_sellers", rank=1, product_name="Meowth ex", expansion="POR", card_number="062"),
        ], collected_at=old_time)
        payload = build_ai_market_intel_payload()
        self.assertTrue(payload["stale"])

    def test_matching_and_score_boost_capped_at_100(self):
        trend = CardmarketTrend(
            category="best_bargains",
            rank=1,
            product_name="Jigglypuff ex",
            expansion="M2",
            card_number="091/080",
            collected_at=utcnow(),
        )
        db.session.add(trend)
        listing = self._listing()
        self.assertTrue(trend_matches_listing(trend, listing))
        self.assertTrue(apply_ai_market_intel_to_listing(listing, trends=[trend]))
        self.assertEqual(listing.cardmarket_trending_score, 7)
        self.assertEqual(listing.pricing_score, 97)
        self.assertEqual(listing.ai_market_intel_verdict, "STRONG BUY")

    def test_score_boost_never_exceeds_100(self):
        trends = [
            CardmarketTrend(category="best_sellers", rank=1, product_name="Jigglypuff ex", expansion="M2", card_number="091/080", collected_at=utcnow()),
            CardmarketTrend(category="best_bargains", rank=2, product_name="Jigglypuff ex", expansion="M2", card_number="091/080", collected_at=utcnow()),
        ]
        listing = self._listing(score=95)
        self.assertTrue(apply_ai_market_intel_to_listing(listing, trends=trends))
        self.assertEqual(listing.cardmarket_trending_score, 15)
        self.assertEqual(listing.pricing_score, 100)

    def test_avoids_raw_vs_graded_mismatch(self):
        trend = CardmarketTrend(
            category="best_sellers",
            rank=1,
            product_name="PSA 10 Jigglypuff ex",
            expansion="M2",
            card_number="091/080",
            collected_at=utcnow(),
        )
        listing = self._listing("Jigglypuff ex 091/080 Pokemon raw")
        self.assertFalse(trend_matches_listing(trend, listing))

    def test_avoids_sealed_vs_single_card_mismatch(self):
        trend = CardmarketTrend(
            category="best_sellers",
            rank=1,
            product_name="Ascended Heroes Booster Box",
            expansion="ASC",
            card_number=None,
            collected_at=utcnow(),
        )
        listing = self._listing("Charizard ex 125/094 Pokemon")
        self.assertFalse(trend_matches_listing(trend, listing))

    def test_vip_api_endpoint_returns_json(self):
        save_trends_snapshot([
            ParsedTrend(category="best_sellers", rank=1, product_name="Meowth ex", expansion="POR", card_number="062"),
        ])
        user = User(email="admin@example.com", is_admin=True, is_vip=True)
        user.set_password("password")
        db.session.add(user)
        db.session.commit()
        client = self.app.test_client()
        with client.session_transaction() as session:
            session["_user_id"] = str(user.id)
            session["_fresh"] = True
        response = client.get("/api/vip/ai-market-intel")
        self.assertEqual(response.status_code, 200)
        self.assertIn("best_sellers", response.get_json())


if __name__ == "__main__":
    unittest.main()
