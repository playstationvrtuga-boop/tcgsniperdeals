import json
from datetime import datetime, timezone
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from flask import Blueprint, current_app, jsonify, request

from .extensions import db
from .models import Listing
api_bp = Blueprint("api", __name__)


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
        badge_label=str(pick_first(payload, "badge_label", default="Strong")).strip() or "Strong",
        score_label=str(pick_first(payload, "score_label", default="")).strip() or None,
        score=score_value,
        category=str(pick_first(payload, "category", default="")).strip() or None,
        tcg_type=str(pick_first(payload, "tcg_type", default="pokemon")).strip() or "pokemon",
        available_status=str(pick_first(payload, "available_status", default="available")).strip() or "available",
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

        return api_response("inserted", 201, id=listing.id, push={"sent": 0, "enabled": False})
    except Exception as error:
        db.session.rollback()
        current_app.logger.exception("Failed to insert incoming listing")
        return api_response("server_error", 500, message=str(error))
