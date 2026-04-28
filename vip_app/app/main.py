from datetime import datetime, timezone
import time
from decimal import Decimal
from pathlib import Path

from flask import Blueprint, Response, current_app, flash, jsonify, redirect, render_template, request, send_file, send_from_directory, url_for
from flask_login import current_user, login_required
from sqlalchemy import and_, case, or_
from sqlalchemy.orm import defer

from services.ai_market_intel import build_ai_market_intel_payload

from .decorators import vip_required
from .extensions import db
from .feed_cache import get_or_set
from .models import Favorite, Listing, Payment, PushSubscription
from .push import push_enabled


main_bp = Blueprint("main", __name__)


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

from .seo_content import SEO_HOME_CONTENT, SEO_PAGE_ALIASES, SEO_PAGES, SEO_PUBLIC_PATHS


def site_root_url():
    return (current_app.config.get("SITE_URL") or request.url_root).rstrip("/")


def canonical_for_path(path):
    normalized_path = path if path.startswith("/") else f"/{path}"
    return f"{site_root_url()}{normalized_path}"


def build_seo_page_context(slug):
    data = SEO_PAGES[slug]
    page = {
        "slug": slug,
        "title": data["title"],
        "meta_description": data["meta_description"],
        "h1": data["h1"],
        "intro": data["intro"],
        "sections": [dict(section) for section in data["sections"]],
        "related_pages": [
            {
                "slug": related_slug,
                "label": SEO_PAGES[related_slug]["h1"],
                "url": f"/{related_slug}",
            }
            for related_slug in data.get("related", [])
            if related_slug in SEO_PAGES
        ],
    }
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
    for slug in SEO_PAGES:
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
    return [
        {
            "loc": f"{site_root}{path}",
            "lastmod": today,
        }
        for path in SEO_PUBLIC_PATHS
    ]


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
        db.func.coalesce(Listing.detected_at, Listing.created_at).desc(),
        Listing.created_at.desc(),
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


