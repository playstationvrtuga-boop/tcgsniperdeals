import os
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_DB_PATH = BASE_DIR / "data" / "tcg_sniper_deals.db"


def _normalize_multiline_env(value: str) -> str:
    return value.replace("\\n", "\n").strip() if value else value


def _database_uri() -> str:
    raw = os.getenv("DATABASE_URL", "").strip()
    if not raw:
        return f"sqlite:///{DEFAULT_DB_PATH.as_posix()}"

    if raw.startswith("postgres://"):
        raw = raw.replace("postgres://", "postgresql+psycopg2://", 1)
    elif raw.startswith("postgresql://"):
        raw = raw.replace("postgresql://", "postgresql+psycopg2://", 1)

    if raw.startswith("sqlite:///"):
        db_path = raw.replace("sqlite:///", "", 1)
        path = Path(db_path)
        if not path.is_absolute():
            path = (BASE_DIR / path).resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        return f"sqlite:///{path.as_posix()}"

    return raw


class Config:
    SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-key-change-me")
    SQLALCHEMY_DATABASE_URI = _database_uri()
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    BOT_API_KEY = os.getenv("BOT_API_KEY", os.getenv("APP_API_KEY", "dev-bot-key-change-me"))
    VAPID_PUBLIC_KEY = os.getenv("VAPID_PUBLIC_KEY", "")
    VAPID_PRIVATE_KEY = _normalize_multiline_env(os.getenv("VAPID_PRIVATE_KEY", ""))
    VAPID_SUBJECT = os.getenv("VAPID_SUBJECT", "mailto:admin@example.com")
    SITE_URL = os.getenv("SITE_URL", "http://127.0.0.1:5000")
    MOBILE_APP_URL = os.getenv("MOBILE_APP_URL", SITE_URL)
    SEND_FILE_MAX_AGE_DEFAULT = 60
