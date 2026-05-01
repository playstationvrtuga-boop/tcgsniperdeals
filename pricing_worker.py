from __future__ import annotations

import argparse
import json
import os
import random
import re
import time
from datetime import timedelta
from sqlalchemy import and_, or_

from config import (
    APP_API_URL,
    EBAY_CLIENT_ID,
    EBAY_CLIENT_SECRET,
    EBAY_ENABLE_OFFICIAL_API,
    EBAY_MARKETPLACE_ID,
    PRICING_ENABLE_EBAY_HTML_FALLBACK,
    PRICING_RETRY_AFTER_MINUTES,
    PRICING_WORKER_ENABLED,
    PRICING_WORKER_MAX_SLEEP,
    PRICING_WORKER_MIN_SLEEP,
)
from services.alert_formatter import format_vip_alert, make_partial_product_name
from services.ai_market_intel import apply_ai_market_intel_to_listing
from services.deal_detector import (
    EbaySoldError,
    EbaySoldRateLimitError,
    detect_card_language,
    detect_pokemon_set,
    ebay_pause_remaining_seconds,
    evaluate_listing,
)
from services.ebay_api_client import ebay_api_client
from vip_app.app import create_app
from vip_app.app.extensions import db
from vip_app.app.feed_cache import invalidate
from vip_app.app.models import Listing, utcnow
from vip_app.app.push import send_deal_push


app = create_app()
EBAY_PAUSE_WORKER_BACKOFF_MAX_SECONDS = 60
DB_TEXT_LIMIT = 250
PRICING_WORKER_BATCH_LIMIT = max(1, int(os.environ.get("PRICING_WORKER_BATCH_LIMIT", "30")))
PRICING_WORKER_FRESH_WINDOW_HOURS = max(1, int(os.environ.get("PRICING_WORKER_FRESH_WINDOW_HOURS", "24")))


def _pending_listing_filter():
    retry_before = utcnow() - timedelta(minutes=PRICING_RETRY_AFTER_MINUTES)
    checked_before_retry = (
        (Listing.pricing_checked_at.is_(None))
        | (Listing.pricing_checked_at <= retry_before)
    )
    retryable_old_results = (
        Listing.pricing_status.in_([
            "needs_review",
            "insufficient_comparables",
            "retry_later",
            "pricing_deferred",
        ])
        & checked_before_retry
    )
    retryable_incomplete_analyzed = (
        Listing.pricing_status.in_(["analyzed", "priced"])
        & checked_before_retry
        & or_(
            Listing.pricing_basis.is_(None),
            Listing.pricing_basis == "",
            Listing.pricing_reason.is_(None),
            and_(
                ~Listing.pricing_reason.contains("identity=strong"),
                ~Listing.pricing_reason.contains("PRICING_STRONG_ID"),
                ~Listing.pricing_reason.contains("PRICING_WEAK_ID_NEEDS_REVIEW"),
            ),
        )
    )
    retryable_legacy_skips = (
        (Listing.pricing_status == "skipped")
        & checked_before_retry
        & (
            Listing.pricing_error.contains("listing_not_precisely_identified")
            | Listing.pricing_error.contains("not_enough_price")
            | Listing.pricing_error.contains("DEAL_REJECTED_NO_REFERENCE")
        )
    )
    return or_(
        Listing.pricing_status.is_(None),
        Listing.pricing_status == "",
        Listing.pricing_status == "pending",
        (
            Listing.pricing_status.in_(["analyzing", "rate_limited", "api_error"])
            & checked_before_retry
        ),
        retryable_old_results,
        retryable_incomplete_analyzed,
        retryable_legacy_skips,
    )


def _pending_listing_query(*, recent_only: bool | None = None):
    query = Listing.query.filter(_pending_listing_filter())
    if recent_only is not None:
        fresh_cutoff = utcnow() - timedelta(hours=PRICING_WORKER_FRESH_WINDOW_HOURS)
        if recent_only:
            query = query.filter(Listing.detected_at >= fresh_cutoff)
        else:
            query = query.filter(
                or_(Listing.detected_at < fresh_cutoff, Listing.detected_at.is_(None))
            )
    return (
        query
        # Fresh opportunities matter more than old backlog. Retryable old rows still
        # get processed when the stream is quiet, but new listings are checked first.
        .order_by(Listing.detected_at.desc(), Listing.created_at.desc(), Listing.id.desc())
    )


