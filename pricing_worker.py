from __future__ import annotations

import argparse
import random
import time
from sqlalchemy import or_

from config import APP_API_URL, PRICING_WORKER_MAX_SLEEP, PRICING_WORKER_MIN_SLEEP
from services.alert_formatter import format_vip_alert, make_partial_product_name
from services.deal_detector import EbaySoldError, EbaySoldRateLimitError, evaluate_listing
from vip_app.app import create_app
from vip_app.app.extensions import db
from vip_app.app.models import Listing, utcnow
from vip_app.app.push import send_deal_push


app = create_app()


def _pending_listing_query():
    return (
        Listing.query.filter(
            or_(
                Listing.pricing_status.is_(None),
                Listing.pricing_status == "",
                Listing.pricing_status == "pending",
            )
        )
        .order_by(Listing.detected_at.asc(), Listing.created_at.asc(), Listing.id.asc())
    )


def fetch_next_pending_listing() -> Listing | None:
    return _pending_listing_query().first()


def _mark_processed(listing: Listing, result) -> None:
    checked_at = utcnow()
    listing.reference_price = result.reference_price
    listing.discount_percent = result.discount_percent
    listing.gross_margin = result.gross_margin
    listing.estimated_profit = result.gross_margin
    listing.profit_margin = result.gross_margin
    listing.pricing_score = result.score
    listing.score_level = _score_level(result.score)
    listing.is_deal = bool(result.is_deal)
    listing.pricing_status = "analyzed" if result.status in {"deal", "priced"} else result.status
    listing.pricing_error = result.reason
    listing.pricing_reason = result.reason or result.status
    listing.pricing_checked_at = checked_at
    listing.pricing_analyzed_at = checked_at


def _mark_error(listing: Listing, status: str, message: str) -> None:
    listing.pricing_status = status
    listing.pricing_error = message[:255]
    listing.pricing_checked_at = utcnow()


def _short_title(value: str, max_len: int = 78) -> str:
    text = (value or "").strip()
    if len(text) <= max_len:
        return text
    return f"{text[: max_len - 3].rstrip()}..."


def _score_level(score: int | float | None) -> str:
    value = int(score or 0)
    if value >= 85:
        return "INSANE"
    if value >= 70:
        return "HIGH"
    if value >= 45:
        return "MEDIUM"
    return "LOW"


def _describe_result(result) -> str:
    kind = result.listing_kind or "unknown"
    if result.status == "deal":
        return (
            f"DEAL kind={kind} price={result.listing_price:.2f}eur "
            f"ref={result.reference_price:.2f}eur last3={result.comparable_count} "
            f"discount={result.discount_percent:.1f}% margin={result.gross_margin:.2f}eur "
            f"score={result.score}"
        )

    if result.status == "priced":
        return (
            f"PRICED kind={kind} price={result.listing_price:.2f}eur "
            f"ref={result.reference_price:.2f}eur last3={result.comparable_count} "
            f"discount={result.discount_percent:.1f}% margin={result.gross_margin:.2f}eur "
            f"score={result.score}"
        )

    if result.reason == "listing_not_precisely_identified":
        return f"SKIPPED kind={kind} reason=title_not_precise"

    if result.reason == "not_enough_recent_sales":
        return f"SKIPPED kind={kind} reason=only_{result.comparable_count}_recent_sales"

    if result.reason == "invalid_listing_price":
        return f"SKIPPED kind={kind} reason=invalid_price"

    if result.reason == "missing_title":
        return "SKIPPED reason=missing_title"

    if result.reason == "invalid_reference_price":
        return f"SKIPPED kind={kind} reason=invalid_reference"

    return f"{result.status.upper()} kind={kind} reason={result.reason or 'n/a'}"


def process_listing(listing: Listing) -> str:
    try:
        result = evaluate_listing(listing)
        print(
            f"[pricing_worker] listing_id={listing.id} "
            f"title={_short_title(listing.title)}"
        )
        print(f"[pricing_worker] {_describe_result(result)}")
        _mark_processed(listing, result)

        if result.is_deal and listing.deal_alert_sent_at is None:
            vip_alert = format_vip_alert(
                {
                    "title": listing.title,
                    "platform": listing.platform,
                    "listing_price": result.listing_price,
                    "listing_price_text": listing.price_display,
                    "market_price": result.reference_price,
                    "discount_percent": result.discount_percent,
                    "potential_profit": result.gross_margin,
                    "score": result.score,
                    "detected_at": listing.detected_at or utcnow(),
                    "direct_link": listing.external_url,
                    "image_url": listing.image_url,
                }
            )
            partial_title = make_partial_product_name(listing.title)

            listing.badge_label = vip_alert["badge"]
            listing.alert_title = vip_alert["alert_title"]
            listing.partial_title = partial_title
            listing.confidence_label = vip_alert["confidence"]
            listing.deal_level = vip_alert["deal_level"]
            listing.score_label = vip_alert["confidence"]
            listing.is_vip_only = True

            try:
                send_deal_push(listing, result)
            except Exception as push_error:
                print(f"[pricing_worker] app push failed for listing {listing.id}: {push_error}")

            listing.deal_alert_sent_at = utcnow()
            print(f"[pricing_worker] VIP app alert ready for listing_id={listing.id}")

        db.session.commit()
        return result.status
    except EbaySoldRateLimitError as error:
        db.session.rollback()
        _mark_error(listing, "rate_limited", str(error))
        db.session.commit()
        print(f"[pricing_worker] rate limited on listing {listing.id}: {error}")
        return "rate_limited"
    except EbaySoldError as error:
        db.session.rollback()
        _mark_error(listing, "api_error", str(error))
        db.session.commit()
        print(f"[pricing_worker] pricing source error on listing {listing.id}: {error}")
        return "api_error"
    except Exception as error:
        db.session.rollback()
        _mark_error(listing, "worker_error", str(error))
        db.session.commit()
        print(f"[pricing_worker] unexpected error on listing {listing.id}: {error}")
        return "worker_error"
def run_worker(*, once: bool = False, limit: int | None = None) -> None:
    processed = 0

    with app.app_context():
        database_uri = app.config.get("SQLALCHEMY_DATABASE_URI")
        print(f"[pricing_worker] database={database_uri}")
        print(f"[pricing_worker] bot_app_api_url={APP_API_URL}")
        if "127.0.0.1" not in str(APP_API_URL) and "localhost" not in str(APP_API_URL) and str(database_uri).startswith("sqlite"):
            print("[pricing_worker] warning: bot is configured for online API, but this worker is reading local SQLite")
        while True:
            listing = fetch_next_pending_listing()
            if listing is not None:
                status = process_listing(listing)
                processed += 1
                print(f"[pricing_worker] listing_id={listing.id} status={status}")
            else:
                print("[pricing_worker] idle - no pending listings")
                if once:
                    break
                time.sleep(random.uniform(PRICING_WORKER_MIN_SLEEP, PRICING_WORKER_MAX_SLEEP))
                continue

            if once:
                break
            if limit is not None and processed >= limit:
                break

            time.sleep(random.uniform(PRICING_WORKER_MIN_SLEEP, PRICING_WORKER_MAX_SLEEP))


def main() -> None:
    parser = argparse.ArgumentParser(description="Sequential lightweight pricing worker")
    parser.add_argument("--once", action="store_true", help="Process only one pending listing")
    parser.add_argument("--limit", type=int, default=None, help="Process up to N pending listings")
    args = parser.parse_args()
    run_worker(once=args.once, limit=args.limit)


if __name__ == "__main__":
    main()
