import os
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
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


LOCAL_ENV = _load_simple_env(VIP_APP_ENV_PATH)


def _get_setting(name: str, default=None):
    return os.getenv(name, LOCAL_ENV.get(name, default))


def _get_flag(name: str, default=False):
    value = _get_setting(name)
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


TOKEN = _get_setting("TOKEN", "8734676998:AAF-Ari5Kfrbuhj3HzTbG3llaxCo0vSnADs")
VIP_CHAT_ID = _get_setting("VIP_CHAT_ID", "-1003793745882")
FREE_CHAT_ID = _get_setting("FREE_CHAT_ID", "-1003921330386")

APP_API_URL = _get_setting(
    "APP_API_URL",
    f"{str(_get_setting('SITE_URL', 'http://127.0.0.1:5000')).rstrip('/')}/api/listings",
)
APP_API_KEY = _get_setting("APP_API_KEY", _get_setting("BOT_API_KEY", "change-me-bot-api-key"))
APP_API_TIMEOUT = float(_get_setting("APP_API_TIMEOUT", "8"))
APP_API_ENABLED = _get_flag("APP_API_ENABLED", default=bool(APP_API_URL and APP_API_KEY))
