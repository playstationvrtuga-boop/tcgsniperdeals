from __future__ import annotations

import argparse
import json
import os
import random
import time
from datetime import timedelta
from sqlalchemy import or_

from config import (
    APP_API_URL,
    EBAY_CLIENT_ID,
    EBAY_CLIENT_SECRET,
    EBAY_ENABLE_OFFICIAL_API,
    EBAY_MARKETPLACE_ID,
    PRICING_ENABLE_EBAY_HTML_FALLBACK,
    PRICING_RETRY_AFTER_MINUTES,
    PRICING_WORKER_MAX_SLEEP,
    PRICING_WORKER_MIN_SLEEP,
)
from services.alert_formatter import format_vip_alert, make_partial_product_name
from services.ai_market_intel import apply_ai_market_intel_to_listing
from services.deal_detector import EbaySoldError, EbaySoldRateLimitError, evaluate_listing
from services.ebay_api_client import ebay_api_client
from vip_app.app import create_app
from vip_app.app.extensions import db
from vip_app.app.models import Listing, utcnow
from vip_app.app.push import send_deal_push


app = create_app()


def _pending_listing_query():
    retry_before = utcnow() - timedelta(minutes=PRICING_RETRY_AFTER_MINUTES)
    retryable_old_results = (
        Listing.pricing_status.in_(["needs_review", "insufficient_comparables"])
        & (
            (Listing.pricing_checked_at.is_(None))
            | (Listing.pricing_checked_at <= retry_before)
        )
    )
    retryable_legacy_skips = (
        (Listing.pricing_status == "skipped")
        & (
            (Listing.pricing_checked_at.is_(None))
            | (Listing.pricing_checked_at <= retry_before)
        )
        & (
            Listing.pricing_error.contains("listing_not_precisely_identified")
            | Listing.pricing_error.contains("not_enough_price")
            | Listing.pricing_error.contains("DEAL_REJECTED_NO_REFERENCE")
        )
    )
    return (
        Listing.query.filter(
            or_(
                Listing.pricing_status.is_(None),
                Listing.pricing_status == "",
                Listing.pricing_status == "pending",
                (
                    Listing.pricing_status.in_(["rate_limited", "api_error"])
                    & (
                        (Listing.pricing_checked_at.is_(None))
                        | (Listing.pricing_checked_at <= retry_before)
                    )
                ),
                retryable_old_results,
                retryable_legacy_skips,
            )
        )
        # Fresh opportunities matter more than old backlog. Retryable old rows still
        # get processed when the stream is quiet, but new listings are checked first.
        .order_by(Listing.detected_at.desc(), Listing.created_at.desc(), Listing.id.desc())
    )


def fetch_next_pending_listing() -> Listing | None:
    return _pending_listing_query().first()


def _mark_processed(listing: Listing, result) -> None:
    checked_at = utcnow()
    listing.reference_price = result.estimated_fair_value or result.reference_price
    listing.market_buy_now_min = result.market_buy_now_min
    listing.market_buy_now_avg = result.market_buy_now_avg
    listing.market_buy_now_median = result.market_buy_now_median
    listing.last_sold_prices_json = json.dumps(result.last_sold_prices or [], ensure_ascii=False)
    listing.last_2_sales_json = json.dumps(result.last_2_sales or [], ensure_ascii=False)
    listing.sold_avg_price = result.sold_avg_price
    listing.sold_median_price = result.sold_median_price
    listing.estimated_fair_value = result.estimated_fair_value or result.reference_price
    listing.pricing_basis = result.pricing_basis
    listing.confidence_score = result.confidence_score
    listing.listing_type = result.listing_type
    listing.discount_percent = result.discount_percent
    listing.gross_margin = result.gross_margin
    listing.estimated_profit = result.gross_margin
    listing.profit_margin = result.gross_margin
    listing.pricing_score = result.score
    listing.score_level = _score_level(result.score)
    listing.is_deal = bool(result.is_deal)
    listing.pricing_status = "analyzed" if result.status in {"deal", "priced"} else result.status
    listing.pricing_error = result.reason if result.status not in {"deal", "priced"} else None
    listing.pricing_reason = _pricing_reason(result)
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


def _mask_config_value(value: str) -> str:
    return "present" if value else "missing"


def _runtime_setting(name: str, fallback: str = "") -> str:
    value = os.environ.get(name)
    if value is None:
        return str(fallback or "")
    return str(value).strip()


