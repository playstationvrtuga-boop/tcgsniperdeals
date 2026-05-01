import time
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, redirect, request
from werkzeug.middleware.proxy_fix import ProxyFix

from services.site_config import DEFAULT_PUBLIC_SITE_URL, OLD_PUBLIC_SITE_HOST, normalize_public_site_url

from .extensions import db, login_manager
from .filters import datetime_format, register_template_filters, relative_time, urgency_hint


def ensure_runtime_schema(app):
    if not app.config.get("RUN_STARTUP_SCHEMA_CHECK", False):
        return

    from sqlalchemy import inspect, text

    inspector = inspect(db.engine)
    if "listings" not in inspector.get_table_names():
        return

    existing_columns = {column["name"] for column in inspector.get_columns("listings")}
    is_sqlite = db.engine.dialect.name == "sqlite"
    if is_sqlite:
        alter_statements = {
            "normalized_url": "ALTER TABLE listings ADD COLUMN normalized_url VARCHAR(1000)",
            "score": "ALTER TABLE listings ADD COLUMN score FLOAT",
            "category": "ALTER TABLE listings ADD COLUMN category VARCHAR(80)",
            "available_status": "ALTER TABLE listings ADD COLUMN available_status VARCHAR(40)",
            "pricing_status": "ALTER TABLE listings ADD COLUMN pricing_status VARCHAR(40)",
            "pricing_checked_at": "ALTER TABLE listings ADD COLUMN pricing_checked_at DATETIME",
            "pricing_error": "ALTER TABLE listings ADD COLUMN pricing_error VARCHAR(255)",
            "reference_price": "ALTER TABLE listings ADD COLUMN reference_price FLOAT",
            "market_buy_now_min": "ALTER TABLE listings ADD COLUMN market_buy_now_min FLOAT",
            "market_buy_now_avg": "ALTER TABLE listings ADD COLUMN market_buy_now_avg FLOAT",
            "market_buy_now_median": "ALTER TABLE listings ADD COLUMN market_buy_now_median FLOAT",
            "last_sold_prices_json": "ALTER TABLE listings ADD COLUMN last_sold_prices_json TEXT",
            "last_2_sales_json": "ALTER TABLE listings ADD COLUMN last_2_sales_json TEXT",
            "sold_avg_price": "ALTER TABLE listings ADD COLUMN sold_avg_price FLOAT",
            "sold_median_price": "ALTER TABLE listings ADD COLUMN sold_median_price FLOAT",
            "estimated_fair_value": "ALTER TABLE listings ADD COLUMN estimated_fair_value FLOAT",
            "pricing_basis": "ALTER TABLE listings ADD COLUMN pricing_basis VARCHAR(40)",
            "confidence_score": "ALTER TABLE listings ADD COLUMN confidence_score INTEGER",
            "listing_type": "ALTER TABLE listings ADD COLUMN listing_type VARCHAR(40)",
            "card_language": "ALTER TABLE listings ADD COLUMN card_language VARCHAR(20)",
            "set_code": "ALTER TABLE listings ADD COLUMN set_code VARCHAR(20)",
            "set_name": "ALTER TABLE listings ADD COLUMN set_name VARCHAR(100)",
            "cardmarket_trending_score": "ALTER TABLE listings ADD COLUMN cardmarket_trending_score INTEGER",
            "cardmarket_trend_rank": "ALTER TABLE listings ADD COLUMN cardmarket_trend_rank INTEGER",
            "cardmarket_trend_category": "ALTER TABLE listings ADD COLUMN cardmarket_trend_category VARCHAR(40)",
            "ai_market_intel_verdict": "ALTER TABLE listings ADD COLUMN ai_market_intel_verdict VARCHAR(40)",
            "estimated_profit": "ALTER TABLE listings ADD COLUMN estimated_profit FLOAT",
            "discount_percent": "ALTER TABLE listings ADD COLUMN discount_percent FLOAT",
            "profit_margin": "ALTER TABLE listings ADD COLUMN profit_margin FLOAT",
            "gross_margin": "ALTER TABLE listings ADD COLUMN gross_margin FLOAT",
            "pricing_score": "ALTER TABLE listings ADD COLUMN pricing_score INTEGER",
            "score_level": "ALTER TABLE listings ADD COLUMN score_level VARCHAR(40)",
            "pricing_reason": "ALTER TABLE listings ADD COLUMN pricing_reason VARCHAR(255)",
            "pricing_analyzed_at": "ALTER TABLE listings ADD COLUMN pricing_analyzed_at DATETIME",
            "status": "ALTER TABLE listings ADD COLUMN status VARCHAR(40)",
            "status_updated_at": "ALTER TABLE listings ADD COLUMN status_updated_at DATETIME",
            "availability_checked_at": "ALTER TABLE listings ADD COLUMN availability_checked_at DATETIME",
            "gone_detected_at": "ALTER TABLE listings ADD COLUMN gone_detected_at DATETIME",
            "gone_alert_sent_at": "ALTER TABLE listings ADD COLUMN gone_alert_sent_at DATETIME",
            "sold_after_seconds": "ALTER TABLE listings ADD COLUMN sold_after_seconds INTEGER",
            "is_deal": "ALTER TABLE listings ADD COLUMN is_deal BOOLEAN",
            "deal_alert_sent_at": "ALTER TABLE listings ADD COLUMN deal_alert_sent_at DATETIME",
            "alert_title": "ALTER TABLE listings ADD COLUMN alert_title VARCHAR(80)",
            "partial_title": "ALTER TABLE listings ADD COLUMN partial_title VARCHAR(255)",
            "confidence_label": "ALTER TABLE listings ADD COLUMN confidence_label VARCHAR(40)",
            "deal_level": "ALTER TABLE listings ADD COLUMN deal_level VARCHAR(40)",
            "is_vip_only": "ALTER TABLE listings ADD COLUMN is_vip_only BOOLEAN",
            "free_send_at": "ALTER TABLE listings ADD COLUMN free_send_at DATETIME",
            "free_sent": "ALTER TABLE listings ADD COLUMN free_sent BOOLEAN",
            "free_message_variant": "ALTER TABLE listings ADD COLUMN free_message_variant VARCHAR(16)",
            "detected_at": "ALTER TABLE listings ADD COLUMN detected_at DATETIME",
            "source_published_at": "ALTER TABLE listings ADD COLUMN source_published_at DATETIME",
        }
    else:
        alter_statements = {
            "normalized_url": "ALTER TABLE listings ADD COLUMN IF NOT EXISTS normalized_url VARCHAR(1000)",
            "score": "ALTER TABLE listings ADD COLUMN IF NOT EXISTS score DOUBLE PRECISION",
            "category": "ALTER TABLE listings ADD COLUMN IF NOT EXISTS category VARCHAR(80)",
            "available_status": "ALTER TABLE listings ADD COLUMN IF NOT EXISTS available_status VARCHAR(40)",
            "pricing_status": "ALTER TABLE listings ADD COLUMN IF NOT EXISTS pricing_status VARCHAR(40)",
            "pricing_checked_at": "ALTER TABLE listings ADD COLUMN IF NOT EXISTS pricing_checked_at TIMESTAMP WITH TIME ZONE",
            "pricing_error": "ALTER TABLE listings ADD COLUMN IF NOT EXISTS pricing_error VARCHAR(255)",
            "reference_price": "ALTER TABLE listings ADD COLUMN IF NOT EXISTS reference_price DOUBLE PRECISION",
            "market_buy_now_min": "ALTER TABLE listings ADD COLUMN IF NOT EXISTS market_buy_now_min DOUBLE PRECISION",
            "market_buy_now_avg": "ALTER TABLE listings ADD COLUMN IF NOT EXISTS market_buy_now_avg DOUBLE PRECISION",
            "market_buy_now_median": "ALTER TABLE listings ADD COLUMN IF NOT EXISTS market_buy_now_median DOUBLE PRECISION",
            "last_sold_prices_json": "ALTER TABLE listings ADD COLUMN IF NOT EXISTS last_sold_prices_json TEXT",
            "last_2_sales_json": "ALTER TABLE listings ADD COLUMN IF NOT EXISTS last_2_sales_json TEXT",
            "sold_avg_price": "ALTER TABLE listings ADD COLUMN IF NOT EXISTS sold_avg_price DOUBLE PRECISION",
            "sold_median_price": "ALTER TABLE listings ADD COLUMN IF NOT EXISTS sold_median_price DOUBLE PRECISION",
            "estimated_fair_value": "ALTER TABLE listings ADD COLUMN IF NOT EXISTS estimated_fair_value DOUBLE PRECISION",
            "pricing_basis": "ALTER TABLE listings ADD COLUMN IF NOT EXISTS pricing_basis VARCHAR(40)",
            "confidence_score": "ALTER TABLE listings ADD COLUMN IF NOT EXISTS confidence_score INTEGER",
            "listing_type": "ALTER TABLE listings ADD COLUMN IF NOT EXISTS listing_type VARCHAR(40)",
            "card_language": "ALTER TABLE listings ADD COLUMN IF NOT EXISTS card_language VARCHAR(20)",
            "set_code": "ALTER TABLE listings ADD COLUMN IF NOT EXISTS set_code VARCHAR(20)",
            "set_name": "ALTER TABLE listings ADD COLUMN IF NOT EXISTS set_name VARCHAR(100)",
            "cardmarket_trending_score": "ALTER TABLE listings ADD COLUMN IF NOT EXISTS cardmarket_trending_score INTEGER",
            "cardmarket_trend_rank": "ALTER TABLE listings ADD COLUMN IF NOT EXISTS cardmarket_trend_rank INTEGER",
            "cardmarket_trend_category": "ALTER TABLE listings ADD COLUMN IF NOT EXISTS cardmarket_trend_category VARCHAR(40)",
            "ai_market_intel_verdict": "ALTER TABLE listings ADD COLUMN IF NOT EXISTS ai_market_intel_verdict VARCHAR(40)",
            "estimated_profit": "ALTER TABLE listings ADD COLUMN IF NOT EXISTS estimated_profit DOUBLE PRECISION",
            "discount_percent": "ALTER TABLE listings ADD COLUMN IF NOT EXISTS discount_percent DOUBLE PRECISION",
            "profit_margin": "ALTER TABLE listings ADD COLUMN IF NOT EXISTS profit_margin DOUBLE PRECISION",
            "gross_margin": "ALTER TABLE listings ADD COLUMN IF NOT EXISTS gross_margin DOUBLE PRECISION",
            "pricing_score": "ALTER TABLE listings ADD COLUMN IF NOT EXISTS pricing_score INTEGER",
            "score_level": "ALTER TABLE listings ADD COLUMN IF NOT EXISTS score_level VARCHAR(40)",
            "pricing_reason": "ALTER TABLE listings ADD COLUMN IF NOT EXISTS pricing_reason VARCHAR(255)",
            "pricing_analyzed_at": "ALTER TABLE listings ADD COLUMN IF NOT EXISTS pricing_analyzed_at TIMESTAMP WITH TIME ZONE",
            "status": "ALTER TABLE listings ADD COLUMN IF NOT EXISTS status VARCHAR(40)",
            "status_updated_at": "ALTER TABLE listings ADD COLUMN IF NOT EXISTS status_updated_at TIMESTAMP WITH TIME ZONE",
            "availability_checked_at": "ALTER TABLE listings ADD COLUMN IF NOT EXISTS availability_checked_at TIMESTAMP WITH TIME ZONE",
            "gone_detected_at": "ALTER TABLE listings ADD COLUMN IF NOT EXISTS gone_detected_at TIMESTAMP WITH TIME ZONE",
            "gone_alert_sent_at": "ALTER TABLE listings ADD COLUMN IF NOT EXISTS gone_alert_sent_at TIMESTAMP WITH TIME ZONE",
            "sold_after_seconds": "ALTER TABLE listings ADD COLUMN IF NOT EXISTS sold_after_seconds INTEGER",
            "is_deal": "ALTER TABLE listings ADD COLUMN IF NOT EXISTS is_deal BOOLEAN",
            "deal_alert_sent_at": "ALTER TABLE listings ADD COLUMN IF NOT EXISTS deal_alert_sent_at TIMESTAMP WITH TIME ZONE",
            "alert_title": "ALTER TABLE listings ADD COLUMN IF NOT EXISTS alert_title VARCHAR(80)",
            "partial_title": "ALTER TABLE listings ADD COLUMN IF NOT EXISTS partial_title VARCHAR(255)",
            "confidence_label": "ALTER TABLE listings ADD COLUMN IF NOT EXISTS confidence_label VARCHAR(40)",
            "deal_level": "ALTER TABLE listings ADD COLUMN IF NOT EXISTS deal_level VARCHAR(40)",
            "is_vip_only": "ALTER TABLE listings ADD COLUMN IF NOT EXISTS is_vip_only BOOLEAN",
            "free_send_at": "ALTER TABLE listings ADD COLUMN IF NOT EXISTS free_send_at TIMESTAMP WITH TIME ZONE",
            "free_sent": "ALTER TABLE listings ADD COLUMN IF NOT EXISTS free_sent BOOLEAN",
            "free_message_variant": "ALTER TABLE listings ADD COLUMN IF NOT EXISTS free_message_variant VARCHAR(16)",
            "detected_at": "ALTER TABLE listings ADD COLUMN IF NOT EXISTS detected_at TIMESTAMP WITH TIME ZONE",
            "source_published_at": "ALTER TABLE listings ADD COLUMN IF NOT EXISTS source_published_at TIMESTAMP WITH TIME ZONE",
        }

    with db.engine.begin() as connection:
        for column_name, statement in alter_statements.items():
            if column_name not in existing_columns:
                connection.execute(text(statement))

        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_listings_normalized_url ON listings (normalized_url)"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_listings_detected_at ON listings (detected_at)"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_listings_detected_at_id ON listings (detected_at, id)"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_listings_pricing_status ON listings (pricing_status)"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_listings_score_level ON listings (score_level)"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_listings_gone_detected_at ON listings (gone_detected_at)"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_listings_status_updated_at ON listings (status_updated_at)"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_listings_availability_checked_at ON listings (availability_checked_at)"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_listings_platform_detected_at ON listings (platform, detected_at)"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_listings_is_deal_detected_at ON listings (is_deal, detected_at)"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_listings_badge_label_detected_at ON listings (badge_label, detected_at)"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_listings_set_code ON listings (set_code)"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_listings_cardmarket_trend ON listings (cardmarket_trend_category, cardmarket_trend_rank)"))
        connection.execute(text("UPDATE listings SET normalized_url = external_url WHERE normalized_url IS NULL"))
        connection.execute(text("UPDATE listings SET available_status = 'available' WHERE available_status IS NULL"))
        connection.execute(text("UPDATE listings SET status = available_status WHERE status IS NULL"))
        connection.execute(text("UPDATE listings SET pricing_status = 'pending' WHERE pricing_status IS NULL"))
        connection.execute(text("UPDATE listings SET is_deal = false WHERE is_deal IS NULL"))
        connection.execute(text("UPDATE listings SET is_vip_only = true WHERE is_vip_only IS NULL"))
        connection.execute(text("UPDATE listings SET free_sent = false WHERE free_sent IS NULL"))
        connection.execute(text("UPDATE listings SET detected_at = created_at WHERE detected_at IS NULL"))

    from .models import CardmarketTrend

    CardmarketTrend.__table__.create(db.engine, checkfirst=True)
    inspector = inspect(db.engine)
    cardmarket_columns = {column["name"] for column in inspector.get_columns("cardmarket_trends")}
    if "image_data_url" not in cardmarket_columns:
        statement = (
            "ALTER TABLE cardmarket_trends ADD COLUMN image_data_url TEXT"
            if is_sqlite
            else "ALTER TABLE cardmarket_trends ADD COLUMN IF NOT EXISTS image_data_url TEXT"
        )
        with db.engine.begin() as connection:
            connection.execute(text(statement))


