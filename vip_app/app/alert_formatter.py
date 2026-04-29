from __future__ import annotations

from datetime import datetime, timezone

from services.ebay_affiliate import build_ebay_affiliate_url


def _coerce_float(value) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _coerce_datetime(value) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        try:
            dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone()


def _relative_time(value) -> str:
    dt = _coerce_datetime(value)
    if not dt:
        return "recently"

    seconds = max(int((datetime.now().astimezone() - dt).total_seconds()), 0)
    if seconds < 60:
        return "just now"
    minutes = seconds // 60
    if minutes < 60:
        return "1 min ago" if minutes == 1 else f"{minutes} min ago"
    hours = minutes // 60
    if hours < 24:
        return "1 hour ago" if hours == 1 else f"{hours} hours ago"
    days = hours // 24
    if days == 1:
        return "yesterday"
    return f"{days} days ago"


def _confidence_from_score(score) -> str:
    value = int(round(_coerce_float(score) or 0))
    if value >= 80:
        return "High"
    if value >= 60:
        return "Medium"
    if value >= 35:
        return "Low"
    return "Low"


def _format_eur(value) -> str:
    number = _coerce_float(value)
    if number is None:
        return "Unknown"
    return f"{number:.2f} EUR"


def classify_deal_level(discount_percent, potential_profit):
    discount = _coerce_float(discount_percent) or 0.0
    profit = _coerce_float(potential_profit) or 0.0

    if discount >= 25 or profit >= 20:
        return {
            "badge": "HOT DEAL",
            "deal_level": "elite",
            "alert_title": "HOT DEAL DETECTED",
        }
    if discount >= 15 or profit >= 10:
        return {
            "badge": "EASY FLIP",
            "deal_level": "strong",
            "alert_title": "EASY FLIP",
        }
    if discount >= 10 and profit >= 5:
        return {
            "badge": "VALUE DEAL",
            "deal_level": "good",
            "alert_title": "LIVE DEAL",
        }
    return None


def format_vip_alert(deal: dict) -> dict:
    title = (deal.get("title") or deal.get("full_name") or "Unknown product").strip()
    marketplace = (deal.get("platform") or deal.get("marketplace") or "Unknown").strip()
    listing_price = _coerce_float(deal.get("listing_price"))
    market_price = _coerce_float(deal.get("market_price"))
    discount_percent = round(_coerce_float(deal.get("discount_percent")) or 0.0, 1)
    potential_profit = round(_coerce_float(deal.get("potential_profit")) or 0.0, 2)
    score = int(round(_coerce_float(deal.get("score")) or 0))
    confidence = (deal.get("confidence") or _confidence_from_score(score)).strip()
    deal_meta = classify_deal_level(discount_percent, potential_profit) or {
        "badge": "LIVE DEAL",
        "deal_level": "good",
        "alert_title": "JUST DROPPED",
    }
    relative_label = _relative_time(deal.get("detected_at"))

    return {
        "alert_title": deal_meta["alert_title"],
        "badge": deal_meta["badge"],
        "deal_level": deal_meta["deal_level"],
        "full_name": title,
        "marketplace": marketplace,
        "listing_price": listing_price,
        "listing_price_text": deal.get("listing_price_text") or _format_eur(listing_price),
        "market_price": market_price,
        "market_price_text": _format_eur(market_price),
        "discount_percent": discount_percent,
        "discount_percent_text": f"-{discount_percent:.1f}%",
        "potential_profit": potential_profit,
        "potential_profit_text": f"+{potential_profit:.2f} EUR",
        "confidence": confidence,
        "score": score,
        "relative_detection_time": relative_label,
        "detected_label": f"detected {relative_label}",
        "direct_link": build_ebay_affiliate_url(
            deal.get("direct_link") or deal.get("url") or "",
            deal.get("affiliate_source") or "vip",
            listing_id=deal.get("id") or deal.get("listing_id"),
        ),
        "image_url": deal.get("image_url"),
        "cta_primary": "Open Listing",
        "cta_secondary": "View Details",
        "cta_save": "Save",
        "push_title": f"🚨 {deal_meta['badge']}",
        "push_body": f"{title} {discount_percent:.1f}% below market",
    }