def apply_listing_filters(query, search, platform, badge):
    if search:
        query = query.filter(Listing.title.ilike(f"%{search}%"))
    if platform:
        query = query.filter(Listing.platform == platform)
    if badge:
        if badge == "Fresh":
            query = query.filter(Listing.is_deal.is_(False))
        else:
            query = query.filter(Listing.is_deal.is_(True), Listing.badge_label == badge)
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
):
    feed_started = time.perf_counter()
    search = request.args.get("q", "").strip()
    platform = request.args.get("platform", "").strip()
    badge = request.args.get("badge", "").strip()
    query = apply_listing_filters(query.options(defer(Listing.raw_payload)), search, platform, badge)

    cache_hit = False
    if cache_key and not search and not platform and not badge:
        def build_snapshot():
            listings = query.order_by(*order_by).limit(60).all()
            return {
                "listings": listings,
                "live_listings_count": len(listings),
                "deal_count": sum(1 for listing in listings if listing.is_deal),
                "last_detected_at": listings[0].feed_timestamp if listings else None,
            }

        feed_snapshot, cache_hit = get_or_set(cache_key, current_app.config["FEED_CACHE_TTL_SECONDS"], build_snapshot)
        listings = feed_snapshot["listings"]
        live_listings_count = feed_snapshot["live_listings_count"]
        deal_count = feed_snapshot["deal_count"]
        last_detected_at = feed_snapshot["last_detected_at"]
    else:
        listings = query.order_by(*order_by).limit(60).all()
        live_listings_count = len(listings)
        deal_count = sum(1 for listing in listings if listing.is_deal)
        last_detected_at = listings[0].feed_timestamp if listings else None

    live_stats = {
        "count": live_listings_count,
        "deal_count": deal_count,
        "last_detected_at": last_detected_at,
        "alerts_active": alerts_are_active(),
    }
    platforms, badges = feed_options()

    if current_app.config.get("LOG_FEED_TIMING", False):
        total_ms = (time.perf_counter() - feed_started) * 1000
        current_app.logger.info(
            "[%s] cache=%s listings=%s total=%.1fms",
            page_mode,
            "hit" if cache_hit else "miss",
            len(listings),
            total_ms,
        )

    return render_template(
        "feed.html",
        listings=listings,
        favorite_ids=favorite_ids_for_current_user(),
        push_enabled=push_enabled(),
        platforms=platforms,
        badges=badges,
        search=search,
        selected_platform=platform,
        selected_badge=badge,
        live_stats=live_stats,
        feed_poll_interval_ms=current_app.config["FEED_POLL_INTERVAL_MS"],
        feed_delta_max_items=current_app.config["FEED_DELTA_MAX_ITEMS"],
        enable_live_radar=current_app.config["ENABLE_LIVE_RADAR"] and page_mode == "live",
        enable_target_feedback=current_app.config["ENABLE_TARGET_FEEDBACK"] and page_mode == "live",
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
        "last_detected_at": listings[0].feed_timestamp if listings else None,
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
@vip_required
def feed():
    return render_deals_board(
        query=Listing.query,
        order_by=newest_listing_order(),
        cache_key=None,
        page_mode="live",
    )


@main_bp.route("/smart-deals")
@vip_required
def smart_deals():
    score_level = db.func.upper(db.func.coalesce(Listing.score_level, ""))
    profit_value = db.func.coalesce(Listing.estimated_profit, Listing.profit_margin, Listing.gross_margin, 0)
    pricing_status = db.func.lower(db.func.coalesce(Listing.pricing_status, ""))
    pricing_basis = db.func.lower(db.func.coalesce(Listing.pricing_basis, ""))
    confidence_value = db.func.coalesce(Listing.confidence_score, 0)
    query = Listing.query.filter(
        pricing_status.in_(["analyzed", "priced", "deal"]),
        pricing_basis.in_(["sold", "buy_now", "mixed"]),
        or_(Listing.estimated_fair_value.isnot(None), Listing.reference_price.isnot(None)),
        confidence_value >= 50,
        or_(
            Listing.pricing_reason.is_(None),
            ~Listing.pricing_reason.ilike("%PRICE_COMPARE_INSUFFICIENT_RAW_COMPARABLES%"),
        ),
        or_(
            Listing.is_deal.is_(True),
            score_level.in_(["MEDIUM", "HIGH", "INSANE"]),
            profit_value >= 10,
            Listing.discount_percent >= 10,
        ),
    )
    return render_deals_board(
        query=query,
        order_by=smart_deal_order(),
        cache_key="feed:smart:v3",
        page_mode="smart",
        board_label="Sniper pricing",
        board_title="Sniper Deals with pricing edge",
        board_intro="Only enriched listings with market signals, discount pressure or real profit potential.",
        stat_label="Sniper stream",
    )


@main_bp.route("/missed-deals")
@vip_required
def missed_deals():
    status_value = db.func.lower(db.func.coalesce(Listing.status, Listing.available_status, ""))
    query = Listing.query.filter(status_value.in_(gone_status_values()))
    return render_deals_board(
        query=query,
        order_by=missed_deal_order(),
        cache_key="feed:missed",
        page_mode="missed",
        board_label="Lost opportunities",
        board_title="Missed Deals already gone",
        board_intro="Sold, removed or unavailable listings detected earlier by TCG Sniper Deals.",
        stat_label="Missed stream",
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
    feed_timestamp_expr = db.func.coalesce(Listing.detected_at, Listing.created_at)
    query = Listing.query.options(defer(Listing.raw_payload))
    if cursor_detected_at is not None and cursor_id is not None:
        query = query.filter(
            or_(
                feed_timestamp_expr > cursor_detected_at,
                and_(feed_timestamp_expr == cursor_detected_at, Listing.id > cursor_id),
            )
        )
    query = query.order_by(*newest_listing_order()).limit(limit)
    items = query.all()

    rendered_items = []
    for listing in items:
        rendered_items.append(
            {
                "id": listing.id,
                "detected_at": listing.feed_timestamp_iso,
                "platform": listing.platform,
                "platform_key": listing.platform.lower().replace(" ", "-") if listing.platform else "",
                "html": render_template("partials/listing_card.html", listing=listing, favorite_ids=set()),
            }
        )

    next_cursor = None
    if items:
        newest = items[0]
        next_cursor = {
            "latest_detected_at": newest.feed_timestamp_iso,
            "latest_id": newest.id,
        }

    if current_app.config.get("LOG_FEED_TIMING", False):
        current_app.logger.info(
            "[feed-updates] returned=%s limit=%s total=%.1fms",
            len(rendered_items),
            limit,
            (time.perf_counter() - started) * 1000,
        )

    return jsonify(
        {
            "status": "ok",
            "items": rendered_items,
            "cursor": next_cursor,
            "has_more": len(rendered_items) == limit,
        }
    )


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
    site_root = (current_app.config.get("SITE_URL") or request.url_root).rstrip("/")
    lines = [
        "User-agent: *",
        "Allow: /",
        "Disallow: /feed",
        "Disallow: /deals",
        "Disallow: /live-deals",
        "Disallow: /smart-deals",
        "Disallow: /missed-deals",
        "Disallow: /favorites",
        "Disallow: /profile",
        "Disallow: /billing",
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
    return "ok", 200, {"Cache-Control": "no-store, max-age=0"}


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
