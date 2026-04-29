from __future__ import annotations

import os
import re
import time
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


FALLBACK_CAMPAIGN_IDS = {
    "app": "5339151558",
    "website": "5339151557",
    "vip": "5339151556",
    "telegram_free": "5339151554",
}

CAMPAIGN_ENV_KEYS = {
    "app": "EBAY_EPN_APP_CAMPAIGN_ID",
    "website": "EBAY_EPN_WEBSITE_CAMPAIGN_ID",
    "vip": "EBAY_EPN_VIP_CAMPAIGN_ID",
    "telegram_free": "EBAY_EPN_TELEGRAM_CAMPAIGN_ID",
}

CUSTOM_ID_PREFIXES = {
    "app": "tcg_app",
    "website": "tcg_web",
    "vip": "tcg_vip",
    "telegram_free": "tcg_tg_free",
}

EBAY_ROTATION_IDS = {
    "ebay.at": "5221-53469-19255-0",
    "ebay.com.au": "705-53470-19255-0",
    "ebay.be": "1553-53471-19255-0",
    "ebay.ca": "706-53473-19255-0",
    "ebay.ch": "5222-53480-19255-0",
    "ebay.de": "707-53477-19255-0",
    "ebay.es": "1185-53479-19255-0",
    "ebay.fr": "709-53476-19255-0",
    "ebay.ie": "5282-53468-19255-0",
    "ebay.co.uk": "710-53481-19255-0",
    "ebay.it": "724-53478-19255-0",
    "ebay.nl": "1346-53482-19255-0",
    "ebay.pl": "4908-226936-19255-0",
    "ebay.com": "711-53200-19255-0",
}

TRACKING_PARAMS = {
    "mkevt",
    "mkcid",
    "mkrid",
    "campid",
    "toolid",
    "customid",
    "mkgroupid",
    "amdata",
}


def _env_flag(name: str, default: bool = True) -> bool:
    value = _setting(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _setting(name: str, default=None):
    value = os.getenv(name)
    if value is not None:
        return value
    try:
        from config import LOCAL_ENV

        return LOCAL_ENV.get(name, default)
    except Exception:
        return default


def _log(message: str) -> None:
    print(f"[EBAY_EPN] {message}", flush=True)


def _safe_custom_id_value(value) -> str:
    raw = str(value or "").strip()
    if not raw:
        raw = str(int(time.time()))
    cleaned = re.sub(r"[^A-Za-z0-9_-]+", "_", raw).strip("_")
    return cleaned[:96] or str(int(time.time()))


def _custom_id(source: str, listing_id=None) -> str:
    prefix = CUSTOM_ID_PREFIXES.get(source, "tcg_epn")
    return f"{prefix}_{_safe_custom_id_value(listing_id)}"


def _host_root(host: str) -> str | None:
    host = (host or "").lower().strip(".")
    for root in sorted(EBAY_ROTATION_IDS, key=len, reverse=True):
        if host == root or host.endswith(f".{root}"):
            return root
    if re.search(r"(^|\.)ebay\.[a-z]{2,}(?:\.[a-z]{2})?$", host):
        return host[host.index("ebay.") :]
    return None


def is_ebay_url(url: str) -> bool:
    try:
        parts = urlsplit(str(url or "").strip())
    except ValueError:
        return False
    return parts.scheme in {"http", "https"} and _host_root(parts.netloc) is not None


def _has_existing_tracking(query: str) -> bool:
    params = {key.lower() for key, _value in parse_qsl(query, keep_blank_values=True)}
    return bool(params & TRACKING_PARAMS)


def _campaign_id(source: str) -> str:
    env_key = CAMPAIGN_ENV_KEYS.get(source)
    if env_key:
        value = str(_setting(env_key, "") or "").strip()
        if value:
            return value
    return FALLBACK_CAMPAIGN_IDS.get(source, "")


def _rotation_id_for_url(parts) -> str:
    root = _host_root(parts.netloc) or "ebay.com"
    return EBAY_ROTATION_IDS.get(root, EBAY_ROTATION_IDS["ebay.com"])


def build_ebay_affiliate_url(original_url, source, listing_id=None) -> str:
    url = str(original_url or "").strip()
    source_key = str(source or "").strip().lower()
    if source_key == "telegram":
        source_key = "telegram_free"

    if not url:
        _log("status=skipped reason=empty_url")
        return url

    if not _env_flag("EBAY_EPN_ENABLED", default=True):
        _log("status=disabled")
        return url

    try:
        parts = urlsplit(url)
    except ValueError:
        _log("status=skipped reason=invalid_url")
        return url

    if not is_ebay_url(url):
        _log("status=skipped reason=not_ebay_url")
        return url

    if parts.netloc.lower().strip(".").startswith("rover.ebay."):
        _log("status=already_tracked")
        return url

    if _has_existing_tracking(parts.query):
        _log("status=already_tracked")
        return url

    campaign_id = _campaign_id(source_key)
    if not campaign_id:
        _log(f"status=missing_campaign_id source={source_key}")
        return url

    query_params = parse_qsl(parts.query, keep_blank_values=True)
    query_params.extend(
        [
            ("mkevt", "1"),
            ("mkcid", "1"),
            ("mkrid", _rotation_id_for_url(parts)),
            ("campid", campaign_id),
            ("toolid", "10001"),
            ("customid", _custom_id(source_key, listing_id)),
        ]
    )
    affiliate_url = urlunsplit(
        (
            parts.scheme,
            parts.netloc,
            parts.path,
            urlencode(query_params, doseq=True),
            parts.fragment,
        )
    )
    _log(
        f"source={source_key} listing_id={listing_id or 'generated'} "
        f"campaign={campaign_id} status=converted"
    )
    return affiliate_url
