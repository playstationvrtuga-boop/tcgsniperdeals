from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from html import unescape
from typing import Iterable
from urllib.parse import urljoin

import requests
from sqlalchemy import func

from services.deal_detector import classify_listing_type, is_comparable_listing
from services.pokemon_title_parser import extract_card_signals, normalize_title
from vip_app.app.extensions import db
from vip_app.app.models import CardmarketTrend, Listing, utcnow


TREND_CATEGORIES = ("best_sellers", "best_bargains")
DEFAULT_SOURCE_URL = "https://www.cardmarket.com/en/Pokemon"
DEFAULT_USER_AGENT = "TCGSniperDealsBot/1.0"


@dataclass(frozen=True)
class ParsedTrend:
    category: str
    rank: int
    product_name: str
    expansion: str | None = None
    card_number: str | None = None
    price: float | None = None
    currency: str = "EUR"
    image_url: str | None = None
    product_url: str | None = None
    source_url: str = DEFAULT_SOURCE_URL
    raw_payload: dict | None = None


def _clean_text(value: str) -> str:
    text = re.sub(r"<[^>]+>", " ", value or "")
    text = unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _parse_price(value: str) -> tuple[float | None, str]:
    match = re.search(r"(\d{1,6}(?:[.,]\d{2}))\s*(€|EUR)", value or "", flags=re.IGNORECASE)
    if not match:
        return None, "EUR"
    amount = float(match.group(1).replace(".", "").replace(",", "."))
    return amount, "EUR"


def _split_name_metadata(name: str) -> tuple[str, str | None, str | None]:
    cleaned = _clean_text(name)
    match = re.search(r"^(.*?)\s*\(([^)]*)\)\s*$", cleaned)
    if not match:
        signals = extract_card_signals(cleaned)
        return cleaned, signals.set_code or signals.set_name, signals.full_number or signals.card_number

    product_name = match.group(1).strip()
    metadata = match.group(2).strip()
    signals = extract_card_signals(f"{product_name} {metadata}")
    expansion = signals.set_code or signals.set_name
    card_number = signals.full_number or signals.card_number
    if not expansion and metadata:
        expansion_match = re.search(r"\b([A-Z0-9]{2,6})\b", metadata)
        expansion = expansion_match.group(1) if expansion_match else metadata
    if not card_number:
        number_match = re.search(r"\b\d{1,3}(?:/\d{1,3})?\b", metadata)
        card_number = number_match.group(0) if number_match else None
    return product_name, expansion, card_number


def _section_html(html: str, heading: str) -> str:
    pattern = re.compile(re.escape(heading), re.IGNORECASE)
    match = pattern.search(html or "")
    if not match:
        return ""
    start = match.start()
    next_match = re.search(r"Best\s+(?:Sellers|Bargains)", html[match.end():], flags=re.IGNORECASE)
    end = match.end() + next_match.start() if next_match else len(html)
    return html[start:end]


def _extract_image_near(section: str, start_index: int) -> str | None:
    before = section[max(0, start_index - 1800):start_index]
    image_matches = list(re.finditer(r"<img[^>]+(?:src|data-src)=[\"']([^\"']+)[\"']", before, flags=re.IGNORECASE))
    if image_matches:
        return image_matches[-1].group(1)
    return None


def parse_cardmarket_trends(html: str, *, source_url: str = DEFAULT_SOURCE_URL, max_items: int = 20) -> list[ParsedTrend]:
    trends: list[ParsedTrend] = []
    category_headings = {
        "best_sellers": "Best Sellers",
        "best_bargains": "Best Bargains",
    }

    for category, heading in category_headings.items():
        section = _section_html(html, heading)
        if not section:
            continue

        seen_names: set[str] = set()
        rank = 1
        for anchor in re.finditer(r"<a\b[^>]*href=[\"']([^\"']+)[\"'][^>]*>(.*?)</a>", section, flags=re.IGNORECASE | re.DOTALL):
            href = anchor.group(1)
            label = _clean_text(anchor.group(2))
            if not label or label.lower() in {"view all", "all"}:
                continue
            if not re.search(r"\b[A-Za-z0-9]{2,}\b", label):
                continue
            if label.lower() in seen_names:
                continue

            nearby = section[anchor.start(): anchor.end() + 650]
            price, currency = _parse_price(nearby)
            product_name, expansion, card_number = _split_name_metadata(label)
            image_url = _extract_image_near(section, anchor.start())
            trends.append(
                ParsedTrend(
                    category=category,
                    rank=rank,
                    product_name=product_name,
                    expansion=expansion,
                    card_number=card_number,
                    price=price,
                    currency=currency,
                    image_url=urljoin(source_url, image_url) if image_url else None,
                    product_url=urljoin(source_url, href),
                    source_url=source_url,
                    raw_payload={
                        "label": label,
                        "href": href,
                        "price_text": _clean_text(nearby),
                    },
                )
            )
            seen_names.add(label.lower())
            rank += 1
            if rank > max_items:
                break

    return trends


