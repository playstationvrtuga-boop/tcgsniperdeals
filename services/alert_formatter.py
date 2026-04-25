from __future__ import annotations

import random
import re
from datetime import datetime, timezone


CONDITION_PATTERNS = [
    r"\bnear mint\b",
    r"\bnm\b",
    r"\blight played\b",
    r"\blp\b",
    r"\bmoderately played\b",
    r"\bmp\b",
    r"\bheavily played\b",
    r"\bhp\b",
    r"\bdamaged\b",
    r"\bdmg\b",
    r"\benglish\b",
    r"\bjapanese\b",
    r"\bfrench\b",
    r"\bgerman\b",
    r"\bitalian\b",
    r"\bspanish\b",
    r"\bportuguese\b",
    r"\bsealed\b",
    r"\breverse holo\b",
    r"\bholo\b",
]

CARD_CODE_PATTERNS = [
    r"\b[a-z]{2,5}\d{2,4}[a-z]?\b",
    r"\b[a-z]{2,5}\s*\d{1,3}\s*/\s*\d{1,3}\b",
    r"\b\d{1,3}\s*/\s*\d{1,3}\b",
]

GENERIC_FALLBACK = "Premium Pokemon card spotted"
TELEGRAM_FREE_TIMING_VARIANTS = (
    ("Caught", "⚡"),
    ("Spotted", "👀"),
    ("Detected", "🚀"),
    ("Found", "🎯"),
    ("Gotcha", "⚡"),
)
GONE_ALERT_VARIANTS = (
    (
        "⚠️ GONE ALERT",
        [
            "📦 {title}",
            "🛒 {platform}",
            "💰 Last seen at {price}",
            "🕒 Went unavailable {time}",
            "",
            "This one disappeared fast.",
            "",
            "Want the next one before it disappears?",
            "Tap the button below to get VIP access.",
        ],
    ),
    (
        "⚠️ GONE ALERT",
        [
            "📦 {title}",
            "💰 {price}",
            "🕒 No longer available {time}",
            "📍 {platform}",
            "",
            "A clean FOMO signal from the live stream.",
            "",
            "VIP users see fresh listings first.",
            "Tap the button below to open the app.",
        ],
    ),
    (
        "⚠️ GONE ALERT",
        [
            "📦 {title}",
            "🛒 {platform}",
            "💰 Last seen at {price}",
            "🕒 Gone {time}",
            "",
            "That one moved quickly.",
            "",
            "Catch the next live opportunity inside VIP.",
            "Tap below to join.",
        ],
    ),
)


def _clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", (value or "").strip())


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


def _get_value(data, *keys, default=None):
    if isinstance(data, dict):
        for key in keys:
            value = data.get(key)
            if value is not None and value != "":
                return value
        return default

    for key in keys:
        value = getattr(data, key, None)
        if value is not None and value != "":
            return value
    return default


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


def _pretty_platform(value: str) -> str:
    text = _clean_text(value)
    lowered = text.lower()
    if lowered == "ebay":
        return "eBay"
    if lowered == "vinted":
        return "Vinted"
    if not text:
        return "Unknown"
    return text


def _format_listing_price_for_telegram(value) -> str:
    text = _clean_text(str(value or ""))
    if not text:
        return "Not available"
    if "€" in text or "EUR" in text.upper() or "$" in text:
        return text
    return f"€{text}"


def _truncate_title(value: str, max_length: int = 180) -> str:
    text = _clean_text(value)
    if len(text) <= max_length:
        return text
    trimmed = text[: max_length - 1].rsplit(" ", 1)[0].strip()
    return f"{trimmed or text[: max_length - 1].strip()}…"


def listing_age_details(listing, now: datetime | None = None) -> dict:
    detected_at = _get_value(listing, "detected_at")
    created_at = _get_value(listing, "created_at")
    timestamp = _coerce_datetime(detected_at) or _coerce_datetime(created_at)
    source = "detected_at" if _coerce_datetime(detected_at) else ("created_at" if timestamp else "missing")

    if not timestamp:
        return {
            "age_text": "just now",
            "age_seconds": None,
            "source": source,
            "used_created_at_fallback": False,
        }

    current = now.astimezone() if isinstance(now, datetime) else datetime.now().astimezone()
    seconds = max(int((current - timestamp).total_seconds()), 0)
    if seconds < 60:
        age_text = f"{seconds}s"
    elif seconds < 120:
        age_text = "1m"
    else:
        age_text = f"{seconds // 60}m"

    return {
        "age_text": age_text,
        "age_seconds": seconds,
        "source": source,
        "used_created_at_fallback": source == "created_at",
    }


def format_listing_age(listing, now: datetime | None = None) -> str:
    details = listing_age_details(listing, now=now)
    label, icon = random.choice(TELEGRAM_FREE_TIMING_VARIANTS)
    age_text = details["age_text"]
    if age_text == "just now":
        return f"{label} just now {icon}"
    return f"{label} {age_text} ago {icon}"


