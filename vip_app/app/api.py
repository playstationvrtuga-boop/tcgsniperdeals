import json
import unicodedata
from datetime import datetime, timezone
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from flask import Blueprint, current_app, jsonify, request
from flask_login import current_user

from services.ebay_api_client import ebay_api_client
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
        "ebay": "eBay",
        "vinted": "Vinted",
        "olx": "OLX",
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

    detected_at = parse_datetime(pick_first(payload, "detected_at", "posted_at"))
    source_published_at = parse_datetime(payload.get("source_published_at"), fallback=None) if payload.get("source_published_at") else None
    score_value = pick_first(payload, "score")
    try:
        score_value = float(score_value) if score_value is not None else None
    except (TypeError, ValueError):
        score_value = None

    listing = Listing(
        source=source,
        external_id=external_id,
        external_url=external_url,
        normalized_url=normalized_url or external_url,
        image_url=str(payload.get("image_url") or "").strip() or None,
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
        discount_percent=None,
        gross_margin=None,
        pricing_score=None,
        is_deal=False,
        deal_alert_sent_at=None,
        detected_at=detected_at,
        posted_at=detected_at,
        source_published_at=source_published_at,
        raw_payload=json.dumps(payload, ensure_ascii=False),
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
            return api_response("duplicate", 200, id=existing.id, url=existing.external_url)

        db.session.add(listing)
        db.session.commit()
        invalidate("feed:")

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
        if payload.get("source_published_at"):
            listing.source_published_at = parse_datetime(payload.get("source_published_at"), fallback=listing.source_published_at)
        if payload.get("detected_at"):
            listing.detected_at = parse_datetime(payload.get("detected_at"), fallback=listing.detected_at)

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
