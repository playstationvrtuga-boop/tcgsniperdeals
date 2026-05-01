import json
import unicodedata
from datetime import datetime, timezone
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from flask import Blueprint, current_app, jsonify, request
from flask_login import current_user

from services.pokemon_title_parser import detect_card_language, detect_pokemon_set
from services.ebay_api_client import ebay_api_client
from services.image_urls import high_resolution_listing_image_url
from .extensions import db
from .feed_cache import invalidate
from .models import Listing
api_bp = Blueprint("api", __name__)

GONE_STATUSES = {"deleted", "expired", "removed", "reserved", "sold", "unavailable"}


TRACKING_QUERY_KEYS = {
    "_branch_match_id",
    "_branch_referrer",
    "fbclid",
    "gclid",
    "igshid",
    "mc_cid",
    "mc_eid",
    "mkevt",
    "mkcid",
    "mkrid",
    "mkloc",
    "mkrid",
    "msclkid",
    "si",
}


def api_response(status, http_status, **extra):
    payload = {"status": status}
    payload.update(extra)
    return jsonify(payload), http_status


def parse_datetime(value, fallback=None):
    if not value:
        return fallback or datetime.now(timezone.utc)

    if isinstance(value, datetime):
        parsed = value
    else:
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return fallback or datetime.now(timezone.utc)

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def normalize_listing_url(url):
    value = str(url or "").strip()
    if not value:
        return ""

    parsed = urlsplit(value)
    scheme = (parsed.scheme or "https").lower()
    netloc = parsed.netloc.lower()
    path = parsed.path.rstrip("/") or "/"

    filtered_query = []
    for key, query_value in parse_qsl(parsed.query, keep_blank_values=True):
        lowered = key.lower()
        if lowered.startswith("utm_") or lowered in TRACKING_QUERY_KEYS:
            continue
        filtered_query.append((key, query_value))

    query = urlencode(filtered_query, doseq=True)
    return urlunsplit((scheme, netloc, path, query, ""))


def normalize_platform(value):
    raw = str(value or "").strip().lower()
    mapping = {
        "ebay": "ebay",
        "vinted": "Vinted",
        "olx": "OLX",
        "wallapop": "Wallapop",
    }
    return mapping.get(raw, str(value or "").strip() or "Unknown")


def normalize_source(value, platform):
    raw = str(value or "").strip().lower()
    if raw:
        return raw
    return normalize_platform(platform).lower().replace(" ", "_")


def _plain_token(value):
    raw = str(value or "").strip().lower().replace("_", "-")
    return "".join(
        char for char in unicodedata.normalize("NFKD", raw)
        if not unicodedata.combining(char)
    )


def normalize_available_status(value):
    raw = _plain_token(value)
    if not raw:
        return "available"

    mapping = {
        "active": "available",
        "ativo": "available",
        "ativa": "available",
        "available": "available",
        "disponivel": "available",
        "live": "available",
        "sold": "sold",
        "vendida": "sold",
        "vendido": "sold",
        "deleted": "removed",
        "eliminada": "removed",
        "eliminado": "removed",
        "apagada": "removed",
        "apagado": "removed",
        "removed": "removed",
        "removida": "removed",
        "removido": "removed",
        "esgotada": "unavailable",
        "esgotado": "unavailable",
        "indisponivel": "unavailable",
        "not-available": "unavailable",
        "out-of-stock": "unavailable",
        "unavailable": "unavailable",
        "reservada": "reserved",
        "reservado": "reserved",
        "reserved": "reserved",
    }
    return mapping.get(raw, raw)


def pick_first(payload, *keys, default=None):
    for key in keys:
        value = payload.get(key)
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        return value
    return default


def check_api_key():
    supplied = request.headers.get("X-API-Key", "")
    expected = current_app.config["BOT_API_KEY"]
    return bool(expected and supplied and supplied == expected)


def check_debug_access():
    return check_api_key() or bool(getattr(current_user, "is_authenticated", False) and getattr(current_user, "is_admin", False))


def _iso_datetime(value):
    if not value:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.isoformat()


def _listing_debug_payload(listing):
    return {
        "id": listing.id,
        "external_id": listing.external_id,
        "platform": listing.platform,
        "pricing_status": listing.pricing_status,
        "detected_at": _iso_datetime(listing.detected_at),
        "pricing_checked_at": _iso_datetime(listing.pricing_checked_at),
        "pricing_analyzed_at": _iso_datetime(listing.pricing_analyzed_at),
        "score_level": listing.score_level,
        "estimated_profit": listing.estimated_profit,
        "discount_percent": listing.discount_percent,
        "pricing_error": listing.pricing_error,
        "title": listing.title,
    }