def fetch_pending_listing_batch(limit: int | None = None) -> list[Listing]:
    batch_limit = max(1, int(limit or PRICING_WORKER_BATCH_LIMIT))
    fresh_listings = _pending_listing_query(recent_only=True).limit(batch_limit).all()
    remaining = batch_limit - len(fresh_listings)
    if remaining <= 0:
        return fresh_listings

    older_backfill = _pending_listing_query(recent_only=False).limit(remaining).all()
    return fresh_listings + older_backfill


def fetch_next_pending_listing() -> Listing | None:
    batch = fetch_pending_listing_batch(limit=1)
    return batch[0] if batch else None


def _mark_analyzing(listing: Listing) -> None:
    listing.pricing_status = "analyzing"
    listing.pricing_checked_at = utcnow()
    db.session.commit()


def _invalidate_feed_cache() -> None:
    try:
        invalidate("feed:")
    except Exception as error:
        print(f"[pricing_worker] cache invalidation skipped: {error}", flush=True)


def _log_processed_status(listing: Listing, result) -> None:
    final_status = (listing.pricing_status or result.status or "").strip().lower()
    if final_status in {"analyzed", "priced", "deal"}:
        print(
            f"[pricing] analyzed listing_id={listing.id} status={final_status} "
            f"score={listing.pricing_score} level={listing.score_level}",
            flush=True,
        )
        return

    print(
        f"[pricing] skipped listing_id={listing.id} status={final_status or 'unknown'} "
        f"reason={result.reason or listing.pricing_error or 'n/a'}",
        flush=True,
    )


def _mark_processed(listing: Listing, result) -> None:
    checked_at = utcnow()
    listing.card_language = result.card_language or listing.card_language or detect_card_language(
        listing.title or "",
        marketplace=listing.platform,
    )
    set_info = detect_pokemon_set(listing.title or "")
    listing.set_code = result.set_code or listing.set_code or set_info.get("set_code")
    listing.set_name = result.set_name or listing.set_name or set_info.get("set_name")
    if result.status in {"retry_later", "pricing_deferred"}:
        listing.confidence_score = result.confidence_score
        listing.listing_type = result.listing_type or listing.listing_type
        listing.pricing_score = result.score
        listing.score_level = _score_level(result.score)
        listing.is_deal = False
        listing.pricing_status = result.status
        listing.pricing_error = _truncate_db_text(result.reason)
        listing.pricing_reason = _truncate_db_text(_pricing_reason(result))
        listing.pricing_checked_at = checked_at
        listing.pricing_analyzed_at = checked_at
        return

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
    listing.pricing_error = _truncate_db_text(result.reason) if result.status not in {"deal", "priced"} else None
    listing.pricing_reason = _truncate_db_text(_pricing_reason(result))
    listing.pricing_checked_at = checked_at
    listing.pricing_analyzed_at = checked_at


def _mark_error(listing: Listing, status: str, message: str) -> None:
    listing.pricing_status = status
    listing.pricing_error = _truncate_db_text(message)
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


def _truncate_db_text(value, limit: int = DB_TEXT_LIMIT) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text[:limit]


def _mask_config_value(value: str) -> str:
    return "present" if value else "missing"


def _mask_database_uri(value: str | None) -> str:
    raw = str(value or "")
    if "://" not in raw or "@" not in raw:
        return raw
    return re.sub(r"://([^:/@]+):([^@]+)@", r"://\1:***@", raw)


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


def _is_local_app_url(value: str | None) -> bool:
    text = str(value or "").lower()
    return any(marker in text for marker in ("localhost", "127.0.0.1", "::1"))


def _database_kind(database_uri: str | None) -> str:
    text = str(database_uri or "").lower()
    if text.startswith("sqlite:"):
        return "sqlite"
    if text.startswith(("postgres:", "postgresql:")) or "postgresql+" in text:
        return "postgres"
    return "unknown"


def _target_kind(app_api_url: str | None) -> str:
    return "local" if _is_local_app_url(app_api_url) else "online"


