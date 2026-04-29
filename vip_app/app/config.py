import os
import secrets
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_DB_PATH = BASE_DIR / "data" / "tcg_sniper_deals.db"


def _normalize_multiline_env(value: str) -> str:
    return value.replace("\\n", "\n").strip() if value else value


def _bool_env(name: str) -> bool:
    value = os.getenv(name, "")
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _bool_env_default(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _database_uri() -> str:
    raw = os.getenv("DATABASE_URL", "").strip()
    if not raw:
        return f"sqlite:///{DEFAULT_DB_PATH.as_posix()}"

    if raw.startswith("postgres://"):
        raw = raw.replace("postgres://", "postgresql+psycopg://", 1)
    elif raw.startswith("postgresql://"):
        raw = raw.replace("postgresql://", "postgresql+psycopg://", 1)

    if raw.startswith("sqlite:///"):
        db_path = raw.replace("sqlite:///", "", 1)
        path = Path(db_path)
        if not path.is_absolute():
            path = (BASE_DIR / path).resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        return f"sqlite:///{path.as_posix()}"

    return raw


def _engine_options(database_uri: str) -> dict:
    options = {
        "pool_pre_ping": True,
        "pool_recycle": 280,
    }
    if not database_uri.startswith("sqlite:"):
        options.update(
            {
                "pool_size": int(os.getenv("DB_POOL_SIZE", "5")),
                "max_overflow": int(os.getenv("DB_MAX_OVERFLOW", "5")),
            }
        )
    return options


class Config:
    SECRET_KEY = os.getenv("SECRET_KEY") or secrets.token_urlsafe(32)
    SQLALCHEMY_DATABASE_URI = _database_uri()
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = _engine_options(SQLALCHEMY_DATABASE_URI)
    BOT_API_KEY = os.environ.get("BOT_API_KEY") or os.environ.get("APP_API_KEY", "")
    VAPID_PUBLIC_KEY = os.getenv("VAPID_PUBLIC_KEY", "")
    VAPID_PRIVATE_KEY = _normalize_multiline_env(os.getenv("VAPID_PRIVATE_KEY", ""))
    VAPID_SUBJECT = os.getenv("VAPID_SUBJECT", "mailto:admin@example.com")
    SITE_URL = os.getenv("SITE_URL", "http://127.0.0.1:5000")
    MOBILE_APP_URL = os.getenv("MOBILE_APP_URL", SITE_URL)
    ANDROID_APK_URL = os.getenv("ANDROID_APK_URL", "").strip()
    TELEGRAM_FREE_URL = os.getenv("TELEGRAM_FREE_URL", "https://t.me/tcgsniperdeals").strip()
    IS_PRODUCTION = _bool_env("RENDER") or _bool_env("FLASK_FORCE_HTTPS") or SITE_URL.startswith("https://")
    RUN_STARTUP_SCHEMA_CHECK = _bool_env_default("RUN_STARTUP_SCHEMA_CHECK", True)
    RUN_DB_CREATE_ALL = _bool_env_default("RUN_DB_CREATE_ALL", not IS_PRODUCTION)
    LOG_STARTUP_TIMING = _bool_env_default("LOG_STARTUP_TIMING", IS_PRODUCTION)
    LOG_FEED_TIMING = _bool_env_default("LOG_FEED_TIMING", False)
    FEED_CACHE_TTL_SECONDS = int(os.getenv("FEED_CACHE_TTL_SECONDS", "5"))
    FEED_OPTIONS_CACHE_TTL_SECONDS = int(os.getenv("FEED_OPTIONS_CACHE_TTL_SECONDS", "60"))
    FEED_POLL_INTERVAL_MS = int(os.getenv("FEED_POLL_INTERVAL_MS", "2500"))
    FEED_DELTA_MAX_ITEMS = int(os.getenv("FEED_DELTA_MAX_ITEMS", "12"))
    ENABLE_LIVE_RADAR = _bool_env_default("ENABLE_LIVE_RADAR", True)
    ENABLE_CARD_ENTRY_ANIMATIONS = _bool_env_default("ENABLE_CARD_ENTRY_ANIMATIONS", True)
    ENABLE_RELATIVE_TIME_UPDATES = _bool_env_default("ENABLE_RELATIVE_TIME_UPDATES", True)
    ENABLE_TARGET_FEEDBACK = _bool_env_default("ENABLE_TARGET_FEEDBACK", True)
    RELATIVE_TIME_UPDATE_MS = int(os.getenv("RELATIVE_TIME_UPDATE_MS", "15000"))
    CARDMARKET_TRENDS_ENABLED = _bool_env_default("CARDMARKET_TRENDS_ENABLED", True)
    CARDMARKET_TRENDS_INTERVAL_HOURS = int(os.getenv("CARDMARKET_TRENDS_INTERVAL_HOURS", "24"))
    CARDMARKET_TRENDS_MAX_ITEMS = int(os.getenv("CARDMARKET_TRENDS_MAX_ITEMS", "20"))
    CARDMARKET_TRENDS_SOURCE_URL = os.getenv("CARDMARKET_TRENDS_SOURCE_URL", "https://www.cardmarket.com/en/Pokemon")
    CARDMARKET_TRENDS_TIMEOUT_SECONDS = float(os.getenv("CARDMARKET_TRENDS_TIMEOUT_SECONDS", "20"))
    CARDMARKET_TRENDS_USER_AGENT = os.getenv("CARDMARKET_TRENDS_USER_AGENT", "TCGSniperDealsBot/1.0")
    SESSION_COOKIE_SECURE = IS_PRODUCTION
    REMEMBER_COOKIE_SECURE = IS_PRODUCTION
    SESSION_COOKIE_HTTPONLY = True
    REMEMBER_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    REMEMBER_COOKIE_SAMESITE = "Lax"
    PREFERRED_URL_SCHEME = "https" if IS_PRODUCTION else "http"
    SEND_FILE_MAX_AGE_DEFAULT = 60