def fetch_cardmarket_trends(
    *,
    source_url: str = DEFAULT_SOURCE_URL,
    timeout_seconds: float = 20,
    user_agent: str = DEFAULT_USER_AGENT,
    max_items: int = 20,
) -> list[ParsedTrend]:
    headers = {"User-Agent": user_agent, "Accept": "text/html,application/xhtml+xml"}
    response = requests.get(source_url, headers=headers, timeout=timeout_seconds)
    if response.status_code in {401, 403, 429}:
        raise PermissionError(f"cardmarket_blocked status={response.status_code}")
    response.raise_for_status()
    print("[ai_market_intel] CARDMARKET_TRENDS_FETCH_OK", flush=True)
    trends = parse_cardmarket_trends(response.text, source_url=source_url, max_items=max_items)
    if not trends:
        raise RuntimeError("no Cardmarket trend rows parsed")
    print(f"[ai_market_intel] CARDMARKET_TRENDS_PARSE_OK count={len(trends)}", flush=True)
    return trends


def latest_snapshot_time() -> datetime | None:
    return db.session.query(func.max(CardmarketTrend.collected_at)).scalar()


def latest_trends() -> list[CardmarketTrend]:
    last_updated = latest_snapshot_time()
    if not last_updated:
        return []
    return (
        CardmarketTrend.query.filter(CardmarketTrend.collected_at == last_updated)
        .order_by(CardmarketTrend.category.asc(), CardmarketTrend.rank.asc())
        .all()
    )


def save_trends_snapshot(trends: Iterable[ParsedTrend], *, collected_at: datetime | None = None) -> int:
    moment = collected_at or utcnow()
    day_start = moment.replace(hour=0, minute=0, second=0, microsecond=0)
    day_end = day_start + timedelta(days=1)
    trend_items = list(trends)
    if not trend_items:
        return 0

    categories = sorted({item.category for item in trend_items})
    CardmarketTrend.query.filter(
        CardmarketTrend.category.in_(categories),
        CardmarketTrend.collected_at >= day_start,
        CardmarketTrend.collected_at < day_end,
    ).delete(synchronize_session=False)

    for item in trend_items:
        db.session.add(
            CardmarketTrend(
                category=item.category,
                rank=item.rank,
                product_name=item.product_name,
                expansion=item.expansion,
                card_number=item.card_number,
                price=item.price,
                currency=item.currency or "EUR",
                image_url=item.image_url,
                product_url=item.product_url,
                source_url=item.source_url,
                collected_at=moment,
                raw_payload_json=json.dumps(item.raw_payload or {}, ensure_ascii=False),
            )
        )
    db.session.commit()
    print(f"[ai_market_intel] CARDMARKET_TRENDS_SAVED count={len(trend_items)}", flush=True)
    return len(trend_items)


def should_collect(interval_hours: int = 24) -> bool:
    last_updated = latest_snapshot_time()
    if not last_updated:
        return True
    if last_updated.tzinfo is None:
        last_updated = last_updated.replace(tzinfo=timezone.utc)
    return utcnow() - last_updated >= timedelta(hours=max(interval_hours, 1))


def _trend_identity_text(trend: CardmarketTrend) -> str:
    return " ".join(value for value in (trend.product_name, trend.expansion, trend.card_number) if value)


def _listing_identity_text(listing: Listing) -> str:
    return " ".join(value for value in (listing.title, listing.listing_type) if value)


