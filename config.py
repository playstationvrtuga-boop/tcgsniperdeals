import os
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
ROOT_ENV_PATH = BASE_DIR / ".env"
VIP_APP_ENV_PATH = BASE_DIR / "vip_app" / ".env"


def _load_simple_env(path: Path):
    values = {}
    if not path.exists():
        return values

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


# Support both the project root .env and vip_app/.env.
# Root .env wins so local bot setup can stay in one obvious place.
LOCAL_ENV = {}
LOCAL_ENV.update(_load_simple_env(VIP_APP_ENV_PATH))
LOCAL_ENV.update(_load_simple_env(ROOT_ENV_PATH))


def _get_setting(name: str, default=None):
    return os.getenv(name, LOCAL_ENV.get(name, default))


def _get_flag(name: str, default=False):
    value = _get_setting(name)
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


# Telegram bot token must come from environment, never from source code.
TOKEN = _get_setting("TELEGRAM_BOT_TOKEN", _get_setting("TOKEN", ""))
VIP_CHAT_ID = _get_setting("VIP_CHAT_ID", "-1003793745882")
FREE_CHAT_ID = _get_setting("FREE_CHAT_ID", "-1003921330386")

APP_API_URL = _get_setting(
    "APP_API_URL",
    f"{str(_get_setting('SITE_URL', 'http://127.0.0.1:5000')).rstrip('/')}/api/listings",
)
APP_API_STATUS_URL = _get_setting(
    "APP_API_STATUS_URL",
    f"{str(_get_setting('SITE_URL', 'http://127.0.0.1:5000')).rstrip('/')}/api/listings/status",
)
BOT_API_KEY = os.environ.get("BOT_API_KEY") or LOCAL_ENV.get("BOT_API_KEY", "")
APP_API_KEY = BOT_API_KEY or os.environ.get("APP_API_KEY") or LOCAL_ENV.get("APP_API_KEY", "")
APP_API_TIMEOUT = float(_get_setting("APP_API_TIMEOUT", "8"))
APP_API_ENABLED = _get_flag("APP_API_ENABLED", default=bool(APP_API_URL and BOT_API_KEY))

CARDMARKET_API_BASE = _get_setting("CARDMARKET_API_BASE", "https://apiv2.cardmarket.com/ws/v2.0/output.json")
CARDMARKET_APP_TOKEN = _get_setting("CARDMARKET_APP_TOKEN", "")
CARDMARKET_APP_SECRET = _get_setting("CARDMARKET_APP_SECRET", "")
CARDMARKET_ACCESS_TOKEN = _get_setting("CARDMARKET_ACCESS_TOKEN", "")
CARDMARKET_ACCESS_SECRET = _get_setting("CARDMARKET_ACCESS_SECRET", "")
CARDMARKET_TIMEOUT = float(_get_setting("CARDMARKET_TIMEOUT", "15"))
CARDMARKET_GAME_NAME = _get_setting("CARDMARKET_GAME_NAME", "Pokemon")

PRICING_WORKER_MIN_SLEEP = float(_get_setting("PRICING_WORKER_MIN_SLEEP", "1"))
PRICING_WORKER_MAX_SLEEP = float(_get_setting("PRICING_WORKER_MAX_SLEEP", "3"))
PRICING_DEAL_MIN_DISCOUNT = float(_get_setting("PRICING_DEAL_MIN_DISCOUNT", "20"))
PRICING_DEAL_MIN_MARGIN = float(_get_setting("PRICING_DEAL_MIN_MARGIN", "5"))
PRICING_DEAL_MIN_SCORE = int(_get_setting("PRICING_DEAL_MIN_SCORE", "60"))
FREE_ALERT_DELAY_MINUTES = int(_get_setting("FREE_ALERT_DELAY_MINUTES", "15"))
FREE_ALERT_DELAY_MIN_MINUTES = int(_get_setting("FREE_ALERT_DELAY_MIN_MINUTES", "5"))
FREE_ALERT_DELAY_MAX_MINUTES = int(_get_setting("FREE_ALERT_DELAY_MAX_MINUTES", "10"))
FREE_ALERT_MAX_AGE_MINUTES = int(_get_setting("FREE_ALERT_MAX_AGE_MINUTES", "30"))
FREE_MIN_DISCOUNT_PERCENT = float(_get_setting("FREE_MIN_DISCOUNT_PERCENT", "10"))
FREE_CTA_EVERY_N_POSTS = int(_get_setting("FREE_CTA_EVERY_N_POSTS", "20"))
FREE_CTA_APP_LINK = _get_setting(
    "FREE_CTA_APP_LINK",
    _get_setting("MOBILE_APP_URL", _get_setting("SITE_URL", "")),
)
ENABLE_FREE_GONE_ALERTS = _get_flag("ENABLE_FREE_GONE_ALERTS", default=False)
FREE_GONE_MIN_PER_DAY = int(_get_setting("FREE_GONE_MIN_PER_DAY", "3"))
FREE_GONE_MAX_PER_DAY = int(_get_setting("FREE_GONE_MAX_PER_DAY", "5"))
FREE_GONE_WINDOWS = _get_setting(
    "FREE_GONE_WINDOWS",
    "10:00-13:00,15:00-19:00,20:00-23:00",
)
FREE_GONE_WORKER_INTERVAL_MINUTES = int(_get_setting("FREE_GONE_WORKER_INTERVAL_MINUTES", "10"))
FREE_GONE_MAX_AGE_HOURS = int(_get_setting("FREE_GONE_MAX_AGE_HOURS", "48"))
FREE_GONE_PREFERRED_AGE_HOURS = int(_get_setting("FREE_GONE_PREFERRED_AGE_HOURS", "24"))