def _runtime_flag(name: str, fallback: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return bool(fallback)
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _pricing_reason(result) -> str:
    parts = [
        f"source={result.price_source or 'unknown'}",
        f"sold_refs={result.comparable_count or 0}",
        f"buy_now_refs={getattr(result, 'buy_now_count', 0) or 0}",
    ]
    if getattr(result, "parser_confidence", None):
        parts.append(f"confidence={result.parser_confidence}")
    if getattr(result, "parser_query", None):
        parts.append(f"query={result.parser_query}")
    if getattr(result, "buy_now_reference_price", None) is not None:
        parts.append(f"buy_now_ref={result.buy_now_reference_price:.2f}eur")
    if getattr(result, "estimated_fair_value", None) is not None:
        parts.append(f"fair_value={result.estimated_fair_value:.2f}eur")
    if getattr(result, "pricing_basis", None):
        parts.append(f"basis={result.pricing_basis}")
    if getattr(result, "listing_type", None):
        parts.append(f"listing_type={result.listing_type}")
    if getattr(result, "confidence_score", None) is not None:
        parts.append(f"confidence_score={result.confidence_score}")
    if getattr(result, "last_2_sales", None):
        parts.append("last_2_sales=" + ",".join(f"{price:.2f}" for price in result.last_2_sales[:2]))
    if result.reason:
        parts.append(f"note={result.reason}")
    return "; ".join(parts)[:255]


def _describe_result(result) -> str:
    kind = result.listing_kind or "unknown"
    source = result.price_source or "unknown"
    buy_now_count = getattr(result, "buy_now_count", 0) or 0
    buy_now_reference = getattr(result, "buy_now_reference_price", None)
    sold_median = getattr(result, "sold_median_price", None)
    fair_value = getattr(result, "estimated_fair_value", None) or result.reference_price
    buy_now_part = f" buy_now={buy_now_count}"
    if buy_now_reference is not None:
        buy_now_part += f" buy_now_ref={buy_now_reference:.2f}eur"
    if sold_median is not None:
        buy_now_part += f" sold_median={sold_median:.2f}eur"

    if result.status == "deal":
        return (
            f"DEAL kind={kind} price={result.listing_price:.2f}eur "
            f"fair_value={fair_value:.2f}eur basis={getattr(result, 'pricing_basis', None) or source} "
            f"last3={result.comparable_count}{buy_now_part} "
            f"discount={result.discount_percent:.1f}% margin={result.gross_margin:.2f}eur "
            f"score={result.score} confidence={getattr(result, 'confidence_score', None) or 'n/a'}"
        )

    if result.status == "priced":
        return (
            f"PRICED kind={kind} price={result.listing_price:.2f}eur "
            f"fair_value={fair_value:.2f}eur basis={getattr(result, 'pricing_basis', None) or source} "
            f"last3={result.comparable_count}{buy_now_part} "
            f"discount={result.discount_percent:.1f}% margin={result.gross_margin:.2f}eur "
            f"score={result.score} confidence={getattr(result, 'confidence_score', None) or 'n/a'}"
        )

    if result.status == "needs_review":
        return (
            f"NEEDS_REVIEW kind={kind} reason={result.reason or 'n/a'} "
            f"confidence={getattr(result, 'parser_confidence', None) or 'n/a'} "
            f"query={getattr(result, 'parser_query', None) or 'n/a'} "
            f"sold={result.comparable_count} buy_now={buy_now_count}"
        )

    if result.reason == "listing_not_precisely_identified":
        return f"SKIPPED kind={kind} reason=title_not_precise"

    if result.reason == "not_pokemon_related":
        return f"SKIPPED kind={kind} confidence={getattr(result, 'parser_confidence', None) or 'UNKNOWN'} reason=not_pokemon_related"

    if result.reason in {"not_enough_recent_sales", "not_enough_price_references"} or str(result.reason or "").startswith("not_enough_price_references"):
        return (
            f"SKIPPED kind={kind} reason=not_enough_price_refs "
            f"sold={result.comparable_count} buy_now={buy_now_count}"
        )

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
        if result.reason:
            print(f"[pricing_worker] diagnostic_reason={result.reason}")
        _mark_processed(listing, result)
        try:
            apply_ai_market_intel_to_listing(listing)
        except Exception as intel_error:
            print(f"[pricing_worker] ai market intel skipped for listing {listing.id}: {intel_error}")

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
        ebay_enabled = _runtime_flag("EBAY_ENABLE_OFFICIAL_API", EBAY_ENABLE_OFFICIAL_API)
        ebay_client_id = _runtime_setting("EBAY_CLIENT_ID", EBAY_CLIENT_ID)
        ebay_client_secret = _runtime_setting("EBAY_CLIENT_SECRET", EBAY_CLIENT_SECRET)
        ebay_marketplace = _runtime_setting("EBAY_MARKETPLACE_ID", EBAY_MARKETPLACE_ID) or "EBAY_US"
        ebay_html_fallback = _runtime_flag(
            "PRICING_ENABLE_EBAY_HTML_FALLBACK",
            PRICING_ENABLE_EBAY_HTML_FALLBACK,
        )
        print(f"[pricing_worker] database={database_uri}", flush=True)
        print(f"[pricing_worker] bot_app_api_url={APP_API_URL}", flush=True)
        print(
            "[pricing_worker] ebay_api "
            f"enabled={ebay_enabled} "
            f"client_id={_mask_config_value(ebay_client_id)} "
            f"client_secret={_mask_config_value(ebay_client_secret)} "
            f"marketplace={ebay_marketplace}"
            f" html_fallback={ebay_html_fallback}",
            flush=True,
        )
        if ebay_client_id and ebay_client_secret:
            print("[config] environment variables loaded successfully", flush=True)
        else:
            print("[config] required environment variables not found", flush=True)
            print("[config] check deployment environment configuration", flush=True)
        if ebay_enabled and (not ebay_client_id or not ebay_client_secret):
            print("[ebay_api] API_KEYS_MISSING", flush=True)
            print(
                "[ebay_api] Add EBAY_CLIENT_ID and EBAY_CLIENT_SECRET to Render service "
                "tcg-sniper-deals-worker Environment Variables",
                flush=True,
            )
        ebay_api_client.startup_check(query="pokemon", limit=20, log=True)
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
