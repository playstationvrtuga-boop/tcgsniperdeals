from collections import Counter
from datetime import datetime, timezone
import os
import re
import time
from decimal import Decimal
from pathlib import Path

from flask import Blueprint, Response, current_app, flash, jsonify, redirect, render_template, request, send_file, send_from_directory, url_for
from flask_login import current_user, login_required
from sqlalchemy import and_, case, or_
from sqlalchemy.orm import defer

from services.ai_market_intel import build_ai_market_intel_payload
from services.pokemon_title_parser import detect_pokemon_set
from services.site_config import normalize_public_site_url

from .decorators import vip_required
from .extensions import db
from .feed_cache import get_or_set
from .models import Favorite, Listing, Payment, PushSubscription
from .push import push_enabled


main_bp = Blueprint("main", __name__)

LANGUAGE_FILTER_OPTIONS = [
    ("en", "EN"),
    ("jp", "JP"),
    ("fr", "FR"),
    ("es", "ES"),
    ("pt", "PT"),
    ("de", "DE"),
    ("it", "IT"),
    ("unknown", "Unknown"),
]


SET_FILTER_OPTIONS = [
    ("PFL", "PFL - Phantasmal Flames"),
    ("MEG", "MEG - Mega Evolution"),
    ("PRE", "PRE - Prismatic Evolutions"),
    ("SSP", "SSP - Surging Sparks"),
    ("TWM", "TWM - Twilight Masquerade"),
    ("TEF", "TEF - Temporal Forces"),
    ("PAF", "PAF - Paldean Fates"),
    ("OBF", "OBF - Obsidian Flames"),
    ("PAL", "PAL - Paldea Evolved"),
    ("SVI", "SVI - Scarlet & Violet"),
    ("CRZ", "CRZ - Crown Zenith"),
    ("EVS", "EVS - Evolving Skies"),
    ("BRS", "BRS - Brilliant Stars"),
    ("FST", "FST - Fusion Strike"),
    ("CEL", "CEL - Celebrations"),
]

MARKET_TYPE_FILTER_OPTIONS = [
    ("raw_card", "RAW"),
    ("graded_card", "GRADED"),
    ("sealed_product", "SEALED"),
    ("lot_bundle", "LOT"),
]

REGION_PLATFORM_MAP = {
    "eu": ["vinted", "wallapop"],
    "ebay": ["ebay"],
}

PLATFORM_LABELS = {
    "ebay": "eBay",
    "vinted": "Vinted",
    "wallapop": "Wallapop",
    "olx": "OLX",
}


BILLING_PLANS = {
    "monthly": {
        "name": "Monthly",
        "price": "3.90\u20ac",
        "amount": Decimal("3.90"),
        "label": "Flexible access",
        "description": "Stay in the live stream with a flexible monthly plan.",
        "tag": "",
        "highlight": False,
    },
    "yearly": {
        "name": "Yearly",
        "price": "39.90\u20ac",
        "amount": Decimal("39.90"),
        "label": "Best value",
        "description": "The strongest value for buyers who want a full-year edge.",
        "tag": "Most popular",
        "highlight": True,
    },
    "lifetime": {
        "name": "Lifetime",
        "price": "79.90\u20ac",
        "amount": Decimal("79.90"),
        "label": "Locked-in access",
        "description": "A limited one-time unlock for long-term access without renewals.",
        "tag": "Limited",
        "highlight": False,
    },
}


BILLING_METHODS = [
    {
        "key": "revolut",
        "name": "Revolut",
        "description": "Fast payment with no fees.",
        "recommended": True,
        "links": {
            "monthly": "https://revolut.me/srgiojoeq",
            "yearly": "https://revolut.me/srgiojoeq",
            "lifetime": "https://revolut.me/srgiojoeq",
        },
    },
    {
        "key": "paypal",
        "name": "PayPal",
        "description": "Fast checkout with buyer-friendly familiarity.",
        "recommended": False,
        "links": {
            "monthly": "https://www.paypal.com/ncp/payment/PJVH9WVQQC326",
            "yearly": "https://www.paypal.com/ncp/payment/PJVH9WVQQC326",
            "lifetime": "https://www.paypal.com/ncp/payment/PJVH9WVQQC326",
        },
    },
    {
        "key": "skrill",
        "name": "Skrill",
        "description": "Use the exact payment link for the plan you select.",
        "recommended": False,
        "links": {
            "monthly": "https://skrill.me/rq/Sergio/3.9/EUR?key=JsRvn-KlKusSAqQZ9KhtD1n2RlB",
            "yearly": "https://skrill.me/rq/Sergio/39.9/EUR?key=oMfiyh88FluEyn4Ir-fbnUSOUUU",
            "lifetime": "https://skrill.me/rq/Sergio/79.9/EUR?key=z4adwupMWqQk80qxii-_QaNpVWl",
        },
    },
    {
        "key": "neteller",
        "name": "Neteller",
        "description": "Use the matching plan link and send your confirmation after payment.",
        "recommended": False,
        "links": {
            "monthly": "https://neteller.me/rq/Sergio/3.9/EUR?key=XoRbRMFLrffV8esA3WjFqXsbWuR",
            "yearly": "https://neteller.me/rq/Sergio/39.9/EUR?key=Kj3kZ7nL-ltlxgq4ymi-PVEUX0J",
            "lifetime": "https://neteller.me/rq/Sergio/79.9/EUR?key=LuG8OoCtAd40g5ksW0VXyHsTNVC",
        },
    },
]


