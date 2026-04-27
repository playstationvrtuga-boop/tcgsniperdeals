import time
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask
from werkzeug.middleware.proxy_fix import ProxyFix

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
        connection.execute(text("UPDATE listings SET normalized_url = external_url WHERE normalized_url IS NULL"))
        connection.execute(text("UPDATE listings SET available_status = 'available' WHERE available_status IS NULL"))
        connection.execute(text("UPDATE listings SET status = available_status WHERE status IS NULL"))
        connection.execute(text("UPDATE listings SET pricing_status = 'pending' WHERE pricing_status IS NULL"))
        connection.execute(text("UPDATE listings SET is_deal = false WHERE is_deal IS NULL"))
        connection.execute(text("UPDATE listings SET is_vip_only = true WHERE is_vip_only IS NULL"))
        connection.execute(text("UPDATE listings SET free_sent = false WHERE free_sent IS NULL"))
        connection.execute(text("UPDATE listings SET detected_at = posted_at WHERE detected_at IS NULL"))


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
            print("[startup] 4.7) database init completed", flush=True)
    else:
        print("[startup] 4.5) database create_all skipped", flush=True)
        if not skip_db and app.config.get("RUN_STARTUP_SCHEMA_CHECK", False):
            print("[startup] 4.6) running lightweight schema check", flush=True)
            with app.app_context():
                from . import models  # noqa: F401

                ensure_runtime_schema(app)
            print("[startup] 4.7) lightweight schema check completed", flush=True)

    if app.config.get("LOG_STARTUP_TIMING", False):
        elapsed_ms = (time.perf_counter() - startup_started) * 1000
        print(f"[startup] create_app finished in {elapsed_ms:.1f}ms", flush=True)
    print("[startup] 6) create_app finished", flush=True)
    return app