def _age_seconds(value):
    if not value:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return max(0, int((datetime.now(timezone.utc) - value).total_seconds()))


def build_listing_from_payload(payload):
    title = str(pick_first(payload, "title", default="")).strip()
    price_display = str(pick_first(payload, "price_display", "price", default="")).strip()
    external_url = str(pick_first(payload, "external_url", "url", default="")).strip()
    platform = normalize_platform(pick_first(payload, "platform", "source", default=""))
    source = normalize_source(pick_first(payload, "source", default=""), platform)

    missing = []
    if not title:
        missing.append("title")
    if not price_display:
        missing.append("price")
    if not external_url:
        missing.append("url")
    if not platform or platform == "Unknown":
        missing.append("platform")

    if missing:
        return None, missing, None

    normalized_url = normalize_listing_url(external_url)
    external_id = Listing.derive_external_id(source, normalized_url or external_url, pick_first(payload, "external_id"))

    existing = (
        Listing.query.filter(
            (Listing.normalized_url == normalized_url)
            | ((Listing.source == source) & (Listing.external_id == external_id))
        )
        .order_by(Listing.id.desc())
        .first()
    )
    if existing:
        return None, None, existing

    detected_at = parse_datetime(payload.get("detected_at"))
    score_value = pick_first(payload, "score")
    try:
        score_value = float(score_value) if score_value is not None else None
    except (TypeError, ValueError):
        score_value = None
    raw_payload = dict(payload)
    for timestamp_key in ("posted_at", "created_at", "source_published_at"):
        raw_payload.pop(timestamp_key, None)
    card_language = detect_card_language(
        title,
        description=str(payload.get("description") or payload.get("body") or ""),
        marketplace=platform,
    )
    set_info = detect_pokemon_set(title, description=str(payload.get("description") or payload.get("body") or ""))
    current_app.logger.info("[LANG_DETECT] listing_id=new language=%s", card_language)
    current_app.logger.info(
        "[SET_DETECT] listing_id=new set_code=%s set_name=%s confidence=%s",
        set_info.get("set_code") or "unknown",
        set_info.get("set_name") or "unknown",
        set_info.get("confidence") or "unknown",
    )

    image_url = high_resolution_listing_image_url(str(payload.get("image_url") or "").strip())

    listing = Listing(
        source=source,
        external_id=external_id,
        external_url=external_url,
        normalized_url=normalized_url or external_url,
        image_url=image_url or None,
        title=title,
        price_display=price_display,
        platform=platform,
        badge_label=str(pick_first(payload, "badge_label", default="Fresh")).strip() or "Fresh",
        score_label=str(pick_first(payload, "score_label", default="")).strip() or None,
        score=score_value,
        category=str(pick_first(payload, "category", default="")).strip() or None,
        tcg_type=str(pick_first(payload, "tcg_type", default="pokemon")).strip() or "pokemon",
        available_status=normalize_available_status(pick_first(payload, "available_status", "status", default="available")),
        status=normalize_available_status(pick_first(payload, "available_status", "status", default="available")),
        pricing_status="pending",
        pricing_error=None,
        reference_price=None,
        market_buy_now_min=None,
        market_buy_now_avg=None,
        market_buy_now_median=None,
        last_sold_prices_json=None,
        last_2_sales_json=None,
        sold_avg_price=None,
        sold_median_price=None,
        estimated_fair_value=None,
        pricing_basis=None,
        confidence_score=None,
        listing_type=None,
        card_language=card_language,
        set_code=set_info.get("set_code"),
        set_name=set_info.get("set_name"),
        discount_percent=None,
        gross_margin=None,
        pricing_score=None,
        is_deal=False,
        deal_alert_sent_at=None,
        detected_at=detected_at,
        raw_payload=json.dumps(raw_payload, ensure_ascii=False),
    )
    current_app.logger.debug(
        "[listing-ingest] timestamp_source=detected_at external_id=%s detected_at=%s",
        external_id,
        listing.detected_at.isoformat() if listing.detected_at else None,
    )
    return listing, None, None


def find_listing_for_status_update(payload):
    source = str(pick_first(payload, "source", default="")).strip().lower()
    external_id = str(pick_first(payload, "external_id", "listing_id", default="")).strip()
    normalized_url = normalize_listing_url(pick_first(payload, "external_url", "url", default=""))

    query = Listing.query
    if source and external_id:
        query = query.filter(Listing.source == source, Listing.external_id == external_id)
    elif normalized_url:
        query = query.filter(Listing.normalized_url == normalized_url)
    else:
        return None

    return query.order_by(Listing.id.desc()).first()