SEO_PAGES = {
    "pokemon-deals": {
        "title": "Real-Time Pokémon TCG Deals | TCG Sniper Deals",
        "meta_description": "Find real-time Pokémon TCG deals, booster packs, ETBs, Charizard cards and sealed products before they disappear.",
        "h1": "Real-Time Pokémon TCG Deals",
        "intro": (
            "TCG Sniper Deals helps collectors and resellers find Pokémon TCG opportunities faster. "
            "The app tracks listings from marketplaces like Vinted and eBay and highlights Pokémon cards, "
            "booster packs, Elite Trainer Boxes, sealed products and underpriced listings before they disappear."
        ),
        "sections": [
            {
                "title": "Why speed matters in Pokémon deals",
                "text": (
                    "The best Pokémon deals usually do not stay available for long. Charizard cards, booster packs, ETBs "
                    "and sealed Pokémon products can sell within minutes when the price is too low. TCG Sniper Deals is "
                    "built to help users react faster instead of manually refreshing marketplaces all day."
                ),
            },
            {
                "title": "VIP alerts",
                "text": (
                    "VIP users get faster access to deal alerts, while public users may only see limited or delayed opportunities. "
                    "If you collect, resell or flip Pokémon cards, real-time alerts can give you a serious advantage."
                ),
            },
        ],
        "related": ["charizard-deals", "pokemon-etb-deals", "pokemon-booster-deals", "pokemon-ebay-deals"],
    },
    "charizard-deals": {
        "title": "Charizard Card Deals | Real-Time Pokémon Alerts",
        "meta_description": "Track Charizard Pokémon card deals, underpriced listings and real-time marketplace alerts.",
        "h1": "Charizard Card Deals",
        "intro": (
            "Charizard is one of the most searched and collected Pokémon cards worldwide. Because of that demand, "
            "good Charizard card deals often disappear quickly."
        ),
        "sections": [
            {
                "title": "Find Charizard listings faster",
                "text": (
                    "TCG Sniper Deals helps track marketplace listings where Charizard cards may appear below market value. "
                    "This includes raw cards, graded cards, PSA slabs, vintage cards and modern Charizard hits."
                ),
            },
            {
                "title": "Built for collectors and resellers",
                "text": (
                    "Instead of checking Vinted and eBay manually, users can use alerts to react faster when a potential Charizard deal appears."
                ),
            },
        ],
        "related": ["pokemon-deals", "pokemon-ebay-deals", "cheap-pokemon-cards", "pokemon-vinted-deals"],
    },
    "pokemon-etb-deals": {
        "title": "Pokémon ETB Deals | Elite Trainer Box Alerts",
        "meta_description": "Find Pokémon Elite Trainer Box deals, ETB discounts and sealed Pokémon TCG product alerts.",
        "h1": "Pokémon ETB Deals",
        "intro": (
            "Elite Trainer Boxes are one of the most popular sealed Pokémon TCG products for collectors, investors and resellers."
        ),
        "sections": [
            {
                "title": "Track sealed Pokémon products",
                "text": (
                    "TCG Sniper Deals helps users monitor ETB listings across marketplaces and identify potential underpriced sealed products."
                ),
            },
            {
                "title": "Why ETBs matter",
                "text": (
                    "Pokémon ETBs are easy to store, popular with collectors and often sell fast when listed below normal market prices."
                ),
            },
        ],
        "related": ["pokemon-deals", "pokemon-booster-deals", "pokemon-vinted-deals", "pokemon-ebay-deals"],
    },
    "pokemon-booster-deals": {
        "title": "Pokémon Booster Pack Deals | Real-Time TCG Alerts",
        "meta_description": "Track Pokémon booster pack deals, booster boxes and sealed pack listings in real time.",
        "h1": "Pokémon Booster Pack Deals",
        "intro": (
            "Booster packs and booster boxes are among the most searched Pokémon TCG products online."
        ),
        "sections": [
            {
                "title": "Find booster pack opportunities",
                "text": (
                    "TCG Sniper Deals tracks marketplace listings for booster packs, booster boxes and sealed Pokémon TCG products."
                ),
            },
            {
                "title": "React before deals disappear",
                "text": (
                    "Good booster deals can sell quickly, especially when they include popular sets, rare packs or discounted sealed products."
                ),
            },
        ],
        "related": ["pokemon-deals", "pokemon-etb-deals", "pokemon-ebay-deals", "cheap-pokemon-cards"],
    },
    "pokemon-ebay-deals": {
        "title": "Pokémon eBay Deals | Real-Time Card Alerts",
        "meta_description": "Find Pokémon eBay deals, underpriced cards, sealed products and real-time TCG alerts.",
        "h1": "Pokémon eBay Deals",
        "intro": (
            "eBay is one of the biggest marketplaces for Pokémon cards, graded slabs, sealed boxes and rare collectibles."
        ),
        "sections": [
            {
                "title": "Track eBay Pokémon listings",
                "text": (
                    "TCG Sniper Deals helps users monitor new Pokémon listings and detect possible opportunities faster."
                ),
            },
            {
                "title": "Useful for flipping and collecting",
                "text": (
                    "Whether you are looking for cheap cards, graded Pokémon cards or sealed products, fast alerts can help you act before other buyers."
                ),
            },
        ],
        "related": ["pokemon-deals", "charizard-deals", "pokemon-vinted-deals", "cheap-pokemon-cards"],
    },
    "pokemon-vinted-deals": {
        "title": "Pokémon Vinted Deals | Cheap Pokémon Card Alerts",
        "meta_description": "Track Pokémon Vinted deals, cheap Pokémon cards and underpriced TCG listings.",
        "h1": "Pokémon Vinted Deals",
        "intro": (
            "Vinted can be a strong place to find cheap Pokémon cards, bundles and collection listings from casual sellers."
        ),
        "sections": [
            {
                "title": "Find underpriced listings",
                "text": (
                    "Many sellers on Vinted list Pokémon cards without checking the full market value. This can create opportunities for collectors and resellers."
                ),
            },
            {
                "title": "Real-time advantage",
                "text": (
                    "The best Vinted Pokémon deals often sell very fast. TCG Sniper Deals helps users spot new listings faster."
                ),
            },
        ],
        "related": ["pokemon-deals", "cheap-pokemon-cards", "pokemon-etb-deals", "pokemon-ebay-deals"],
    },
    "cheap-pokemon-cards": {
        "title": "Cheap Pokémon Cards | Find Undervalued Deals",
        "meta_description": "Find cheap Pokémon cards, undervalued listings and real-time Pokémon TCG deal alerts.",
        "h1": "Cheap Pokémon Cards",
        "intro": (
            "Finding cheap Pokémon cards online is not just about searching manually. The best opportunities usually appear and disappear quickly."
        ),
        "sections": [
            {
                "title": "Undervalued Pokémon listings",
                "text": (
                    "TCG Sniper Deals helps identify new listings that may be cheaper than normal market value."
                ),
            },
            {
                "title": "For collectors and resellers",
                "text": (
                    "Whether you want cards for your personal collection or for resale, speed and timing are key."
                ),
            },
        ],
        "related": ["pokemon-deals", "pokemon-vinted-deals", "pokemon-ebay-deals", "charizard-deals"],
    },
}


SEO_HOME_CONTENT = {
    "eyebrow": "Pokémon TCG search",
    "title": "Find real-time Pokémon TCG deals before they disappear",
    "text": (
        "TCG Sniper Deals tracks Pokémon cards, ETBs, booster packs and sealed products across Vinted and eBay. "
        "Collectors and resellers use the app to spot underpriced listings faster and keep up with the live deal stream."
    ),
    "sections": [
        {
            "title": "Pokémon cards, ETBs and booster packs",
            "text": (
                "If you are searching for Charizard cards, Elite Trainer Boxes, booster packs or cheap Pokémon cards, "
                "the live feed highlights fresh listings as they are detected."
            ),
        },
        {
            "title": "Built for collectors and resellers",
            "text": (
                "The public home gives a preview of the stream, while VIP users get the fastest alerts, full access and the strongest opportunities."
            ),
        },
    ],
    "links": [
        ("Charizard deals", "main.seo_page_charizard_deals"),
        ("ETB deals", "main.seo_page_pokemon_etb_deals"),
        ("Booster pack deals", "main.seo_page_pokemon_booster_deals"),
        ("eBay deals", "main.seo_page_pokemon_ebay_deals"),
        ("Vinted deals", "main.seo_page_pokemon_vinted_deals"),
        ("Cheap Pokémon cards", "main.seo_page_cheap_pokemon_cards"),
    ],
}

from .seo_content import DYNAMIC_SEO_PAGES, SEO_HOME_CONTENT, SEO_PAGE_ALIASES, SEO_PAGES, SEO_PUBLIC_PATHS


def site_root_url():
    return normalize_public_site_url(current_app.config.get("PUBLIC_SITE_URL"))


def canonical_for_path(path):
    normalized_path = path if path.startswith("/") else f"/{path}"
    return f"{site_root_url()}{normalized_path}"


def seo_page_catalog():
    return {**SEO_PAGES, **DYNAMIC_SEO_PAGES}


def seo_page_data(slug):
    pages = seo_page_catalog()
    return pages[slug]


def _seo_related_pages(data, slug):
    pages = seo_page_catalog()
    if slug in DYNAMIC_SEO_PAGES:
        fixed_slugs = [
            "pokemon-deals",
            "pokemon-deals-today",
            "charizard-deals-under-100",
            "cheap-pokemon-cards-eu",
            "top-pokemon-deals-eu",
        ]
        related_pages = [{"slug": "", "label": "TCG Sniper Deals homepage", "url": "/"}]
        related_pages.extend(
            {
                "slug": related_slug,
                "label": pages[related_slug]["h1"],
                "url": f"/{related_slug}",
            }
            for related_slug in fixed_slugs
            if related_slug in pages
        )
        return related_pages[:10]

    related_pages = []
    seen_urls = set()

    def add_related(related_slug, label, url):
        if url in seen_urls or related_slug == slug:
            return
        seen_urls.add(url)
        related_pages.append({"slug": related_slug, "label": label, "url": url})

    add_related("", "TCG Sniper Deals homepage", "/")
    for related_slug in data.get("related", []):
        if related_slug in pages:
            add_related(related_slug, pages[related_slug]["h1"], f"/{related_slug}")
    for base_slug in ("pokemon-deals", "charizard-deals"):
        if base_slug in pages:
            add_related(base_slug, pages[base_slug]["h1"], f"/{base_slug}")

    return related_pages[:10]


