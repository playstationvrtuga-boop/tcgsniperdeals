import os
from pathlib import Path

from services.site_config import (
    DEFAULT_PUBLIC_SITE_URL,
    normalize_known_public_url,
    public_site_url_from,
)


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
FREE_REALTIME_SAMPLE_PERCENT = int(_get_setting("FREE_REALTIME_SAMPLE_PERCENT", "10"))

APP_API_URL = _get_setting(
    "APP_API_URL",
    f"{str(_get_setting('SITE_URL', 'http://127.0.0.1:5000')).rstrip('/')}/api/listings",
)
APP_API_STATUS_URL = _get_setting(
    "APP_API_STATUS_URL",
    f"{str(_get_setting('SITE_URL', 'http://127.0.0.1:5000')).rstrip('/')}/api/listings/status",
)
PUBLIC_SITE_URL = public_site_url_from(_get_setting)
SITE_URL = normalize_known_public_url(_get_setting("SITE_URL", "http://127.0.0.1:5000"), default="http://127.0.0.1:5000")
APP_PUBLIC_URL = normalize_known_public_url(_get_setting("APP_PUBLIC_URL", PUBLIC_SITE_URL), default=DEFAULT_PUBLIC_SITE_URL)
BOT_API_KEY = (
    os.environ.get("BOT_API_KEY")
    or os.environ.get("APP_API_KEY")
    or LOCAL_ENV.get("BOT_API_KEY", "")
    or LOCAL_ENV.get("APP_API_KEY", "")
    or TOKEN
)
APP_API_KEY = BOT_API_KEY
APP_API_TIMEOUT = float(_get_setting("APP_API_TIMEOUT", "8"))
APP_API_ENABLED = _get_flag("APP_API_ENABLED", default=bool(APP_API_URL and (BOT_API_KEY or TOKEN)))

ENABLE_WALLAPOP = _get_flag("ENABLE_WALLAPOP", default=False)
WALLAPOP_INLINE_IN_MAIN_BOT = _get_flag("WALLAPOP_INLINE_IN_MAIN_BOT", default=False)
WALLAPOP_MAX_ITEMS_PER_RUN = int(_get_setting("WALLAPOP_MAX_ITEMS_PER_RUN", "6"))
WALLAPOP_SEND_TELEGRAM = _get_flag("WALLAPOP_SEND_TELEGRAM", default=False)
WALLAPOP_HEADLESS = _get_flag("WALLAPOP_HEADLESS", default=True)
WALLAPOP_DELAY_MIN_SECONDS = float(_get_setting("WALLAPOP_DELAY_MIN_SECONDS", "2"))
WALLAPOP_DELAY_MAX_SECONDS = float(_get_setting("WALLAPOP_DELAY_MAX_SECONDS", "5"))

CARDMARKET_API_BASE = _get_setting("CARDMARKET_API_BASE", "https://apiv2.cardmarket.com/ws/v2.0/output.json")
CARDMARKET_APP_TOKEN = _get_setting("CARDMARKET_APP_TOKEN", "")
CARDMARKET_APP_SECRET = _get_setting("CARDMARKET_APP_SECRET", "")
CARDMARKET_ACCESS_TOKEN = _get_setting("CARDMARKET_ACCESS_TOKEN", "")
CARDMARKET_ACCESS_SECRET = _get_setting("CARDMARKET_ACCESS_SECRET", "")
CARDMARKET_TIMEOUT = float(_get_setting("CARDMARKET_TIMEOUT", "15"))
CARDMARKET_GAME_NAME = _get_setting("CARDMARKET_GAME_NAME", "Pokemon")
CARDMARKET_TRENDS_ENABLED = _get_flag("CARDMARKET_TRENDS_ENABLED", default=True)
CARDMARKET_TRENDS_INTERVAL_HOURS = int(_get_setting("CARDMARKET_TRENDS_INTERVAL_HOURS", "24"))
CARDMARKET_TRENDS_MAX_ITEMS = int(_get_setting("CARDMARKET_TRENDS_MAX_ITEMS", "20"))
CARDMARKET_TRENDS_SOURCE_URL = _get_setting("CARDMARKET_TRENDS_SOURCE_URL", "https://www.cardmarket.com/en/Pokemon")
CARDMARKET_TRENDS_TIMEOUT_SECONDS = float(_get_setting("CARDMARKET_TRENDS_TIMEOUT_SECONDS", "20"))
CARDMARKET_TRENDS_USER_AGENT = _get_setting("CARDMARKET_TRENDS_USER_AGENT", "TCGSniperDealsBot/1.0")

