import os
import time

from services.wallapop_scraper import fetch_wallapop_listings, wallapop_enabled, wallapop_max_items
from vip_app.app import create_app
from vip_app.app.api import build_listing_from_payload
from vip_app.app.extensions import db
from vip_app.app.feed_cache import invalidate
from vip_app.app.models import Listing


def _env_int(name: str, default: int, minimum: int = 1) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default
    return max(minimum, value)


def _env_float(name: str, default: float, minimum: float = 0.0) -> float:
    try:
        value = float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default
    return max(minimum, value)


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def existing_wallapop_ids(limit: int = 1000) -> set[str]:
    rows = (
        db.session.query(Listing.external_id)
        .filter(Listing.source == "wallapop")
        .order_by(Listing.id.desc())
        .limit(limit)
        .all()
    )
    return {row[0] for row in rows if row and row[0]}


def _payload_from_wallapop_item(item: dict) -> dict:
    return {
        "source": "wallapop",
        "platform": "Wallapop",
        "external_id": item.get("external_id") or item.get("id"),
        "title": item.get("title") or item.get("titulo"),
        "price": item.get("price") or item.get("preco"),
        "url": item.get("url") or item.get("link"),
        "image_url": item.get("image_url") or item.get("imagem"),
        "detected_at": item.get("detected_at"),
        "available_status": "available",
        "badge_label": "Fresh",
        "tcg_type": "pokemon",
        "category": "wallapop",
        "raw_payload": item.get("raw_payload") or {},
    }


def run_once(app=None) -> dict:
    if app is None:
        app = create_app()

    if not wallapop_enabled():
        print("[WALLAPOP_WORKER] status=disabled", flush=True)
        return {"status": "disabled", "fetched": 0, "inserted": 0, "duplicates": 0, "errors": 0}

    with app.app_context():
        max_items = wallapop_max_items()
        seen_ids = existing_wallapop_ids()
        fetched_items, scrape_stats = fetch_wallapop_listings(
            max_items=max_items,
            headless=_env_bool("WALLAPOP_HEADLESS", True),
            delay_min_seconds=_env_float("WALLAPOP_DELAY_MIN_SECONDS", 2.0),
            delay_max_seconds=_env_float("WALLAPOP_DELAY_MAX_SECONDS", 5.0),
            seen_ids=seen_ids,
            return_stats=True,
        )

        inserted = 0
        db_duplicates = 0
        errors = 0
        for item in fetched_items:
            payload = _payload_from_wallapop_item(item)
            try:
                listing, missing_fields, existing = build_listing_from_payload(payload)
                if missing_fields:
                    errors += 1
                    print(
                        f"[WALLAPOP_DB_SKIPPED] reason=missing_fields fields={','.join(missing_fields)} "
                        f"external_id={payload.get('external_id')}",
                        flush=True,
                    )
                    continue
                if existing:
                    db_duplicates += 1
                    print(
                        f"[WALLAPOP_DB_DUPLICATE] listing_id={existing.id} external_id={payload.get('external_id')}",
                        flush=True,
                    )
                    continue

                db.session.add(listing)
                db.session.commit()
                invalidate("feed:")
                inserted += 1
                print(
                    f"[WALLAPOP_DB_INSERTED] listing_id={listing.id} external_id={listing.external_id} "
                    f"title={listing.title[:90]}",
                    flush=True,
                )
            except Exception as exc:
                db.session.rollback()
                errors += 1
                print(f"[WALLAPOP_DB_ERROR] external_id={payload.get('external_id')} error={exc}", flush=True)

        duplicates = db_duplicates + int(scrape_stats.get("duplicates", 0))
        result = {
            "status": "ok",
            "fetched": len(fetched_items),
            "inserted": inserted,
            "duplicates": duplicates,
            "errors": errors,
        }
        print(
            f"[WALLAPOP_WORKER_RUN_DONE] fetched={result['fetched']} inserted={inserted} "
            f"duplicates={duplicates} db_duplicates={db_duplicates} scrape_duplicates={scrape_stats.get('duplicates', 0)} "
            f"errors={errors}",
            flush=True,
        )
        return result


def main():
    app = create_app()
    interval = _env_int("WALLAPOP_WORKER_INTERVAL_SECONDS", 300, minimum=30)
    run_once_only = _env_bool("WALLAPOP_RUN_ONCE", False)
    while True:
        run_once(app)
        if run_once_only:
            break
        time.sleep(interval)


if __name__ == "__main__":
    main()