def _parse_price_eur(price_display):
    if not price_display:
        return None
    text = str(price_display).replace("\xa0", " ").strip()
    match = re.search(r"(\d+(?:[.,]\d{3})*(?:[.,]\d{1,2})?|\d+)", text)
    if not match:
        return None
    raw = match.group(1)
    if "," in raw and "." in raw:
        raw = raw.replace(".", "").replace(",", ".")
    elif "," in raw:
        raw = raw.replace(",", ".")
    try:
        return float(raw)
    except ValueError:
        return None


def _base_dynamic_seo_query():
    status_value = db.func.lower(db.func.coalesce(Listing.status, Listing.available_status, ""))
    gone_values = gone_status_values() + ["gone_confirmed"]
    return Listing.query.options(defer(Listing.raw_payload)).filter(
        db.func.lower(db.func.coalesce(Listing.tcg_type, "pokemon")) == "pokemon",
        or_(status_value == "", ~status_value.in_(gone_values)),
    )


def _dynamic_seo_query(filters):
    query = _base_dynamic_seo_query()
    keywords = [keyword for keyword in filters.get("keywords", []) if keyword.lower() != "pokemon"]
    if keywords:
        query = query.filter(or_(*[Listing.title.ilike(f"%{keyword}%") for keyword in keywords]))

    if filters.get("region") == "eu":
        query = query.filter(db.func.lower(Listing.platform).in_(REGION_PLATFORM_MAP["eu"]))

    if filters.get("mode") == "best":
        score_level = db.func.upper(db.func.coalesce(Listing.score_level, ""))
        query = query.filter(
            or_(
                Listing.is_deal.is_(True),
                score_level.in_(["MEDIUM", "HIGH", "INSANE"]),
                db.func.coalesce(Listing.estimated_profit, Listing.profit_margin, Listing.gross_margin, 0) > 0,
                db.func.coalesce(Listing.discount_percent, 0) > 0,
            )
        )
        return query.order_by(
            Listing.is_deal.desc(),
            db.func.coalesce(Listing.discount_percent, 0).desc(),
            db.func.coalesce(Listing.estimated_profit, Listing.profit_margin, Listing.gross_margin, 0).desc(),
            Listing.detected_at.desc(),
            Listing.id.desc(),
        )

    return query.order_by(Listing.detected_at.desc(), Listing.id.desc())


def _seo_listing_candidates(data, limit=40):
    filters = data.get("filters", {})
    try:
        max_price = filters.get("max_price_eur")
        fetch_limit = max(limit * 3, 40) if max_price is not None else limit
        candidates = _dynamic_seo_query(filters).limit(fetch_limit).all()
    except Exception as error:
        current_app.logger.info("[dynamic_seo] listing_query_failed slug=%s error=%s", data.get("slug", ""), error)
        return []

    listings = []
    for listing in candidates:
        max_price = filters.get("max_price_eur")
        if max_price is not None:
            parsed_price = _parse_price_eur(listing.price_display)
            if parsed_price is None or parsed_price > float(max_price):
                continue
        listings.append(listing)
        if len(listings) >= limit:
            break
    return listings


def dynamic_seo_listings(data, limit=9):
    return _seo_listing_candidates(data, limit=limit)


def _platforms_for_filters(filters):
    if filters.get("region") == "eu":
        return ["Vinted", "Wallapop"]
    return ["Vinted", "eBay", "Wallapop"]


def _featured_category_for_listings(listings):
    category_labels = {
        "raw_card": "Pokemon cards",
        "graded_card": "Graded cards",
        "sealed_product": "Booster boxes and ETBs",
        "lot_bundle": "Card lots",
    }
    values = [
        (listing.listing_type or listing.category or "").strip().lower()
        for listing in listings
        if (listing.listing_type or listing.category or "").strip()
    ]
    if not values:
        return "Pokemon deals"
    key = Counter(values).most_common(1)[0][0]
    return category_labels.get(key, key.replace("_", " ").title())


def dynamic_seo_snapshot(data, *, listing_limit=9, stats_limit=40):
    candidates = _seo_listing_candidates(data, limit=max(listing_limit, stats_limit))
    newest_detected_at = next((listing.detected_at for listing in candidates if listing.detected_at), None)
    platform_names = sorted(
        {
            PLATFORM_LABELS.get((listing.platform or "").strip().lower(), (listing.platform or "").strip())
            for listing in candidates
            if (listing.platform or "").strip()
        }
    )
    if not platform_names:
        platform_names = _platforms_for_filters(data.get("filters", {}))

    count_label = f"{len(candidates)}+" if len(candidates) >= stats_limit else str(len(candidates))
    return {
        "listings": candidates[:listing_limit],
        "stats": {
            "live_deals_count": count_label,
            "newest_detected_at": newest_detected_at,
            "platforms": platform_names,
            "platforms_label": ", ".join(platform_names),
            "featured_category": _featured_category_for_listings(candidates),
        },
    }


def dynamic_seo_lastmod(slug, today):
    data = dict(seo_page_data(slug), slug=slug)
    listings = dynamic_seo_listings(data, limit=1)
    if not listings or not listings[0].detected_at:
        return today
    detected_at = listings[0].detected_at
    if detected_at.tzinfo is None:
        detected_at = detected_at.replace(tzinfo=timezone.utc)
    return detected_at.date().isoformat()


def build_seo_page_context(slug):
    data = seo_page_data(slug)
    snapshot = dynamic_seo_snapshot(dict(data, slug=slug))
    show_live_listings = bool(data.get("show_live_listings") or slug in DYNAMIC_SEO_PAGES)
    page = {
        "slug": slug,
        "title": data["title"],
        "meta_description": data["meta_description"],
        "h1": data["h1"],
        "intro": data["intro"],
        "sections": [dict(section) for section in data["sections"]],
        "related_pages": _seo_related_pages(data, slug),
        "faqs": data.get(
            "faqs",
            [
                {
                    "question": "Where to find cheap Pokemon cards?",
                    "answer": "Cheap Pokemon cards can appear on eBay, Vinted and EU marketplaces, especially in fresh listings, mixed lots and local-language posts. Always check condition, shipping, seller history and recent comparable prices before buying.",
                },
                {
                    "question": "Are Pokemon deals worth it?",
                    "answer": "Pokemon deals can be worth it when the item, condition, language, shipping and market value all make sense. Real-time alerts help you see listings earlier, but every purchase still needs manual review.",
                },
                {
                    "question": "How often are these Pokemon deal pages updated?",
                    "answer": "Dynamic pages read from the bot listing database at request time, so public deal previews and sitemap freshness can change as new listings are detected.",
                },
            ],
        ),
        "is_dynamic": slug in DYNAMIC_SEO_PAGES,
        "show_live_listings": show_live_listings,
        "deal_section_title": data.get("deal_section_title", "Live deals from the bot"),
        "empty_state": data.get("empty_state", "No matching public deals are available right now."),
        "stats": snapshot["stats"],
    }
    page["listings"] = snapshot["listings"] if show_live_listings else []
    return page


def render_seo_page(slug):
    page = build_seo_page_context(slug)
    return render_template(
        "seo_page.html",
        page=page,
        canonical_url=canonical_for_path(f"/{slug}"),
        vip_access_url=url_for("main.billing"),
        app_url=url_for("main.index"),
    )