def format_telegram_listing_message(listing: dict, *, now: datetime | None = None, return_meta: bool = False):
    title = _truncate_title(
        str(_get_value(listing, "title", "titulo", "full_name", default=GENERIC_FALLBACK)),
    )
    source = _pretty_platform(_get_value(listing, "source", "platform", "marketplace", default=""))
    source_label = source if source != "Unknown" else "Marketplace"
    price = _format_listing_price_for_telegram(_get_value(listing, "price", "preco", "listing_price_text", "price_display"))
    seller_rating = _clean_text(str(_get_value(listing, "seller_rating", default="")))
    url = _clean_text(str(_get_value(listing, "url", "share_link", "public_link", "direct_link", "link", default="")))
    timing_line = format_listing_age(listing, now=now)
    age_meta = listing_age_details(listing, now=now)

    lines = [
        "-----",
        "🔥 Pokemon Sniper Deals",
        timing_line,
        "-----",
        "",
        "🎴 Pokémon TCG",
        f"🛒 {source_label}",
        "",
        title,
        "",
        f"💰 Price: {price}",
    ]
    if seller_rating:
        lines.append(f"📊 Seller rating: {seller_rating}")

    if url:
        lines.extend(["", "🔗 View listing:", url])

    lines.extend(["", "", "━━━━━━━━━━━━━━━━━━━━━━━", "", ""])
    message = "\n".join(lines)
    if return_meta:
        return message, age_meta
    return message


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


def make_partial_product_name(full_name: str) -> str:
    text = _clean_text(full_name)
    if not text:
        return GENERIC_FALLBACK

    lowered = text.lower()
    if "etb" in lowered or "elite trainer box" in lowered:
        cleaned = re.sub(r"\betb\b|\belite trainer box\b", "", text, flags=re.IGNORECASE)
        cleaned = re.sub(r"\bpokemon\b", "", cleaned, flags=re.IGNORECASE)
        cleaned = _clean_text(cleaned)
        if cleaned:
            words = cleaned.split()[:3]
            return f"Pokemon ETB ({' '.join(words)})"
        return "Pokemon ETB (sealed product)"

    softened = text
    for pattern in CONDITION_PATTERNS:
        softened = re.sub(pattern, "", softened, flags=re.IGNORECASE)
    for pattern in CARD_CODE_PATTERNS:
        softened = re.sub(pattern, "", softened, flags=re.IGNORECASE)

    softened = re.sub(r"[()\\[\\]#|]", " ", softened)
    softened = _clean_text(softened)
    softened = re.sub(
        r"\b(?:special illustration rare|illustration rare|special art rare|full art|alt art|promo)\b",
        "premium version",
        softened,
        flags=re.IGNORECASE,
    )
    softened = _clean_text(softened)

    if not softened:
        return GENERIC_FALLBACK

    tokens = softened.split()
    if len(tokens) >= 2:
        base = " ".join(tokens[:3])
        if re.search(r"\b(ex|gx|vmax|vstar)\b", base, flags=re.IGNORECASE):
            return f"{base} (special edition)"
        return f"{base} (premium version)"

    return GENERIC_FALLBACK


def format_vip_alert(deal: dict) -> dict:
    title = _clean_text(deal.get("title") or deal.get("full_name") or "Unknown product")
    marketplace = _clean_text(deal.get("platform") or deal.get("marketplace") or "Unknown")
    listing_price = _coerce_float(deal.get("listing_price"))
    market_price = _coerce_float(deal.get("market_price"))
    discount_percent = round(_coerce_float(deal.get("discount_percent")) or 0.0, 1)
    potential_profit = round(_coerce_float(deal.get("potential_profit")) or 0.0, 2)
    score = int(round(_coerce_float(deal.get("score")) or 0))
    confidence = _clean_text(deal.get("confidence") or _confidence_from_score(score))
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
        "direct_link": deal.get("direct_link") or deal.get("url") or "",
        "image_url": deal.get("image_url"),
        "cta_primary": "Open Listing",
        "cta_secondary": "View Details",
        "cta_save": "Save",
        "push_title": f"🚨 {deal_meta['badge']}",
        "push_body": f"{title} {discount_percent:.1f}% below market",
    }


def format_free_alert_text(deal: dict) -> str:
    title = _clean_text(deal.get("title") or deal.get("full_name") or deal.get("partial_title") or "")
    if not title:
        title = GENERIC_FALLBACK

    platform = _pretty_platform(deal.get("platform") or deal.get("marketplace"))
    listing_price = deal.get("listing_price_text") or _format_eur(deal.get("listing_price"))
    direct_link = _clean_text(
        deal.get("share_link")
        or deal.get("public_link")
        or deal.get("direct_link")
        or deal.get("url")
        or ""
    )
    tcg_label = _clean_text(deal.get("tcg_label") or deal.get("tcg_type") or "Pokemon TCG")

    body_lines = [
        tcg_label,
        platform,
        "",
        title,
        f"Listing Price: {listing_price}",
    ]

    if direct_link:
        body_lines.extend(["", direct_link])

    return "\n".join(body_lines)


def format_free_gone_alert_text(deal: dict, *, variant: int = 0) -> str:
    title = _clean_text(deal.get("title") or deal.get("full_name") or deal.get("partial_title") or "")
    if not title:
        title = GENERIC_FALLBACK

    platform = _pretty_platform(deal.get("platform") or deal.get("marketplace"))
    price = deal.get("listing_price_text") or _format_eur(deal.get("listing_price"))
    relative_label = _relative_time(deal.get("unavailable_at") or deal.get("updated_at") or deal.get("detected_at"))
    variant_index = variant % len(GONE_ALERT_VARIANTS)
    headline, lines = GONE_ALERT_VARIANTS[variant_index]

    rendered = [headline]
    for line in lines:
        rendered.append(
            line.format(
                title=title,
                platform=platform,
                price=price,
                time=relative_label,
            )
        )

    return "\n".join(rendered)
def prepare_free_preview_image(image_path: str) -> str:
    return image_path