def _log_runtime_and_should_continue(
    *,
    app_api_url: str,
    database_uri: str | None,
    pricing_enabled: bool,
) -> bool:
    target = _target_kind(app_api_url)
    database = _database_kind(database_uri)
    print(
        "[PRICING_WORKER_RUNTIME] "
        f"target={target} "
        f"database={database} "
        f"app_api_url={app_api_url} "
        f"pricing_enabled={str(pricing_enabled).lower()}",
        flush=True,
    )
    if not pricing_enabled:
        print("[pricing_worker] stopped reason=pricing_worker_disabled", flush=True)
        return False
    if target == "online" and database == "sqlite":
        print(
            "[pricing_worker] stopped reason=runtime_mismatch "
            "detail=APP_API_URL points online but worker database is local sqlite",
            flush=True,
        )
        return False
    return True


def _pricing_reason(result) -> str:
    sold_refs = result.comparable_count or 0
    buy_now_refs = getattr(result, "buy_now_count", 0) or 0
    parts = [
        f"source={result.price_source or 'unknown'}",
        f"sold_refs={sold_refs}",
        f"buy_now_refs={buy_now_refs}",
        f"comparable_results={sold_refs + buy_now_refs}",
    ]
    reason_text = str(result.reason or "")
    if "PRICING_STRONG_ID" in reason_text:
        parts.append("identity=strong")
    elif "PRICING_WEAK_ID_NEEDS_REVIEW" in reason_text:
        parts.append("identity=weak")
    if "PRICING_SKIPPED_SNIPER_FALSE_POSITIVE_RISK" in reason_text:
        parts.append("false_positive_risk=true")
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
        parts.append(f"market_type={result.listing_type}")
    if getattr(result, "confidence_score", None) is not None:
        parts.append(f"confidence_score={result.confidence_score}")
    if getattr(result, "last_2_sales", None):
        parts.append("last_2_sales=" + ",".join(f"{price:.2f}" for price in result.last_2_sales[:2]))
    if result.reason:
        parts.append(f"note={result.reason}")
    return _truncate_db_text("; ".join(parts)) or ""


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


def _log_queue_snapshot() -> None:
    since = utcnow() - timedelta(hours=24)
    rows = (
        db.session.query(
            db.func.lower(db.func.coalesce(Listing.pricing_status, "pending")),
            db.func.count(Listing.id),
        )
        .filter(Listing.created_at >= since)
        .group_by(db.func.lower(db.func.coalesce(Listing.pricing_status, "pending")))
        .all()
    )
    counts = {str(status or "pending"): int(count or 0) for status, count in rows}
    pending_count = _pending_listing_query().limit(500).count()
    latest_analyzed = (
        Listing.query.filter(Listing.pricing_analyzed_at.isnot(None))
        .order_by(Listing.pricing_analyzed_at.desc())
        .first()
    )
    latest_text = (
        f"id={latest_analyzed.id} status={latest_analyzed.pricing_status} "
        f"score={latest_analyzed.pricing_score} confidence={latest_analyzed.confidence_score}"
        if latest_analyzed
        else "none"
    )
    print(
        "[pricing_worker] queue_status "
        f"pending_like={pending_count} last24={counts} latest_analyzed={latest_text}",
        flush=True,
    )


def process_listing(listing: Listing) -> str:
    try:
        previous_status = (listing.pricing_status or "pending").strip().lower() or "pending"
        print(
            f"[pricing_worker] queue_picked listing_id={listing.id} "
            f"previous_status={previous_status} detected_at={listing.detected_at}",
            flush=True,
        )
        _mark_analyzing(listing)
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
                    "id": listing.id,
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
                    "affiliate_source": "vip",
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
        _invalidate_feed_cache()
        _log_processed_status(listing, result)
        return result.status
    except EbaySoldRateLimitError as error:
        db.session.rollback()
        _mark_error(listing, "rate_limited", str(error))
        db.session.commit()
        _invalidate_feed_cache()
        print(f"[pricing_worker] rate limited on listing {listing.id}: {error}")
        return "rate_limited"
    except EbaySoldError as error:
        db.session.rollback()
        _mark_error(listing, "api_error", str(error))
        db.session.commit()
        _invalidate_feed_cache()
        print(f"[pricing_worker] pricing source error on listing {listing.id}: {error}")
        return "api_error"
    except Exception as error:
        db.session.rollback()
        _mark_error(listing, "worker_error", str(error))
        db.session.commit()
        _invalidate_feed_cache()
        print(f"[pricing_worker] unexpected error on listing {listing.id}: {error}")
        return "worker_error"


def _listing_has_pricing_data(listing: Listing) -> bool:
    return bool(
        listing.estimated_fair_value
        or listing.reference_price
        or listing.sold_avg_price
        or listing.market_buy_now_median
    )