def register_seo_page_routes():
    for slug in seo_page_catalog():
        endpoint = f"seo_page_{slug.replace('-', '_')}"

        def view(page_slug=slug):
            return render_seo_page(page_slug)

        view.__name__ = endpoint
        main_bp.add_url_rule(f"/{slug}", endpoint=endpoint, view_func=view)

    for alias_slug, target_slug in SEO_PAGE_ALIASES.items():
        endpoint = f"seo_alias_{alias_slug.replace('-', '_')}"

        def alias_view(page_slug=target_slug):
            return redirect(url_for(f"main.seo_page_{page_slug.replace('-', '_')}"), code=301)

        alias_view.__name__ = endpoint
        main_bp.add_url_rule(f"/{alias_slug}", endpoint=endpoint, view_func=alias_view)


register_seo_page_routes()


def build_sitemap_urls():
    site_root = site_root_url()
    today = datetime.now(timezone.utc).date().isoformat()
    urls = []
    for path in SEO_PUBLIC_PATHS:
        slug = path.strip("/")
        urls.append(
            {
                "loc": f"{site_root}{path}",
                "lastmod": dynamic_seo_lastmod(slug, today) if slug in seo_page_catalog() else today,
            }
        )
    return urls


def get_current_plan_key(user):
    latest_paid = (
        Payment.query.filter_by(user_id=user.id, status="paid")
        .order_by(Payment.paid_at.desc().nullslast(), Payment.created_at.desc())
        .first()
    )
    if latest_paid and latest_paid.plan in BILLING_PLANS:
        return latest_paid.plan
    if user.vip_active:
        return "yearly"
    return "yearly"


def newest_listing_order():
    return (
        Listing.detected_at.desc(),
        Listing.id.desc(),
    )


def smart_deal_order():
    score_rank = case(
        (db.func.upper(db.func.coalesce(Listing.score_level, "")) == "INSANE", 3),
        (db.func.upper(db.func.coalesce(Listing.score_level, "")) == "HIGH", 2),
        (db.func.upper(db.func.coalesce(Listing.score_level, "")) == "MEDIUM", 1),
        else_=0,
    )
    return (
        score_rank.desc(),
        db.func.coalesce(Listing.estimated_profit, Listing.profit_margin, Listing.gross_margin, -999).desc(),
        *newest_listing_order(),
    )


def missed_deal_order():
    return (
        db.func.coalesce(Listing.gone_detected_at, Listing.status_updated_at, Listing.updated_at).desc(),
        *newest_listing_order(),
    )


def favorite_ids_for_current_user():
    return {
        listing_id
        for (listing_id,) in Favorite.query.filter_by(user_id=current_user.id).with_entities(Favorite.listing_id).all()
    }


def gone_status_values():
    return [
        "deleted",
        "eliminada",
        "eliminado",
        "esgotada",
        "esgotado",
        "expired",
        "indisponivel",
        "indisponível",
        "not-available",
        "out-of-stock",
        "out_of_stock",
        "removed",
        "removida",
        "removido",
        "reserved",
        "sold",
        "unavailable",
        "vendida",
        "vendido",
    ]


def parse_language_filter(raw_value: str) -> list[str]:
    allowed = {value for value, _label in LANGUAGE_FILTER_OPTIONS}
    selected = []
    for item in (raw_value or "").split(","):
        value = item.strip().lower()
        if value in allowed and value not in selected:
            selected.append(value)
    return selected


def parse_set_filter(raw_value: str) -> list[str]:
    allowed = {value for value, _label in SET_FILTER_OPTIONS}
    selected = []
    for item in (raw_value or "").split(","):
        value = item.strip().upper()
        if value in allowed and value not in selected:
            selected.append(value)
    return selected


def parse_market_type_filter(raw_value: str) -> list[str]:
    allowed = {value for value, _label in MARKET_TYPE_FILTER_OPTIONS}
    selected = []
    for item in (raw_value or "").split(","):
        value = item.strip().lower()
        if value in allowed and value not in selected:
            selected.append(value)
    return selected


def parse_region_filter(raw_value: str) -> str:
    value = (raw_value or "").strip().lower()
    return value if value in REGION_PLATFORM_MAP else ""


def normalize_platform_filter(raw_value: str) -> str:
    value = (raw_value or "").strip().lower()
    return value.replace(" ", "-").replace("_", "-")


def platform_filter_label(platform_key: str) -> str:
    normalized = normalize_platform_filter(platform_key).replace("-", "_")
    return PLATFORM_LABELS.get(normalized, PLATFORM_LABELS.get(platform_key, platform_key))


def _search_set_conditions(search: str):
    detected = detect_pokemon_set(search)
    conditions = []
    if detected.get("set_code"):
        conditions.append(db.func.upper(db.func.coalesce(Listing.set_code, "")).in_([detected["set_code"]]))
    if detected.get("set_name"):
        conditions.append(Listing.set_name.ilike(f"%{detected['set_name']}%"))
    return conditions


def apply_listing_filters(query, search, platform, badge, languages=None, sets=None, region="", market_types=None):
    if search:
        search_conditions = [Listing.title.ilike(f"%{search}%")]
        search_conditions.extend(_search_set_conditions(search))
        query = query.filter(or_(*search_conditions))
    region = parse_region_filter(region)
    if region:
        query = query.filter(db.func.lower(Listing.platform).in_(REGION_PLATFORM_MAP[region]))
    if platform:
        platform_key = normalize_platform_filter(platform)
        platform_values = {platform_key, platform_key.replace("-", " "), platform_key.replace("-", "_")}
        label = platform_filter_label(platform_key)
        if label:
            platform_values.add(label.lower())
        query = query.filter(db.func.lower(Listing.platform).in_([value.lower() for value in platform_values if value]))
    if badge:
        if badge == "Fresh":
            query = query.filter(Listing.is_deal.is_(False))
        else:
            query = query.filter(Listing.is_deal.is_(True), Listing.badge_label == badge)
    if languages:
        normalized_languages = [language.lower() for language in languages]
        language_conditions = [db.func.lower(db.func.coalesce(Listing.card_language, "unknown")).in_(normalized_languages)]
        if "unknown" in normalized_languages:
            language_conditions.append(Listing.card_language.is_(None))
        query = query.filter(or_(*language_conditions))
    if sets:
        normalized_sets = [set_code.upper() for set_code in sets]
        query = query.filter(db.func.upper(db.func.coalesce(Listing.set_code, "")).in_(normalized_sets))
    if market_types:
        normalized_market_types = [market_type.lower() for market_type in market_types]
        query = query.filter(db.func.lower(db.func.coalesce(Listing.listing_type, "")).in_(normalized_market_types))
    return query


def feed_options():
    def build_platforms():
        return [row[0] for row in db.session.query(Listing.platform).distinct().all()]

    def build_badges():
        deal_badges = [
            row[0]
            for row in db.session.query(Listing.badge_label)
            .filter(Listing.is_deal.is_(True), Listing.badge_label.isnot(None), Listing.badge_label != "")
            .distinct()
            .all()
        ]
        return ["Fresh"] + [badge_name for badge_name in deal_badges if badge_name != "Fresh"]

    platforms, _ = get_or_set("feed:platforms", current_app.config["FEED_OPTIONS_CACHE_TTL_SECONDS"], build_platforms)
    badges, _ = get_or_set("feed:badges", current_app.config["FEED_OPTIONS_CACHE_TTL_SECONDS"], build_badges)
    return platforms, badges


def alerts_are_active():
    if not push_enabled():
        return False
    return PushSubscription.query.filter_by(user_id=current_user.id).first() is not None