def backfill_listing_set_metadata(app, limit=1000):
    if not app.config.get("RUN_STARTUP_SCHEMA_CHECK", False):
        return

    from services.pokemon_title_parser import detect_pokemon_set
    from .models import Listing

    try:
        missing_rows = (
            Listing.query.filter(
                (Listing.set_code.is_(None)) | (Listing.set_code == ""),
            )
            .order_by(Listing.id.desc())
            .limit(limit)
            .all()
        )
    except Exception as error:
        app.logger.warning("[SET_DETECT] backfill skipped error=%s", error)
        return

    updated = 0
    for listing in missing_rows:
        detected = detect_pokemon_set(listing.title or "")
        if not detected.get("set_code"):
            continue
        listing.set_code = detected.get("set_code")
        listing.set_name = detected.get("set_name")
        updated += 1
        app.logger.info(
            "[SET_DETECT] listing_id=%s set_code=%s set_name=%s confidence=%s",
            listing.id,
            listing.set_code,
            listing.set_name,
            detected.get("confidence") or "unknown",
        )
    if updated:
        db.session.commit()
        app.logger.info("[SET_DETECT] backfill updated=%s scanned=%s", updated, len(missing_rows))


def create_app(minimal=False, skip_db=False, skip_blueprints=False):
    startup_started = time.perf_counter()
    print("[startup] 3) create_app started", flush=True)
    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
    print("[startup] 3.1) .env loaded", flush=True)
    from .config import Config
    print("[startup] 3.2) Config imported", flush=True)

    app = Flask(
        __name__,
        template_folder="templates",
        static_folder="static",
    )
    print("[startup] 3.3) Flask app object created", flush=True)
    app.config.from_object(Config)
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)
    print("[startup] 3.4) Config applied", flush=True)

    if minimal:
        @app.get("/")
        def minimal_home():
            return "TCG Sniper Deals minimal app is running"

        print("[startup] 5) minimal route registered", flush=True)
        if app.config.get("LOG_STARTUP_TIMING", False):
            elapsed_ms = (time.perf_counter() - startup_started) * 1000
            print(f"[startup] create_app finished in {elapsed_ms:.1f}ms", flush=True)
        print("[startup] 6) create_app finished", flush=True)
        return app

    if app.config["SQLALCHEMY_DATABASE_URI"].startswith("sqlite:"):
        data_dir = Path(app.root_path).parent / "data"
        data_dir.mkdir(parents=True, exist_ok=True)
        print("[startup] 3.5) data directory ensured", flush=True)

    run_db_create_all = app.config.get("RUN_DB_CREATE_ALL", not app.config.get("IS_PRODUCTION", False))
    if not skip_db:
        db.init_app(app)
        print("[startup] 4.1) database extension init completed", flush=True)
    else:
        print("[startup] 4.1) database extension skipped", flush=True)

    login_manager.init_app(app)
    print("[startup] 4.2) login manager init completed", flush=True)
    register_template_filters(app)
    app.add_template_filter(datetime_format, "datetime_format")
    app.add_template_filter(relative_time, "relative_time")
    app.add_template_filter(urgency_hint, "urgency_hint")

    from services.ebay_affiliate import build_ebay_affiliate_url

    def ebay_affiliate_url(value, source="website", listing_id=None):
        return build_ebay_affiliate_url(value, source, listing_id=listing_id)

    app.add_template_filter(ebay_affiliate_url, "ebay_affiliate_url")

    @app.context_processor
    def inject_public_links():
        return {
            "telegram_free_url": app.config.get("TELEGRAM_FREE_URL", ""),
            "public_site_url": app.config.get("PUBLIC_SITE_URL", ""),
        }

    @app.before_request
    def redirect_legacy_public_host():
        forwarded_host = (request.headers.get("X-Forwarded-Host") or "").split(",", 1)[0].strip()
        host_candidates = [
            forwarded_host,
            request.host,
            request.environ.get("HTTP_HOST", ""),
            request.environ.get("SERVER_NAME", ""),
        ]
        hosts = {candidate.split(":", 1)[0].lower() for candidate in host_candidates if candidate}
        if OLD_PUBLIC_SITE_HOST not in hosts:
            return None

        path = request.path or "/"
        technical_prefixes = ("/api", "/static", "/assets")
        technical_paths = {"/health", "/service-worker.js", "/manifest.webmanifest"}
        if path in technical_paths or path.startswith(technical_prefixes):
            return None

        public_site_url = normalize_public_site_url(app.config.get("PUBLIC_SITE_URL"), default=DEFAULT_PUBLIC_SITE_URL)
        target = f"{public_site_url}{request.full_path}"
        return redirect(target[:-1] if target.endswith("?") else target, code=301)

    print("[startup] 4.3) template filters registered", flush=True)

    if skip_blueprints:
        print("[startup] 5) blueprint registration skipped", flush=True)
        print("[startup] 6) create_app finished", flush=True)
        return app

    print("[startup] 4.4) importing route blueprints", flush=True)
    from .auth import auth_bp
    from .main import main_bp
    from .admin import admin_bp
    from .api import api_bp

    print("[startup] 5) registering routes", flush=True)
    app.register_blueprint(auth_bp)
    app.register_blueprint(main_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(api_bp, url_prefix="/api")
    print("[startup] 5.1) routes registered", flush=True)

    if not skip_db and run_db_create_all:
        print("[startup] 4.5) importing models", flush=True)
        with app.app_context():
            from . import models  # noqa: F401

            print("[startup] 4.6) models imported", flush=True)
            db.create_all()
            ensure_runtime_schema(app)
            backfill_listing_set_metadata(app)
            print("[startup] 4.7) database init completed", flush=True)
    else:
        print("[startup] 4.5) database create_all skipped", flush=True)
        if not skip_db and app.config.get("RUN_STARTUP_SCHEMA_CHECK", False):
            print("[startup] 4.6) running lightweight schema check", flush=True)
            with app.app_context():
                from . import models  # noqa: F401

                ensure_runtime_schema(app)
                backfill_listing_set_metadata(app)
            print("[startup] 4.7) lightweight schema check completed", flush=True)

    if app.config.get("LOG_STARTUP_TIMING", False):
        elapsed_ms = (time.perf_counter() - startup_started) * 1000
        print(f"[startup] create_app finished in {elapsed_ms:.1f}ms", flush=True)
    print("[startup] 6) create_app finished", flush=True)
    return app
