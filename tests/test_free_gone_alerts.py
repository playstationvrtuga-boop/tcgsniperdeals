import unittest
import os
import tempfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from services.alert_formatter import format_free_gone_alert_text
from services import free_gone_alerts
from services.free_gone_alerts import (
    GONE_AVAILABLE_STATUSES,
    GONE_PENDING_CONFIRMATION_STATUS,
    build_daily_plan,
    mark_recent_gone_listings,
    parse_windows,
)
from services.listing_availability import AvailabilityResult
from vip_app.app import create_app
from vip_app.app.config import Config
from vip_app.app.extensions import db
from vip_app.app.models import Listing


class FreeGoneAlertTests(unittest.TestCase):
    def test_gone_alert_text_is_english_and_link_free(self):
        text = format_free_gone_alert_text(
            {
                "title": "Charizard ex 223/197 Obsidian Flames",
                "platform": "Vinted",
                "listing_price_text": "75.00 EUR",
                "updated_at": "2026-04-23T10:15:00+01:00",
            }
        )
        self.assertIn("GONE ALERT", text)
        self.assertIn("Last seen", text)
        self.assertIn("VIP", text)
        self.assertIn("button", text.lower())
        self.assertNotIn("Produto", text)
        self.assertNotIn("http", text.lower())
        self.assertNotIn("vinted.pt/items", text.lower())

    def test_daily_plan_spreads_counts_across_windows(self):
        windows = parse_windows("10:00-13:00,15:00-19:00,20:00-23:00")
        plan = build_daily_plan(date(2026, 4, 23), windows)
        self.assertGreaterEqual(plan["daily_target_count"], 3)
        self.assertLessEqual(plan["daily_target_count"], 5)
        self.assertEqual(sum(plan["window_plan"].values()), plan["daily_target_count"])
        self.assertEqual(sum(plan["window_posted"].values()), 0)
        self.assertEqual(set(plan["window_plan"].keys()), {window.key for window in windows})

    def test_gone_statuses_accept_portuguese_sold_terms(self):
        self.assertIn("vendido", GONE_AVAILABLE_STATUSES)
        self.assertIn("vendida", GONE_AVAILABLE_STATUSES)
        self.assertIn("indisponível", GONE_AVAILABLE_STATUSES)


    def test_pending_and_unknown_are_not_gone_statuses(self):
        self.assertNotIn(GONE_PENDING_CONFIRMATION_STATUS, GONE_AVAILABLE_STATUSES)
        self.assertNotIn("unknown_check_failed", GONE_AVAILABLE_STATUSES)


class GoneAvailabilityStateTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        db_path = Path(self.tmpdir.name) / "free_gone_alerts_test.db"
        self.test_db_uri = f"sqlite:///{db_path.as_posix()}"
        os.environ["DATABASE_URL"] = self.test_db_uri
        os.environ["RUN_DB_CREATE_ALL"] = "true"
        os.environ["RUN_STARTUP_SCHEMA_CHECK"] = "false"
        Config.SQLALCHEMY_DATABASE_URI = self.test_db_uri
        Config.SQLALCHEMY_ENGINE_OPTIONS = {}
        self.app = create_app()
        self.app.config.update(TESTING=True, WTF_CSRF_ENABLED=False)
        self.ctx = self.app.app_context()
        self.ctx.push()
        db.drop_all()
        db.create_all()
        self.original_check = free_gone_alerts.check_listing_availability

    def tearDown(self):
        free_gone_alerts.check_listing_availability = self.original_check
        db.session.remove()
        db.drop_all()
        db.engine.dispose()
        self.ctx.pop()
        self.tmpdir.cleanup()

    def _listing(self, *, status="available", available_status="available", detected_at=None):
        listing = Listing(
            source="vinted",
            external_id=f"gone-test-{status}-{available_status}",
            external_url="https://www.vinted.pt/items/1-test",
            title="Pokemon Trainer Mysterious Fossil 109/110",
            price_display="7,00 EUR",
            platform="Vinted",
            status=status,
            available_status=available_status,
            detected_at=detected_at or datetime(2026, 4, 30, 18, 0, tzinfo=timezone.utc),
            updated_at=detected_at or datetime(2026, 4, 30, 18, 0, tzinfo=timezone.utc),
        )
        db.session.add(listing)
        db.session.commit()
        return listing

    def test_gone_requires_second_strong_confirmation(self):
        base = datetime(2026, 4, 30, 20, 0, tzinfo=timezone.utc)
        listing = self._listing(detected_at=base - timedelta(hours=1))
        responses = [
            AvailabilityResult(status="sold", is_gone=True, reason="text_marker:sold"),
            AvailabilityResult(status="sold", is_gone=True, reason="text_marker:sold"),
        ]
        free_gone_alerts.check_listing_availability = lambda *_args, **_kwargs: responses.pop(0)

        marked_first = mark_recent_gone_listings(now=base, limit=1)
        db.session.refresh(listing)
        self.assertEqual(marked_first, 0)
        self.assertEqual(listing.status, "available")
        self.assertEqual(listing.available_status, GONE_PENDING_CONFIRMATION_STATUS)
        self.assertIsNone(listing.gone_detected_at)

        marked_second = mark_recent_gone_listings(now=base + timedelta(hours=4), limit=1)
        db.session.refresh(listing)
        self.assertEqual(marked_second, 1)
        self.assertEqual(listing.status, "sold")
        self.assertEqual(listing.available_status, "sold")
        self.assertIsNotNone(listing.gone_detected_at)

    def test_available_result_recovers_false_positive_sold_listing(self):
        base = datetime(2026, 4, 30, 20, 0, tzinfo=timezone.utc)
        listing = self._listing(status="sold", available_status="sold", detected_at=base - timedelta(hours=1))
        listing.gone_detected_at = base - timedelta(minutes=10)
        listing.sold_after_seconds = 300
        db.session.commit()
        free_gone_alerts.check_listing_availability = lambda *_args, **_kwargs: AvailabilityResult(
            status="available",
            is_gone=False,
            reason="vinted_active_action:buy now",
        )

        marked = mark_recent_gone_listings(now=base, limit=1)
        db.session.refresh(listing)
        self.assertEqual(marked, 0)
        self.assertEqual(listing.status, "available")
        self.assertEqual(listing.available_status, "available")
        self.assertIsNone(listing.gone_detected_at)
        self.assertIsNone(listing.sold_after_seconds)


if __name__ == "__main__":
    unittest.main()
