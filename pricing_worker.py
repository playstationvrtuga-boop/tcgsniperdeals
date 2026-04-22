from __future__ import annotations

import argparse
import random
import time
from datetime import datetime

from sqlalchemy import or_

from config import PRICING_WORKER_MAX_SLEEP, PRICING_WORKER_MIN_SLEEP
from services.alert_formatter import classify_deal_level, format_free_alert_text, format_vip_alert, make_partial_product_name
from services.deal_detector import EbaySoldError, EbaySoldRateLimitError, evaluate_listing
from services.free_alert_queue import enqueue_free_alert
from vip_app.app import create_app
from vip_app.app.extensions import db
from vip_app.app.models import Listing, utcnow
from vip_app.app.push import send_deal_push


app = create_app()


def _minutes_until(iso_value: str | None) -> int | None:
    if not iso_value:
        return None
    try:
        target = datetime.fromisoformat(iso_value)
    except ValueError:
        return None
    if target.tzinfo is None:
        target = target.replace(tzinfo=utcnow().tzinfo)
    delta_seconds = (target - utcnow()).total_seconds()
    return max(0, int(round(delta_seconds / 60)))


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
    listing.reference_price = result.reference_price
    listing.discount_percent = result.discount_percent
    listing.gross_margin = result.gross_margin
    listing.pricing_score = result.score
    listing.is_deal = bool(result.is_deal)
    listing.pricing_status = result.status
    listing.pricing_error = result.reason
    listing.pricing_checked_at = utcnow()


def _mark_error(listing: Listing, status: str, message: str) -> None:
    listing.pricing_status = status
    listing.pricing_error = message[:255]
    listing.pricing_checked_at = utcnow()


def _short_title(value: str, max_len: int = 78) -> str:
    text = (value or "").strip()
    if len(text) <= max_len:
        return text
    return f"{text[: max_len - 3].rstrip()}..."


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
            free_variant = random.choice(["full", "short"])
            deal_meta = classify_deal_level(result.discount_percent, result.gross_margin)

            listing.badge_label = vip_alert["badge"]
            listing.alert_title = vip_alert["alert_title"]
            listing.partial_title = partial_title
            listing.confidence_label = vip_alert["confidence"]
            listing.deal_level = vip_alert["deal_level"]
            listing.score_label = vip_alert["confidence"]
            listing.is_vip_only = True
            listing.free_message_variant = free_variant

            try:
                send_deal_push(listing, result)
            except Exception as push_error:
                print(f"[pricing_worker] app push failed for listing {listing.id}: {push_error}")

            if deal_meta:
                free_payload = {
                    "listing_id": listing.id,
                    "title": listing.title,
                    "full_name": listing.title,
                    "partial_title": partial_title,
                    "platform": listing.platform,
                    "tcg_type": listing.tcg_type,
                    "listing_price": result.listing_price,
                    "listing_price_text": listing.price_display,
                    "market_price": result.reference_price,
                    "discount_percent": result.discount_percent,
                    "potential_profit": result.gross_margin,
                    "score": result.score,
                    "detected_at": (listing.detected_at or utcnow()).isoformat(),
                    "free_message_variant": free_variant,
                }
                free_payload["free_message_text"] = format_free_alert_text(free_payload)
                eligible_at = enqueue_free_alert(free_payload)
                if eligible_at:
                    listing.free_send_at = datetime.fromisoformat(eligible_at)
                    listing.free_sent = False
                    wait_minutes = _minutes_until(eligible_at)
                    print(
                        f"[pricing_worker] FREE queued listing_id={listing.id} "
                        f"delay={wait_minutes}min send_at={eligible_at}"
                    )

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
        while True:
            listing = fetch_next_pending_listing()
            if listing is None:
                print("[pricing_worker] no pending listings")
                break

            status = process_listing(listing)
            processed += 1
            print(f"[pricing_worker] listing_id={listing.id} status={status}")

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