def render_deals_board(
    *,
    query,
    order_by,
    cache_key=None,
    page_mode="live",
    board_title="Live feed for fresh opportunity flow",
    board_intro="New listings land here in real time. The radar stays active, the stream stays light, and the strongest signals rise first.",
    board_label="Market intelligence",
    stat_label="Live stream",
    default_region="",
    default_platform="",
):
    feed_started = time.perf_counter()
    search = request.args.get("q", "").strip()
    platform = request.args.get("platform", default_platform).strip()
    badge = request.args.get("badge", "").strip()
    language_raw = request.args.get("language", "").strip()
    selected_languages = parse_language_filter(language_raw)
    set_raw = request.args.get("set", "").strip()
    selected_sets = parse_set_filter(set_raw)
    region = parse_region_filter(request.args.get("region", default_region).strip())
    market_type_raw = request.args.get("market_type", "").strip()
    selected_market_types = parse_market_type_filter(market_type_raw)
    platform_key = normalize_platform_filter(platform)
    query = apply_listing_filters(
        query.options(defer(Listing.raw_payload)),
        search,
        platform,
        badge,
        selected_languages,
        selected_sets,
        region,
        selected_market_types,
    )

    cache_hit = False
    if cache_key and not search and not platform and not badge and not region and not selected_languages and not selected_sets and not selected_market_types:
        def build_snapshot():
            listings = query.order_by(*order_by).limit(30).all()
            return {
                "listings": listings,
                "live_listings_count": len(listings),
                "deal_count": sum(1 for listing in listings if listing.is_deal),
                "last_detected_at": listings[0].detected_at if listings else None,
            }

        feed_snapshot, cache_hit = get_or_set(cache_key, current_app.config["FEED_CACHE_TTL_SECONDS"], build_snapshot)
        listings = feed_snapshot["listings"]
        live_listings_count = feed_snapshot["live_listings_count"]
        deal_count = feed_snapshot["deal_count"]
        last_detected_at = feed_snapshot["last_detected_at"]
    else:
        listings = query.order_by(*order_by).limit(30).all()
        live_listings_count = len(listings)
        deal_count = sum(1 for listing in listings if listing.is_deal)
        last_detected_at = listings[0].detected_at if listings else None

    if page_mode == "ebay":
        if cache_key:
            current_app.logger.info(
                "[EBAY_FEED_CACHE_%s] key=%s",
                "HIT" if cache_hit else "MISS",
                cache_key,
            )
        else:
            current_app.logger.info("[EBAY_FEED_CACHE_MISS] key=none reason=disabled")
        current_app.logger.info(
            "[EBAY_DEALS_PAGE_QUERY] count=%s ids=%s",
            len(listings),
            ",".join(str(listing.external_id or listing.id) for listing in listings[:10]),
        )

    live_stats = {
        "count": live_listings_count,
        "deal_count": deal_count,
        "last_detected_at": last_detected_at,
        "alerts_active": alerts_are_active(),
    }
    feed_cursor_id = max((listing.id for listing in listings), default=0)
    platforms, badges = feed_options()
    if region == "eu":
        platforms = ["Vinted", "Wallapop"]
        platform_all_label = "All EU"
    elif region == "ebay" or page_mode == "ebay":
        platforms = ["eBay"]
        platform_all_label = "All eBay"
    else:
        platform_all_label = "All platforms"
    current_app.logger.info(
        "[FEED_FILTER] region=%s platform=%s set=%s language=%s market_type=%s results=%s",
        region or "all",
        platform_key or "all",
        ",".join(selected_sets) if selected_sets else "all",
        ",".join(selected_languages) if selected_languages else "all",
        ",".join(selected_market_types) if selected_market_types else "all",
        len(listings),
    )

    total_ms = (time.perf_counter() - feed_started) * 1000
    current_app.logger.debug(
        "[feed-render] mode=%s timestamp_source=detected_at first_id=%s first_detected_at=%s listings=%s",
        page_mode,
        listings[0].id if listings else None,
        listings[0].detected_at_iso if listings else None,
        len(listings),
    )
    if current_app.config.get("LOG_FEED_TIMING", False):
        current_app.logger.info(
            "[%s] cache=%s listings=%s total=%.1fms",
            page_mode,
            "hit" if cache_hit else "miss",
            len(listings),
            total_ms,
        )
    if page_mode == "ebay":
        current_app.logger.info(
            "[EBAY_DEALS_PAGE_RENDER] count=%s ids=%s",
            len(listings),
            ",".join(str(listing.external_id or listing.id) for listing in listings[:10]),
        )

    return render_template(
        "feed.html",
        listings=listings,
        favorite_ids=favorite_ids_for_current_user(),
        push_enabled=push_enabled(),
        platforms=platforms,
        platform_all_label=platform_all_label,
        badges=badges,
        search=search,
        selected_platform=platform_key,
        selected_badge=badge,
        selected_languages=selected_languages,
        language_filter_value=",".join(selected_languages),
        language_options=LANGUAGE_FILTER_OPTIONS,
        selected_sets=selected_sets,
        set_filter_value=",".join(selected_sets),
        set_options=SET_FILTER_OPTIONS,
        region_filter_value=region,
        selected_market_types=selected_market_types,
        market_type_filter_value=",".join(selected_market_types),
        market_type_options=MARKET_TYPE_FILTER_OPTIONS,
        live_stats=live_stats,
        feed_poll_interval_ms=current_app.config["FEED_POLL_INTERVAL_MS"],
        feed_delta_max_items=current_app.config["FEED_DELTA_MAX_ITEMS"],
        feed_cursor_id=feed_cursor_id,
        enable_live_radar=current_app.config["ENABLE_LIVE_RADAR"] and page_mode in {"live", "eu", "ebay"},
        enable_target_feedback=current_app.config["ENABLE_TARGET_FEEDBACK"] and page_mode in {"live", "eu", "ebay"},
        enable_card_entry_animations=current_app.config["ENABLE_CARD_ENTRY_ANIMATIONS"],
        enable_relative_time_updates=current_app.config["ENABLE_RELATIVE_TIME_UPDATES"],
        relative_time_update_ms=current_app.config["RELATIVE_TIME_UPDATE_MS"],
        page_mode=page_mode,
        board_title=board_title,
        board_intro=board_intro,
        board_label=board_label,
        stat_label=stat_label,
        active_tab=page_mode,
    )


def get_android_apk_path():
    project_root = Path(__file__).resolve().parents[2]
    return project_root / "vip_app_mobile" / "android" / "app" / "build" / "outputs" / "apk" / "debug" / "app-debug.apk"


def get_android_apk_download():
    external_url = (current_app.config.get("ANDROID_APK_URL") or "").strip()
    if external_url:
        return {
            "available": True,
            "url": external_url,
            "is_external": True,
            "size_mb": None,
            "updated_at": None,
        }

    apk_path = get_android_apk_path()
    if not apk_path.exists():
        return {
            "available": False,
            "url": None,
            "is_external": False,
            "size_mb": None,
            "updated_at": None,
        }

    stat = apk_path.stat()
    return {
        "available": True,
        "url": url_for("main.download_android_apk"),
        "is_external": False,
        "size_mb": round(stat.st_size / (1024 * 1024), 1),
        "updated_at": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc),
    }


@main_bp.route("/")
def index():
    if current_user.is_authenticated:
        return redirect(url_for("main.feed"))
    query = Listing.query.options(defer(Listing.raw_payload))
    listings = query.order_by(*newest_listing_order()).limit(12).all()
    live_stats = {
        "count": len(listings),
        "deal_count": sum(1 for listing in listings if listing.is_deal),
        "last_detected_at": listings[0].detected_at if listings else None,
        "alerts_active": False,
    }
    return render_template(
        "landing.html",
        listings=listings,
        favorite_ids=set(),
        live_stats=live_stats,
        public_preview=True,
        enable_live_radar=True,
        enable_card_entry_animations=True,
        enable_relative_time_updates=True,
        relative_time_update_ms=current_app.config["RELATIVE_TIME_UPDATE_MS"],
        feed_poll_interval_ms=current_app.config["FEED_POLL_INTERVAL_MS"],
        feed_delta_max_items=current_app.config["FEED_DELTA_MAX_ITEMS"],
        seo_home=SEO_HOME_CONTENT,
        canonical_url=canonical_for_path("/"),
    )