def trend_matches_listing(trend: CardmarketTrend, listing: Listing) -> bool:
    original_type = listing.listing_type or classify_listing_type(listing.title)
    trend_type = classify_listing_type(_trend_identity_text(trend))
    comparable, _reason = is_comparable_listing(
        listing.title,
        _trend_identity_text(trend),
        original_type,
        listing_kind=trend_type,
    )
    if not comparable:
        return False

    listing_signals = extract_card_signals(listing.title)
    trend_signals = extract_card_signals(_trend_identity_text(trend))
    if listing_signals.full_number and trend_signals.full_number and listing_signals.full_number != trend_signals.full_number:
        return False
    if listing_signals.card_number and trend.card_number and listing_signals.card_number not in trend.card_number:
        return False

    listing_name = listing_signals.pokemon_name or listing_signals.keyword_name
    trend_name = trend_signals.pokemon_name or trend_signals.keyword_name
    if listing_name and trend_name and listing_name != trend_name:
        return False
    if listing_name and not trend_name:
        return listing_name in normalize_title(_trend_identity_text(trend))
    if trend_name and not listing_name:
        return trend_name in normalize_title(listing.title)
    return bool(set(normalize_title(trend.product_name).split()) & set(normalize_title(listing.title).split()))


def _boost_for_category(categories: set[str]) -> int:
    if {"best_sellers", "best_bargains"}.issubset(categories):
        return 15
    if "best_sellers" in categories:
        return 10
    if "best_bargains" in categories:
        return 7
    return 0


def _ai_verdict(listing: Listing) -> str:
    confidence = int(listing.confidence_score or 0)
    profit_percent = float(listing.discount_percent or 0)
    profit_amount = float(listing.effective_profit or 0)
    if confidence >= 70 and profit_percent >= 30 and profit_amount > 0:
        return "STRONG BUY"
    if confidence >= 45 and profit_percent >= 15 and profit_amount > 0:
        return "WATCH"
    return "CAUTION"


def apply_ai_market_intel_to_listing(listing: Listing, *, trends: list[CardmarketTrend] | None = None) -> bool:
    trend_rows = trends if trends is not None else latest_trends()
    matches = [trend for trend in trend_rows if trend_matches_listing(trend, listing)]
    if not matches:
        return False

    categories = {trend.category for trend in matches}
    best_rank = min(trend.rank for trend in matches)
    boost = _boost_for_category(categories)
    if boost <= 0:
        return False

    base_score = int(listing.pricing_score or listing.score or 0)
    boosted = min(base_score + boost, 100)
    listing.cardmarket_trending_score = boost
    listing.cardmarket_trend_rank = best_rank
    listing.cardmarket_trend_category = "+".join(sorted(categories))
    listing.ai_market_intel_verdict = _ai_verdict(listing)
    listing.pricing_score = boosted
    if boosted >= 85:
        listing.score_level = "INSANE"
    elif boosted >= 70:
        listing.score_level = "HIGH"
    elif boosted >= 45:
        listing.score_level = "MEDIUM"
    print(
        f"[ai_market_intel] AI_MARKET_INTEL_MATCHED_LISTING listing_id={listing.id} "
        f"rank={best_rank} categories={listing.cardmarket_trend_category}",
        flush=True,
    )
    print(
        f"[ai_market_intel] AI_MARKET_INTEL_SNIPER_SCORE_BOOSTED listing_id={listing.id} "
        f"base={base_score} boost={boost} final={boosted}",
        flush=True,
    )
    return True


def build_market_summary(trends: list[CardmarketTrend]) -> dict:
    sellers = [trend for trend in trends if trend.category == "best_sellers"]
    bargains = [trend for trend in trends if trend.category == "best_bargains"]
    top_demand = sellers[0].product_name if sellers else "Not enough data yet"
    rising_category = "single cards"
    if any("booster" in normalize_title(trend.product_name) or "etb" in normalize_title(trend.product_name) for trend in trends):
        rising_category = "sealed products"
    if sellers and bargains:
        market_status = "heating_up"
        summary_text = f"Demand is led by {top_demand}, while bargain activity is visible across {rising_category}."
    elif sellers or bargains:
        market_status = "stable"
        summary_text = "Not enough data yet. Showing latest Cardmarket snapshot."
    else:
        market_status = "stable"
        summary_text = "Not enough data yet. Showing latest Cardmarket snapshot."
    return {
        "market_status": market_status,
        "top_demand": top_demand,
        "rising_category": rising_category,
        "summary_text": summary_text,
    }


def _trend_to_dict(trend: CardmarketTrend) -> dict:
    return {
        "id": trend.id,
        "category": trend.category,
        "rank": trend.rank,
        "product_name": trend.product_name,
        "expansion": trend.expansion,
        "card_number": trend.card_number,
        "price": trend.price,
        "currency": trend.currency,
        "image_url": trend.image_url,
        "product_url": trend.product_url,
        "liquidity": trend.liquidity_label,
        "collected_at": trend.collected_at.isoformat() if trend.collected_at else None,
    }