PRICING_WORKER_MIN_SLEEP = float(_get_setting("PRICING_WORKER_MIN_SLEEP", "1"))
PRICING_WORKER_MAX_SLEEP = float(_get_setting("PRICING_WORKER_MAX_SLEEP", "3"))
PRICING_WORKER_ENABLED = _get_flag("PRICING_WORKER_ENABLED", default=True)
PRICING_DEAL_MIN_DISCOUNT = float(_get_setting("PRICING_DEAL_MIN_DISCOUNT", "20"))
PRICING_DEAL_MIN_MARGIN = float(_get_setting("PRICING_DEAL_MIN_MARGIN", "5"))
PRICING_DEAL_MIN_SCORE = int(_get_setting("PRICING_DEAL_MIN_SCORE", "60"))
PRICING_ENABLE_BUY_NOW_REFERENCE = _get_flag("PRICING_ENABLE_BUY_NOW_REFERENCE", default=True)
PRICING_ENABLE_EBAY_HTML_FALLBACK = _get_flag("PRICING_ENABLE_EBAY_HTML_FALLBACK", default=False)
PRICING_BUY_NOW_MAX_RESULTS = int(_get_setting("PRICING_BUY_NOW_MAX_RESULTS", "5"))
PRICING_BUY_NOW_MIN_COMPARABLES = int(_get_setting("PRICING_BUY_NOW_MIN_COMPARABLES", "3"))
PRICING_RETRY_AFTER_MINUTES = int(_get_setting("PRICING_RETRY_AFTER_MINUTES", "60"))
EBAY_CLIENT_ID = _get_setting("EBAY_CLIENT_ID", "")
EBAY_CLIENT_SECRET = _get_setting("EBAY_CLIENT_SECRET", "")
EBAY_MARKETPLACE_ID = _get_setting("EBAY_MARKETPLACE_ID", "EBAY_US")
EBAY_API_ENVIRONMENT = str(_get_setting("EBAY_API_ENVIRONMENT", "PRODUCTION")).strip().upper()
EBAY_OAUTH_SCOPE = _get_setting("EBAY_OAUTH_SCOPE", "https://api.ebay.com/oauth/api_scope")
EBAY_API_TIMEOUT = float(_get_setting("EBAY_API_TIMEOUT", "12"))
EBAY_ENABLE_OFFICIAL_API = _get_flag(
    "EBAY_ENABLE_OFFICIAL_API",
    default=bool(EBAY_CLIENT_ID and EBAY_CLIENT_SECRET),
)
EBAY_ENABLE_MARKETPLACE_INSIGHTS = _get_flag("EBAY_ENABLE_MARKETPLACE_INSIGHTS", default=False)
EBAY_MARKETPLACE_INSIGHTS_SEARCH_URL = _get_setting("EBAY_MARKETPLACE_INSIGHTS_SEARCH_URL", "")
FREE_MIN_DISCOUNT_PERCENT = float(_get_setting("FREE_MIN_DISCOUNT_PERCENT", "10"))
FREE_ALERT_DELAY_MINUTES = int(_get_setting("FREE_ALERT_DELAY_MINUTES", "5"))
FREE_ALERT_DELAY_MIN_MINUTES = int(_get_setting("FREE_ALERT_DELAY_MIN_MINUTES", "5"))
FREE_ALERT_DELAY_MAX_MINUTES = int(_get_setting("FREE_ALERT_DELAY_MAX_MINUTES", "10"))
FREE_CTA_EVERY_N_POSTS = int(_get_setting("FREE_CTA_EVERY_N_POSTS", "20"))
FREE_CTA_APP_LINK = _get_setting(
    "FREE_CTA_APP_LINK",
    APP_PUBLIC_URL,
)
FREE_PROMO_ENABLED = _get_flag("FREE_PROMO_ENABLED", default=True)
FREE_PROMO_FOLDER = _get_setting(
    "FREE_PROMO_FOLDER",
    str(BASE_DIR / "vip_app" / "app" / "static" / "promos"),
)
FREE_PROMO_INTERVAL_MINUTES = int(_get_setting("FREE_PROMO_INTERVAL_MINUTES", "60"))
ENABLE_FREE_GONE_ALERTS = _get_flag("ENABLE_FREE_GONE_ALERTS", default=True)
FREE_GONE_MIN_PER_DAY = int(_get_setting("FREE_GONE_MIN_PER_DAY", "3"))
FREE_GONE_MAX_PER_DAY = int(_get_setting("FREE_GONE_MAX_PER_DAY", "5"))
FREE_GONE_WINDOWS = _get_setting(
    "FREE_GONE_WINDOWS",
    "10:00-13:00,15:00-19:00,20:00-23:00",
)
FREE_GONE_WORKER_INTERVAL_MINUTES = int(_get_setting("FREE_GONE_WORKER_INTERVAL_MINUTES", "10"))
FREE_GONE_MAX_AGE_HOURS = int(_get_setting("FREE_GONE_MAX_AGE_HOURS", "48"))
FREE_GONE_PREFERRED_AGE_HOURS = int(_get_setting("FREE_GONE_PREFERRED_AGE_HOURS", "24"))
FREE_GONE_AVAILABILITY_CHECK_LIMIT = int(_get_setting("FREE_GONE_AVAILABILITY_CHECK_LIMIT", "10"))
FREE_GONE_AVAILABILITY_MIN_AGE_MINUTES = int(_get_setting("FREE_GONE_AVAILABILITY_MIN_AGE_MINUTES", "5"))
FREE_GONE_AVAILABILITY_RECHECK_MINUTES = int(_get_setting("FREE_GONE_AVAILABILITY_RECHECK_MINUTES", "180"))
