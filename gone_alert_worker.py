from __future__ import annotations

import argparse
import random
import time
from datetime import datetime

from config import ENABLE_FREE_GONE_ALERTS, FREE_GONE_WORKER_INTERVAL_MINUTES
from services.free_gone_alerts import (
    find_next_gone_candidate,
    get_or_create_state,
    next_due_window_slot,
    post_gone_alert,
    record_gone_alert_post,
)
from vip_app.app import create_app
from vip_app.app.extensions import db
from vip_app.app.models import FreeGoneAlertState


app = create_app(skip_blueprints=True)


def _sleep_seconds() -> float:
    return max(60.0, float(FREE_GONE_WORKER_INTERVAL_MINUTES) * 60.0)


def ensure_schema() -> None:
    FreeGoneAlertState.__table__.create(bind=db.engine, checkfirst=True)


def _build_listing_summary(listing) -> str:
    title = (listing.title or "Unknown listing").strip()
    platform = (listing.platform or "Unknown").strip()
    updated = listing.updated_at or listing.detected_at
    updated_text = updated.isoformat(timespec="seconds") if updated else "n/a"
    return f"id={listing.id} platform={platform} updated={updated_text} title={title[:90]}"


def run_worker(*, once: bool = False, limit: int | None = None) -> None:
    processed = 0
    with app.app_context():
        ensure_schema()
        print(f"[gone_worker] database={app.config.get('SQLALCHEMY_DATABASE_URI')}")
        print(f"[gone_worker] enabled={ENABLE_FREE_GONE_ALERTS}")
        while True:
            if not ENABLE_FREE_GONE_ALERTS:
                print("[gone_worker] disabled - sleeping")
                if once:
                    break
                time.sleep(_sleep_seconds())
                continue

            state = get_or_create_state()
            now = datetime.now().astimezone()
            window, due_at = next_due_window_slot(state, now)

            if state.daily_posted_count >= state.daily_target_count:
                print(
                    f"[gone_worker] daily target reached posted={state.daily_posted_count} "
                    f"target={state.daily_target_count}"
                )
            elif not window or not due_at:
                print("[gone_worker] idle - no active gone slot")
            elif now < due_at:
                minutes_left = max(0, int(round((due_at - now).total_seconds() / 60)))
                print(f"[gone_worker] waiting for {window.label} slot in ~{minutes_left}m")
            else:
                candidate = find_next_gone_candidate(state, now)
                if candidate is not None:
                    variant = random.randint(0, 2)
                    ok = post_gone_alert(candidate, variant=variant)
                    if ok:
                        record_gone_alert_post(state, candidate, sent_at=now)
                        print(f"[gone_worker] sent {_build_listing_summary(candidate)}")
                        processed += 1
                    else:
                        print(f"[gone_worker] send failed {_build_listing_summary(candidate)}")
                else:
                    print("[gone_worker] no eligible gone candidates")

            if once:
                break
            if limit is not None and processed >= limit:
                break

            time.sleep(_sleep_seconds())


def main() -> None:
    parser = argparse.ArgumentParser(description="Lightweight free gone-alert worker")
    parser.add_argument("--once", action="store_true", help="Run a single cycle")
    parser.add_argument("--limit", type=int, default=None, help="Stop after N sent gone alerts")
    args = parser.parse_args()
    run_worker(once=args.once, limit=args.limit)


if __name__ == "__main__":
    main()