@main_bp.route("/download-app")
def download_app():
    apk_download = get_android_apk_download()
    preview_listing = (
        Listing.query.options(defer(Listing.raw_payload)).filter(
            Listing.image_url.isnot(None),
            Listing.image_url != "",
            Listing.image_url.notlike("%example.com%"),
        )
        .order_by(*newest_listing_order())
        .first()
    )

    return render_template(
        "download_app.html",
        apk_available=apk_download["available"],
        apk_size_mb=apk_download["size_mb"],
        apk_updated_at=apk_download["updated_at"],
        apk_url=apk_download["url"],
        apk_is_external=apk_download["is_external"],
        preview_listing=preview_listing,
    )


@main_bp.route("/download-app/android")
def download_android_apk():
    external_url = (current_app.config.get("ANDROID_APK_URL") or "").strip()
    if external_url:
        return redirect(external_url)

    apk_path = get_android_apk_path()
    if not apk_path.exists():
        return redirect(url_for("main.download_app"))
    return send_file(
        apk_path,
        as_attachment=True,
        download_name="TCG-Sniper-Deals-Android.apk",
        mimetype="application/vnd.android.package-archive",
    )


@main_bp.route("/feed")
@main_bp.route("/deals")
@main_bp.route("/live-deals")
@main_bp.route("/eu-deals")
@vip_required
def feed():
    return render_deals_board(
        query=Listing.query,
        order_by=newest_listing_order(),
        cache_key=None,
        page_mode="eu",
        board_label="EU marketplaces",
        board_title="EU Deals",
        board_intro="Fresh Vinted and Wallapop listings in one focused stream.",
        stat_label="EU stream",
        default_region="eu",
    )


@main_bp.route("/ebay-deals")
@vip_required
def ebay_deals():
    return render_deals_board(
        query=Listing.query,
        order_by=newest_listing_order(),
        cache_key=None,
        page_mode="ebay",
        board_label="eBay marketplace",
        board_title="eBay Deals",
        board_intro="Fresh eBay listings kept separate from the European marketplace stream.",
        stat_label="eBay stream",
        default_platform="ebay",
    )


@main_bp.route("/smart-deals")
@vip_required
def smart_deals():
    query = build_smart_deals_query()
    log_smart_deals_diagnostics(query)
    return render_deals_board(
        query=query,
        order_by=smart_deal_order(),
        cache_key="feed:smart:v5",
        page_mode="smart",
        board_label="Sniper pricing",
        board_title="Sniper Deals with pricing edge",
        board_intro="Only enriched listings with market signals, discount pressure or real profit potential.",
        stat_label="Sniper stream",
    )


def build_smart_deals_query():
    score_level = db.func.upper(db.func.coalesce(Listing.score_level, ""))
    profit_value = db.func.coalesce(Listing.estimated_profit, Listing.profit_margin, Listing.gross_margin, 0)
    pricing_status = db.func.lower(db.func.coalesce(Listing.pricing_status, ""))
    pricing_basis = db.func.lower(db.func.coalesce(Listing.pricing_basis, ""))
    listing_type = db.func.lower(db.func.coalesce(Listing.listing_type, "unknown"))
    confidence_value = db.func.coalesce(Listing.confidence_score, 0)
    sold_comparable_signal = or_(
        and_(Listing.last_2_sales_json.isnot(None), Listing.last_2_sales_json.ilike("%,%")),
        Listing.pricing_reason.ilike("%sold_refs=1%"),
        Listing.pricing_reason.ilike("%sold_refs=2%"),
        Listing.pricing_reason.ilike("%sold_refs=3%"),
        Listing.pricing_reason.ilike("%PRICING_SOLD_FOUND%"),
        Listing.pricing_reason.ilike("%SIMPLE_SOLD_AVG_OPPORTUNITY%"),
        Listing.pricing_reason.ilike("%comparable_results=1%"),
        Listing.pricing_reason.ilike("%comparable_results=2%"),
        Listing.pricing_reason.ilike("%comparable_results=3%"),
        Listing.pricing_reason.ilike("%comparable_results=4%"),
        Listing.pricing_reason.ilike("%comparable_results=5%"),
        Listing.pricing_reason.ilike("%comparable_results=6%"),
        Listing.pricing_reason.ilike("%comparable_results=7%"),
        Listing.pricing_reason.ilike("%comparable_results=8%"),
        Listing.pricing_reason.ilike("%comparable_results=9%"),
    )
    buy_now_comparable_signal = or_(
        Listing.pricing_reason.ilike("%buy_now_refs=2%"),
        Listing.pricing_reason.ilike("%buy_now_refs=3%"),
        Listing.pricing_reason.ilike("%buy_now_refs=4%"),
        Listing.pricing_reason.ilike("%buy_now_refs=5%"),
    )
    strong_identity_signal = or_(
        Listing.pricing_reason.ilike("%identity=strong%"),
        Listing.pricing_reason.ilike("%PRICING_STRONG_ID%"),
    )
    false_positive_risk_signal = or_(
        Listing.pricing_reason.ilike("%false_positive_risk=true%"),
        Listing.pricing_reason.ilike("%PRICING_SKIPPED_SNIPER_FALSE_POSITIVE_RISK%"),
    )
    sold_opportunity_signal = and_(
        pricing_basis == "sold",
        sold_comparable_signal,
        or_(
            Listing.is_deal.is_(True),
            Listing.pricing_reason.ilike("%DEAL_ACCEPTED%"),
            Listing.pricing_reason.ilike("%SIMPLE_SOLD_AVG_OPPORTUNITY%"),
            and_(
                confidence_value >= 70,
                or_(
                    score_level.in_(["MEDIUM", "HIGH", "INSANE"]),
                    profit_value >= 5,
                    Listing.discount_percent >= 8,
                ),
            ),
        ),
    )
    buy_now_market_signal = and_(
        pricing_basis == "buy_now",
        buy_now_comparable_signal,
        confidence_value >= 58,
        or_(
            score_level.in_(["MEDIUM", "HIGH", "INSANE"]),
            profit_value >= 10,
            Listing.discount_percent >= 10,
        ),
    )
    return Listing.query.filter(
        pricing_status.in_(["analyzed", "priced", "deal"]),
        pricing_basis.in_(["sold", "buy_now", "mixed"]),
        listing_type.in_(["raw_card", "graded_card", "sealed_product"]),
        or_(Listing.estimated_fair_value.isnot(None), Listing.reference_price.isnot(None)),
        strong_identity_signal,
        or_(Listing.pricing_reason.is_(None), ~false_positive_risk_signal),
        or_(
            Listing.pricing_reason.is_(None),
            ~Listing.pricing_reason.ilike("%PRICE_COMPARE_INSUFFICIENT_RAW_COMPARABLES%"),
        ),
        or_(sold_opportunity_signal, buy_now_market_signal),
    )


def log_smart_deals_diagnostics(query) -> None:
    try:
        final_count = query.limit(31).count()
        pricing_status = db.func.lower(db.func.coalesce(Listing.pricing_status, ""))
        strong_count = Listing.query.filter(Listing.pricing_reason.ilike("%identity=strong%")).count()
        analyzed_count = Listing.query.filter(pricing_status.in_(["analyzed", "priced", "deal"])).count()
        current_app.logger.info(
            "[SNIPER_DEALS_QUERY] final_count=%s analyzed_like=%s strong_identity=%s",
            final_count,
            analyzed_count,
            strong_count,
        )
    except Exception as error:
        current_app.logger.warning(
            "[SNIPER_DEALS_QUERY] diagnostics_failed error=%s",
            error,
        )