def _listing_to_opportunity(listing: Listing) -> dict:
    return {
        "listing_id": listing.id,
        "listing_title": listing.title,
        "marketplace": listing.platform,
        "listing_price": listing.price_display,
        "estimated_fair_value": listing.estimated_fair_value or listing.reference_price,
        "potential_profit": listing.effective_profit,
        "profit_percent": listing.discount_percent,
        "confidence_score": listing.confidence_score,
        "cardmarket_trend_category": listing.cardmarket_trend_category,
        "cardmarket_rank": listing.cardmarket_trend_rank,
        "ai_verdict": listing.ai_market_intel_verdict or _ai_verdict(listing),
    }


def build_hidden_signals(trends: list[CardmarketTrend], opportunities: list[Listing]) -> list[dict]:
    signals: list[dict] = []
    names = {}
    for trend in trends:
        key = normalize_title(trend.product_name)
        names[key] = names.get(key, 0) + 1
    repeated = [name for name, count in names.items() if count > 1]
    if repeated:
        signals.append({"title": "Repeated demand signal", "body": "Some products appear across multiple Cardmarket trend groups."})
    if any(trend.category == "best_bargains" and trend.price is not None and trend.price <= 2 for trend in trends):
        signals.append({"title": "Low-cost bargain signal detected", "body": "Cheap Cardmarket bargains may point to fast-moving binder cards."})
    if opportunities:
        signals.append({"title": "Trending product also found live", "body": "Recent Vinted/eBay listings overlap with Cardmarket market movement."})
    if not signals:
        signals.append({"title": "Snapshot warming up", "body": "More daily data will improve hidden signal quality."})
    return signals[:4]


def build_ai_market_intel_payload() -> dict:
    trends = latest_trends()
    last_updated = latest_snapshot_time()
    stale = False
    if last_updated:
        timestamp = last_updated if last_updated.tzinfo else last_updated.replace(tzinfo=timezone.utc)
        stale = utcnow() - timestamp > timedelta(hours=30)
    if stale:
        print("[ai_market_intel] AI_MARKET_INTEL_USING_LAST_SNAPSHOT", flush=True)

    recent_candidates = (
        Listing.query.filter(Listing.cardmarket_trending_score.isnot(None))
        .order_by(
            func.coalesce(Listing.cardmarket_trending_score, 0).desc(),
            func.coalesce(Listing.estimated_profit, Listing.profit_margin, Listing.gross_margin, 0).desc(),
            Listing.detected_at.desc(),
        )
        .limit(12)
        .all()
    )

    payload = {
        "last_updated": last_updated.isoformat() if last_updated else None,
        "stale": stale,
        "market_summary": build_market_summary(trends),
        "best_sellers": [_trend_to_dict(trend) for trend in trends if trend.category == "best_sellers"],
        "best_bargains": [_trend_to_dict(trend) for trend in trends if trend.category == "best_bargains"],
        "smart_opportunities": [_listing_to_opportunity(listing) for listing in recent_candidates],
        "hidden_signals": build_hidden_signals(trends, recent_candidates),
    }
    print("[ai_market_intel] AI_MARKET_INTEL_API_OK", flush=True)
    return payload


def collect_cardmarket_trends_once(
    *,
    source_url: str = DEFAULT_SOURCE_URL,
    timeout_seconds: float = 20,
    user_agent: str = DEFAULT_USER_AGENT,
    max_items: int = 20,
) -> int:
    print("[ai_market_intel] AI_MARKET_INTEL_STARTED", flush=True)
    try:
        trends = fetch_cardmarket_trends(
            source_url=source_url,
            timeout_seconds=timeout_seconds,
            user_agent=user_agent,
            max_items=max_items,
        )
        return save_trends_snapshot(trends)
    except PermissionError as error:
        print(f"[ai_market_intel] CARDMARKET_TRENDS_BLOCKED {error}", flush=True)
        print("[ai_market_intel] AI_MARKET_INTEL_USING_LAST_SNAPSHOT", flush=True)
        return 0
    except Exception as error:
        print(f"[ai_market_intel] CARDMARKET_TRENDS_FAILED error={error}", flush=True)
        return 0