def _sleep_for_active_ebay_pause(*, once: bool = False) -> bool:
    remaining = ebay_pause_remaining_seconds()
    if remaining <= 0:
        return False
    sleep_seconds = min(max(1, remaining + 1), EBAY_PAUSE_WORKER_BACKOFF_MAX_SECONDS)
    print(
        f"[pricing_worker] ebay_pause_backoff remaining={remaining}s sleep={sleep_seconds}s",
        flush=True,
    )
    if not once:
        time.sleep(sleep_seconds)
    return True


def run_worker(*, once: bool = False, limit: int | None = None) -> None:
    processed = 0
    data_found = 0
    opportunities = 0
    updated_in_db = 0
    idle_cycles = 0

    with app.app_context():
        database_uri = app.config.get("SQLALCHEMY_DATABASE_URI")
        pricing_enabled = _runtime_flag("PRICING_WORKER_ENABLED", PRICING_WORKER_ENABLED)
        ebay_enabled = _runtime_flag("EBAY_ENABLE_OFFICIAL_API", EBAY_ENABLE_OFFICIAL_API)
        ebay_client_id = _runtime_setting("EBAY_CLIENT_ID", EBAY_CLIENT_ID)
        ebay_client_secret = _runtime_setting("EBAY_CLIENT_SECRET", EBAY_CLIENT_SECRET)
        ebay_marketplace = _runtime_setting("EBAY_MARKETPLACE_ID", EBAY_MARKETPLACE_ID) or "EBAY_US"
        ebay_html_fallback = _runtime_flag(
            "PRICING_ENABLE_EBAY_HTML_FALLBACK",
            PRICING_ENABLE_EBAY_HTML_FALLBACK,
        )
        if not _log_runtime_and_should_continue(
            app_api_url=str(APP_API_URL),
            database_uri=database_uri,
            pricing_enabled=pricing_enabled,
        ):
            return
        print(f"[pricing_worker] database={_mask_database_uri(database_uri)}", flush=True)
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
        ebay_api_client.log_config_status(log=True)
        if "127.0.0.1" not in str(APP_API_URL) and "localhost" not in str(APP_API_URL) and str(database_uri).startswith("sqlite"):
            print("[pricing_worker] warning: bot is configured for online API, but this worker is reading local SQLite")
        while True:
            if _sleep_for_active_ebay_pause(once=once):
                if once:
                    break
                continue

            cycle_limit = 1 if once else PRICING_WORKER_BATCH_LIMIT
            if limit is not None:
                remaining_limit = max(0, limit - processed)
                if remaining_limit <= 0:
                    break
                cycle_limit = min(cycle_limit, remaining_limit)

            listings = fetch_pending_listing_batch(limit=cycle_limit)
            if listings:
                idle_cycles = 0
                print(
                    f"[pricing_worker] batch_start size={len(listings)} "
                    f"fresh_window_hours={PRICING_WORKER_FRESH_WINDOW_HOURS}",
                    flush=True,
                )
                for index, listing in enumerate(listings, start=1):
                    previous_checked_at = listing.pricing_checked_at
                    previous_analyzed_at = listing.pricing_analyzed_at
                    status = process_listing(listing)
                    processed += 1
                    try:
                        db.session.refresh(listing)
                    except Exception:
                        pass
                    if (
                        listing.pricing_checked_at != previous_checked_at
                        or listing.pricing_analyzed_at != previous_analyzed_at
                    ):
                        updated_in_db += 1
                    if _listing_has_pricing_data(listing):
                        data_found += 1
                    if listing.is_deal:
                        opportunities += 1
                    print(f"[pricing_worker] listing_id={listing.id} status={status}")
                    print(
                        "[pricing_worker] analysis_summary "
                        f"listings_analyzed={processed} "
                        f"with_data={data_found} "
                        f"opportunities={opportunities} "
                        f"updated_in_db={updated_in_db}",
                        flush=True,
                    )
                    if once or (limit is not None and processed >= limit):
                        break
                    if index < len(listings):
                        time.sleep(random.uniform(PRICING_WORKER_MIN_SLEEP, PRICING_WORKER_MAX_SLEEP))
            else:
                print("[pricing_worker] idle - no pending listings")
                idle_cycles += 1
                if idle_cycles == 1 or idle_cycles % 10 == 0:
                    _log_queue_snapshot()
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