@main_bp.route("/missed-deals")
@vip_required
def missed_deals():
    query = build_missed_deals_query()
    log_missed_deals_diagnostics(query)
    return render_deals_board(
        query=query,
        order_by=missed_deal_order(),
        cache_key="feed:missed:v2",
        page_mode="missed",
        board_label="Lost opportunities",
        board_title="Missed Deals already gone",
        board_intro="Sold, removed or unavailable listings detected earlier by TCG Sniper Deals.",
        stat_label="Missed stream",
    )


def build_missed_deals_query():
    status_value = db.func.lower(db.func.coalesce(Listing.status, Listing.available_status, ""))
    confirmation_value = db.func.lower(db.func.coalesce(Listing.available_status, ""))
    return Listing.query.filter(
        status_value.in_(gone_status_values()),
        confirmation_value == "gone_confirmed",
    )


def log_missed_deals_diagnostics(query) -> None:
    try:
        status_value = db.func.lower(db.func.coalesce(Listing.status, Listing.available_status, ""))
        confirmation_value = db.func.lower(db.func.coalesce(Listing.available_status, ""))
        total_candidates = Listing.query.filter(status_value.in_(gone_status_values())).count()
        confirmed = Listing.query.filter(
            status_value.in_(gone_status_values()),
            confirmation_value == "gone_confirmed",
        ).count()
        shown = query.count()
        current_app.logger.info(
            "[MISSED_DEALS_QUERY] total_candidates=%s confirmed=%s shown=%s",
            total_candidates,
            confirmed,
            shown,
        )
    except Exception as error:
        current_app.logger.warning(
            "[MISSED_DEALS_QUERY] diagnostics_failed error=%s",
            error,
        )


@main_bp.route("/ai-market-intel")
@vip_required
def ai_market_intel():
    payload = build_ai_market_intel_payload()
    return render_template(
        "ai_market_intel.html",
        intel=payload,
        active_tab="ai",
        push_enabled=push_enabled(),
    )


@main_bp.route("/api/vip/ai-market-intel")
@vip_required
def ai_market_intel_api():
    return jsonify(build_ai_market_intel_payload())


@main_bp.route("/feed/updates")
@vip_required
def feed_updates():
    cursor_detected_at_raw = request.args.get("latest_detected_at", "").strip()
    cursor_id_raw = request.args.get("latest_id", "").strip()
    limit_raw = request.args.get("limit", "").strip()
    selected_languages = parse_language_filter(request.args.get("language", "").strip())
    selected_sets = parse_set_filter(request.args.get("set", "").strip())
    selected_market_types = parse_market_type_filter(request.args.get("market_type", "").strip())
    region = parse_region_filter(request.args.get("region", "").strip())
    platform = normalize_platform_filter(request.args.get("platform", "").strip())

    try:
        limit = max(1, min(int(limit_raw or current_app.config.get("FEED_DELTA_MAX_ITEMS", 12)), 24))
    except (TypeError, ValueError):
        limit = current_app.config.get("FEED_DELTA_MAX_ITEMS", 12)

    cursor_detected_at = None
    cursor_id = None
    if cursor_detected_at_raw and cursor_id_raw:
        try:
            cursor_detected_at = datetime.fromisoformat(cursor_detected_at_raw.replace("Z", "+00:00"))
            if cursor_detected_at.tzinfo is None:
                cursor_detected_at = cursor_detected_at.replace(tzinfo=timezone.utc)
            cursor_id = int(cursor_id_raw)
        except (TypeError, ValueError):
            cursor_detected_at = None
            cursor_id = None

    started = time.perf_counter()
    detected_at_expr = Listing.detected_at
    query = Listing.query.options(defer(Listing.raw_payload))
    query = apply_listing_filters(query, "", platform, "", selected_languages, selected_sets, region, selected_market_types)
    if cursor_detected_at is not None and cursor_id is not None:
        query = query.filter(
            or_(
                Listing.id > cursor_id,
                detected_at_expr > cursor_detected_at,
                and_(detected_at_expr == cursor_detected_at, Listing.id > cursor_id),
            )
        )
    query = query.order_by(*newest_listing_order()).limit(limit)
    items = query.all()

    rendered_items = []
    for listing in items:
        rendered_items.append(
            {
                "id": listing.id,
                "external_id": listing.external_id,
                "detected_at": listing.detected_at_iso,
                "platform": listing.platform,
                "platform_key": listing.platform.lower().replace(" ", "-") if listing.platform else "",
                "html": render_template("partials/listing_card.html", listing=listing, favorite_ids=set()),
            }
        )

    next_cursor = None
    if items:
        newest = items[0]
        latest_detected_at = newest.detected_at_iso
        if cursor_detected_at is not None and newest.detected_at:
            newest_detected_at = newest.detected_at
            cursor_compare_at = cursor_detected_at
            if newest_detected_at.tzinfo is None and cursor_compare_at.tzinfo is not None:
                newest_detected_at = newest_detected_at.replace(tzinfo=timezone.utc)
            elif newest_detected_at.tzinfo is not None and cursor_compare_at.tzinfo is None:
                cursor_compare_at = cursor_compare_at.replace(tzinfo=timezone.utc)
            if newest_detected_at <= cursor_compare_at:
                latest_detected_at = cursor_detected_at_raw
        next_cursor = {
            "latest_detected_at": latest_detected_at,
            "latest_id": max([cursor_id or 0, *[item.id for item in items]]),
        }

    current_app.logger.debug(
        "[LIVE_POLL] received count=%s",
        len(rendered_items),
    )
    current_app.logger.info(
        "[FEED_FILTER] region=%s platform=%s set=%s language=%s market_type=%s results=%s",
        region or "all",
        platform or "all",
        ",".join(selected_sets) if selected_sets else "all",
        ",".join(selected_languages) if selected_languages else "all",
        ",".join(selected_market_types) if selected_market_types else "all",
        len(rendered_items),
    )
    for item in rendered_items:
        current_app.logger.debug("[LIVE_POLL_ITEM] id=%s platform=%s", item["id"], item["platform"])
    if platform == "ebay":
        newest_item = rendered_items[0] if rendered_items else None
        current_app.logger.info(
            "[EBAY_LIVE_POLL] platform=ebay count=%s newest_id=%s newest_detected_at=%s",
            len(rendered_items),
            newest_item["external_id"] if newest_item else None,
            newest_item["detected_at"] if newest_item else None,
        )
    current_app.logger.debug(
        "[feed-updates] timestamp_source=detected_at returned=%s cursor_detected_at=%s cursor_id=%s first_item_detected_at=%s",
        len(rendered_items),
        next_cursor["latest_detected_at"] if next_cursor else None,
        next_cursor["latest_id"] if next_cursor else None,
        rendered_items[0]["detected_at"] if rendered_items else None,
    )
    if current_app.config.get("LOG_FEED_TIMING", False):
        current_app.logger.info(
            "[feed-updates] returned=%s limit=%s total=%.1fms",
            len(rendered_items),
            limit,
            (time.perf_counter() - started) * 1000,
        )

    response = jsonify(
        {
            "status": "ok",
            "items": rendered_items,
            "cursor": next_cursor,
            "has_more": len(rendered_items) == limit,
        }
    )
    response.headers["Cache-Control"] = "no-store, max-age=0"
    return response


