from pathlib import Path

from dotenv import load_dotenv
from flask import Flask
from sqlalchemy import inspect, text
from werkzeug.middleware.proxy_fix import ProxyFix

from .extensions import db, login_manager
from .filters import datetime_format, register_template_filters, relative_time, urgency_hint


def ensure_runtime_schema(app):
    if not app.config.get("SQLALCHEMY_DATABASE_URI", "").startswith("sqlite"):
        return

    inspector = inspect(db.engine)
    if "listings" not in inspector.get_table_names():
        return

    existing_columns = {column["name"] for column in inspector.get_columns("listings")}
    alter_statements = {
        "normalized_url": "ALTER TABLE listings ADD COLUMN normalized_url VARCHAR(1000)",
        "score": "ALTER TABLE listings ADD COLUMN score FLOAT",
        "category": "ALTER TABLE listings ADD COLUMN category VARCHAR(80)",
        "available_status": "ALTER TABLE listings ADD COLUMN available_status VARCHAR(40)",
        "detected_at": "ALTER TABLE listings ADD COLUMN detected_at DATETIME",
        "source_published_at": "ALTER TABLE listings ADD COLUMN source_published_at DATETIME",
    }

    with db.engine.begin() as connection:
        for column_name, statement in alter_statements.items():
            if column_name not in existing_columns:
                connection.execute(text(statement))

        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_listings_normalized_url ON listings (normalized_url)"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_listings_detected_at ON listings (detected_at)"))
        connection.execute(text("UPDATE listings SET normalized_url = external_url WHERE normalized_url IS NULL"))
        connection.execute(text("UPDATE listings SET available_status = 'available' WHERE available_status IS NULL"))
        connection.execute(text("UPDATE listings SET detected_at = posted_at WHERE detected_at IS NULL"))


def create_app(minimal=False, skip_db=False, skip_blueprints=False):
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
        print("[startup] 6) create_app finished", flush=True)
        return app

    data_dir = Path(app.root_path).parent / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    print("[startup] 3.5) data directory ensured", flush=True)

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

    if not skip_db:
        print("[startup] 4.5) importing models", flush=True)
        with app.app_context():
            from . import models  # noqa: F401

            print("[startup] 4.6) models imported", flush=True)
            db.create_all()
            ensure_runtime_schema(app)
            print("[startup] 4.7) database init completed", flush=True)
    else:
        print("[startup] 4.5) database create_all skipped", flush=True)

    print("[startup] 6) create_app finished", flush=True)
    return app