def serialize_listing(listing):
    return {
        "id": listing.id,
        "source": listing.source,
        "external_id": listing.external_id,
        "platform": listing.platform,
        "title": listing.title,
        "price": listing.price_display,
        "url": listing.external_url,
        "image_url": listing.image_url,
        "detected_at": listing.detected_at_iso,
        "created_at": listing.created_at.isoformat() if listing.created_at else None,
        "status": listing.status,
        "available_status": listing.available_status,
    }


def refresh_existing_ebay_listing(existing, payload):
    if (existing.source or "").strip().lower() != "ebay":
        return False

    title = str(pick_first(payload, "title", default=existing.title or "")).strip()
    price_display = str(pick_first(payload, "price_display", "price", default=existing.price_display or "")).strip()
    external_url = str(pick_first(payload, "external_url", "url", default=existing.external_url or "")).strip()
    image_url = high_resolution_listing_image_url(str(payload.get("image_url") or "").strip())

    existing.source = "ebay"
    existing.platform = "ebay"
    existing.status = normalize_available_status(pick_first(payload, "available_status", "status", default="available"))
    existing.available_status = existing.status
    if title:
        existing.title = title
    if price_display:
        existing.price_display = price_display
    if external_url:
        existing.external_url = external_url
        existing.normalized_url = normalize_listing_url(external_url) or external_url
    if image_url:
        existing.image_url = image_url

    raw_payload = dict(payload)
    for timestamp_key in ("posted_at", "created_at", "source_published_at"):
        raw_payload.pop(timestamp_key, None)
    existing.raw_payload = json.dumps(raw_payload, ensure_ascii=False)
    return True


@api_bp.route("/listings", methods=["GET"])
def list_listings():
    if not check_debug_access():
        return api_response("unauthorized", 401, message="Admin login or X-API-Key required.")

    query = Listing.query
    external_id = (request.args.get("external_id") or "").strip()
    platform = (request.args.get("platform") or "").strip().lower()
    if external_id:
        query = query.filter(Listing.external_id == external_id)
    if platform:
        query = query.filter(db.func.lower(Listing.platform) == platform)

    try:
        limit = min(max(int(request.args.get("limit", 20)), 1), 100)
    except (TypeError, ValueError):
        limit = 20
    try:
        page = max(int(request.args.get("page", 1)), 1)
    except (TypeError, ValueError):
        page = 1

    listings = query.order_by(Listing.detected_at.desc(), Listing.id.desc()).offset((page - 1) * limit).limit(limit).all()
    if platform == "ebay":
        newest = listings[0] if listings else None
        current_app.logger.info(
            "[EBAY_API_LISTINGS_GET] count=%s newest_id=%s newest_detected_at=%s",
            len(listings),
            newest.external_id if newest else None,
            newest.detected_at_iso if newest else None,
        )
    return jsonify(
        {
            "status": "ok",
            "count": len(listings),
            "page": page,
            "limit": limit,
            "listings": [serialize_listing(listing) for listing in listings],
        }
    )


@api_bp.route("/listings", methods=["POST"])
def create_listing():
    if not check_api_key():
        return api_response("unauthorized", 401, message="Invalid API key.")

    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return api_response("validation_error", 400, message="Invalid JSON payload.")

    try:
        listing, missing_fields, existing = build_listing_from_payload(payload)
        if missing_fields:
            return api_response("validation_error", 400, message=f"Missing fields: {', '.join(missing_fields)}")

        if existing:
            if refresh_existing_ebay_listing(existing, payload):
                db.session.commit()
                invalidate("feed:")
                current_app.logger.info(
                    "[EBAY_FEED_CACHE_INVALIDATED] id=%s status=duplicate",
                    existing.external_id,
                )
                current_app.logger.info(
                    "[APP_FEED_VISIBLE] id=%s app_listing_id=%s source=%s status=duplicate refreshed=true",
                    existing.external_id,
                    existing.id,
                    existing.source,
                )
            return api_response("duplicate", 200, id=existing.id, url=existing.external_url)

        db.session.add(listing)
        db.session.commit()
        invalidate("feed:")
        if (listing.source or "").strip().lower() == "ebay":
            current_app.logger.info(
                "[EBAY_FEED_CACHE_INVALIDATED] id=%s status=inserted",
                listing.external_id,
            )
        current_app.logger.debug(
            "[listing-inserted] timestamp_source=detected_at id=%s detected_at=%s",
            listing.id,
            listing.detected_at.isoformat() if listing.detected_at else None,
        )
        current_app.logger.info(
            "[APP_FEED_VISIBLE] id=%s app_listing_id=%s source=%s",
            listing.external_id,
            listing.id,
            listing.source,
        )

        return api_response("inserted", 201, id=listing.id, push={"sent": 0, "enabled": False})
    except Exception as error:
        db.session.rollback()
        current_app.logger.exception("Failed to insert incoming listing")
        return api_response("server_error", 500, message=str(error))