@main_bp.route("/billing", methods=["GET", "POST"])
@main_bp.route("/vip-access", methods=["GET", "POST"])
@login_required
def billing():
    current_plan_key = get_current_plan_key(current_user)
    selected_plan = request.values.get("plan", current_plan_key)
    if selected_plan not in BILLING_PLANS:
        selected_plan = "yearly"

    selected_method = request.values.get("payment_method", "revolut")
    method_keys = {method["key"] for method in BILLING_METHODS}
    if selected_method not in method_keys:
        selected_method = "revolut"

    if request.method == "POST":
        note = request.form.get("note", "").strip() or None
        telegram_username = request.form.get("telegram_username", "").strip() or None
        chosen_plan = request.form.get("plan", selected_plan).strip()
        chosen_method = request.form.get("payment_method", selected_method).strip()

        if chosen_plan not in BILLING_PLANS:
            flash("Choose a valid plan before sending confirmation.", "error")
            return redirect(url_for("main.billing"))

        if chosen_method not in method_keys:
            flash("Choose a valid payment method before sending confirmation.", "error")
            return redirect(url_for("main.billing", plan=chosen_plan))

        if telegram_username:
            current_user.telegram_username = telegram_username

        payment = Payment(
            user_id=current_user.id,
            plan=chosen_plan,
            amount=BILLING_PLANS[chosen_plan]["amount"],
            method=chosen_method.title(),
            status="pending_confirmation",
            notes=note,
        )
        db.session.add(payment)
        db.session.commit()
        flash("Payment confirmation received. Access is delivered shortly after review.", "success")
        return redirect(url_for("main.billing", plan=chosen_plan, payment_method=chosen_method))

    latest_payment = (
        Payment.query.filter_by(user_id=current_user.id)
        .order_by(Payment.created_at.desc())
        .first()
    )

    return render_template(
        "billing.html",
        plans=BILLING_PLANS,
        payment_methods=BILLING_METHODS,
        selected_plan=selected_plan,
        selected_method=selected_method,
        current_plan_key=current_plan_key,
        latest_payment=latest_payment,
    )


@main_bp.route("/listings/<int:listing_id>")
@vip_required
def listing_detail(listing_id):
    listing = db.session.get(Listing, listing_id)
    if not listing:
        return redirect(url_for("main.feed"))
    favorite = Favorite.query.filter_by(user_id=current_user.id, listing_id=listing_id).first() is not None
    return render_template("listing_detail.html", listing=listing, favorite=favorite, push_enabled=push_enabled())


@main_bp.route("/share/<int:listing_id>")
def share_listing(listing_id):
    listing = db.session.get(Listing, listing_id)
    if not listing:
        return redirect(url_for("main.index"))

    return render_template(
        "listing_share.html",
        listing=listing,
        source_url=listing.external_url,
        public_url=url_for("main.share_listing", listing_id=listing.id, _external=True),
    )


@main_bp.route("/favorites", methods=["GET"])
@vip_required
def favorites():
    listings = (
        Listing.query
        .join(Favorite, Favorite.listing_id == Listing.id)
        .options(defer(Listing.raw_payload))
        .filter(Favorite.user_id == current_user.id)
        .order_by(*newest_listing_order())
        .all()
    )
    favorite_ids = {listing.id for listing in listings}
    return render_template(
        "favorites.html",
        listings=listings,
        favorite_ids=favorite_ids,
        push_enabled=push_enabled(),
        saved_count=len(listings),
    )


@main_bp.route("/favorites/<int:listing_id>", methods=["POST"])
@vip_required
def toggle_favorite(listing_id):
    listing = db.session.get(Listing, listing_id)
    if not listing:
        return jsonify({"ok": False, "message": "Listing not found"}), 404

    favorite = Favorite.query.filter_by(user_id=current_user.id, listing_id=listing_id).first()
    if favorite:
        db.session.delete(favorite)
        db.session.commit()
        return jsonify({"ok": True, "saved": False})

    favorite = Favorite(user_id=current_user.id, listing_id=listing_id)
    db.session.add(favorite)
    db.session.commit()
    return jsonify({"ok": True, "saved": True})


@main_bp.route("/profile")
@login_required
def profile():
    saved_count = Favorite.query.filter_by(user_id=current_user.id).count()
    return render_template("profile.html", saved_count=saved_count)


@main_bp.route("/vip-pending")
@login_required
def vip_pending():
    if current_user.is_admin or current_user.vip_active:
        return redirect(url_for("main.feed"))
    return render_template("vip_pending.html")


@main_bp.route("/manifest.webmanifest")
def manifest():
    return send_from_directory(current_app.static_folder, "manifest.webmanifest", mimetype="application/manifest+json")


@main_bp.route("/sitemap.xml")
def sitemap():
    urls = build_sitemap_urls()
    xml = render_template("seo_sitemap.xml", urls=urls)
    return Response(xml, mimetype="application/xml")


@main_bp.route("/robots.txt")
def robots_txt():
    site_root = site_root_url()
    lines = [
        "User-agent: *",
        "Allow: /",
        "Disallow: /feed",
        "Disallow: /favorites",
        "Disallow: /profile",
        "Disallow: /billing",
        "Disallow: /vip",
        "Disallow: /vip-access",
        "Disallow: /vip-pending",
        "Disallow: /admin",
        "Disallow: /api",
        "Disallow: /push-info",
        "Disallow: /push-subscriptions",
        f"Sitemap: {site_root}/sitemap.xml",
        "",
    ]
    return Response("\n".join(lines), mimetype="text/plain")


@main_bp.route("/service-worker.js")
def service_worker():
    return send_from_directory(current_app.static_folder, "service-worker.js", mimetype="application/javascript")


@main_bp.route("/offline")
def offline():
    return render_template("offline.html")


@main_bp.route("/health")
def health():
    return jsonify(
        {
            "status": "ok",
            "app_version": "2026-04-30-ebay-route-trace",
            "git_commit": os.getenv("RENDER_GIT_COMMIT", os.getenv("GIT_COMMIT", "unknown")),
            "ebay_platform_normalization": True,
            "ebay_duplicate_refresh": True,
            "ebay_api_listings_detected_order": True,
            "ebay_deals_platform_filter": True,
            "ebay_route_trace": True,
        }
    ), 200, {"Cache-Control": "no-store, max-age=0"}


@main_bp.route("/push-info")
@login_required
def push_info():
    return jsonify(
        {
            "enabled": push_enabled(),
            "publicKey": current_app.config["VAPID_PUBLIC_KEY"],
        }
    )


@main_bp.route("/push-subscriptions", methods=["POST", "DELETE"])
@vip_required
def save_push_subscription():
    payload = request.get_json(silent=True) or {}
    if request.method == "DELETE":
        endpoint = str(payload.get("endpoint") or "").strip()
        query = PushSubscription.query.filter_by(user_id=current_user.id)
        if endpoint:
            query = query.filter_by(endpoint=endpoint)
        removed = query.delete(synchronize_session=False)
        db.session.commit()
        return jsonify({"ok": True, "removed": removed, "active": False})

    endpoint = payload.get("endpoint")
    keys = payload.get("keys") or {}
    p256dh = keys.get("p256dh")
    auth = keys.get("auth")

    if not endpoint or not p256dh or not auth:
        return jsonify({"ok": False, "message": "Invalid subscription payload"}), 400

    subscription = PushSubscription.query.filter_by(endpoint=endpoint).first()
    if subscription is None:
        subscription = PushSubscription(
            endpoint=endpoint,
            p256dh=p256dh,
            auth=auth,
            user_id=current_user.id,
            user_agent=request.headers.get("User-Agent", "")[:255],
        )
        db.session.add(subscription)
    else:
        subscription.p256dh = p256dh
        subscription.auth = auth
        subscription.user_id = current_user.id
        subscription.user_agent = request.headers.get("User-Agent", "")[:255]

    db.session.commit()
    return jsonify({"ok": True, "active": True})