@api_bp.route("/listings/status", methods=["POST"])
def update_listing_status():
    if not check_api_key():
        return api_response("unauthorized", 401, message="Invalid API key.")

    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return api_response("validation_error", 400, message="Invalid JSON payload.")

    status = normalize_available_status(pick_first(payload, "available_status", "status", default=""))
    if not status:
        return api_response("validation_error", 400, message="Missing fields: available_status")

    try:
        listing = find_listing_for_status_update(payload)
        if not listing:
            return api_response("not_found", 404, message="Listing not found.")

        old_status = (listing.available_status or "").strip().lower()
        listing.available_status = status
        listing.status = status
        listing.status_updated_at = datetime.now(timezone.utc)
        if status in GONE_STATUSES:
            gone_at = parse_datetime(payload.get("gone_detected_at") or payload.get("status_updated_at"), fallback=listing.status_updated_at)
            listing.gone_detected_at = listing.gone_detected_at or gone_at
            if listing.detected_at and listing.gone_detected_at and listing.sold_after_seconds is None:
                detected_at = listing.detected_at
                gone_detected_at = listing.gone_detected_at
                if detected_at.tzinfo is None:
                    detected_at = detected_at.replace(tzinfo=timezone.utc)
                if gone_detected_at.tzinfo is None:
                    gone_detected_at = gone_detected_at.replace(tzinfo=timezone.utc)
                listing.sold_after_seconds = max(int((gone_detected_at - detected_at).total_seconds()), 0)
        db.session.commit()
        if old_status != status:
            invalidate("feed:")

        return api_response(
            "updated",
            200,
            id=listing.id,
            available_status=listing.available_status,
        )
    except Exception as error:
        db.session.rollback()
        current_app.logger.exception("Failed to update listing availability")
        return api_response("server_error", 500, message=str(error))


@api_bp.route("/debug/ebay", methods=["GET"])
def debug_ebay_api():
    if not check_debug_access():
        return api_response("unauthorized", 401, message="Admin login or X-API-Key required.")

    result = ebay_api_client.startup_check(query=request.args.get("q", "pokemon"), limit=20, log=False)
    return jsonify(
        {
            "enabled": result["enabled"],
            "keys_present": result["keys_present"],
            "environment": result["environment"],
            "marketplace": result["marketplace"],
            "token_status": result["token_status"],
            "search_status": result["search_status"],
            "results_count": result["results_count"],
            "sample_items": result["sample_items"],
            "error": result["error"],
        }
    )


@api_bp.route("/debug/pricing", methods=["GET"])
def debug_pricing():
    if not check_debug_access():
        return api_response("unauthorized", 401, message="Admin login or X-API-Key required.")

    pricing_status = db.func.lower(db.func.coalesce(Listing.pricing_status, "pending"))
    status_rows = (
        db.session.query(pricing_status, db.func.count(Listing.id))
        .group_by(pricing_status)
        .order_by(db.func.count(Listing.id).desc())
        .all()
    )
    latest_detected = Listing.query.order_by(Listing.detected_at.desc(), Listing.id.desc()).limit(10).all()
    latest_analyzed = (
        Listing.query.filter(Listing.pricing_analyzed_at.isnot(None))
        .order_by(Listing.pricing_analyzed_at.desc(), Listing.id.desc())
        .limit(10)
        .all()
    )
    latest_checked_at = db.session.query(db.func.max(Listing.pricing_checked_at)).scalar()
    latest_analyzed_activity_at = db.session.query(db.func.max(Listing.pricing_analyzed_at)).scalar()
    latest_worker_activity_at = max(
        [value for value in (latest_checked_at, latest_analyzed_activity_at) if value],
        default=None,
    )
    latest_analyzed_at = latest_analyzed[0].pricing_analyzed_at if latest_analyzed else None

    return jsonify(
        {
            "status": "ok",
            "status_counts": {str(status or "pending"): int(count or 0) for status, count in status_rows},
            "latest_detected": [_listing_debug_payload(listing) for listing in latest_detected],
            "latest_analyzed": [_listing_debug_payload(listing) for listing in latest_analyzed],
            "latest_analyzed_age_seconds": _age_seconds(latest_analyzed_at),
            "latest_worker_activity_at": _iso_datetime(latest_worker_activity_at),
            "latest_worker_activity_age_seconds": _age_seconds(latest_worker_activity_at),
        }
    )
