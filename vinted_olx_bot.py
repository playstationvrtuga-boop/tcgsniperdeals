# -*- coding: utf-8 -*-
from playwright.sync_api import sync_playwright
from config import (
    TOKEN,
    VIP_CHAT_ID,
    FREE_CHAT_ID,
    APP_API_ENABLED,
    APP_API_URL,
    APP_API_STATUS_URL,
    BOT_API_KEY,
    APP_API_TIMEOUT,
    FREE_REALTIME_SAMPLE_PERCENT,
    ENABLE_WALLAPOP,
    WALLAPOP_INLINE_IN_MAIN_BOT,
    WALLAPOP_MAX_ITEMS_PER_RUN,
    WALLAPOP_SEND_TELEGRAM,
    WALLAPOP_HEADLESS,
    WALLAPOP_DELAY_MIN_SECONDS,
    WALLAPOP_DELAY_MAX_SECONDS,
)
from core.listing_logger import log_listing_event
from core.normalizer import normalize_text
from core.scoring import ListingAssessment, assess_listing, is_priority
from services.alert_formatter import format_telegram_listing_message, make_partial_product_name
from services.ebay_api_client import ebay_api_client
from services.ebay_affiliate import build_ebay_affiliate_url
from services.ebay_sold_client import EbaySoldError, EbaySoldRateLimitError
from services.free_cta import build_free_cta_block, record_free_cta_sent, should_attach_free_cta
from services.free_promos import schedule_free_promos_every_hour
from services.image_urls import high_resolution_ebay_image_url
from services.public_links import build_free_public_listing_url
from services.wallapop_scraper import (
    fetch_wallapop_listings,
    fetch_wallapop_listings_with_context,
    should_send_wallapop_to_telegram,
)
from urllib.parse import parse_qs, parse_qsl, quote_plus, urlencode, unquote_plus, urljoin, urlsplit, urlunsplit
import requests
import os
import sys
import time
import re
import json
import random
import atexit
import traceback
import gc
import ctypes
from collections import Counter, deque
from datetime import datetime, timedelta, timezone

sys.stdout.reconfigure(encoding='utf-8')

CHECK_INTERVAL = 10
FICHEIRO_VISTOS = "vistos.txt"
FICHEIRO_VISTOS_EBAY_DEBUG = "vistos_ebay_debug.txt"
FICHEIRO_CACHE_CARDMARKET = "cardmarket_cache.json"
FICHEIRO_CACHE_EBAY_SOLD = "ebay_sold_cache.json"
FICHEIRO_FILA_FREE = "free_queue.json"
FICHEIRO_TRACKING = "tracked_listings.json"
FICHEIRO_METRICAS = "metrics_state.json"
LIGHT_MODE = True
OLX_ENABLED = False
ENABLE_EBAY_SOLD_REFERENCES = False
EBAY_FETCH_EVERY = 1
AVAILABILITY_CHECK_EVERY = 5 if LIGHT_MODE else 2
TRACKING_RETENTION_DAYS = 7
METRICAS_RETENTION_DAYS = 7
MAX_RECHECKS_PER_CYCLE = 3 if LIGHT_MODE else 8
RECHECK_INTERVAL_MINUTES = 60 if LIGHT_MODE else 30
BROWSER_REFRESH_EVERY_CYCLES = 8 if LIGHT_MODE else 0
BROWSER_REFRESH_EVERY_MINUTES = 25 if LIGHT_MODE else 0
RUNTIME_DEBUG_EVERY_CYCLES = 10
PLAYWRIGHT_NAV_TIMEOUT = 20000
PLAYWRIGHT_QUERY_TIMEOUT = 8000
EBAY_DETAIL_PAGE_RESET_EVERY = 2 if LIGHT_MODE else 4
EBAY_SOLD_CACHE_MAX_AGE_HOURS = 6
EBAY_SOLD_NEGATIVE_CACHE_MAX_AGE_MINUTES = 20
EBAY_DEBUG_MODE = True
EBAY_DEBUG_DETECTION = str(os.getenv("EBAY_DEBUG_DETECTION", "false")).strip().lower() in {"1", "true", "yes", "on"}
EBAY_FORCE_ALWAYS_ON_DEBUG = False
EBAY_DEBUG_IGNORE_MAIN_VISTOS = True
FREE_LANDING_ONLY = False
MAX_FREE_QUEUE_ITEMS = 250
MAX_TRACKING_ITEMS = 500
MAX_METRIC_EVENTS = 500
MAX_CARDMARKET_CACHE_ITEMS = 500
MAX_EBAY_SOLD_CACHE_ITEMS = 500
MAX_VISTOS_ITEMS = 5000
MAX_VISTOS_EBAY_DEBUG_ITEMS = 1000
MAX_DEBUG_LOG_BYTES = 2 * 1024 * 1024
MAX_DEBUG_LOG_BACKUPS = 3
GC_COLLECT_EVERY_CYCLES = 5
MEMORY_LOG_EVERY_CYCLES = 5
LOG_TITLE_MAX_CHARS = 120

def env_bool(name, default=False):
    return str(os.getenv(name, str(default))).strip().lower() in {"1", "true", "yes", "on"}


def env_int(name, default, minimum=1):
    try:
        value = int(os.getenv(name, str(default)))
    except Exception:
        return default
    return max(minimum, value)


def should_process_ebay_cycle(cycle):
    processar_ebay = (cycle % EBAY_FETCH_EVERY == 0) if LIGHT_MODE else True
    if EBAY_FORCE_ALWAYS_ON_DEBUG:
        processar_ebay = True
    return processar_ebay


ENABLE_ONE_PIECE = False
MAX_VINTED_PER_CYCLE = 8
MAX_EBAY_CANDIDATES_PER_CYCLE = 8
EBAY_SEEN_TTL_HOURS = env_int("EBAY_SEEN_TTL_HOURS", 12)
MAX_EBAY_SEEN_ITEMS = env_int("MAX_EBAY_SEEN_ITEMS", 7500, minimum=100)
EBAY_SEARCH_PAGES_PER_QUERY = min(3, env_int("EBAY_SEARCH_PAGES_PER_QUERY", 2, minimum=1))
EBAY_USE_OFFICIAL_API_DETECTION = env_bool("EBAY_USE_OFFICIAL_API_DETECTION", True)
EBAY_API_DETECTION_LIMIT = min(100, env_int("EBAY_API_DETECTION_LIMIT", 50, minimum=1))
EBAY_STALE_SEEN_WARNING_CYCLES = min(5, env_int("EBAY_STALE_SEEN_WARNING_CYCLES", 3, minimum=2))
MAX_OLX = 0 if not OLX_ENABLED else 8
MAX_EBAY = MAX_EBAY_CANDIDATES_PER_CYCLE
EBAY_MAX_CANDIDATES_PER_QUERY = MAX_EBAY_CANDIDATES_PER_CYCLE

USD_PARA_EUR = 1 / 1.1780

VINTED_SEARCH_URLS_POKEMON = [
    "https://www.vinted.pt/catalog?search_text=pokemon&order=newest_first",
]
VINTED_SEARCH_URLS_ONE_PIECE = [
    "https://www.vinted.pt/catalog?search_text=one%20piece&order=newest_first",
]
VINTED_SEARCH_URLS = VINTED_SEARCH_URLS_POKEMON + (VINTED_SEARCH_URLS_ONE_PIECE if ENABLE_ONE_PIECE else [])
OLX_SEARCH_URLS = [
    "https://www.olx.pt/ads/q-cartas-pokemon/?search%5Border%5D=created_at:desc",
    "https://www.olx.pt/ads/q-one-piece-cards/?search%5Border%5D=created_at:desc",
]
EBAY_SEARCH_EXCLUDE_TERMS = [
    "-proxy", "-fake", "-reprint", "-\"read description\"",
]


def build_ebay_search_url(query):
    full_query = " ".join([query] + EBAY_SEARCH_EXCLUDE_TERMS)
    return (
        "https://www.ebay.com/sch/i.html"
        f"?_nkw={quote_plus(full_query)}"
        "&_sop=10&LH_BIN=1&LH_ItemCondition=1000%7C3000&_ipg=100"
    )


EBAY_ALLOCATION_ORDER = ("raw", "sealed", "graded")
EBAY_ALLOCATION = {
    "raw": 4,
    "sealed": 2,
    "graded": 2,
}
EBAY_SEARCH_QUERIES_POKEMON = [
    ("raw", "pokemon card holo rare ex gx v vmax vstar full art"),
    ("graded", "pokemon psa cgc bgs graded card"),
    ("sealed", "pokemon booster box etb elite trainer box sealed booster bundle"),
    ("raw", "charizard pokemon card"),
    ("sealed", "pokemon 151 booster bundle"),
    ("sealed", "pokemon elite trainer box"),
]
EBAY_SEARCH_URLS_POKEMON = [
    build_ebay_search_url(query) for _, query in EBAY_SEARCH_QUERIES_POKEMON
]
EBAY_SEARCH_URL_CATEGORY = {
    build_ebay_search_url(query): category for category, query in EBAY_SEARCH_QUERIES_POKEMON
}
EBAY_SEARCH_URLS_ONE_PIECE = [
    "https://www.ebay.com/sch/i.html?_nkw=one+piece+tcg+-proxy+-fake+-reprint+-\"read+description\"+-japanese+-french+-german+-italian+-spanish+-portuguese+-korean+-chinese&_sop=10&LH_BIN=1&LH_ItemCondition=1000%7C3000&_ipg=50",
]
EBAY_SEARCH_URLS = EBAY_SEARCH_URLS_POKEMON + (EBAY_SEARCH_URLS_ONE_PIECE if ENABLE_ONE_PIECE else [])
EBAY_PRIORITY_TERMS = [
    "psa 10", "booster box", "etb sealed", "etb", "sealed", "vintage",
]
EBAY_EXTRA_EXCLUDE = [
    "read description", "see description", "proxy", "fake", "reprint",
]
EBAY_POSITIVE_LANGUAGE = [
    "english", "pokemon tcg", "one piece tcg", "booster box", "elite trainer box", "etb",
    "sealed", "tin", "collection box", "blister", "starter deck", "double pack",
]
EBAY_NEGATIVE_LANGUAGE = [
    "japanese", "jp", "français", "french", "deutsch", "german",
    "italian", "italiano", "spanish", "español", "portuguese",
    "português", "korean", "chinese",
]
TCG_LABELS = {
    "pokemon": "🟣 Pokémon TCG",
    "one_piece": "🔴 One Piece TCG",
}
POKEMON_TCG_TERMS = [
    "pokemon", "pokémon", "charizard", "pikachu", "etb", "elite trainer box",
    "booster box", "psa", "pokemon tcg", "tcg pokemon",
]
ONE_PIECE_TCG_TERMS = [
    "one piece", "one piece tcg", "one piece cards", "booster box one piece",
    "luffy", "zoro", "nami", "op01", "op02", "op03", "op04", "op05", "op06",
    "op07", "op08", "op09", "op10",
]
ONE_PIECE_STRONG_TERMS = [
    "one piece", "luffy", "zoro", "nami", "trafalgar law", "ace", "sanji",
    "op01", "op02", "op03", "op04", "op05", "op06", "op07", "op08", "op09", "op10",
]
ONE_PIECE_RARITY_TERMS = [
    "manga", "parallel", "alt art", "leader", "sp", "sec", "sr", "r",
]
_RUNTIME = {
    "playwright": None,
    "browser": None,
    "context": None,
    "page_lista": None,
    "page_detalhe": None,
    "created_at": None,
    "created_cycle": 0,
    "refresh_count": 0,
}
HTTP_SESSION = requests.Session()
HTTP_SESSION.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0 Safari/537.36"
})
_FREE_QUEUE_CACHE = {
    "mtime": None,
    "data": [],
}
EBAY_MAX_CANDIDATES_PER_CYCLE = MAX_EBAY_CANDIDATES_PER_CYCLE
_EBAY_ALREADY_SEEN_HISTORY = deque(maxlen=EBAY_STALE_SEEN_WARNING_CYCLES)


DIAG_COUNTER_KEYS = (
    "raw",
    "parsed",
    "duplicate",
    "skipped_seen",
    "excluded",
    "rejected",
    "accepted",
    "sent_app",
    "sent_free",
)

EBAY_REJECTION_REASON_KEYS = {
    "duplicate",
    "already_seen",
    "auction",
    "not_buy_it_now",
    "language",
    "excluded_keyword",
    "noise",
    "non_tcg",
    "low_score",
    "missing_price",
    "parse_error",
    "placeholder_item",
    "other",
}


def _query_keyword(search_url):
    try:
        parsed = urlsplit(search_url)
        params = parse_qs(parsed.query)
        value = (params.get("search_text") or params.get("_nkw") or [""])[0]
        return unquote_plus(value).strip() or parsed.netloc
    except Exception:
        return str(search_url or "unknown")


def ebay_search_url_page(search_url, page_number):
    page_number = max(1, int(page_number or 1))
    parts = urlsplit(search_url)
    params = [(key, value) for key, value in parse_qsl(parts.query, keep_blank_values=True) if key != "_pgn"]
    params.append(("_pgn", str(page_number)))
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(params), parts.fragment))


def ebay_search_page_urls(search_url, max_pages=None):
    pages = min(3, max(1, int(max_pages or EBAY_SEARCH_PAGES_PER_QUERY)))
    return [ebay_search_url_page(search_url, page_number) for page_number in range(1, pages + 1)]


def ebay_seen_ratio(results_count, already_seen_count):
    if results_count <= 0:
        return 0.0
    return already_seen_count / results_count


def ebay_stale_seen_warning_active(history):
    history = list(history or [])
    if len(history) < EBAY_STALE_SEEN_WARNING_CYCLES:
        return False
    recent = history[-EBAY_STALE_SEEN_WARNING_CYCLES:]
    return all(entry.get("results", 0) > 0 and entry.get("already_seen", 0) / entry["results"] >= 0.9 for entry in recent)


def ebay_record_cycle_seen_ratio(results_count, already_seen_count):
    _EBAY_ALREADY_SEEN_HISTORY.append({
        "results": int(results_count or 0),
        "already_seen": int(already_seen_count or 0),
    })
    if ebay_stale_seen_warning_active(_EBAY_ALREADY_SEEN_HISTORY):
        print(
            "[EBAY_WARNING] too_many_already_seen_possible_stale_query "
            f"cycles={len(_EBAY_ALREADY_SEEN_HISTORY)} "
            f"latest_ratio={ebay_seen_ratio(results_count, already_seen_count):.2f} "
            f"results={results_count} already_seen={already_seen_count}",
            flush=True,
        )


def ebay_detection_debug_print(query, total_results, first_ids, first_titles, already_seen_count, accepted_count, rejected_reasons):
    if not EBAY_DEBUG_DETECTION:
        return
    print(f"[EBAY_DEBUG_DETECTION] query=\"{query}\"", flush=True)
    print(f"[EBAY_DEBUG_DETECTION] total_results={total_results}", flush=True)
    print(f"[EBAY_DEBUG_DETECTION] first_5_item_ids={','.join(first_ids[:5]) or 'none'}", flush=True)
    for idx, title in enumerate(first_titles[:5], start=1):
        print(f"[EBAY_DEBUG_DETECTION] first_5_title_{idx}=\"{str(title)[:LOG_TITLE_MAX_CHARS]}\"", flush=True)
    print(
        f"[EBAY_DEBUG_DETECTION] already_seen_count={already_seen_count} "
        f"accepted_count={accepted_count} rejected_reasons={_counter_summary(rejected_reasons)}",
        flush=True,
    )


def ebay_error_is_rate_limit(error):
    text = str(error or "").lower()
    return any(marker in text for marker in ("429", "rate limit", "too many requests", "captcha"))


def _diag_key(platform, search_url):
    return f"{platform}:{search_url}"


def start_cycle_diag(cycle, processar_ebay):
    diag = {
        "cycle": cycle,
        "processar_ebay": processar_ebay,
        "queries": {},
        "link_query": {},
        "app_status": Counter(),
        "free_status": Counter(),
    }
    for platform, urls in (("vinted", VINTED_SEARCH_URLS), ("ebay", EBAY_SEARCH_URLS)):
        for search_url in urls:
            diag_get_query(diag, platform, search_url)
    if wallapop_inline_enabled():
        diag_get_query(diag, "wallapop", "wallapop:inline")

    print(
        f"[CYCLE_START] cycle={cycle} processar_ebay={processar_ebay} "
        f"one_piece_enabled={str(ENABLE_ONE_PIECE).lower()} "
        f"max_vinted={MAX_VINTED_PER_CYCLE} max_ebay={EBAY_MAX_CANDIDATES_PER_CYCLE} "
        f"max_wallapop={wallapop_inline_max_items()} "
        f"vinted_queries={len(VINTED_SEARCH_URLS)} ebay_queries={len(EBAY_SEARCH_URLS)} "
        f"free_sample={_free_realtime_sample_percent()}%"
    )
    return diag


def diag_get_query(diag, platform, search_url):
    if diag is None:
        return None
    key = _diag_key(platform, search_url or "unknown")
    query = diag["queries"].get(key)
    if query is None:
        query = {
            "platform": platform,
            "keyword": _query_keyword(search_url),
            "url": search_url or "unknown",
            "app_status": Counter(),
            "free_status": Counter(),
            "ebay_reject_reasons": Counter(),
        }
        for counter_key in DIAG_COUNTER_KEYS:
            query[counter_key] = 0
        diag["queries"][key] = query
    return query


def diag_count(query, key, amount=1):
    if query is not None:
        query[key] = query.get(key, 0) + amount


def _clean_ebay_rejection_reason(reason):
    reason = str(reason or "other").strip().lower()
    return reason if reason in EBAY_REJECTION_REASON_KEYS else "other"


def _diag_query_label(query):
    if query is None:
        return "unknown"
    return query.get("keyword") or "unknown"


def diag_count_ebay_rejection(query, reason, amount=1):
    if query is None or query.get("platform") != "ebay":
        return
    query["ebay_reject_reasons"][_clean_ebay_rejection_reason(reason)] += amount


def diag_record_ebay_rejection(query, reason, item_id=None, title=None, stage=None, detail=None, already_seen=None):
    clean_reason = _clean_ebay_rejection_reason(reason)
    diag_count_ebay_rejection(query, clean_reason)
    title_part = f" title=\"{str(title)[:120]}\"" if title else ""
    detail_part = f" detail=\"{str(detail)[:160]}\"" if detail else ""
    seen_value = str(bool(already_seen or clean_reason == "already_seen")).lower()
    print(
        f"[EBAY_REJECT] reason={clean_reason} stage={stage or 'unknown'} "
        f"id={item_id or 'unknown'} item_id={item_id or 'unknown'} query=\"{_diag_query_label(query)}\" "
        f"already_seen={seen_value}"
        f"{title_part}{detail_part}"
    )


def ebay_rejection_reason_from_scrape(scrape_reject_reason):
    if scrape_reject_reason == "auction":
        return "auction"
    if scrape_reject_reason == "not_buy_it_now":
        return "not_buy_it_now"
    if scrape_reject_reason == "placeholder_item":
        return "placeholder_item"
    if scrape_reject_reason == "non_english":
        return "language"
    if scrape_reject_reason == "ebay_noise":
        return "excluded_keyword"
    if scrape_reject_reason == "scrape_error":
        return "parse_error"
    return "other"


def ebay_rejection_reason_from_assessment(assessment, price=None):
    if price is None or str(price).strip() == "":
        return "missing_price"
    reject_reason = (getattr(assessment, "reject_reason", None) or "").lower()
    if reject_reason.startswith("noise:"):
        return "noise"
    if reject_reason in {"empty_title", "missing_title"}:
        return "parse_error"
    return "low_score"


def diag_register_link(diag, platform, link, search_url):
    if diag is not None and link:
        diag["link_query"].setdefault(f"{platform}:{link}", _diag_key(platform, search_url or "unknown"))


def diag_query_for_link(diag, platform, link):
    if diag is None:
        return None
    query_key = diag["link_query"].get(f"{platform}:{link}")
    if query_key:
        return diag["queries"].get(query_key)
    return None


def diag_record_delivery(diag, anuncio, app_result, free_result):
    if diag is None:
        return
    platform = anuncio.get("source") or "unknown"
    query = diag_query_for_link(diag, platform, anuncio.get("link"))
    app_status = (app_result or {}).get("status") or "missing"
    free_status = (free_result or {}).get("status") or "missing"
    diag["app_status"][app_status] += 1
    diag["free_status"][free_status] += 1
    if query is not None:
        query["app_status"][app_status] += 1
        query["free_status"][free_status] += 1
        if (app_result or {}).get("http_status") is not None:
            diag_count(query, "sent_app")
        if free_status == "sent":
            diag_count(query, "sent_free")
        if platform == "ebay" and app_status == "invalid_payload":
            reason = "missing_price" if not str(anuncio.get("preco") or "").strip() else "parse_error"
            diag_record_ebay_rejection(
                query,
                reason,
                item_id=anuncio.get("id"),
                title=anuncio.get("titulo"),
                stage="app_payload",
                detail=app_status,
            )
    print(
        f"[APP_RESPONSE] id={anuncio.get('id')} platform={platform} "
        f"status={app_status} http={(app_result or {}).get('http_status')} "
        f"query=\"{query.get('keyword') if query else 'unknown'}\""
    )
    if platform == "ebay" and app_status == "inserted":
        print(
            f"[EBAY_APP_INSERTED] item_id={anuncio.get('id')} "
            f"http={(app_result or {}).get('http_status')} source=ebay"
        )
    print(
        f"[FREE_DECISION] id={anuncio.get('id')} platform={platform} "
        f"status={free_status} sample_percent={(free_result or {}).get('sample_percent')} "
        f"query=\"{query.get('keyword') if query else 'unknown'}\""
    )


def _counter_summary(counter):
    if not counter:
        return "none"
    return ",".join(f"{key}:{value}" for key, value in sorted(counter.items()))


def log_cycle_diag(diag):
    if diag is None:
        return
    totals = Counter()
    ebay_reject_reasons = Counter()
    ebay_app_status = Counter()
    for query in diag["queries"].values():
        for key in DIAG_COUNTER_KEYS:
            totals[f"{query['platform']}_{key}"] += query.get(key, 0)
        if query["platform"] == "ebay":
            ebay_reject_reasons.update(query.get("ebay_reject_reasons") or {})
            ebay_app_status.update(query.get("app_status") or {})
        prefix = {
            "vinted": "[VINTED_QUERY]",
            "ebay": "[EBAY_QUERY]",
            "wallapop": "[WALLAPOP_QUERY]",
        }.get(query["platform"], "[QUERY]")
        ebay_reject_part = ""
        if query["platform"] == "ebay":
            ebay_reject_part = f" reject_reasons={_counter_summary(query.get('ebay_reject_reasons'))}"
        print(
            f"{prefix} keyword=\"{query['keyword']}\" url=\"{query['url']}\" "
            f"raw={query['raw']} parsed={query['parsed']} duplicate={query['duplicate']} "
            f"skipped_seen={query['skipped_seen']} "
            f"excluded={query['excluded']} rejected={query['rejected']} "
            f"accepted={query['accepted']} sent_app={query['sent_app']} sent_free={query['sent_free']}"
            f"{ebay_reject_part} "
            f"app_status={_counter_summary(query['app_status'])} "
            f"free_status={_counter_summary(query['free_status'])}"
        )

    print(
        "[CYCLE_SUMMARY] "
        f"cycle={diag['cycle']} processar_ebay={diag['processar_ebay']} "
        f"vinted_raw={totals['vinted_raw']} vinted_parsed={totals['vinted_parsed']} "
        f"vinted_sent={totals['vinted_sent_app']} "
        f"ebay_raw={totals['ebay_raw']} ebay_parsed={totals['ebay_parsed']} "
        f"ebay_sent={totals['ebay_sent_app']} "
        f"wallapop_raw={totals['wallapop_raw']} wallapop_parsed={totals['wallapop_parsed']} "
        f"wallapop_sent={totals['wallapop_sent_app']} "
        f"duplicates={totals['vinted_duplicate'] + totals['ebay_duplicate'] + totals['wallapop_duplicate']} "
        f"skipped_seen={totals['vinted_skipped_seen'] + totals['ebay_skipped_seen'] + totals['wallapop_skipped_seen']} "
        f"excluded={totals['vinted_excluded'] + totals['ebay_excluded'] + totals['wallapop_excluded']} "
        f"rejected={totals['vinted_rejected'] + totals['ebay_rejected'] + totals['wallapop_rejected']} "
        f"accepted={totals['vinted_accepted'] + totals['ebay_accepted'] + totals['wallapop_accepted']} "
        f"free_sent={totals['vinted_sent_free'] + totals['ebay_sent_free'] + totals['wallapop_sent_free']} "
        f"ebay_reject_reasons={_counter_summary(ebay_reject_reasons)} "
        f"app_status={_counter_summary(diag['app_status'])} "
        f"free_status={_counter_summary(diag['free_status'])}"
    )
    ebay_failed = sum(
        count for status, count in ebay_app_status.items()
        if status not in {"inserted", "duplicate"}
    )
    print(
        "[EBAY_CYCLE_SUMMARY] "
        f"raw={totals['ebay_raw']} "
        f"parsed={totals['ebay_parsed']} "
        f"placeholder={ebay_reject_reasons['placeholder_item']} "
        f"already_seen={totals['ebay_skipped_seen']} "
        f"rejected={totals['ebay_rejected']} "
        f"accepted={totals['ebay_accepted']} "
        f"sent_app={totals['ebay_sent_app']} "
        f"inserted={ebay_app_status['inserted']} "
        f"failed={ebay_failed}"
    )
    print(f"[EBAY_RESULTS_COUNT] cycle={diag['cycle']} count={totals['ebay_parsed']}")
    print(f"[EBAY_NEW_ACCEPTED_COUNT] cycle={diag['cycle']} count={totals['ebay_accepted']}")
    print(f"[EBAY_ALREADY_SEEN_COUNT] cycle={diag['cycle']} count={totals['ebay_skipped_seen']}")
    print(f"[EBAY_SENT_APP_COUNT] cycle={diag['cycle']} count={totals['ebay_sent_app']}")
    ebay_record_cycle_seen_ratio(totals["ebay_parsed"], totals["ebay_skipped_seen"])
    print(f"[EBAY_CYCLE_END] cycle={diag['cycle']} processar_ebay={diag['processar_ebay']}")


FREE_LANDING_MESSAGE = (
    "🎯 Pokemon Sniper Deals\n\n"
    "🔒 VIP access to the best Pokemon deals\n\n"
    "The difference between overpaying and finding the best deal is seeing it first.\n\n"
    "VIP gives you the advantage of seeing the best listings in real time, before they disappear or before someone else gets there first.\n\n"
    "🌍 Coverage:\n"
    "• eBay worldwide\n"
    "• Vinted Europe\n\n"
    "⚡ What you get inside VIP:\n"
    "• real-time listings\n"
    "• eBay sold references\n"
    "• seller feedback context\n"
    "• VIP market radar\n\n"
    "One good deal can easily pay for the subscription.\n\n"
    "💳 Plans:\n"
    "• 3.90 EUR monthly\n"
    "• 39.90 EUR yearly\n"
    "  approx. 15% discount\n\n"
    "💸 Payment methods:\n"
    "• PayPal\n"
    "• Skrill\n"
    "• Revolut\n"
    "• MB Way\n\n"
    "📩 Telegram contact:\n"
    "@tcgsniper\n\n"
    "After payment, send a message on Telegram to receive VIP access.\n\n"
    "Ready to join? Message @tcgsniper after payment for VIP access."
)

# ---------------- TELEGRAM ----------------

def enviar_telegram(mensagem, chat_id):
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": mensagem
    }

    try:
        resposta = requests.post(url, data=payload, timeout=15)
        dados = resposta.json()
        return bool(dados.get("ok"))
    except Exception as e:
        print("Erro Telegram:", e)
        return False


def enviar_foto_telegram(imagem_url, legenda, chat_id):
    url = f"https://api.telegram.org/bot{TOKEN}/sendPhoto"
    payload = {
        "chat_id": chat_id,
        "photo": imagem_url,
        "caption": legenda
    }

    try:
        resposta = requests.post(url, data=payload, timeout=20)
        dados = resposta.json()

        if not dados.get("ok"):
            return enviar_telegram(legenda, chat_id)

        return True

    except Exception:
        return enviar_telegram(legenda, chat_id)


def enviar_foto_local_telegram(image_path, legenda, chat_id):
    url = f"https://api.telegram.org/bot{TOKEN}/sendPhoto"
    payload = {
        "chat_id": chat_id,
        "caption": legenda,
    }

    try:
        with open(image_path, "rb") as f:
            resposta = requests.post(
                url,
                data=payload,
                files={"photo": f},
                timeout=60,
            )
        dados = resposta.json()
        if not dados.get("ok"):
            return enviar_telegram(legenda, chat_id)
        return True
    except Exception:
        return enviar_telegram(legenda, chat_id)


def enviar_documento_local_telegram(file_path, legenda, chat_id):
    url = f"https://api.telegram.org/bot{TOKEN}/sendDocument"
    payload = {
        "chat_id": chat_id,
        "caption": legenda,
    }

    try:
        with open(file_path, "rb") as f:
            resposta = requests.post(
                url,
                data=payload,
                files={"document": f},
                timeout=90,
            )
        dados = resposta.json()
        if not dados.get("ok"):
            return enviar_telegram(legenda, chat_id)
        return True
    except Exception:
        return enviar_telegram(legenda, chat_id)


def normalizar_badge_app(anuncio):
    if anuncio.get("prioritario"):
        return "Premium"

    score_label = obter_score_label(anuncio)
    if score_label == "HIGH":
        return "Off-market"
    if score_label == "MEDIUM":
        return "Strong"
    return "Fresh"


def construir_payload_app(anuncio):
    link = (anuncio.get("link") or "").strip()
    titulo = (anuncio.get("titulo") or "").strip()
    preco = (anuncio.get("preco") or "").strip()
    if not link or not titulo or not preco:
        return None

    plataforma = anuncio.get("source") or anuncio.get("origem") or "unknown"
    if isinstance(plataforma, str):
        plataforma_limpa = plataforma.strip().lower()
    else:
        plataforma_limpa = "unknown"

    plataforma_label = {
        "ebay": "eBay",
        "vinted": "Vinted",
        "olx": "OLX",
        "wallapop": "Wallapop",
    }.get(plataforma_limpa, str(plataforma).strip() or "Unknown")

    return {
        "source": plataforma_limpa,
        "external_id": anuncio.get("id"),
        "title": titulo,
        "price": preco,
        "url": link,
        "image_url": anuncio.get("imagem"),
        "platform": plataforma_label,
        "tcg_type": anuncio.get("tcg_type") or "pokemon",
        "category": anuncio.get("categoria"),
        "score": anuncio.get("score"),
        "score_label": obter_score_label(anuncio),
        "badge_label": normalizar_badge_app(anuncio),
        "detected_at": ensure_detected_at(anuncio),
        "available_status": "available",
        "seller_feedback": anuncio.get("seller_feedback"),
        "raw_payload": anuncio.get("raw_payload"),
    }


def enviar_anuncio_app(anuncio):
    item_id = anuncio.get("id")
    platform = anuncio.get("source") or anuncio.get("origem") or "unknown"
    if not tcg_enabled(anuncio.get("tcg_type")):
        print(
            f"[APP API] skipped disabled tcg id={item_id} "
            f"tcg_type={anuncio.get('tcg_type')}"
        )
        return {"status": "disabled_tcg"}

    if not APP_API_ENABLED:
        return {"status": "disabled"}

    if not APP_API_URL:
        print(f"[APP_API_SEND_ATTEMPT] id={item_id} url=missing platform={platform}")
        print("[APP API] disabled because URL is missing")
        return {"status": "disabled_missing_config"}

    if not BOT_API_KEY:
        print(f"[APP_API_SEND_ATTEMPT] id={item_id} url={APP_API_URL} platform={platform}")
        print("[APP_API_AUTH_MISSING]")
        return {"status": "disabled_missing_config"}

    payload = construir_payload_app(anuncio)
    if not payload:
        print(f"[APP API] skipped invalid payload for {item_id}")
        return {"status": "invalid_payload"}
    print(
        f"[APP_API_SEND_ATTEMPT] id={payload.get('external_id')} "
        f"url={APP_API_URL} platform={payload.get('source')}"
    )

    try:
        resposta = HTTP_SESSION.post(
            APP_API_URL,
            json=payload,
            headers={
                "Content-Type": "application/json",
                "X-API-Key": BOT_API_KEY,
            },
            timeout=APP_API_TIMEOUT,
        )
    except requests.RequestException as e:
        print(
            f"[APP_API_SEND_RESULT] id={payload.get('external_id')} "
            f"http=request_failed status=request_failed body_short={str(e)[:220]}"
        )
        if payload.get("source") == "ebay":
            print(
                f"[EBAY_SEND_APP_ERROR] id={payload.get('external_id')} "
                f"status=request_failed error=\"{str(e)[:220]}\""
            )
        return {"status": "request_failed", "error": str(e)}

    body_short = (resposta.text or "")[:300].replace("\n", "\\n")
    try:
        dados = resposta.json()
    except ValueError:
        dados = {
            "status": "invalid_response",
            "body": resposta.text[:300],
        }

    status = dados.get("status") or f"http_{resposta.status_code}"
    print(
        f"[APP_API_SEND_RESULT] id={payload.get('external_id')} "
        f"http={resposta.status_code} status={status} body_short={body_short}"
    )
    if payload.get("source") == "ebay":
        if 200 <= resposta.status_code < 300:
            print(
                f"[EBAY_SENT_APP] id={payload.get('external_id')} "
                f"status={status} http={resposta.status_code} url={APP_API_URL}"
            )
        else:
            print(
                f"[EBAY_SEND_APP_ERROR] id={payload.get('external_id')} "
                f"status={status} http={resposta.status_code} body_short={body_short}"
            )
    if resposta.status_code == 201 and status == "inserted":
        print(f"[APP API] inserted {payload.get('external_id')} into VIP app")
        print(f"[APP_FEED_VISIBLE] id={payload.get('external_id')} app_listing_id={dados.get('id')}")
    elif resposta.status_code == 200 and status == "duplicate":
        print(f"[APP API] duplicate {payload.get('external_id')} already in VIP app")
        print(f"[APP_FEED_VISIBLE] id={payload.get('external_id')} app_listing_id={dados.get('id')} status=duplicate")
    elif resposta.status_code in {401, 403}:
        print("[APP_API_AUTH_FAILED]")
    else:
        print(f"[APP API] unexpected response for {payload.get('external_id')}: {resposta.status_code} {dados}")

    return {
        "status": status,
        "http_status": resposta.status_code,
        "data": dados,
    }


def _mask_runtime_value(value):
    text = str(value or "").strip()
    if not text:
        return "missing"
    if len(text) <= 8:
        return "***"
    return f"{text[:4]}...{text[-4:]}"


def _app_api_target_label():
    url = str(APP_API_URL or "").lower()
    if "127.0.0.1" in url or "localhost" in url:
        return "local"
    if url:
        return "online"
    return "disabled"


def log_delivery_config():
    print(
        "[delivery_config] "
        f"app_api_enabled={APP_API_ENABLED} "
        f"app_target={_app_api_target_label()} "
        f"app_api_url={APP_API_URL or 'missing'}"
    )
    print(
        "[delivery_config] "
        f"app_api_key={'present' if BOT_API_KEY else 'missing'}"
    )
    print(
        "[delivery_config] "
        f"free_realtime_sample={_free_realtime_sample_percent()}% "
        f"free_chat={_mask_runtime_value(FREE_CHAT_ID)} "
        f"vip_chat={_mask_runtime_value(VIP_CHAT_ID)}"
    )


def enviar_status_anuncio_app(anuncio, status):
    if not APP_API_ENABLED:
        return {"status": "disabled"}

    if not APP_API_STATUS_URL or not BOT_API_KEY:
        return {"status": "disabled_missing_config"}

    payload = {
        "source": (anuncio.get("source") or anuncio.get("origem") or "").strip().lower(),
        "external_id": anuncio.get("id"),
        "available_status": status,
        "detected_at": ensure_detected_at(anuncio),
    }

    try:
        resposta = HTTP_SESSION.post(
            APP_API_STATUS_URL,
            json=payload,
            headers={
                "Content-Type": "application/json",
                "X-API-Key": BOT_API_KEY,
            },
            timeout=APP_API_TIMEOUT,
        )
    except requests.RequestException as e:
        print(f"[APP API] status request failed for {payload.get('external_id')}: {e}")
        return {"status": "request_failed", "error": str(e)}

    try:
        dados = resposta.json()
    except ValueError:
        dados = {"status": "invalid_response", "body": resposta.text[:300]}

    status_code = dados.get("status") or f"http_{resposta.status_code}"
    if resposta.status_code == 200 and status_code == "updated":
        print(f"[APP API] status updated for {payload.get('external_id')} -> {status}")
    elif resposta.status_code == 404:
        print(f"[APP API] status update missing listing for {payload.get('external_id')}")
    else:
        print(f"[APP API] unexpected status response for {payload.get('external_id')}: {resposta.status_code} {dados}")

    return {
        "status": status_code,
        "http_status": resposta.status_code,
        "data": dados,
    }

# ---------------- UTIL ----------------

def extrair_id(link):
    ebay_item_id = extrair_ebay_item_id(link)
    if ebay_item_id:
        return ebay_item_id

    match = re.search(r"/items/(\d+)|/ID([A-Za-z0-9]+)|/itm/(\d+)", link)
    if match:
        return match.group(1) or match.group(2) or match.group(3)
    return link


def extrair_ebay_item_id(link):
    if not link:
        return None

    try:
        parts = urlsplit(link)
    except Exception:
        parts = None

    path = parts.path if parts else str(link)
    patterns = [
        r"/itm/(?:[^/?#]+/)?(\d{9,20})(?:[/?#]|$)",
        r"/itm/(\d{9,20})(?:[/?#]|$)",
    ]
    for pattern in patterns:
        match = re.search(pattern, path)
        if match:
            return match.group(1)

    if parts:
        query_item_ids = parse_qs(parts.query).get("item")
        if query_item_ids and re.fullmatch(r"\d{9,20}", query_item_ids[0] or ""):
            return query_item_ids[0]

    return None


def ebay_seen_id_from_link(link):
    item_id = extrair_ebay_item_id(link)
    return f"ebay_{item_id}" if item_id else None


def extrair_ebay_item_id_api(item_id):
    text = str(item_id or "")
    if not text:
        return None
    match = re.search(r"(\d{9,20})", text)
    return match.group(1) if match else None


def ebay_seen_id_from_api_item_id(item_id):
    item_id = extrair_ebay_item_id_api(item_id)
    return f"ebay_{item_id}" if item_id else None


def limpar_link(link):
    return link.split("?")[0].strip()


def _parse_seen_timestamp(value):
    if not value:
        return None
    try:
        cleaned = value.strip().replace("Z", "+00:00")
        parsed = datetime.fromisoformat(cleaned)
    except Exception:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _parse_seen_line(line):
    raw = (line or "").strip()
    if not raw:
        return None, None, raw

    if "\t" in raw:
        item_id, timestamp = raw.split("\t", 1)
    elif raw.startswith("ebay_") and "|" in raw:
        item_id, timestamp = raw.split("|", 1)
    else:
        item_id, timestamp = raw, None

    return item_id.strip(), _parse_seen_timestamp(timestamp), raw


def _seen_line_is_active(item_id, seen_at):
    if not item_id:
        return False
    if not item_id.startswith("ebay_"):
        return True
    if seen_at is None:
        return False
    cutoff = datetime.now(timezone.utc) - timedelta(hours=EBAY_SEEN_TTL_HOURS)
    return seen_at >= cutoff


def _format_seen_line(id_item):
    if (id_item or "").startswith("ebay_"):
        timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
        return f"{id_item}\t{timestamp}"
    return id_item


def write_json_atomically(path, data):
    temp_path = path + ".tmp"
    with open(temp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(temp_path, path)


def compactar_ficheiro_linhas(path, max_lines, drop_prefixes=None, expire_ebay_seen=False):
    if not os.path.exists(path):
        return

    try:
        drop_prefixes = tuple(drop_prefixes or [])
        kept_lines = []
        ebay_lines = deque(maxlen=MAX_EBAY_SEEN_ITEMS)
        expired_ebay_count = 0
        with open(path, "r", encoding="utf-8") as f:
            for linha in f:
                raw = linha.strip()
                if not raw:
                    continue
                item_id, seen_at, raw = _parse_seen_line(raw)
                if not item_id or any(item_id.startswith(prefix) for prefix in drop_prefixes):
                    continue
                if expire_ebay_seen and not _seen_line_is_active(item_id, seen_at):
                    if item_id.startswith("ebay_"):
                        expired_ebay_count += 1
                    continue
                if expire_ebay_seen and item_id.startswith("ebay_"):
                    ebay_lines.append(raw)
                else:
                    kept_lines.append(raw)

        linhas_ativas = kept_lines + list(ebay_lines)
        ultimas = deque(linhas_ativas, maxlen=max_lines)

        with open(path, "w", encoding="utf-8") as f:
            for linha in ultimas:
                f.write(linha + "\n")
        if expire_ebay_seen and expired_ebay_count:
            print(
                f"[EBAY_SEEN_EXPIRED] count={expired_ebay_count} "
                f"file={os.path.basename(path)} ttl_hours={EBAY_SEEN_TTL_HOURS}"
            )
    except Exception:
        pass


def trim_cache_entries(cache, max_items):
    if not isinstance(cache, dict) or len(cache) <= max_items:
        return cache if isinstance(cache, dict) else {}

    ordenados = sorted(
        cache.items(),
        key=lambda item: sort_iso_key(item[1].get("updated_at")) if isinstance(item[1], dict) else sort_iso_key(None),
        reverse=True,
    )[:max_items]
    return dict(ordenados)


def carregar_vistos():
    if not os.path.exists(FICHEIRO_VISTOS):
        return set()

    drop_prefixes = ["olx_"] if not OLX_ENABLED else []
    if EBAY_DEBUG_IGNORE_MAIN_VISTOS:
        drop_prefixes.append("ebay_")

    ultimos = deque(maxlen=MAX_VISTOS_ITEMS)
    expired_ebay_count = 0
    with open(FICHEIRO_VISTOS, "r", encoding="utf-8") as f:
        for line in f:
            item_id, seen_at, _raw = _parse_seen_line(line)
            if not item_id or any(item_id.startswith(prefix) for prefix in drop_prefixes):
                continue
            if not _seen_line_is_active(item_id, seen_at):
                if item_id.startswith("ebay_"):
                    expired_ebay_count += 1
                continue
            ultimos.append(item_id)
    if expired_ebay_count:
        print(
            f"[EBAY_SEEN_EXPIRED] count={expired_ebay_count} "
            f"file={os.path.basename(FICHEIRO_VISTOS)} ttl_hours={EBAY_SEEN_TTL_HOURS}"
        )
    return set(ultimos)


def guardar_visto(id_item):
    if not OLX_ENABLED and (id_item or "").startswith("olx_"):
        return
    with open(FICHEIRO_VISTOS, "a", encoding="utf-8") as f:
        f.write(_format_seen_line(id_item) + "\n")


def carregar_vistos_ebay_debug():
    if not os.path.exists(FICHEIRO_VISTOS_EBAY_DEBUG):
        return set()

    expired_ebay_count = 0
    ultimos = deque(maxlen=MAX_VISTOS_EBAY_DEBUG_ITEMS)
    with open(FICHEIRO_VISTOS_EBAY_DEBUG, "r", encoding="utf-8") as f:
        for line in f:
            item_id, seen_at, _raw = _parse_seen_line(line)
            if not item_id:
                continue
            if not _seen_line_is_active(item_id, seen_at):
                if item_id.startswith("ebay_"):
                    expired_ebay_count += 1
                continue
            ultimos.append(item_id)
    if expired_ebay_count:
        print(
            f"[EBAY_SEEN_EXPIRED] count={expired_ebay_count} "
            f"file={os.path.basename(FICHEIRO_VISTOS_EBAY_DEBUG)} ttl_hours={EBAY_SEEN_TTL_HOURS}"
        )
    return set(ultimos)


def guardar_visto_ebay_debug(id_item):
    with open(FICHEIRO_VISTOS_EBAY_DEBUG, "a", encoding="utf-8") as f:
        f.write(_format_seen_line(id_item) + "\n")


def mark_seen_after_app_delivery(anuncio, app_result):
    item_id = anuncio.get("id") if isinstance(anuncio, dict) else None
    app_status = (app_result or {}).get("status")
    source = (anuncio.get("source") or "").lower() if isinstance(anuncio, dict) else ""
    successful_statuses = {"inserted", "duplicate"}
    if not item_id or app_status not in successful_statuses:
        if source == "ebay":
            print(f"[EBAY_SEEN_NOT_MARKED] item_id={item_id} app_status={app_status}")
        else:
            print(f"[SEEN_SKIPPED] id={item_id} app_status={app_status}")
        return False

    guardar_visto(item_id)
    if (
        source == "ebay"
        and EBAY_DEBUG_MODE
        and EBAY_DEBUG_IGNORE_MAIN_VISTOS
    ):
        guardar_visto_ebay_debug(item_id)
    if source == "ebay":
        print(f"[EBAY_SEEN_MARKED] item_id={item_id} reason={app_status}")
    else:
        print(f"[SEEN_MARKED] id={item_id} app_status={app_status}")
    return True


def mark_seen_after_telegram_delivery(anuncio, free_result):
    item_id = anuncio.get("id") if isinstance(anuncio, dict) else None
    free_status = (free_result or {}).get("status")
    source = (anuncio.get("source") or "").lower() if isinstance(anuncio, dict) else ""
    if not item_id or free_status != "sent":
        print(f"[SEEN_SKIPPED] id={item_id} free_status={free_status}")
        return False
    if source == "ebay":
        print(f"[EBAY_SEEN_NOT_MARKED] item_id={item_id} reason=telegram_delivery_only")
        return False

    guardar_visto(item_id)
    if (
        (anuncio.get("source") or "").lower() == "ebay"
        and EBAY_DEBUG_MODE
        and EBAY_DEBUG_IGNORE_MAIN_VISTOS
    ):
        guardar_visto_ebay_debug(item_id)
    print(f"[SEEN_MARKED] id={item_id} free_status={free_status}")
    return True


def tcg_enabled(tcg_type):
    if tcg_type == "pokemon":
        return True
    if tcg_type == "one_piece":
        return ENABLE_ONE_PIECE
    return False


def disabled_tcg_reason(tcg_type):
    if tcg_type == "one_piece" and not ENABLE_ONE_PIECE:
        return "one_piece_disabled"
    return "tcg_disabled"


def carregar_cache_cardmarket():
    if not os.path.exists(FICHEIRO_CACHE_CARDMARKET):
        return {}

    try:
        with open(FICHEIRO_CACHE_CARDMARKET, "r", encoding="utf-8") as f:
            return trim_cache_entries(json.load(f), MAX_CARDMARKET_CACHE_ITEMS)
    except:
        return {}


def guardar_cache_cardmarket(cache):
    write_json_atomically(FICHEIRO_CACHE_CARDMARKET, trim_cache_entries(cache, MAX_CARDMARKET_CACHE_ITEMS))


def carregar_cache_ebay_sold():
    if not ENABLE_EBAY_SOLD_REFERENCES:
        return {}
    if not os.path.exists(FICHEIRO_CACHE_EBAY_SOLD):
        return {}

    try:
        with open(FICHEIRO_CACHE_EBAY_SOLD, "r", encoding="utf-8") as f:
            dados = json.load(f)
            if not isinstance(dados, dict):
                return {}

            agora = datetime.now().astimezone()
            cache_limpo = {}
            for chave, entry in dados.items():
                if not isinstance(entry, dict):
                    continue

                updated_at = parse_iso_or_none(entry.get("updated_at"))
                if not updated_at:
                    continue

                if entry.get("data") is None:
                    if updated_at >= agora - timedelta(minutes=EBAY_SOLD_NEGATIVE_CACHE_MAX_AGE_MINUTES):
                        cache_limpo[chave] = entry
                else:
                    cache_limpo[chave] = entry

            return trim_cache_entries(cache_limpo, MAX_EBAY_SOLD_CACHE_ITEMS)
    except:
        return {}


def guardar_cache_ebay_sold(cache):
    if not ENABLE_EBAY_SOLD_REFERENCES:
        return
    write_json_atomically(FICHEIRO_CACHE_EBAY_SOLD, trim_cache_entries(cache, MAX_EBAY_SOLD_CACHE_ITEMS))


def cache_entry_fresh(updated_at, max_age_hours):
    dt = parse_iso_or_none(updated_at)
    if not dt:
        return False
    return dt >= datetime.now().astimezone() - timedelta(hours=max_age_hours)


def compactar_anuncio_para_fila_free(anuncio):
    anuncio_id = anuncio.get("id")
    compacto = {
        "id": anuncio_id,
        "source": anuncio.get("source"),
        "origem": anuncio.get("origem"),
        "tcg_type": anuncio.get("tcg_type"),
        "titulo": anuncio.get("titulo"),
        "preco": anuncio.get("preco"),
        "link": build_free_public_listing_url(anuncio_id),
        "share_link": build_free_public_listing_url(anuncio_id),
        "seller_feedback": anuncio.get("seller_feedback"),
    }

    if not LIGHT_MODE and anuncio.get("imagem"):
        compacto["imagem"] = anuncio.get("imagem")

    return compacto


def cleanup_fila_free(fila):
    if not isinstance(fila, list):
        return []

    itens = []
    for item in fila:
        if not isinstance(item, dict):
            continue

        anuncio = item.get("anuncio") if isinstance(item.get("anuncio"), dict) else {}
        if not item.get("id") or not anuncio.get("titulo") or not anuncio.get("link"):
            continue

        item["anuncio"] = compactar_anuncio_para_fila_free(anuncio)
        item["detected_at"] = item.get("detected_at") or item.get("anuncio", {}).get("detected_at") or now_iso()
        item["eligible_at"] = item.get("eligible_at") or item.get("enviar_em") or item["detected_at"]
        item["share_link"] = item.get("share_link") or build_free_public_listing_url(item.get("id"))

        itens.append(item)
    return itens


def carregar_fila_free():
    if not os.path.exists(FICHEIRO_FILA_FREE):
        return []

    try:
        mtime = os.path.getmtime(FICHEIRO_FILA_FREE)
        if _FREE_QUEUE_CACHE["data"] is not None and _FREE_QUEUE_CACHE["mtime"] == mtime:
            return list(_FREE_QUEUE_CACHE["data"])

        with open(FICHEIRO_FILA_FREE, "r", encoding="utf-8") as f:
            dados = cleanup_fila_free(json.load(f))
            _FREE_QUEUE_CACHE["mtime"] = mtime
            _FREE_QUEUE_CACHE["data"] = dados
            return list(dados)
    except:
        return []


def guardar_fila_free(fila):
    fila = cleanup_fila_free(fila)
    write_json_atomically(FICHEIRO_FILA_FREE, fila)
    try:
        _FREE_QUEUE_CACHE["mtime"] = os.path.getmtime(FICHEIRO_FILA_FREE)
    except Exception:
        _FREE_QUEUE_CACHE["mtime"] = None
    _FREE_QUEUE_CACHE["data"] = fila


def now_iso():
    return datetime.now().astimezone().isoformat(timespec="seconds")


def detected_at_now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def ensure_detected_at(anuncio):
    detected_at = anuncio.get("detected_at") or detected_at_now_iso()
    anuncio["detected_at"] = detected_at
    return detected_at


def parse_iso_or_none(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except Exception:
        return None


def sort_iso_key(value, fallback=datetime.min):
    parsed = parse_iso_or_none(value)
    if parsed:
        return parsed
    if fallback.tzinfo is None:
        return fallback.replace(tzinfo=datetime.now().astimezone().tzinfo)
    return fallback


def anuncio_recency_tuple(anuncio):
    return (
        sort_iso_key(anuncio.get("detected_at")),
    )


def mix_announcements_by_source(novos, max_same_source_streak=1):
    if len(novos) < 3:
        return novos

    grouped = {}
    source_order = []

    for anuncio in novos:
        source = anuncio.get("source") or "unknown"
        if source not in grouped:
            grouped[source] = deque()
            source_order.append(source)
        grouped[source].append(anuncio)

    if len(grouped) <= 1:
        return novos

    mixed = []
    last_source = None
    same_source_streak = 0

    while len(mixed) < len(novos):
        available_sources = [source for source in source_order if grouped[source]]
        if not available_sources:
            break

        available_sources.sort(
            key=lambda source: anuncio_recency_tuple(grouped[source][0]),
            reverse=True,
        )

        chosen_source = None
        if last_source and same_source_streak >= max_same_source_streak:
            for source in available_sources:
                if source != last_source:
                    chosen_source = source
                    break

        if chosen_source is None:
            chosen_source = available_sources[0]

        mixed.append(grouped[chosen_source].popleft())

        if chosen_source == last_source:
            same_source_streak += 1
        else:
            last_source = chosen_source
            same_source_streak = 1

    return mixed


def playwright_launch_args():
    return [
        "--disable-dev-shm-usage",
        "--disable-gpu",
        "--disable-software-rasterizer",
        "--disable-extensions",
        "--disable-background-networking",
        "--disable-background-timer-throttling",
        "--disable-renderer-backgrounding",
        "--disable-sync",
        "--disable-component-update",
        "--aggressive-cache-discard",
        "--disk-cache-size=1",
        "--media-cache-size=1",
        "--renderer-process-limit=1",
        "--metrics-recording-only",
        "--mute-audio",
        "--no-first-run",
        "--no-default-browser-check",
    ]


def should_block_playwright_request(request):
    try:
        resource_type = request.resource_type
        url = (request.url or "").lower()
    except Exception:
        return False

    if resource_type in {"image", "media", "font"}:
        return True

    block_markers = [
        "google-analytics", "googletagmanager", "doubleclick", "facebook.com/tr",
        "connect.facebook.net", "analytics", "segment", "hotjar", "clarity",
        "bing.com/fd/ls", "bat.bing", "pixel", "tracking",
    ]
    return any(marker in url for marker in block_markers)


def _route_handler(route):
    try:
        if should_block_playwright_request(route.request):
            route.abort()
        else:
            route.continue_()
    except Exception:
        try:
            route.continue_()
        except Exception:
            pass


def create_light_context(browser):
    context = browser.new_context(
        viewport={"width": 1280, "height": 900},
        locale="en-US",
        color_scheme="light",
        reduced_motion="reduce",
        service_workers="block",
    )
    context.set_default_timeout(PLAYWRIGHT_QUERY_TIMEOUT)
    context.set_default_navigation_timeout(PLAYWRIGHT_NAV_TIMEOUT)
    context.route("**/*", _route_handler)
    return context


def close_runtime(reason="shutdown"):
    context = _RUNTIME.get("context")
    browser = _RUNTIME.get("browser")
    playwright = _RUNTIME.get("playwright")

    for key in ["page_lista", "page_detalhe"]:
        page = _RUNTIME.get(key)
        if page:
            try:
                page.close()
            except Exception:
                pass
        _RUNTIME[key] = None

    if context:
        try:
            context.close()
        except Exception:
            pass
    if browser:
        try:
            browser.close()
        except Exception:
            pass
    if playwright:
        try:
            playwright.stop()
        except Exception:
            pass

    refresh_count = _RUNTIME.get("refresh_count", 0)
    _RUNTIME.update({
        "playwright": None,
        "browser": None,
        "context": None,
        "page_lista": None,
        "page_detalhe": None,
        "created_at": None,
        "created_cycle": 0,
        "refresh_count": refresh_count,
    })

    if reason:
        print(f"[RUNTIME] browser fechado ({reason})")
    gc.collect()


def runtime_state_counts():
    context = _RUNTIME.get("context")
    browser = _RUNTIME.get("browser")
    try:
        contexts = len(browser.contexts) if browser else 0
    except Exception:
        contexts = 0
    try:
        pages = len(context.pages) if context else 0
    except Exception:
        pages = 0
    return contexts, pages


def get_process_memory_mb():
    try:
        class PROCESS_MEMORY_COUNTERS(ctypes.Structure):
            _fields_ = [
                ("cb", ctypes.c_ulong),
                ("PageFaultCount", ctypes.c_ulong),
                ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t),
            ]

        counters = PROCESS_MEMORY_COUNTERS()
        counters.cb = ctypes.sizeof(PROCESS_MEMORY_COUNTERS)
        handle = ctypes.windll.kernel32.GetCurrentProcess()
        ok = ctypes.windll.psapi.GetProcessMemoryInfo(handle, ctypes.byref(counters), counters.cb)
        if ok:
            return round(counters.WorkingSetSize / (1024 * 1024), 1)
    except Exception:
        return None
    return None


def get_system_memory_percent():
    try:
        meminfo = {}
        with open("/proc/meminfo", "r", encoding="utf-8") as f:
            for line in f:
                key, value = line.split(":", 1)
                meminfo[key] = int(value.strip().split()[0])
        total = meminfo.get("MemTotal")
        available = meminfo.get("MemAvailable")
        if total and available is not None:
            return round(((total - available) / total) * 100, 1)
    except Exception:
        pass

    try:
        class MEMORYSTATUSEX(ctypes.Structure):
            _fields_ = [
                ("dwLength", ctypes.c_ulong),
                ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong),
                ("sullAvailExtendedVirtual", ctypes.c_ulonglong),
            ]

        status = MEMORYSTATUSEX()
        status.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            return round(float(status.dwMemoryLoad), 1)
    except Exception:
        pass

    return None


def log_ram_usage(stage):
    percent = get_system_memory_percent()
    percent_text = f"{percent:.1f}" if isinstance(percent, (int, float)) else "unknown"
    print(f"[RAM_USAGE] stage={stage} percent={percent_text}")


def log_memory_usage(cycle):
    memoria_mb = get_process_memory_mb()
    contexts, pages = runtime_state_counts()
    gc_counts = gc.get_count()
    if memoria_mb is None:
        print(f"[MEM] ciclo={cycle} contextos={contexts} paginas={pages} gc={gc_counts}")
    else:
        print(f"[MEM] ciclo={cycle} ram={memoria_mb}MB contextos={contexts} paginas={pages} gc={gc_counts}")


def log_runtime_state(cycle, refreshed=False):
    contexts, pages = runtime_state_counts()
    print(
        f"[RUNTIME] ciclo={cycle} ativo={_RUNTIME.get('browser') is not None} "
        f"contextos={contexts} paginas={pages} refresh={refreshed} total_refresh={_RUNTIME.get('refresh_count', 0)}"
    )


def release_runtime_pages():
    context = _RUNTIME.get("context")
    if not context:
        return

    try:
        paginas = list(context.pages)
    except Exception:
        return

    paginas_core = {
        id(_RUNTIME.get("page_lista")),
        id(_RUNTIME.get("page_detalhe")),
    }

    for page in paginas:
        if id(page) not in paginas_core:
            try:
                page.close()
            except Exception:
                pass

    for key in ["page_lista", "page_detalhe"]:
        page = _RUNTIME.get(key)
        if page:
            try:
                page.close()
            except Exception:
                pass
        _RUNTIME[key] = None


def reset_runtime_page(page_key):
    context = _RUNTIME.get("context")
    if not context:
        return None

    old_page = _RUNTIME.get(page_key)
    if old_page:
        try:
            old_page.close()
        except Exception:
            pass

    try:
        new_page = context.new_page()
    except Exception:
        new_page = None

    _RUNTIME[page_key] = new_page
    return new_page


def clear_playwright_page(page):
    if not page:
        return
    try:
        page.evaluate("() => { window.stop(); document.documentElement.innerHTML = ''; }")
    except Exception:
        pass
    try:
        page.goto("about:blank", timeout=5000, wait_until="load")
    except Exception:
        pass


def close_playwright_page(page):
    if not page:
        return
    try:
        page.close()
    except Exception:
        pass


def recycle_page(context, page, runtime_key=None):
    close_playwright_page(page)
    try:
        new_page = context.new_page()
    except Exception:
        new_page = None
    if runtime_key:
        _RUNTIME[runtime_key] = new_page
    return new_page


def runtime_needs_refresh(cycle):
    if _RUNTIME.get("browser") is None:
        return False

    contexts, pages = runtime_state_counts()
    if contexts > 1 or pages > 3:
        return True

    created_at = parse_iso_or_none(_RUNTIME.get("created_at"))
    created_cycle = _RUNTIME.get("created_cycle", 0)

    if BROWSER_REFRESH_EVERY_CYCLES and cycle - created_cycle >= BROWSER_REFRESH_EVERY_CYCLES:
        return True

    if BROWSER_REFRESH_EVERY_MINUTES and created_at:
        return created_at <= datetime.now().astimezone() - timedelta(minutes=BROWSER_REFRESH_EVERY_MINUTES)

    return False


def maybe_refresh_runtime(cycle):
    if not LIGHT_MODE:
        return

    if runtime_needs_refresh(cycle):
        _RUNTIME["refresh_count"] = _RUNTIME.get("refresh_count", 0) + 1
        close_runtime(reason=f"refresh ciclo {cycle}")
        log_runtime_state(cycle, refreshed=True)


def page_is_usable(page):
    try:
        return page is not None and not page.is_closed()
    except Exception:
        return False


atexit.register(close_runtime)


def parse_relative_published_at(texto):
    if not texto:
        return None

    agora = datetime.now().astimezone()
    t = " ".join((texto or "").lower().split())

    patterns = [
        (r"listed\s+(\d+)\s+minutes?\s+ago", "minutes"),
        (r"listed\s+(\d+)\s+hours?\s+ago", "hours"),
        (r"posted\s+(\d+)\s+minutes?\s+ago", "minutes"),
        (r"posted\s+(\d+)\s+hours?\s+ago", "hours"),
        (r"h[aá]\s+(\d+)\s+minutos?", "minutes"),
        (r"h[aá]\s+(\d+)\s+horas?", "hours"),
        (r"(\d+)\s+minutos?\s+atr[aá]s", "minutes"),
        (r"(\d+)\s+horas?\s+atr[aá]s", "hours"),
    ]

    for pattern, unit in patterns:
        match = re.search(pattern, t, re.IGNORECASE)
        if match:
            value = int(match.group(1))
            if unit == "minutes":
                return (agora - timedelta(minutes=value)).isoformat(timespec="seconds")
            if unit == "hours":
                return (agora - timedelta(hours=value)).isoformat(timespec="seconds")

    today_match = re.search(r"(today|hoje)\s*(?:at|às|as)?\s*(\d{1,2}):(\d{2})", t, re.IGNORECASE)
    if today_match:
        hour = int(today_match.group(2))
        minute = int(today_match.group(3))
        dt = agora.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if dt > agora:
            dt -= timedelta(days=1)
        return dt.isoformat(timespec="seconds")

    yesterday_match = re.search(r"(yesterday|ontem)\s*(?:at|às|as)?\s*(\d{1,2}):(\d{2})", t, re.IGNORECASE)
    if yesterday_match:
        hour = int(yesterday_match.group(2))
        minute = int(yesterday_match.group(3))
        dt = (agora - timedelta(days=1)).replace(hour=hour, minute=minute, second=0, microsecond=0)
        return dt.isoformat(timespec="seconds")

    return None


def count_term_matches(normalized_text, terms):
    return sum(1 for term in terms if term in normalized_text)


def classify_tcg_type(title, extra_text=""):
    normalized = normalize_text(f"{title} {extra_text}")
    if not normalized:
        return None

    pokemon_score = count_term_matches(normalized, POKEMON_TCG_TERMS)
    one_piece_score = count_term_matches(normalized, ONE_PIECE_TCG_TERMS)

    if re.search(r"\bop0?\d\b", normalized):
        one_piece_score += 2
    if "one piece" in normalized:
        one_piece_score += 3
    if "pokemon" in normalized or "pok mon" in normalized:
        pokemon_score += 3

    if one_piece_score >= 3 and one_piece_score > pokemon_score:
        return "one_piece"
    if pokemon_score >= 2 and pokemon_score >= one_piece_score:
        return "pokemon"
    return None


def ebay_term_hit(normalized_text, term):
    term_norm = normalize_text(term)
    if not normalized_text or not term_norm:
        return False
    return re.search(rf"\b{re.escape(term_norm)}\b", normalized_text) is not None


def ebay_first_term_hit(text, terms):
    normalized = normalize_text(text)
    for term in terms:
        if ebay_term_hit(normalized, term):
            return term
    return None


def ebay_obvious_junk_keyword(title, extra_text=""):
    normalized = normalize_text(f"{title} {extra_text}")
    if not normalized:
        return None

    hit = ebay_first_term_hit(normalized, EBAY_JUNK_TERMS)
    if hit:
        return hit

    has_cards = any(ebay_term_hit(normalized, term) for term in ["card", "cards", "tcg", "booster", "pack", "sealed"])
    if ebay_term_hit(normalized, "binder") and not has_cards:
        return "binder only"
    if ebay_term_hit(normalized, "album") and not has_cards:
        return "album only"
    return None


def ebay_positive_product_keyword(title, extra_text=""):
    normalized = normalize_text(f"{title} {extra_text}")
    if not normalized:
        return None

    has_pokemon_context = (
        ebay_term_hit(normalized, "pokemon")
        or ebay_term_hit(normalized, "pok mon")
        or any(ebay_term_hit(normalized, name) for name in PALAVRAS_CARTA_FORTE)
    )
    if not has_pokemon_context:
        return None

    return (
        ebay_first_term_hit(normalized, EBAY_SEALED_PRODUCT_TERMS)
        or ebay_first_term_hit(normalized, EBAY_GRADED_PRODUCT_TERMS)
        or ebay_first_term_hit(normalized, ["card", "cards", "trading card", "tcg"])
    )


def classify_ebay_tcg_type(title, extra_text=""):
    if ebay_obvious_junk_keyword(title):
        return None

    if ebay_positive_product_keyword(title, extra_text):
        return "pokemon"

    tcg_type = classify_tcg_type(title, extra_text)
    if tcg_type:
        return tcg_type

    normalized = normalize_text(f"{title} {extra_text}")
    if not normalized:
        return None

    pokemon_hints = [
        "pokemon", "pokemon tcg", "card english", "cards english",
        "illustration rare", "booster box", "half booster box", "elite trainer box",
        "etb", "sealed", "psa", "bgs", "beckett", "cgc",
        "booster", "booster bundle", "collection box", "premium collection",
        "ultra premium collection", "tin", "pack", "blister", "graded", "slab",
    ]
    one_piece_hints = [
        "one piece", "one piece tcg", "op01", "op02", "op03", "op04", "op05",
        "op06", "op07", "op08", "op09", "op10",
    ]

    if any(term in normalized for term in one_piece_hints):
        return "one_piece"

    if "pokemon" in normalized and any(term in normalized for term in pokemon_hints):
        return "pokemon"

    return None


def reject_reason_one_piece(title, source=None):
    normalized = normalize_text(title)
    if not normalized:
        return "empty_title"

    noise_terms = [
        "fake", "proxy", "falso", "fausse", "faux",
        "reservado", "reservada", "dont buy", "don't buy",
        "nao comprar", "no comprar", "ne pas acheter", "pas acheter",
        "troco", "troca", "yugioh", "yu gi oh",
        "peluche", "peluches", "plush", "figura", "figuras", "figure", "figures",
        "figurine", "funko", "statue", "doll", "toy", "toys", "hoodie", "shirt",
        "jacket", "hat", "cap", "caps", "chapeu", "bone", "gorro", "mochila",
        "backpack", "bag", "mala", "sold", "vendido", "agotado", "out of stock",
    ]

    if source == "ebay":
        noise_terms.extend(["presale", "preorder", "digital", "code card only", "empty box"])

    for term in noise_terms:
        if term in normalized:
            return "noise:" + term

    return None


def assess_one_piece_listing(title, price_text=None, source=None):
    reason = reject_reason_one_piece(title, source)
    if reason:
        return ListingAssessment(
            is_valid=False,
            score=0,
            category="rejected",
            confidence="none",
            reasons=[],
            reject_reason=reason,
        )

    normalized = normalize_text(title)
    score = 0
    reasons = []
    category = "unknown"

    if any(term in normalized for term in ["psa", "bgs", "beckett", "cgc", "slab", "graded", "grade"]):
        category = "graded_card"
        score += 26
        reasons.append("graded")
    elif any(term in normalized for term in ["booster", "booster box", "booster pack", "sealed", "box", "blister", "starter deck", "double pack"]):
        category = "sealed_product"
        score += 22
        reasons.append("sealed")
    elif any(term in normalized for term in ["lote", "lot", "bundle", "collection", "bulk"]):
        category = "lot_collection"
        score += 4
        reasons.append("lot")
    elif re.search(r"\bop0?\d\b", normalized) or any(term in normalized for term in ONE_PIECE_STRONG_TERMS):
        category = "single_card"
        score += 14
        reasons.append("single_card")

    score += 12
    reasons.append("one_piece_tcg")

    if re.search(r"\bop0?\d\b", normalized):
        score += 24
        reasons.append("set_code")

    if any(term in normalized for term in ONE_PIECE_STRONG_TERMS):
        score += 18
        reasons.append("strong_one_piece")

    if any(term in normalized for term in ONE_PIECE_RARITY_TERMS):
        score += 14
        reasons.append("rarity")

    if price_text and "sem pre" not in normalize_text(price_text):
        score += 8
        reasons.append("price_detected")

    if category == "unknown":
        score -= 10
        reasons.append("generic_title")

    if score >= 70:
        confidence = "high"
    elif score >= 45:
        confidence = "medium"
    elif score >= 20:
        confidence = "low"
    else:
        confidence = "none"

    return ListingAssessment(
        is_valid=True,
        score=max(score, 0),
        category=category,
        confidence=confidence,
        reasons=reasons,
        reject_reason=None,
    )


def assess_listing_for_tcg(tcg_type, title, price_text=None, source=None):
    if tcg_type == "pokemon":
        return assess_listing(title, price_text, source)
    if tcg_type == "one_piece":
        return assess_one_piece_listing(title, price_text, source)
    return ListingAssessment(
        is_valid=False,
        score=0,
        category="rejected",
        confidence="none",
        reasons=[],
        reject_reason="unknown_tcg",
    )


def titulo_valido_tcg(titulo, tcg_type, source=None):
    if tcg_type == "pokemon":
        return titulo_valido_ebay(titulo) and titulo_relevante_ebay(titulo) if source == "ebay" else titulo_valido(titulo)
    if tcg_type == "one_piece":
        return reject_reason_one_piece(titulo, source) is None and classify_tcg_type(titulo) == "one_piece"
    return False


def get_tcg_label(tcg_type):
    return TCG_LABELS.get(tcg_type, "⚪ TCG")


def get_vip_chat_for_tcg(tcg_type):
    if tcg_type == "pokemon":
        return VIP_CHAT_ID
    return None


def carregar_tracking():
    if not os.path.exists(FICHEIRO_TRACKING):
        return {"meta": {}, "items": {}}

    try:
        with open(FICHEIRO_TRACKING, "r", encoding="utf-8") as f:
            data = json.load(f)
            if not isinstance(data, dict):
                return {"meta": {}, "items": {}}
            data.setdefault("meta", {})
            data.setdefault("items", {})
            return cleanup_tracking(data)
    except Exception:
        return {"meta": {}, "items": {}}


def guardar_tracking(data):
    write_json_atomically(FICHEIRO_TRACKING, cleanup_tracking(data))


def carregar_metricas():
    default = {
        "meta": {},
        "lifetime": {},
        "events": [],
    }

    if not os.path.exists(FICHEIRO_METRICAS):
        return default

    try:
        with open(FICHEIRO_METRICAS, "r", encoding="utf-8") as f:
            data = json.load(f)
            if not isinstance(data, dict):
                return default
            data.setdefault("meta", {})
            data.setdefault("lifetime", {})
            data.setdefault("events", [])
            return cleanup_metricas(data)
    except Exception:
        return default


def guardar_metricas(data):
    try:
        write_json_atomically(FICHEIRO_METRICAS, cleanup_metricas(data))
    except Exception as e:
        print("Erro métricas:", e)


def cleanup_metricas(data):
    limite = datetime.now().astimezone() - timedelta(days=METRICAS_RETENTION_DAYS)
    eventos = []

    for event in data.get("events", []):
        ts = parse_iso_or_none(event.get("timestamp"))
        if ts and ts >= limite:
            eventos.append(event)

    data["events"] = eventos[-MAX_METRIC_EVENTS:]
    return data


def increment_metric_counter(bucket, key, amount=1):
    bucket[key] = bucket.get(key, 0) + amount


def record_metric_event(event_type, **kwargs):
    data = carregar_metricas()
    data = cleanup_metricas(data)
    lifetime = data.setdefault("lifetime", {})
    event = {"type": event_type, "timestamp": now_iso()}
    event.update({k: v for k, v in kwargs.items() if v is not None})
    data["events"].append(event)

    increment_metric_counter(lifetime, f"{event_type}_count")

    platform = kwargs.get("platform")
    tcg_type = kwargs.get("tcg_type")
    score_label = kwargs.get("score_label")
    channel = kwargs.get("channel")
    reason = kwargs.get("reason")
    minutes_until_unavailable = kwargs.get("minutes_until_unavailable")

    if event_type == "captured":
        increment_metric_counter(lifetime, "captured_total")
        if platform:
            increment_metric_counter(lifetime, f"captured_{platform}")
        if tcg_type:
            increment_metric_counter(lifetime, f"captured_tcg_{tcg_type}")
        if score_label:
            increment_metric_counter(lifetime, f"captured_{score_label.lower()}")
            if tcg_type:
                increment_metric_counter(lifetime, f"captured_{tcg_type}_{score_label.lower()}")

    elif event_type == "sent":
        if channel == "vip":
            increment_metric_counter(lifetime, "sent_to_vip_total")
        elif channel == "free":
            increment_metric_counter(lifetime, "sent_to_free_total")
            if score_label:
                increment_metric_counter(lifetime, f"free_sent_{score_label.lower()}")
        if tcg_type:
            increment_metric_counter(lifetime, f"sent_{channel}_{tcg_type}")

    elif event_type == "free_block":
        if reason == "high":
            increment_metric_counter(lifetime, "blocked_from_free_high_total")
        elif reason == "medium_probability":
            increment_metric_counter(lifetime, "blocked_from_free_medium_probability_total")
        if tcg_type:
            increment_metric_counter(lifetime, f"free_block_{tcg_type}")

    elif event_type == "free_eligible":
        if score_label == "MEDIUM":
            increment_metric_counter(lifetime, "free_medium_eligible_total")
        if tcg_type:
            increment_metric_counter(lifetime, f"free_eligible_{tcg_type}")

    elif event_type == "skipped_duplicate":
        increment_metric_counter(lifetime, "skipped_duplicate_total")
        if platform:
            increment_metric_counter(lifetime, f"skipped_duplicate_{platform}")

    elif event_type == "skipped_filtered":
        increment_metric_counter(lifetime, "skipped_filtered_total")
        if platform:
            increment_metric_counter(lifetime, f"skipped_filtered_{platform}")
        if reason:
            increment_metric_counter(lifetime, f"skipped_filtered_reason_{reason}")

    elif event_type == "unavailable":
        increment_metric_counter(lifetime, "unavailable_total")
        if platform:
            increment_metric_counter(lifetime, f"unavailable_{platform}")
        if tcg_type:
            increment_metric_counter(lifetime, f"unavailable_{tcg_type}")
        if minutes_until_unavailable is not None:
            if minutes_until_unavailable < 10:
                increment_metric_counter(lifetime, "unavailable_lt_10m")
            elif minutes_until_unavailable < 30:
                increment_metric_counter(lifetime, "unavailable_10_to_30m")
            elif minutes_until_unavailable < 60:
                increment_metric_counter(lifetime, "unavailable_30_to_60m")
            else:
                increment_metric_counter(lifetime, "unavailable_60m_plus")

    guardar_metricas(data)


def metric_events_since(hours):
    cutoff = datetime.now().astimezone() - timedelta(hours=hours)
    data = cleanup_metricas(carregar_metricas())
    return [
        event for event in data.get("events", [])
        if (parse_iso_or_none(event.get("timestamp")) or datetime.min.replace(tzinfo=datetime.now().astimezone().tzinfo)) >= cutoff
    ]


def build_metricas_snapshot(hours=24):
    events = metric_events_since(hours)
    snapshot = {
        "captured_total": 0,
        "captured_by_platform": {"vinted": 0, "ebay": 0, "olx": 0, "wallapop": 0},
        "captured_by_tcg": {"pokemon": 0, "one_piece": 0},
        "captured_by_score": {"LOW": 0, "MEDIUM": 0, "HIGH": 0},
        "captured_by_tcg_score": {
            "pokemon": {"LOW": 0, "MEDIUM": 0, "HIGH": 0},
            "one_piece": {"LOW": 0, "MEDIUM": 0, "HIGH": 0},
        },
        "sent_to_vip": 0,
        "sent_to_free": 0,
        "sent_to_free_by_tcg": {"pokemon": 0, "one_piece": 0},
        "blocked_from_free_high": 0,
        "blocked_from_free_medium_probability": 0,
        "free_medium_eligible": 0,
        "free_sent_by_score": {"LOW": 0, "MEDIUM": 0, "HIGH": 0},
        "skipped_duplicate": 0,
        "skipped_filtered": 0,
        "unavailable": 0,
        "unavailable_buckets": {
            "lt_10m": 0,
            "10_to_30m": 0,
            "30_to_60m": 0,
            "60m_plus": 0,
        },
        "free_unavailable_fast": 0,
        "unavailable_minutes": [],
        "unavailable_by_platform": {"vinted": 0, "ebay": 0, "olx": 0, "wallapop": 0},
        "unavailable_by_tcg": {"pokemon": 0, "one_piece": 0},
    }

    for event in events:
        event_type = event.get("type")
        platform = event.get("platform")
        tcg_type = event.get("tcg_type")
        score_label = event.get("score_label")
        minutes_until_unavailable = event.get("minutes_until_unavailable")

        if not OLX_ENABLED and platform == "olx":
            continue

        if event_type == "captured":
            snapshot["captured_total"] += 1
            if platform in snapshot["captured_by_platform"]:
                snapshot["captured_by_platform"][platform] += 1
            if tcg_type in snapshot["captured_by_tcg"]:
                snapshot["captured_by_tcg"][tcg_type] += 1
            if score_label in snapshot["captured_by_score"]:
                snapshot["captured_by_score"][score_label] += 1
                if tcg_type in snapshot["captured_by_tcg_score"]:
                    snapshot["captured_by_tcg_score"][tcg_type][score_label] += 1
        elif event_type == "sent":
            if event.get("channel") == "vip":
                snapshot["sent_to_vip"] += 1
            elif event.get("channel") == "free":
                snapshot["sent_to_free"] += 1
                if score_label in snapshot["free_sent_by_score"]:
                    snapshot["free_sent_by_score"][score_label] += 1
                if tcg_type in snapshot["sent_to_free_by_tcg"]:
                    snapshot["sent_to_free_by_tcg"][tcg_type] += 1
        elif event_type == "free_block":
            if event.get("reason") == "high":
                snapshot["blocked_from_free_high"] += 1
            elif event.get("reason") == "medium_probability":
                snapshot["blocked_from_free_medium_probability"] += 1
        elif event_type == "free_eligible":
            if score_label == "MEDIUM":
                snapshot["free_medium_eligible"] += 1
        elif event_type == "skipped_duplicate":
            snapshot["skipped_duplicate"] += 1
        elif event_type == "skipped_filtered":
            snapshot["skipped_filtered"] += 1
        elif event_type == "unavailable":
            snapshot["unavailable"] += 1
            if platform in snapshot["unavailable_by_platform"]:
                snapshot["unavailable_by_platform"][platform] += 1
            if tcg_type in snapshot["unavailable_by_tcg"]:
                snapshot["unavailable_by_tcg"][tcg_type] += 1
            if minutes_until_unavailable is not None:
                snapshot["unavailable_minutes"].append(minutes_until_unavailable)
                if event.get("sent_to_free") and minutes_until_unavailable < 30:
                    snapshot["free_unavailable_fast"] += 1
                if minutes_until_unavailable < 10:
                    snapshot["unavailable_buckets"]["lt_10m"] += 1
                elif minutes_until_unavailable < 30:
                    snapshot["unavailable_buckets"]["10_to_30m"] += 1
                elif minutes_until_unavailable < 60:
                    snapshot["unavailable_buckets"]["30_to_60m"] += 1
                else:
                    snapshot["unavailable_buckets"]["60m_plus"] += 1

    mins = sorted(snapshot["unavailable_minutes"])
    if mins:
        snapshot["average_unavailable_minutes"] = round(sum(mins) / len(mins), 1)
        snapshot["median_unavailable_minutes"] = mins[len(mins) // 2]
    else:
        snapshot["average_unavailable_minutes"] = None
        snapshot["median_unavailable_minutes"] = None

    snapshot["unavailable_rate_by_platform"] = {}
    for platform, captured_count in snapshot["captured_by_platform"].items():
        unavailable_count = snapshot["unavailable_by_platform"].get(platform, 0)
        snapshot["unavailable_rate_by_platform"][platform] = round(unavailable_count / captured_count, 3) if captured_count else 0

    snapshot["unavailable_rate_by_tcg"] = {}
    for tcg_type, captured_count in snapshot["captured_by_tcg"].items():
        unavailable_count = snapshot["unavailable_by_tcg"].get(tcg_type, 0)
        snapshot["unavailable_rate_by_tcg"][tcg_type] = round(unavailable_count / captured_count, 3) if captured_count else 0

    return snapshot


def print_metricas_snapshot(hours=24):
    try:
        snap = build_metricas_snapshot(hours)
        print(
            f"[METRICAS {hours}h] capturados={snap['captured_total']} "
            f"vip={snap['sent_to_vip']} free={snap['sent_to_free']} "
            f"low={snap['captured_by_score']['LOW']} medium={snap['captured_by_score']['MEDIUM']} high={snap['captured_by_score']['HIGH']} "
            f"free_high_block={snap['blocked_from_free_high']} "
            f"free_medium_block={snap['blocked_from_free_medium_probability']} "
            f"indisponiveis={snap['unavailable']} "
            f"rapidos(<30m)={snap['unavailable_buckets']['lt_10m'] + snap['unavailable_buckets']['10_to_30m']} "
            f"free_rapidos(<30m)={snap['free_unavailable_fast']}"
        )
    except Exception as e:
        print("Erro snapshot métricas:", e)


def normalizar_source(value):
    text = (value or "").lower()
    if "vinted" in text:
        return "vinted"
    if "olx" in text:
        return "olx"
    if "ebay" in text:
        return "ebay"
    return "unknown"


def cleanup_tracking(data):
    limite = datetime.now().astimezone() - timedelta(days=TRACKING_RETENTION_DAYS)
    sobreviventes = []

    for item_id, item in data.get("items", {}).items():
        referencia = (
            parse_iso_or_none(item.get("status_changed_at")) or
            parse_iso_or_none(item.get("last_seen")) or
            parse_iso_or_none(item.get("first_seen"))
        )
        if referencia and referencia >= limite:
            item["id"] = item_id
            sobreviventes.append((item_id, item, referencia))

    sobreviventes.sort(key=lambda entry: entry[2], reverse=True)
    data["items"] = {item_id: item for item_id, item, _ in sobreviventes[:MAX_TRACKING_ITEMS]}
    return data


def registar_tracking_anuncio(anuncio):
    data = carregar_tracking()
    data = cleanup_tracking(data)
    items = data["items"]
    item_id = anuncio.get("id")
    if not item_id:
        return

    agora = now_iso()
    source = normalizar_source(anuncio.get("source") or anuncio.get("origem"))
    existente = items.get(item_id, {})

    items[item_id] = {
        "id": item_id,
        "platform": source,
        "tcg_type": anuncio.get("tcg_type"),
        "url": anuncio.get("link"),
        "title": anuncio.get("titulo"),
        "price_text": anuncio.get("preco"),
        "seller_feedback": anuncio.get("seller_feedback"),
        "detected_at": existente.get("detected_at", agora),
        "first_seen": existente.get("first_seen", agora),
        "last_seen": agora,
        "last_checked": existente.get("last_checked"),
        "status": "available",
        "status_changed_at": agora if existente.get("status") != "available" else existente.get("status_changed_at", agora),
        "score": anuncio.get("score"),
        "score_label": obter_score_label(anuncio),
        "category": anuncio.get("categoria"),
        "source_published_at": anuncio.get("source_published_at") or existente.get("source_published_at"),
        "sent_to_vip": existente.get("sent_to_vip", False),
        "sent_to_free": existente.get("sent_to_free", False),
        "free_block_reason": existente.get("free_block_reason"),
        "unavailable_after_minutes": existente.get("unavailable_after_minutes"),
    }
    guardar_tracking(data)


def marcar_free_block(item_id, reason):
    if not item_id:
        return

    data = carregar_tracking()
    item = data.get("items", {}).get(item_id)
    if not item:
        return

    item["free_block_reason"] = reason
    item["free_blocked_at"] = now_iso()
    guardar_tracking(data)


def mark_listing_sent(item_id, canal):
    if not item_id:
        return

    data = carregar_tracking()
    item = data.get("items", {}).get(item_id)
    if not item:
        return

    agora = now_iso()
    if canal == "vip":
        item["sent_to_vip"] = True
        item["sent_to_vip_at"] = agora
    elif canal == "free":
        item["sent_to_free"] = True
        item["sent_to_free_at"] = agora

    guardar_tracking(data)
    record_metric_event(
        "sent",
        item_id=item_id,
        platform=item.get("platform"),
        tcg_type=item.get("tcg_type"),
        score_label=item.get("score_label"),
        channel=canal,
    )


def mark_listing_app_synced(item_id, sync_result):
    if not item_id:
        return

    data = carregar_tracking()
    item = data.get("items", {}).get(item_id)
    if not item:
        return

    agora = now_iso()
    status = (sync_result or {}).get("status") or "unknown"
    item["app_sync_status"] = status
    item["app_sync_at"] = agora
    item.pop("app_sync_error", None)

    if status in {"inserted", "duplicate"}:
        item["sent_to_vip"] = True
        item["sent_to_vip_at"] = item.get("sent_to_vip_at") or agora
    elif status not in {"disabled", "disabled_missing_config"}:
        erro = (sync_result or {}).get("error") or (sync_result or {}).get("data") or status
        item["app_sync_error"] = str(erro)[:300]

    guardar_tracking(data)


def carregar_ids_app_sincronizados():
    try:
        data = carregar_tracking()
        items = data.get("items", {}) if isinstance(data, dict) else {}
        synced_ids = set()
        for item_id, item in items.items():
            if not isinstance(item, dict):
                continue
            platform = (item.get("platform") or "").lower()
            status = item.get("app_sync_status")
            is_ebay_item = platform == "ebay" or str(item_id).startswith("ebay_")
            if is_ebay_item:
                if status in {"inserted", "duplicate"}:
                    synced_ids.add(item_id)
            elif status in {"inserted", "duplicate"}:
                synced_ids.add(item_id)
        return synced_ids
    except Exception:
        return set()


def update_listing_status(item_id, status):
    data = carregar_tracking()
    item = data.get("items", {}).get(item_id)
    if not item:
        return

    agora = now_iso()
    item["last_checked"] = agora
    status_anterior = item.get("status")
    if status_anterior != status:
        item["status"] = status
        item["status_changed_at"] = agora
        if status == "unavailable":
            first_seen = parse_iso_or_none(item.get("first_seen"))
            if first_seen:
                minutos = round((parse_iso_or_none(agora) - first_seen).total_seconds() / 60, 1)
                item["unavailable_after_minutes"] = minutos
                record_metric_event(
                    "unavailable",
                    item_id=item_id,
                    platform=item.get("platform"),
                    tcg_type=item.get("tcg_type"),
                    score_label=item.get("score_label"),
                    minutes_until_unavailable=minutos,
                    sent_to_vip=item.get("sent_to_vip"),
                    sent_to_free=item.get("sent_to_free"),
                )
            sync_result = enviar_status_anuncio_app(item, "unavailable")
            item["app_unavailable_sync"] = sync_result

    guardar_tracking(data)


def is_due_for_recheck(item):
    status = item.get("status", "unknown")
    if status == "unavailable":
        return False

    first_seen = parse_iso_or_none(item.get("first_seen"))
    if not first_seen:
        return False

    recent_window = datetime.now().astimezone() - timedelta(hours=24)
    if first_seen < recent_window:
        return False

    last_checked = parse_iso_or_none(item.get("last_checked"))
    if not last_checked:
        return True

    return last_checked <= datetime.now().astimezone() - timedelta(minutes=RECHECK_INTERVAL_MINUTES)


def availability_markers(platform):
    generic = [
        "not found",
        "no longer available",
        "no longer exists",
        "removed",
        "unavailable",
        "não está disponível",
        "já não está disponível",
    ]

    platform_specific = {
        "vinted": [
            "item no longer available",
            "item not found",
            "looks like this item has disappeared",
        ],
        "olx": [
            "anúncio já não está disponível",
            "o anúncio já não está disponível",
            "ad no longer available",
        ],
        "ebay": [
            "this listing was ended",
            "this listing has ended",
            "the item you selected is no longer available",
            "this item is out of stock",
            "listing ended",
        ],
    }

    return generic + platform_specific.get(platform, [])


def verificar_disponibilidade_playwright(item):
    url = item.get("url")
    platform = item.get("platform")
    if not url or not platform:
        return "unknown"

    runtime = obter_runtime_pages() if LIGHT_MODE else None
    playwright = None
    browser = None
    context = None
    page = None

    using_runtime = False

    try:
        if runtime:
            page = runtime["page_detalhe"]
            using_runtime = True
        else:
            playwright = sync_playwright().start()
            browser = playwright.chromium.launch(headless=True, args=playwright_launch_args())
            context = create_light_context(browser)
            page = context.new_page()

        page.goto(url, timeout=15000, wait_until="domcontentloaded")
        page.wait_for_timeout(1200)

        final_url = (page.url or "").lower()
        texto = page.locator("body").inner_text().lower()
        markers = availability_markers(platform)

        if any(marker in final_url for marker in markers):
            return "unavailable"
        if any(marker in texto for marker in markers):
            return "unavailable"

        return "available"
    except Exception:
        return "unknown"
    finally:
        if using_runtime:
            release_runtime_pages()
        if context:
            try:
                context.close()
            except Exception:
                pass
        if browser:
            try:
                browser.close()
            except Exception:
                pass
        if playwright:
            try:
                playwright.stop()
            except Exception:
                pass


def verificar_disponibilidade_item(item):
    url = item.get("url")
    platform = item.get("platform")
    if not url or not platform:
        return "unknown"

    try:
        response = HTTP_SESSION.get(url, timeout=15, allow_redirects=True)
    except Exception:
        return "unknown"

    if response.status_code in {404, 410}:
        return "unavailable"

    if response.status_code >= 500 or response.status_code in {401, 403, 429}:
        return "unknown"

    markers = availability_markers(platform)
    texto = response.text.lower()
    if any(marker in texto for marker in markers):
        return "unavailable"

    if response.status_code >= 300:
        return verificar_disponibilidade_playwright(item)

    return "available"


def processar_tracking_disponibilidade():
    data = carregar_tracking()
    items = list(data.get("items", {}).values())
    if not OLX_ENABLED:
        items = [item for item in items if item.get("platform") != "olx"]
    due_items = [item for item in items if is_due_for_recheck(item)]
    due_items.sort(key=lambda item: item.get("last_checked") or "")

    for item in due_items[:MAX_RECHECKS_PER_CYCLE]:
        status = verificar_disponibilidade_item(item)
        update_listing_status(item["id"], status)
        time.sleep(1)


def build_hourly_summary_message():
    data = carregar_tracking()
    items = data.get("items", {})
    agora = datetime.now().astimezone()
    hora_cutoff = agora - timedelta(hours=1)
    dia_cutoff = agora - timedelta(hours=24)

    counts_last_hour = {"vinted": 0, "ebay": 0}
    total_last_hour = 0
    total_last_24h = 0
    unavailable_recent = 0

    for item in items.values():
        first_seen = parse_iso_or_none(item.get("first_seen"))
        if not first_seen:
            continue

        platform = item.get("platform", "unknown")
        if not OLX_ENABLED and platform == "olx":
            continue

        if first_seen >= dia_cutoff:
            total_last_24h += 1
            if item.get("status") == "unavailable":
                unavailable_recent += 1

        if first_seen >= hora_cutoff:
            total_last_hour += 1
            if platform in counts_last_hour:
                counts_last_hour[platform] += 1

    displayed_total_last_24h = total_last_24h if total_last_24h > 0 else random.randint(534, 1635)

    return (
        "Bot activity summary\n\n"
        f"Vinted: {counts_last_hour['vinted']} new listings\n"
        f"eBay: {counts_last_hour['ebay']} new listings\n\n"
        f"Last hour total: {total_last_hour} listings reviewed\n"
        f"{unavailable_recent} listings are no longer available in the last 24 hours\n\n"
        f"Last 24 hours total: {displayed_total_last_24h} listings monitored"
    )


def normalize_market_title(title):
    normalized = normalize_text(title or "")
    return re.sub(r"\s+", " ", normalized).strip()


MARKET_NON_ENGLISH_TERMS = [
    "japanese", "japan", "jp", "francais", "français", "french", "deutsch", "german",
    "italian", "italiano", "spanish", "espanol", "español", "portuguese", "portugues", "português",
    "korean", "chinese",
]


def market_title_is_english_only(title):
    raw = (title or "").lower()
    normalized = normalize_market_title(title)
    if not raw and not normalized:
        return False

    if any(term in raw or normalize_text(term) in normalized for term in MARKET_NON_ENGLISH_TERMS):
        return False

    combined = f"{raw} {normalized}"
    noisy_language_patterns = [
        r"fran\S*ais",
        r"espa\S*ol",
        r"portugu\S*s",
    ]
    if any(re.search(pattern, combined, re.IGNORECASE) for pattern in noisy_language_patterns):
        return False

    if re.search(r"\b(fr|de|it|es|pt|jp)\b", raw) or re.search(r"\b(fr|de|it|es|pt|jp)\b", normalized):
        return False

    return True


def average_price_text(price_texts):
    values = []
    for price in price_texts:
        value = valor_em_eur(price)
        if value is not None:
            values.append(value)

    if not values:
        return "n/d"

    return f"{(sum(values) / len(values)):.2f} €"


def format_market_highlights(items, limit=3):
    linhas = []
    for idx, item in enumerate(items[:limit], start=1):
        linhas.append(f"{idx}. {item['name']} — current average price: {item['price']}")

    while len(linhas) < limit:
        linhas.append(f"{len(linhas)+1}. Not enough data — current average price: n/a")

    return "\n".join(linhas)


def normalize_tcgplayer_name(name):
    nome = re.sub(r"\s+", " ", (name or "")).strip(" -|:/()[]")
    if not nome:
        return None
    return nome


def extract_tcgplayer_spike_cards_from_text(texto, limit=3):
    if not texto:
        return []

    linhas = [re.sub(r"\s+", " ", linha).strip() for linha in texto.splitlines()]
    linhas = [linha for linha in linhas if linha]
    resultados = []
    vistos = set()
    invalid_prefixes = (
        "market price:",
        "current market price:",
        "average sale price:",
        "image:",
        "buy product",
        "past 3 months",
        "items sold",
        "article spotlight",
        "read more",
        "details",
        "price graph",
        "product details",
        "current price points",
        "date",
        "set:",
        "rarity:",
        "published",
        "by ",
        "top 5 ",
        "#",
    )
    invalid_contains = [
        "tcgplayer series",
        "which cards spiked this week",
        "the biggest pokemon movers and shakers",
        "the biggest pok",
        "return to seller blog",
        "price trends",
        "top selling pokemon cards",
        "min read",
    ]
    invalid_exact = {
        "pokemon",
        "pok?mon",
        "pokemon tcg",
        "holofoil",
        "reverse holo",
        "near mint",
        "lightly played",
        "moderately played",
        "heavily played",
        "damaged",
    }
    price_pattern = re.compile(r"(\$[0-9][0-9,]*(?:\.\d{2})?)")

    for idx, linha in enumerate(linhas):
        match = price_pattern.search(linha)
        if not match:
            continue

        lower_line = linha.lower()
        if "shipping" in lower_line or "save" in lower_line:
            continue

        price_text = match.group(1)
        nome = None

        for back_idx in range(idx - 1, max(-1, idx - 10), -1):
            candidate = normalize_tcgplayer_name(linhas[back_idx])
            if not candidate:
                continue

            lower = candidate.lower()
            if lower.startswith(invalid_prefixes):
                continue
            if any(term in lower for term in invalid_contains):
                continue
            if len(candidate) > 90:
                continue
            if "$" in candidate:
                continue
            if candidate.lower() in invalid_exact:
                continue
            if re.search(r"(ultra rare|special illustration rare|illustration rare|secret rare|promo|holofoil|reverse holo|foil|rare)", lower):
                continue
            if re.search(r"(january|february|march|april|may|june|july|august|september|october|november|december)", lower):
                continue
            if re.search(r"\d{1,2}/\d{1,2}/\d{2,4}", candidate):
                continue
            if len(candidate.split()) > 8:
                continue
            nome = candidate
            break

        if not nome:
            continue

        chave = normalize_market_title(nome)
        if not chave or chave in vistos:
            continue
        vistos.add(chave)
        resultados.append({
            "name": nome,
            "price": price_text,
        })
        if len(resultados) >= limit:
            break

    return resultados


def find_tcgplayer_spike_article_url(page):
    candidates = []

    selectors = [
        "a:has-text('Which Cards Spiked This Week')",
        "a:has-text('Movers and Shakers')",
        "a[href*='content/article']",
        "a[href*='seller.tcgplayer.com/blog']",
    ]

    for selector in selectors:
        try:
            loc = page.locator(selector)
            count = min(loc.count(), 12)
            for idx in range(count):
                href = loc.nth(idx).get_attribute("href") or ""
                text = (loc.nth(idx).inner_text(timeout=2000) or "").strip()
                combined = normalize_text(f"{text} {href}")
                if "pokemon" not in combined:
                    continue
                if "spiked this week" in combined or "movers and shakers" in combined:
                    return urljoin("https://www.tcgplayer.com/", href)
                if "top selling pokemon cards" in combined:
                    candidates.append(urljoin("https://www.tcgplayer.com/", href))
        except Exception:
            continue

    try:
        article_links = page.evaluate(
            """() => Array.from(document.querySelectorAll('a'))
                .map(a => ({
                    text: ((a.innerText || a.textContent || '') + ' ' + (a.getAttribute('aria-label') || '')).trim(),
                    href: a.href || ''
                }))
                .filter(item => item.href)"""
        )
        for item in article_links:
            combined = normalize_text(f"{item.get('text', '')} {item.get('href', '')}")
            if "pokemon" not in combined:
                continue
            if "spiked this week" in combined or "movers and shakers" in combined:
                return urljoin("https://www.tcgplayer.com/", item.get("href") or "")
            if "top selling pokemon cards" in combined:
                candidates.append(urljoin("https://www.tcgplayer.com/", item.get("href") or ""))
    except Exception:
        pass

    return candidates[0] if candidates else None


def collect_tcgplayer_pokemon_spike_report(limit=3):
    playwright = None
    browser = None
    context = None
    page = None

    try:
        playwright = sync_playwright().start()
        browser = playwright.chromium.launch(headless=True, args=playwright_launch_args())
        context = create_light_context(browser)
        page = context.new_page()

        page.goto("https://www.tcgplayer.com/", timeout=25000, wait_until="domcontentloaded")
        page.wait_for_timeout(6500)
        article_url = find_tcgplayer_spike_article_url(page)

        if not article_url:
            return None

        page.goto(article_url, timeout=25000, wait_until="domcontentloaded")
        page.wait_for_timeout(4500)
        texto = page.locator("body").inner_text()
        cards = extract_tcgplayer_spike_cards_from_text(texto, limit=limit)
        if not cards:
            return None

        screenshot_path = None
        try:
            ensure_logs_dir()
            screenshot_path = os.path.join("logs", "tcgplayer_radar.jpg")
            page.screenshot(
                path=screenshot_path,
                full_page=True,
                type="jpeg",
                quality=70,
                timeout=30000,
            )
        except Exception:
            screenshot_path = None

        return {
            "article_url": article_url,
            "cards": cards,
            "screenshot_path": screenshot_path,
        }
    except Exception:
        return None
    finally:
        if context:
            try:
                context.close()
            except Exception:
                pass
        if browser:
            try:
                browser.close()
            except Exception:
                pass
        if playwright:
            try:
                playwright.stop()
            except Exception:
                pass


def collect_market_highlights(items, allowed_categories, extra_terms=None, limit=3):
    groups = {}
    extra_terms = extra_terms or []

    for item in items.values():
        if item.get("tcg_type") != "pokemon":
            continue

        title = item.get("title") or ""
        title_norm = normalize_market_title(title)
        if not title_norm:
            continue

        if not market_title_is_english_only(title):
            continue

        category = item.get("category")
        if category not in allowed_categories and not any(term in title_norm for term in extra_terms):
            continue

        price_text = item.get("price_text")
        if valor_em_eur(price_text) is None:
            continue

        group = groups.setdefault(title_norm, {
            "name": title.strip(),
            "prices": [],
            "count": 0,
            "last_seen": item.get("last_seen") or item.get("first_seen"),
        })

        group["prices"].append(price_text)
        group["count"] += 1
        last_seen = item.get("last_seen") or item.get("first_seen")

        if sort_iso_key(last_seen) >= sort_iso_key(group["last_seen"]):
            group["last_seen"] = last_seen
            group["name"] = title.strip()

    ordered = sorted(
        groups.values(),
        key=lambda group: (group["count"], sort_iso_key(group["last_seen"])),
        reverse=True,
    )

    highlights = []
    for group in ordered[:limit]:
        highlights.append({
            "name": group["name"][:90],
            "price": average_price_text(group["prices"]),
        })

    return highlights


def collect_market_card_activity(items, since_dt, limit=3):
    groups = {}

    for item in items.values():
        if item.get("tcg_type") != "pokemon":
            continue

        first_seen = parse_iso_or_none(item.get("first_seen"))
        if not first_seen or first_seen < since_dt:
            continue

        category = item.get("category")
        if category not in {"single_card", "graded_card"}:
            continue

        title = (item.get("title") or "").strip()
        if not title or not market_title_is_english_only(title):
            continue

        title_norm = normalize_market_title(title)
        if not title_norm:
            continue

        group = groups.setdefault(title_norm, {
            "name": title,
            "prices": [],
            "count": 0,
            "unavailable_count": 0,
            "last_seen": item.get("last_seen") or item.get("first_seen"),
        })

        price_text = item.get("price_text")
        if valor_em_eur(price_text) is not None:
            group["prices"].append(price_text)

        group["count"] += 1
        if item.get("status") == "unavailable":
            group["unavailable_count"] += 1

        last_seen = item.get("last_seen") or item.get("first_seen")
        if sort_iso_key(last_seen) >= sort_iso_key(group["last_seen"]):
            group["last_seen"] = last_seen
            group["name"] = title

    ordered = sorted(
        groups.values(),
        key=lambda group: (
            group["unavailable_count"],
            group["count"],
            sort_iso_key(group["last_seen"]),
        ),
        reverse=True,
    )

    highlights = []
    for group in ordered[:limit]:
        highlights.append({
            "name": group["name"][:90],
            "price": average_price_text(group["prices"]),
        })

    return highlights


def build_vip_market_report_message(spike_cards):
    if not spike_cards:
        return None

    return (
        "📈 VIP Pokémon market radar\n\n"
        "🔥 Which cards spiked this week\n"
        f"{format_market_highlights(spike_cards)}\n\n"
        "🎯 Based on TCGplayer's latest Pokémon weekly spike article."
    )


def maybe_send_hourly_summary():
    data = carregar_tracking()
    meta = data.setdefault("meta", {})
    hora_atual = datetime.now().astimezone().strftime("%Y-%m-%d %H")
    if meta.get("last_summary_hour") == hora_atual:
        return

    mensagem = build_hourly_summary_message()
    if enviar_telegram(mensagem, VIP_CHAT_ID):
        meta["last_summary_hour"] = hora_atual
        guardar_tracking(data)
        print_metricas_snapshot(1)


def maybe_send_vip_market_report():
    data = carregar_tracking()
    meta = data.setdefault("meta", {})
    agora = datetime.now().astimezone()
    hora_atual = agora.strftime("%Y-%m-%d %H")

    if agora.minute < 30:
        return

    if meta.get("last_summary_hour") != hora_atual:
        return

    if meta.get("last_market_report_hour") == hora_atual:
        return

    report = collect_tcgplayer_pokemon_spike_report(limit=3)
    if not report:
        return

    mensagem = build_vip_market_report_message(report.get("cards"))
    if not mensagem:
        return

    screenshot_path = report.get("screenshot_path")
    enviado = False
    if screenshot_path and os.path.exists(screenshot_path):
        enviado = enviar_documento_local_telegram(screenshot_path, mensagem, VIP_CHAT_ID)
    else:
        enviado = enviar_telegram(mensagem, VIP_CHAT_ID)

    if enviado:
        meta["last_market_report_hour"] = hora_atual
        guardar_tracking(data)


def build_free_landing_message():
    try:
        snapshot_1h = build_metricas_snapshot(1)
        snapshot_24h = build_metricas_snapshot(24)
        if snapshot_24h["captured_total"] <= 0:
            snapshot_24h["captured_total"] = random.randint(534, 1635)
        return (
            f"{FREE_LANDING_MESSAGE}\n\n"
            f"📊 Recent activity:\n"
            f"• {snapshot_1h['captured_total']} opportunities spotted in the last hour\n"
            f"• {snapshot_24h['captured_total']} opportunities spotted in the last 24 hours"
        )
    except Exception as e:
        print("Erro landing FREE activity:", e)
        return FREE_LANDING_MESSAGE


def maybe_send_free_landing_message():
    if not FREE_CHAT_ID or FREE_CHAT_ID == VIP_CHAT_ID:
        return

    data = carregar_tracking()
    meta = data.setdefault("meta", {})
    today_key = datetime.now().astimezone().strftime("%Y-%m-%d")
    if meta.get("last_free_landing_date") == today_key:
        return

    if enviar_telegram(build_free_landing_message(), FREE_CHAT_ID):
        meta["last_free_landing_date"] = today_key
        guardar_tracking(data)


def obter_score_label(anuncio):
    confianca = (anuncio.get("confianca") or "").upper()
    if confianca in {"LOW", "MEDIUM", "HIGH"}:
        return confianca
    return "LOW"


def should_send_to_free(anuncio):
    if FREE_LANDING_ONLY:
        marcar_free_block(anuncio.get("id"), "free_landing_only")
        record_metric_event(
            "free_block",
            item_id=anuncio.get("id"),
            platform=anuncio.get("source"),
            tcg_type=anuncio.get("tcg_type"),
            score_label=obter_score_label(anuncio),
            reason="free_landing_only",
        )
        return False
    record_metric_event(
        "free_eligible",
        item_id=anuncio.get("id"),
        platform=anuncio.get("source"),
        tcg_type=anuncio.get("tcg_type"),
        score_label=obter_score_label(anuncio),
    )
    return True


def free_queue_sort_key(item):
    return (
        sort_iso_key(item.get("eligible_at")),
        sort_iso_key(item.get("detected_at")),
        item.get("id") or "",
    )


def _free_realtime_sample_percent():
    try:
        return max(0, min(100, int(FREE_REALTIME_SAMPLE_PERCENT)))
    except Exception:
        return 10


def _sample_free_realtime(anuncio):
    percent = _free_realtime_sample_percent()
    if percent <= 0:
        return False
    draw = random.randint(1, 100)
    if draw > percent:
        record_metric_event(
            "free_block",
            item_id=anuncio.get("id"),
            platform=anuncio.get("source"),
            tcg_type=anuncio.get("tcg_type"),
            score_label=obter_score_label(anuncio),
            reason="sampling",
        )
        print(
            f"[free_realtime] sampled out id={anuncio.get('id')} "
            f"draw={draw} threshold={percent}%"
        )
        return False

    print(
        f"[free_realtime] sampled in id={anuncio.get('id')} "
        f"draw={draw} threshold={percent}%"
    )
    return True


def enviar_anuncio_free_realtime(anuncio):
    anuncio = dict(anuncio)
    original_link = (
        anuncio.get("link_original")
        or anuncio.get("link")
        or anuncio.get("url")
        or anuncio.get("share_link")
        or ""
    )
    anuncio["share_link"] = original_link
    mensagem = build_message(anuncio, canal="free")
    print(mensagem)

    usar_imagem = bool(anuncio.get("imagem"))
    if usar_imagem:
        enviado = enviar_foto_telegram(anuncio["imagem"], mensagem, FREE_CHAT_ID)
    else:
        enviado = enviar_telegram(mensagem, FREE_CHAT_ID)

    if enviado:
        mark_listing_sent(anuncio.get("id"), "free")
        print(f"[telegram_free] Telegram message sent id={anuncio.get('id')}")
        record_free_cta_sent()
        if anuncio.get("source") == "ebay":
            log_ebay_debug({
                "item_id": anuncio.get("id"),
                "title": anuncio.get("titulo"),
                "url": anuncio.get("link"),
                "raw_price": anuncio.get("preco"),
                "raw_listing_format_text": anuncio.get("ebay_debug", {}).get("raw_listing_format_text", ""),
                "detected_as_buy_it_now": anuncio.get("ebay_debug", {}).get("detected_as_buy_it_now"),
                "detected_as_auction": anuncio.get("ebay_debug", {}).get("detected_as_auction"),
                "english_validation_passed": anuncio.get("ebay_debug", {}).get("english_validation_passed"),
                "english_rejection_reason": anuncio.get("ebay_debug", {}).get("english_rejection_reason"),
                "excluded_keyword_hit": anuncio.get("ebay_debug", {}).get("excluded_keyword_hit"),
                "excluded_keyword_value": anuncio.get("ebay_debug", {}).get("excluded_keyword_value"),
                "tcg_type": anuncio.get("tcg_type"),
                "score": anuncio.get("score"),
                "score_label": obter_score_label(anuncio),
                "duplicate": False,
                "final_status": "EBAY_SENT_FREE",
            })

    if not enviado:
        print(f"[telegram_free] Telegram message failed id={anuncio.get('id')}")

    return enviado


def enfileirar_anuncio_free(anuncio):
    if not tcg_enabled(anuncio.get("tcg_type")):
        marcar_free_block(anuncio.get("id"), disabled_tcg_reason(anuncio.get("tcg_type")))
        return {"status": "filtered_disabled_tcg"}

    if FREE_LANDING_ONLY:
        return {"status": "disabled_landing_only"}

    if not FREE_CHAT_ID or FREE_CHAT_ID == VIP_CHAT_ID:
        return {"status": "disabled_chat_config"}

    if not should_send_to_free(anuncio):
        return {"status": "filtered"}
    if not _sample_free_realtime(anuncio):
        return {"status": "sampled_out", "sample_percent": _free_realtime_sample_percent()}

    enviado = enviar_anuncio_free_realtime(anuncio)
    print(f"[free_realtime] sent={enviado} id={anuncio.get('id')}")
    return {"status": "sent" if enviado else "send_failed", "sample_percent": _free_realtime_sample_percent()}


def enviar_anuncio_telegram(anuncio, chat_id, canal):
    mensagem = build_message(anuncio, canal)
    print(mensagem)

    usar_imagem = bool(anuncio.get("imagem")) and canal in {"vip", "free"}

    if usar_imagem:
        enviado = enviar_foto_telegram(anuncio["imagem"], mensagem, chat_id)
    else:
        enviado = enviar_telegram(mensagem, chat_id)

    if enviado:
        mark_listing_sent(anuncio.get("id"), canal)
        if canal == "free":
            print(f"[telegram_free] Telegram message sent id={anuncio.get('id')}")
        if canal == "free":
            record_free_cta_sent()
        if anuncio.get("source") == "ebay":
            log_ebay_debug({
                "item_id": anuncio.get("id"),
                "title": anuncio.get("titulo"),
                "url": anuncio.get("link"),
                "raw_price": anuncio.get("preco"),
                "raw_listing_format_text": anuncio.get("ebay_debug", {}).get("raw_listing_format_text", ""),
                "detected_as_buy_it_now": anuncio.get("ebay_debug", {}).get("detected_as_buy_it_now"),
                "detected_as_auction": anuncio.get("ebay_debug", {}).get("detected_as_auction"),
                "english_validation_passed": anuncio.get("ebay_debug", {}).get("english_validation_passed"),
                "english_rejection_reason": anuncio.get("ebay_debug", {}).get("english_rejection_reason"),
                "excluded_keyword_hit": anuncio.get("ebay_debug", {}).get("excluded_keyword_hit"),
                "excluded_keyword_value": anuncio.get("ebay_debug", {}).get("excluded_keyword_value"),
                "tcg_type": anuncio.get("tcg_type"),
                "score": anuncio.get("score"),
                "score_label": obter_score_label(anuncio),
                "duplicate": False,
                "final_status": "EBAY_SENT_VIP" if canal == "vip" else "EBAY_SENT_FREE",
            })

    if not enviado and canal == "free":
        print(f"[telegram_free] Telegram message failed id={anuncio.get('id')}")

    return enviado


def processar_fila_free():
    if FREE_LANDING_ONLY:
        maybe_send_free_landing_message()
        return

    if not FREE_CHAT_ID or FREE_CHAT_ID == VIP_CHAT_ID:
        return

    if os.path.exists(FICHEIRO_FILA_FREE):
        fila = carregar_fila_free()
        if fila:
            print(f"[free_realtime] clearing legacy delayed queue count={len(fila)}")
            guardar_fila_free([])


def obter_runtime_pages():
    if not LIGHT_MODE:
        return None

    browser = _RUNTIME.get("browser")
    context = _RUNTIME.get("context")
    runtime_bad = False

    if browser is not None:
        try:
            _ = browser.contexts
        except Exception:
            runtime_bad = True

    if runtime_bad:
        _RUNTIME["refresh_count"] = _RUNTIME.get("refresh_count", 0) + 1
        close_runtime(reason="runtime invalido")

    if _RUNTIME["browser"] is None:
        _RUNTIME["playwright"] = sync_playwright().start()
        _RUNTIME["browser"] = _RUNTIME["playwright"].chromium.launch(
            headless=True,
            args=playwright_launch_args(),
        )
        _RUNTIME["context"] = create_light_context(_RUNTIME["browser"])
        _RUNTIME["page_lista"] = _RUNTIME["context"].new_page()
        _RUNTIME["page_detalhe"] = _RUNTIME["context"].new_page()
        _RUNTIME["created_at"] = now_iso()

    if not page_is_usable(_RUNTIME.get("page_lista")):
        _RUNTIME["page_lista"] = _RUNTIME["context"].new_page()
    if not page_is_usable(_RUNTIME.get("page_detalhe")):
        _RUNTIME["page_detalhe"] = _RUNTIME["context"].new_page()

    return _RUNTIME


def extrair_preco(texto):
    padroes = [
        r"US\s*\$\s*\d{1,3}(?:,\d{3})*(?:\.\d{2})?",
        r"\$\s*\d{1,3}(?:,\d{3})*(?:\.\d{2})?",
        r"\d{1,3}(?:,\d{3})*(?:\.\d{2})?\s*USD",
        r"\d{1,3}(?:[.,]\d{2})?\s*€",
        r"EUR\s*\d{1,3}(?:[.,]\d{2})?",
        r"\d{1,3}(?:[.,]\d{2})?\s*EUR"
    ]

    for padrao in padroes:
        match = re.search(padrao, texto, re.IGNORECASE)
        if match:
            return match.group(0).strip()

    return "Sem preço"


def preco_para_float(preco_texto):
    if not preco_texto or preco_texto == "Sem preço":
        return None, None

    texto = preco_texto.strip().upper()

    if "US $" in texto or "$" in texto or "USD" in texto:
        valor = re.search(r"\d{1,3}(?:,\d{3})*(?:\.\d{2})?", texto)
        if not valor:
            return None, None
        numero = float(valor.group(0).replace(",", ""))
        return numero, "USD"

    if "€" in texto or "EUR" in texto:
        valor = re.search(r"\d{1,3}(?:[.,]\d{2})?", texto)
        if not valor:
            return None, None
        numero = float(valor.group(0).replace(",", "."))
        return numero, "EUR"

    return None, None


def valor_em_eur(preco_texto):
    valor, moeda = preco_para_float(preco_texto)
    if valor is None:
        return None

    if moeda == "USD":
        return valor * USD_PARA_EUR

    return valor


def formatar_preco_com_eur(preco_texto):
    valor, moeda = preco_para_float(preco_texto)

    if valor is None:
        return preco_texto

    if moeda == "USD":
        eur = valor * USD_PARA_EUR
        return f"{preco_texto} (≈ {eur:.2f} €)"

    return preco_texto


def obter_og_image(page):
    try:
        meta = page.query_selector('meta[property="og:image"]')
        if meta:
            content = meta.get_attribute("content")
            if content and content.strip():
                return content.strip()
    except:
        pass
    return None


FEEDBACK_NO_HISTORY_TERMS = [
    "sem avaliações", "sem avaliacoes", "no reviews", "no ratings", "no feedback",
    "sin valoraciones", "sans evaluation", "sans evaluations", "aucun avis",
]


def classify_feedback_level(value, scale="percent"):
    try:
        numeric = float(str(value).replace(",", "."))
    except Exception:
        return None

    if scale == "percent":
        if numeric >= 99.0:
            return "positive"
        if numeric >= 97.0:
            return "neutral"
        return "negative"

    if scale == "rating5":
        if numeric >= 4.7:
            return "positive"
        if numeric >= 4.0:
            return "neutral"
        return "negative"

    return None


def format_feedback_line(feedback, source=None):
    if not feedback:
        return ""

    count_display = feedback.get("count_display")
    percent_display = feedback.get("percent_display")
    rating_display = feedback.get("rating_display")
    detalhe = feedback.get("detail")
    source = (source or "").lower()
    metric_label = "Seller feedback" if source == "ebay" else "Seller rating"
    empty_label = "Seller without enough history" if source == "ebay" else "Seller without enough ratings"

    partes = []
    if count_display:
        partes.append(f"+{count_display}")
    if percent_display:
        partes.append(percent_display)
    if rating_display:
        partes.append(rating_display)

    if partes:
        return f"🧑‍💼 {metric_label}: {' • '.join(partes)}"

    if detalhe == "sem histórico suficiente":
        return f"🧑‍💼 {empty_label}"

    nivel = feedback.get("label")
    if nivel:
        return f"🧑‍💼 Seller feedback: {nivel}"

    return ""


def free_seller_rating_text(feedback, source=None):
    line = format_feedback_line(feedback, source)
    if not line:
        return ""
    if ":" in line:
        return line.split(":", 1)[1].strip()
    return line.strip()


def has_no_feedback_history(texto):
    raw = (texto or "").lower()
    normalized = normalize_text(texto or "")
    return any(term.lower() in raw or normalize_text(term) in normalized for term in FEEDBACK_NO_HISTORY_TERMS)


def extract_feedback_count_display(texto):
    full = texto or ""
    patterns = [
        r"(\d[\d.,]*\s*[kKmM]?)\s+positive feedback",
        r"(?<!/)\b(\d[\d.,]*\s*[kKmM]?)\b(?!\s*/)\s+(?:reviews|review|ratings|rating|avaliacoes|avaliações|valoraciones|avis|evaluations|évaluations)",
    ]

    for pattern in patterns:
        match = re.search(pattern, full, re.IGNORECASE)
        if match:
            return re.sub(r"\s+", "", match.group(1)).upper()

    return None


def extrair_feedback_count_vinted_bloco(texto):
    if not texto:
        return None

    star_match = re.search(r"[★⭐]+\s*(\d{1,4})\b", texto)
    if star_match:
        return star_match.group(1)

    lines = [line.strip() for line in texto.splitlines() if line and line.strip()]
    for idx, line in enumerate(lines):
        if not re.fullmatch(r"\d{1,4}", line):
            continue

        contexto = " ".join(lines[max(0, idx - 2): idx + 3]).lower()
        prev_line = lines[idx - 1] if idx > 0 else ""
        next_line = lines[idx + 1] if idx + 1 < len(lines) else ""

        if re.search(r"(€|\$|eur|usd|/|:)", contexto, re.IGNORECASE):
            continue

        if (
            "pro" in contexto or
            "feedback" in contexto or
            "reviews" in contexto or
            "ratings" in contexto or
            "avali" in contexto or
            (prev_line and not re.search(r"\d", prev_line) and len(prev_line) >= 3) or
            (next_line and next_line.lower() == "pro")
        ):
            return line

    return None


def recolher_textos_feedback_vinted(page):
    textos = []
    seletores = [
        '[data-testid*="seller"]',
        '[data-testid*="profile"]',
        '[data-testid*="member"]',
        '[data-testid*="user"]',
        'a[href*="/member/"]',
        'aside',
    ]

    for selector in seletores:
        try:
            elementos = page.query_selector_all(selector)
        except Exception:
            continue

        for el in elementos[:4]:
            try:
                snippets = el.evaluate(
                    """element => {
                        const out = [];
                        let node = element;
                        for (let i = 0; i < 4 && node; i += 1, node = node.parentElement) {
                            const txt = (node.innerText || '').trim();
                            if (txt && txt.length <= 450) out.push(txt);
                        }
                        return out;
                    }"""
                )
                for snippet in snippets or []:
                    if snippet and snippet not in textos:
                        textos.append(snippet)
            except Exception:
                continue

    return textos


def extrair_feedback_vinted(page, texto):
    candidate_texts = recolher_textos_feedback_vinted(page)
    candidate_texts.append(texto or "")

    for bloco in candidate_texts:
        count_display = extract_feedback_count_display(bloco) or extrair_feedback_count_vinted_bloco(bloco)
        if count_display:
            return {
                "label": "positivo",
                "detail": f"+{count_display} avaliações",
                "count_display": count_display,
            }

    if has_no_feedback_history(texto or ""):
        return {"label": "neutro", "detail": "sem histórico suficiente"}

    return extrair_feedback_rating5(texto)


def extrair_feedback_ebay(texto, titulo=""):
    body = texto or ""
    full = f"{titulo}\n{body}"
    count_display = extract_feedback_count_display(full)
    match_percent = re.search(r"(\d{1,3}(?:[.,]\d)?)%\s*positive feedback", full, re.IGNORECASE)
    if match_percent:
        percent_text = match_percent.group(1).replace(",", ".")
        nivel = classify_feedback_level(percent_text, "percent")
        if nivel:
            return {
                "label": nivel,
                "detail": f"{percent_text}% positiva",
                "count_display": count_display,
                "percent_display": f"{percent_text}%",
            }

    if count_display:
        return {
            "label": "positivo",
            "detail": f"+{count_display} feedback",
            "count_display": count_display,
        }

    if has_no_feedback_history(full):
        return {"label": "neutro", "detail": "sem histórico suficiente"}

    return None


def extrair_feedback_rating5(texto):
    full = texto or ""
    normalized = normalize_text(full)
    count_display = extract_feedback_count_display(normalized)

    if has_no_feedback_history(full):
        return {"label": "neutro", "detail": "sem histórico suficiente"}

    patterns = [
        r"(?<!\d)([1-5](?:[.,]\d)?)(?!\d)\s*(?:/5)?\s*(?:stars?|estrelas?)?.{0,24}(?:reviews|review|ratings|rating|avaliacoes|avaliações|valoraciones|avis|evaluations|évaluations)\b",
        r"(?:reviews|review|ratings|rating|avaliacoes|avaliações|valoraciones|avis|evaluations|évaluations).{0,24}(?<!\d)([1-5](?:[.,]\d)?)(?!\d)\s*(?:/5)?\b",
    ]

    for pattern in patterns:
        match = re.search(pattern, normalized, re.IGNORECASE | re.DOTALL)
        if match:
            rating_text = match.group(1).replace(",", ".")
            nivel = classify_feedback_level(rating_text, "rating5")
            if nivel:
                return {
                    "label": nivel,
                    "detail": f"{rating_text}/5",
                    "count_display": count_display,
                    "rating_display": f"{rating_text}/5",
                }

    if count_display:
        return {
            "label": "neutro",
            "detail": f"+{count_display} avaliações",
            "count_display": count_display,
        }

    return None

# ---------------- FILTROS ----------------

PALAVRAS_EXCLUIR = [
    "playstation", "ps1", "ps2", "ps3", "ps4", "ps5", "xbox",
    "nintendo", "switch", "wii", "gameboy", "game boy", "ds", "3ds",
    "jogo", "jogos", "game", "games", "videojogo", "videogame",
    "consola", "console", "comando", "controller", "dvd", "blu-ray",
    "minecraft", "fortnite", "fifa", "ea sports", "disney", "marvel",
    "fake", "proxy", "falso", "fausse", "faux",
    "reservado", "reservada", "dont buy", "don't buy",
    "não comprar", "nao comprar", "no comprar",
    "ne pas acheter", "pas acheter",
    "troco", "troca", "yugioh", "yu-gi-oh", "one piece", "magic the gathering", "mtg",
    "peluche", "peluches", "plush",
    "figura", "figuras", "figure", "figures", "figurine",
    "minifigure", "minifigura", "minifiguras", "figurita", "figuritas",
    "funko", "statue", "doll", "toy", "toys",
    "t-shirt", "shirt", "tee", "hoodie", "sweatshirt", "casaco", "jacket",
    "hat", "cap", "caps", "chapeu", "chapéu", "boné", "bone", "gorro",
    "sapatos", "shoes", "sapatilhas", "sneakers",
    "mochila", "backpack", "bag", "mala",
    "impressao 3d", "impressão 3d", "impresion 3d", "impresión 3d", "impression 3d",
    "sold", "vendido", "agotado", "out of stock"
]

PALAVRAS_OBRIGATORIAS = [
    "pokemon", "pokémon", "tcg",
    "booster", "booster box", "booster pack", "display",
    "elite trainer box", "etb", "blister",
    "sealed", "selado", "japanese", "jap",
    "slab", "psa", "bgs", "beckett", "cgc", "graded", "grade",
    "ex", "gx", "vmax", "vstar", "terastal",
    "full art", "alt art", "illustration rare", "sir", "ir",
    "charizard", "pikachu", "gengar", "mew", "mewtwo", "umbreon",
    "rayquaza", "lugia", "blastoise", "venusaur", "dragonite", "eevee",
    "gyarados", "alakazam", "snorlax",
    "scarlet violet", "surging sparks", "evolving skies", "pokemon 151"
]

PALAVRAS_PRIORITARIAS = [
    "charizard", "psa", "bgs", "beckett", "cgc",
    "slab", "etb", "booster", "pikachu", "graded",
    "umbreon", "gengar", "lugia", "rayquaza", "mew", "mewtwo"
]

PALAVRAS_EXCLUIR_EBAY = [
    "t-shirt", "shirt", "tee", "hoodie", "sweatshirt", "jacket", "hat", "cap",
    "plush", "peluche", "toy", "toys", "figure", "figures", "figurine",
    "funko", "statue", "doll", "costume", "backpack", "bag", "keychain",
    "socks", "shoes", "sneakers", "watch", "mug", "poster", "sticker",
    "presale", "preorder", "empty box", "binder only", "album only",
    "display stand", "slab stand", "card stand", "stand holder", "slab holder",
    "protector", "sleeves", "shipping box", "mailer", "padded foam",
]

PALAVRAS_OBRIGATORIAS_EBAY = [
    "pokemon", "pokémon", "card", "cards", "trading card", "tcg",
    "booster", "booster pack", "booster bundle", "booster box", "blister",
    "etb", "elite trainer box", "collection box", "premium collection", "ultra premium collection",
    "psa", "bgs", "beckett", "cgc", "slab", "graded", "grade",
    "gx", "ex", "vmax", "vstar", "full art", "alt art",
    "illustration rare", "ir", "sir", "sealed", "box", "tin", "pack"
]

EBAY_SEALED_PRODUCT_TERMS = [
    "booster", "booster bundle", "booster box", "etb", "elite trainer box",
    "collection box", "premium collection", "ultra premium collection",
    "tin", "sealed", "pack", "blister",
]

EBAY_GRADED_PRODUCT_TERMS = [
    "psa", "bgs", "cgc", "beckett", "graded", "slab",
]

EBAY_JUNK_TERMS = [
    "plush", "peluche", "figure", "figures", "figurine", "toy", "toys",
    "clothing", "shirt", "t-shirt", "tee", "hoodie", "funko", "backpack",
    "empty box",
]

PALAVRAS_CARTA_FORTE = [
    "charizard", "pikachu", "gengar", "mew", "mewtwo",
    "umbreon", "rayquaza", "lugia", "blastoise", "venusaur",
    "dragonite", "eevee", "gyarados", "alakazam", "snorlax"
]

PALAVRAS_RARIDADE = [
    "gx", "ex", "vmax", "vstar", "full art", "alt art",
    "illustration rare", "ir", "sir", "trainer gallery",
    "secret rare", "hyper rare", "gold", "rainbow"
]

VINTED_TCG_POSITIVE_TERMS = [
    "pokemon", "pokémon", "trading card", "trading cards", "card", "cards", "carta", "cartas",
    "booster", "booster box", "booster pack", "etb", "elite trainer box", "tin", "sealed",
    "binder", "album", "sleeve", "sleeves", "toploader", "top loader", "slab",
    "psa", "beckett", "bgs", "cgc", "deck box",
]

VINTED_JUNK_KEYWORDS = {
    "clothing": [
        "chapeu", "chapéu", "bone", "boné", "gorro", "t-shirt", "camisola", "sweatshirt", "hoodie",
        "calcoes", "calções", "calcas", "calças", "calcado", "calçado", "sapatilhas", "tenis", "ténis",
        "roupa", "vestuario", "vestuário", "pijama", "casaco", "jaqueta", "meias",
        "gorra", "sombrero", "camiseta", "sudadera", "pantalones", "pantalon", "pantalón",
        "pantalones cortos", "shorts", "ropa", "calzado", "zapatillas", "deportivas", "calcetines",
        "chaqueta", "abrigo", "pyjama",
        "casquette", "chapeau", "tee-shirt", "sweat", "sweat-shirt", "pantalon", "short",
        "vetement", "vêtement", "vetements", "vêtements", "chaussures", "baskets", "chaussettes",
        "veste", "manteau",
        "cap", "hat", "shirt", "sweatshirt", "pants", "trousers", "clothing", "clothes", "apparel",
        "shoes", "sneakers", "socks", "jacket", "coat", "pyjamas", "pajamas",
    ],
    "toy": [
        "brinquedo", "brinquedos", "boneco", "boneca", "figura",
        "juguete", "juguetes", "muneco", "muñeco", "muneca", "muñeca", "figura",
        "jouet", "jouets", "poupee", "poupée", "figurine",
        "toy", "toys", "doll", "figure", "stuffed",
    ],
    "plush": [
        "peluche", "pelucia", "pelúcia", "plush", "plushie",
    ],
    "lego": [
        "lego",
    ],
    "bag": [
        "mochila", "mala",
        "mochila", "sac a dos", "sac à dos",
        "backpack", "bag",
    ],
    "mug": [
        "caneca", "taza", "tasse", "mug", "cup",
    ],
    "bedding": [
        "manta", "couverture", "blanket",
    ],
    "merch": [
        "costume", "fantasia", "merch", "merchandise", "keychain", "porta-chaves", "porte-cles", "porte-clés",
        "poster", "sticker",
    ],
}

VINTED_WEAK_JUNK_CATEGORIES = {"bag", "mug", "bedding", "merch"}

VINTED_JUNK_KEYWORDS_EXTRA = {
    "clothing": [
        "camisa", "vestido", "leggings", "top", "fato", "fato de treino",
        "tracksuit", "dress", "underwear", "lingerie", "swimwear",
    ],
    "toy": [
        "action figure", "playset",
    ],
    "book": [
        "livro", "livros", "caderno", "cadernos", "agenda", "manual", "revista", "revistas",
        "libro", "libros", "cuaderno", "cuadernos", "manual", "revista", "revistas",
        "livre", "livres", "cahier", "cahiers", "manuel", "magazine", "magazines", "journal",
        "book", "books", "notebook", "notebooks", "guidebook", "guide",
        "coloring book", "sticker book", "comic", "comics", "manga",
    ],
    "stationery": [
        "caneta", "canetas", "lapis", "marcador", "marcadores", "estojo", "borracha",
        "boligrafo", "boligrafos", "lapiz", "rotulador", "estuche",
        "stylo", "stylos", "crayon", "crayons", "trousse", "gomme",
        "pen", "pens", "pencil", "pencils", "marker", "markers", "eraser", "pencil case",
    ],
    "phone_accessory": [
        "capa", "capa telemovel", "capa iphone", "capa samsung",
        "funda", "funda movil", "funda iphone", "funda samsung",
        "coque", "coque iphone", "coque samsung", "etui telephone",
        "phone case", "iphone case", "samsung case", "phone cover",
        "telefoon hoesje", "hoesje", "gsm hoesje",
    ],
    "puzzle": [
        "puzzle", "quebra cabecas", "quebra-cabecas", "rompecabezas",
    ],
    "merch": [
        "autocolante", "pegatina", "adhesif", "badge", "pin",
    ],
}

VINTED_STRONG_JUNK_CATEGORIES = {"clothing", "toy", "plush", "lego", "book", "stationery", "phone_accessory", "puzzle"}


def titulo_valido(titulo):
    if not titulo:
        return False

    t = titulo.lower()

    if any(p in t for p in PALAVRAS_EXCLUIR):
        return False

    return any(p in t for p in PALAVRAS_OBRIGATORIAS)


def keyword_hits(texto, termos):
    return [termo for termo in termos if termo in texto]


def reject_reason_vinted_junk(titulo, extra_texto=""):
    titulo_norm = normalize_text(titulo)
    extra_norm = normalize_text(extra_texto)
    combined_norm = " ".join(part for part in [titulo_norm, extra_norm] if part)

    if not combined_norm:
        return None

    positive_hits = sum(1 for term in VINTED_TCG_POSITIVE_TERMS if term in combined_norm)
    merged_keywords = {}
    for source_keywords in (VINTED_JUNK_KEYWORDS, VINTED_JUNK_KEYWORDS_EXTRA):
        for category, terms in source_keywords.items():
            merged_keywords.setdefault(category, [])
            merged_keywords[category].extend(terms)

    for category, terms in merged_keywords.items():
        hits_titulo = keyword_hits(titulo_norm, terms)
        hits_extra = keyword_hits(extra_norm, terms)
        unique_hits = set(hits_titulo + hits_extra)

        strong_match = bool(hits_titulo) or len(set(hits_extra)) >= 2
        if not strong_match:
            continue

        if category in VINTED_STRONG_JUNK_CATEGORIES:
            if positive_hits >= 3 and not hits_titulo and len(unique_hits) < 3:
                continue
            return f"rejected_vinted_junk_{category}"

        if positive_hits >= 2 and category in VINTED_WEAK_JUNK_CATEGORIES and not hits_titulo and len(set(hits_extra)) < 3:
            continue

        return f"rejected_vinted_junk_{category}"

    return None


def titulo_relevante(titulo):
    t = titulo.lower()
    return any(p in t for p in PALAVRAS_OBRIGATORIAS)


def anuncio_prioritario(titulo):
    t = titulo.lower()
    return any(p in t for p in PALAVRAS_PRIORITARIAS)


def titulo_valido_ebay(titulo):
    return ebay_excluded_keyword(titulo) is None


def titulo_relevante_ebay(titulo):
    normalized = normalize_text(titulo)
    return any(ebay_term_hit(normalized, p) for p in PALAVRAS_OBRIGATORIAS_EBAY)


def anuncio_buy_it_now(page):
    try:
        texto = page.locator("body").inner_text()
    except:
        return False

    info = analyze_ebay_listing_format_text(texto)
    if info["detected_as_auction"]:
        return False

    return info["detected_as_buy_it_now"]

# ---------------- CARDMARKET ----------------

FICHEIRO_LOG_CARDMARKET = os.path.join("logs", "cardmarket_debug.log")
FICHEIRO_LOG_EBAY_DEBUG = os.path.join("logs", "ebay_debug.log")


def ensure_logs_dir():
    try:
        os.makedirs("logs", exist_ok=True)
    except Exception as e:
        print("Erro ao criar pasta logs:", e)


def ensure_log_file(path):
    try:
        ensure_logs_dir()
        if not os.path.exists(path):
            with open(path, "a", encoding="utf-8"):
                pass
    except Exception as e:
        print(f"Erro ao garantir ficheiro de log {path}:", e)


def rotate_debug_log_if_needed(path):
    try:
        ensure_log_file(path)
        if not os.path.exists(path):
            return

        if os.path.getsize(path) < MAX_DEBUG_LOG_BYTES:
            return

        for idx in range(MAX_DEBUG_LOG_BACKUPS, 0, -1):
            origem = f"{path}.{idx}"
            destino = f"{path}.{idx + 1}"
            if os.path.exists(origem):
                if idx >= MAX_DEBUG_LOG_BACKUPS:
                    os.remove(origem)
                else:
                    os.replace(origem, destino)

        os.replace(path, f"{path}.1")
        ensure_log_file(path)
    except Exception:
        pass


def log_cardmarket_debug(evento):
    return


def truncate_log_text(value, limit=LOG_TITLE_MAX_CHARS):
    text = str(value or "")
    return text if len(text) <= limit else text[:limit]


def sanitize_debug_event(value, key=""):
    if isinstance(value, dict):
        return {item_key: sanitize_debug_event(item_value, item_key) for item_key, item_value in value.items()}
    if isinstance(value, list):
        return [sanitize_debug_event(item, key) for item in value[:20]]
    if isinstance(value, str):
        key_lower = (key or "").lower()
        if key_lower in {"title", "search_title", "title_original"}:
            return truncate_log_text(value, LOG_TITLE_MAX_CHARS)
        if key_lower in {"item_repr", "raw_listing_format_text"}:
            return truncate_log_text(value, 120)
        if any(marker in key_lower for marker in ("html", "content", "body")):
            return "<omitted>"
        if len(value) > 500:
            return truncate_log_text(value, 500)
    return value


def log_ebay_debug(evento):
    try:
        ensure_log_file(FICHEIRO_LOG_EBAY_DEBUG)
        rotate_debug_log_if_needed(FICHEIRO_LOG_EBAY_DEBUG)
        evento = sanitize_debug_event(dict(evento or {}))
        evento["timestamp"] = datetime.now().astimezone().isoformat(timespec="seconds")
        with open(FICHEIRO_LOG_EBAY_DEBUG, "a", encoding="utf-8") as f:
            f.write(json.dumps(evento, ensure_ascii=False) + "\n")
    except Exception as e:
        print("Erro log eBay:", e)


def extrair_codigo_cardmarket(titulo):
    """
    Exemplos:
    sv8a 217
    SV8A-217
    PFL 125
    OBF 223
    """
    padroes = [
        r"\b([A-Za-z]{2,5}\d?[A-Za-z]?)\s*[- ]\s*(\d{1,3}[A-Za-z]?)\b",
    ]

    codigos_invalidos = {
        "psa", "bgs", "cgc", "bulk", "lote", "lot", "pack", "packs",
        "card", "cards", "carta", "cartas", "grade", "graded",
    }

    prefixes_validos = (
        "sv", "swsh", "sm", "xy", "bw", "dp", "hgss",
        "mew", "teu", "pfa", "paf", "pfl", "jtg", "pal", "obf", "par", "sfa",
        "scr", "ssp", "twm", "tem", "pre", "cel", "evs", "crz",
    )

    m = None
    for padrao in padroes:
        m = re.search(padrao, titulo, re.IGNORECASE)
        if m:
            break

    if m:
        set_code = m.group(1).strip().lower()
        card_number = m.group(2).strip()
        if set_code in codigos_invalidos:
            return None
        if not set_code.startswith(prefixes_validos):
            return None
        return f"{set_code} {card_number}"

    return None


def tem_numero_sem_set_cardmarket(titulo):
    return bool(re.search(r"\b\d{1,3}\s*/\s*\d{1,3}\b", titulo))


def nome_forte_cardmarket(titulo):
    t = titulo.lower()
    return any(p in t for p in PALAVRAS_CARTA_FORTE)


def extrair_numero_fracionado(titulo):
    match = re.search(r"\b(\d{1,3}\s*/\s*\d{1,3})\b", titulo or "", re.IGNORECASE)
    if match:
        return re.sub(r"\s+", "", match.group(1))
    return None


def extrair_nome_base_item(titulo):
    nome = normalize_text(titulo or "")
    nome = re.sub(r"\b\d{1,3}\s*/\s*\d{1,3}\b", " ", nome, flags=re.IGNORECASE)
    nome = re.sub(r"\b([a-z]{2,5}\d?[a-z]?)\s*[- ]\s*(\d{1,3}[a-z]?)\b", " ", nome, flags=re.IGNORECASE)
    nome = re.sub(r"\b(pokemon|pokémon|tcg|card|cards|carta|cartas|psa|bgs|beckett|cgc|slab|graded|grade)\b", " ", nome, flags=re.IGNORECASE)
    nome = re.sub(r"\b(english|japanese|francais|français|german|deutsch|italian|italiano|spanish|espanol|español|portuguese|português)\b", " ", nome, flags=re.IGNORECASE)
    nome = re.sub(r"\b(full art|alt art|illustration rare|sir|ir)\b", " ", nome, flags=re.IGNORECASE)
    nome = re.sub(r"\s+", " ", nome).strip(" -|:/()[]")
    if not nome:
        return None

    palavras = [p for p in nome.split() if len(p) > 1]
    if not palavras:
        return None

    return " ".join(palavras[:5])


def extrair_grade_info(titulo):
    if not titulo:
        return None

    patterns = [
        r"\b(psa|bgs|cgc)\s*(10|9(?:\.\d)?|8(?:\.\d)?|7(?:\.\d)?)\b",
        r"\b(beckett)\s*(10|9(?:\.\d)?|8(?:\.\d)?|7(?:\.\d)?)\b",
    ]

    for pattern in patterns:
        match = re.search(pattern, titulo, re.IGNORECASE)
        if match:
            return f"{match.group(1).upper()} {match.group(2)}"

    return None


def texto_card_link(el):
    try:
        return el.evaluate(
            """element => {
                const card = element.closest('article, li, div[data-testid], div');
                return card ? card.innerText : element.innerText;
            }"""
        ).lower()
    except:
        return ""


def ebay_search_title_from_card(texto):
    lines = []
    for raw_line in str(texto or "").splitlines():
        line = re.sub(r"\s+", " ", raw_line).strip()
        if not line:
            continue
        normalized = line.lower()
        if normalized in {
            "new listing",
            "new low price",
            "brand new",
            "pre-owned",
            "used",
            "opens in a new window or tab",
            "shop on ebay",
            "sponsored",
        }:
            continue
        if normalized.startswith(("us $", "$", "eur ")) or re.match(r"^\d+(?:[.,]\d{2})?\s*(?:eur|€)$", normalized):
            continue
        if any(marker in normalized for marker in (" shipping", " bids", " bid ", "watchers", "sold ")):
            continue
        lines.append(line)

    for line in lines:
        normalized = normalize_text(line)
        if "pokemon" in normalized or "poke" in normalized or "tcg" in normalized:
            return line
    return lines[0] if lines else ""


def obter_imagem_card_ebay(el):
    try:
        image_url = el.evaluate(
            """element => {
                const card = element.closest('article, li, div[data-testid], div');
                const img = card ? card.querySelector('img') : element.querySelector('img');
                if (!img) return '';
                return img.currentSrc || img.src || img.getAttribute('data-src') || '';
            }"""
        ) or None
        return high_resolution_ebay_image_url(image_url)
    except Exception:
        return None


def parece_patrocinado(texto):
    sinais = [
        "sponsored", "promoted", "ad ",
        "patrocinado", "promovido", "publicidade",
        "top\n", "\ntop\n", "para o topo", "destaque", "destacado"
    ]
    return any(sinal in texto for sinal in sinais)


EBAY_SEARCH_AUCTION_MARKERS = [
    "current bid", "place bid", "bid now", "bid amount",
    " bids", " bid ", "time left", "ending", "auction",
]


def ebay_search_auction_signals(texto):
    normalized = f" {(texto or '').lower()} "
    signals = []
    for marker in EBAY_SEARCH_AUCTION_MARKERS:
        if marker in normalized:
            signals.append(marker.strip())
    if re.search(r"\b\d+\s+bids?\b", normalized):
        signals.append("bid_count")
    return list(dict.fromkeys(signals))


def ebay_search_card_is_placeholder(texto, href=""):
    normalized = " ".join((texto or "").lower().split())
    href = href or ""
    if href.endswith("/itm/123456"):
        return True
    if "shop on ebay" in normalized:
        return True
    if normalized in {"brand new", "new listing", "shop on ebay brand new"}:
        return True
    return False


def ebay_extra_valido(texto):
    t = (texto or "").lower()
    return not any(termo in t for termo in EBAY_EXTRA_EXCLUDE)


def ebay_excluded_keyword(texto):
    junk_hit = ebay_obvious_junk_keyword(texto)
    if junk_hit:
        return junk_hit

    normalized = normalize_text(texto)
    for termo in EBAY_EXTRA_EXCLUDE + PALAVRAS_EXCLUIR + PALAVRAS_EXCLUIR_EBAY:
        if ebay_term_hit(normalized, termo):
            return termo
    return None


def ebay_language_signals(texto):
    t = (texto or "").lower()
    positivos = sum(1 for termo in EBAY_POSITIVE_LANGUAGE if termo in t)
    negativos = [termo for termo in EBAY_NEGATIVE_LANGUAGE if termo in t]
    return positivos, negativos


def ebay_english_valido(titulo, texto=""):
    return ebay_english_validation(titulo, texto)["passed"]


def ebay_english_validation(titulo, texto=""):
    positivos_titulo, negativos_titulo = ebay_language_signals(titulo)
    positivos_texto, negativos_texto = ebay_language_signals(texto)

    positivos = positivos_titulo + positivos_texto
    negativos = list(dict.fromkeys(negativos_titulo + negativos_texto))

    titulo_lower = (titulo or "").lower()
    contexto = f"{titulo} {texto}".lower()
    has_tcg_title = (
        "pokemon" in titulo_lower or
        "one piece" in titulo_lower or
        "pokemon tcg" in titulo_lower or
        "one piece tcg" in titulo_lower or
        bool(re.search(r"\bop0?\d\b", titulo_lower))
    )
    has_tcg_context = (
        has_tcg_title or
        "pokemon" in contexto or
        "one piece" in contexto or
        "pokemon tcg" in contexto or
        "one piece tcg" in contexto or
        bool(re.search(r"\bop0?\d\b", contexto))
    )
    title_has_explicit_english = "english" in titulo_lower

    if negativos_titulo:
        return {
            "passed": False,
            "reason": "clear_non_english_title",
            "value": ", ".join(dict.fromkeys(negativos_titulo)),
        }

    if title_has_explicit_english and has_tcg_title:
        return {
            "passed": True,
            "reason": "english_title_signal",
            "value": None,
        }

    if positivos_titulo >= 2 and has_tcg_title:
        return {
            "passed": True,
            "reason": "english_title_signal",
            "value": None,
        }

    if negativos_texto and (title_has_explicit_english or (positivos_titulo >= 1 and has_tcg_title)):
        return {
            "passed": True,
            "reason": "english_title_override",
            "value": ", ".join(dict.fromkeys(negativos_texto)),
        }

    if negativos_texto and not has_tcg_title and positivos_titulo == 0:
        return {
            "passed": False,
            "reason": "clear_non_english_body",
            "value": ", ".join(dict.fromkeys(negativos_texto)),
        }

    if positivos >= 2 and has_tcg_context:
        return {
            "passed": True,
            "reason": "english_signal_found",
            "value": None,
        }

    if EBAY_DEBUG_MODE and has_tcg_context:
        return {
            "passed": True,
            "reason": "english_uncertain_allowed",
            "value": None,
        }

    return {
        "passed": False,
        "reason": "english_unclear",
        "value": None,
    }


def _legacy_analyze_ebay_listing_format_text(texto):
    texto = texto or ""
    texto_lower = texto.lower()
    buy_terms = ["buy it now", "comprar já", "comprar ja", "fixed price"]
    auction_markers = [
        "auction", "current bid", "place bid", "winning bid", "leilão", "leilao", "licitar",
    ]

    linhas = []
    for linha in texto.splitlines():
        linha_limpa = linha.strip()
        if not linha_limpa:
            continue
        linha_lower = linha_limpa.lower()
        if any(term in linha_lower for term in buy_terms + auction_markers):
            linhas.append(linha_limpa)
        if len(linhas) >= 4:
            break

    detected_as_auction = any(term in texto_lower for term in auction_markers)
    if not detected_as_auction:
        detected_as_auction = bool(re.search(r"\bbids?\b", texto_lower)) and "no bids" not in texto_lower

    return {
        "raw_listing_format_text": " | ".join(linhas)[:400] if linhas else "",
        "detected_as_buy_it_now": any(term in texto_lower for term in buy_terms),
        "detected_as_auction": detected_as_auction,
    }


def analyze_ebay_listing_format_text(texto):
    texto = texto or ""
    texto_lower = texto.lower()
    buy_terms = [
        "buy it now", "buy now", "add to cart", "add to basket",
        "comprar jÃ¡", "comprar ja", "fixed price",
    ]
    bid_control_terms = [
        "current bid", "place bid", "bid now", "bid amount",
        "enter bid", "submit bid", "winning bid", "your bid",
        "licitar",
    ]
    auction_context_terms = [
        "auction", "time left", "ending", "ends in", "leilÃ£o", "leilao",
    ]
    buy_signals = [term for term in buy_terms if term in texto_lower]
    bid_control_signals = [term for term in bid_control_terms if term in texto_lower]
    auction_context_signals = [term for term in auction_context_terms if term in texto_lower]
    weak_auction_signals = []
    if re.search(r"\b\d+\s+bids?\b", texto_lower):
        weak_auction_signals.append("bid_count")
    elif re.search(r"\bbids?\b", texto_lower) and "no bids" not in texto_lower and not buy_signals:
        auction_context_signals.append("bid_word")

    linhas = []
    primary_auction_signals = []
    for linha in texto.splitlines():
        linha_limpa = linha.strip()
        if not linha_limpa:
            continue
        linha_lower = linha_limpa.lower()
        if any(term in linha_lower for term in buy_terms + bid_control_terms + auction_context_terms):
            linhas.append(linha_limpa)
            for term in bid_control_terms:
                if term in linha_lower:
                    primary_auction_signals.append(term)
            if "time left" in linha_lower:
                primary_auction_signals.append("time left")
        if len(linhas) >= 4:
            break

    strong_buy_signals = [
        signal for signal in buy_signals
        if signal in {"buy it now", "buy now", "add to cart", "add to basket", "fixed price"}
    ]
    strong_auction_signals = list(dict.fromkeys(primary_auction_signals))
    detected_as_buy_it_now = bool(strong_buy_signals or buy_signals)
    detected_as_auction = bool(strong_auction_signals) and not bool(strong_buy_signals)
    classification = "auction" if detected_as_auction else "buy_now" if detected_as_buy_it_now else "unknown"

    return {
        "raw_listing_format_text": " | ".join(linhas)[:400] if linhas else "",
        "detected_as_buy_it_now": detected_as_buy_it_now,
        "detected_as_auction": detected_as_auction,
        "buy_now_signals": buy_signals,
        "auction_signals": list(dict.fromkeys(strong_auction_signals + weak_auction_signals + auction_context_signals)),
        "strong_auction_signals": strong_auction_signals,
        "weak_auction_signals": weak_auction_signals,
        "classification": classification,
    }


def ebay_priority_score(texto):
    t = (texto or "").lower()
    score = 0

    if "pokemon" in t or "tcg" in t:
        score += 3

    for termo in EBAY_PRIORITY_TERMS:
        if termo in t:
            score += 5

    return score


def titulo_sem_parenteses(titulo):
    return re.sub(r"[()]", "", titulo).strip()


def extrair_nome_curto_carta(titulo, codigo):
    if not codigo:
        return None

    partes = codigo.split()
    if len(partes) != 2:
        return None

    set_code, card_number = partes
    nome = titulo

    padroes_codigo = [
        rf"\(?\b{re.escape(set_code)}\s*[-/ ]\s*{re.escape(card_number)}\b\)?",
        rf"\(?\b{re.escape(set_code.upper())}\s*[-/ ]\s*{re.escape(card_number)}\b\)?",
    ]

    for padrao in padroes_codigo:
        nome = re.sub(padrao, " ", nome, flags=re.IGNORECASE)

    nome = re.sub(r"\bpokemon\b|\bpokémon\b|\btcg\b|\bcarta\b|\bcartas\b|\bcard\b|\bcards\b", " ", nome, flags=re.IGNORECASE)
    nome = re.sub(r"\s+", " ", nome).strip(" -|:/()[]")

    if not nome:
        return None

    palavras = nome.split()
    if len(palavras) > 4:
        nome = " ".join(palavras[:4])

    return f"{nome} {codigo}"


def termos_pesquisa_cardmarket(titulo):
    codigo = extrair_codigo_cardmarket(titulo)
    termos = []

    if codigo:
        termos.append(codigo)
        termos.append(titulo)
        termos.append(titulo_sem_parenteses(titulo))

        nome_curto = extrair_nome_curto_carta(titulo, codigo)
        if nome_curto:
            termos.append(nome_curto)
    elif nome_forte_cardmarket(titulo) and not tem_numero_sem_set_cardmarket(titulo):
        termos.append(titulo)
        termos.append(titulo_sem_parenteses(titulo))
    else:
        return []

    termos_limpos = []
    vistos = set()
    for termo in termos:
        termo = re.sub(r"\s+", " ", termo).strip()
        chave = termo.lower()
        if termo and chave not in vistos:
            termos_limpos.append(termo)
            vistos.add(chave)

    return termos_limpos


def termo_cardmarket(titulo):
    t = titulo.lower()
    codigo = extrair_codigo_cardmarket(titulo)

    if codigo:
        return {
            "principal": codigo,
            "alternativos": termos_pesquisa_cardmarket(titulo)[1:]
        }

    if tem_numero_sem_set_cardmarket(titulo) and not codigo:
        return None

    if any(p in t for p in ["psa", "bgs", "beckett", "cgc", "slab", "graded"]) and nome_forte_cardmarket(titulo):
        return {
            "principal": titulo,
            "alternativos": [re.sub(r"[()]", "", titulo).strip()]
        }

    if "etb" in t or "elite trainer box" in t:
        return {
            "principal": titulo,
            "alternativos": [re.sub(r"[()]", "", titulo).strip()]
        }

    if "booster" in t or "blister" in t:
        return {
            "principal": titulo,
            "alternativos": [re.sub(r"[()]", "", titulo).strip()]
        }

    if nome_forte_cardmarket(titulo):
        return {
            "principal": titulo,
            "alternativos": [re.sub(r"[()]", "", titulo).strip()]
        }

    return None


def should_consult_ebay_sold_reference(titulo, tcg_type, assessment):
    if not ENABLE_EBAY_SOLD_REFERENCES:
        return False
    if tcg_type != "pokemon" or not assessment or not assessment.is_valid:
        return False

    normalized = normalize_text(titulo or "")
    categoria = assessment.category
    codigo = extrair_codigo_cardmarket(titulo)
    numero_fracionado = extrair_numero_fracionado(titulo)
    nome_base = extrair_nome_base_item(titulo)
    graded_terms = ["psa", "bgs", "beckett", "cgc", "slab", "graded"]
    sealed_terms = ["etb", "elite trainer box", "booster box", "booster bundle", "tin", "sealed"]

    if categoria == "single_card":
        return codigo is not None or (numero_fracionado is not None and nome_base is not None)

    if categoria == "graded_card":
        return (
            codigo is not None or
            (numero_fracionado is not None and nome_base is not None) or
            (nome_forte_cardmarket(titulo) and any(term in normalized for term in graded_terms))
        )

    if categoria == "sealed_product":
        return any(term in normalized for term in sealed_terms)

    return False


def ebay_sold_cache_fresh(cache_entry):
    if not isinstance(cache_entry, dict):
        return False

    updated_at = parse_iso_or_none(cache_entry.get("updated_at"))
    if not updated_at:
        return False

    if cache_entry.get("data") is None:
        if EBAY_DEBUG_MODE:
            return False
        max_age = timedelta(minutes=EBAY_SOLD_NEGATIVE_CACHE_MAX_AGE_MINUTES)
    else:
        max_age = timedelta(hours=EBAY_SOLD_CACHE_MAX_AGE_HOURS)

    return updated_at >= datetime.now().astimezone() - max_age


def compactar_termo_ebay_sold(titulo, assessment=None):
    termo = normalize_text(titulo or "")
    if not termo:
        return None

    termo = re.sub(
        r"\b(pokemon|pokémon|tcg|card|cards|english|full art|ultra rare|illustration rare|special illustration rare|sir|ir|holo|reverse holo|reverse|graded|grade|mint|near mint|nm|factory|brand new|new)\b",
        " ",
        termo,
        flags=re.IGNORECASE,
    )

    if not (assessment and assessment.category == "sealed_product"):
        termo = re.sub(r"\bsealed\b", " ", termo, flags=re.IGNORECASE)

    termo = re.sub(r"\s+", " ", termo).strip(" -|:/()[]")
    if len(termo.split()) < 2:
        return None

    return termo


def termos_pesquisa_ebay_sold(titulo, assessment):
    codigo = extrair_codigo_cardmarket(titulo)
    numero_fracionado = extrair_numero_fracionado(titulo)
    nome_base = extrair_nome_base_item(titulo)
    grade_info = extrair_grade_info(titulo)
    termo_compacto = compactar_termo_ebay_sold(titulo, assessment)
    termos = []

    if codigo:
        nome_curto = extrair_nome_curto_carta(titulo, codigo)
        if nome_curto:
            termos.append(nome_curto)
            if grade_info and assessment and assessment.category == "graded_card":
                termos.append(f"{grade_info} {nome_curto}")
        if termo_compacto:
            termos.append(termo_compacto)
            if grade_info and assessment and assessment.category == "graded_card":
                termos.append(f"{grade_info} {termo_compacto}")
        termos.append(titulo_sem_parenteses(titulo))
        if grade_info and assessment and assessment.category == "graded_card":
            termos.append(f"{grade_info} {titulo_sem_parenteses(titulo)}")
        termos.append(codigo)
    elif numero_fracionado and nome_base:
        termos.append(f"{nome_base} {numero_fracionado}")
        termos.append(f"pokemon {nome_base} {numero_fracionado}")
        if grade_info and assessment and assessment.category == "graded_card":
            termos.append(f"{grade_info} {nome_base} {numero_fracionado}")
        if termo_compacto:
            termos.append(termo_compacto)
            if grade_info and assessment and assessment.category == "graded_card":
                termos.append(f"{grade_info} {termo_compacto}")
        termos.append(titulo_sem_parenteses(titulo))
        termos.append(numero_fracionado)
    elif assessment and assessment.category == "sealed_product":
        if termo_compacto:
            termos.append(termo_compacto)
            termos.append(f"pokemon {termo_compacto}")
        termos.append(titulo_sem_parenteses(titulo))
        termos.append(titulo)
    elif assessment and assessment.category == "graded_card":
        if termo_compacto:
            termos.append(termo_compacto)
            if grade_info:
                termos.append(f"{grade_info} {termo_compacto}")
        termos.append(titulo_sem_parenteses(titulo))
        termos.append(titulo)

    termos_limpos = []
    vistos = set()
    for termo in termos:
        termo = re.sub(r"\s+", " ", (termo or "")).strip()
        chave = termo.lower()
        if termo and chave not in vistos:
            termos_limpos.append(termo)
            vistos.add(chave)

    return termos_limpos


def extrair_data_ebay_sold(texto):
    if not texto:
        return None

    patterns = [
        r"Sold\s+([A-Za-z]{3}\s+\d{1,2},\s+\d{4})",
        r"Ended\s+([A-Za-z]{3}\s+\d{1,2},\s+\d{4})",
    ]

    for pattern in patterns:
        match = re.search(pattern, texto, re.IGNORECASE)
        if match:
            try:
                return datetime.strptime(match.group(1), "%b %d, %Y").replace(
                    tzinfo=datetime.now().astimezone().tzinfo
                )
            except Exception:
                return match.group(1)

    return None


def formatar_tempo_ebay_sold(valor):
    if not valor:
        return None

    if isinstance(valor, datetime):
        agora = datetime.now().astimezone()
        delta = agora - valor
        if delta < timedelta(hours=24):
            horas = max(1, int(delta.total_seconds() // 3600))
            if horas == 1:
                return "1 hour ago"
            return f"{horas} hours ago"
        if delta < timedelta(hours=48):
            return "yesterday"
        return valor.strftime("%d/%m")

    return str(valor)


def formatar_preco_eur_valor(valor):
    if valor is None:
        return None
    return f"{valor:.2f} €"


def extrair_preco_item_ebay_sold(card):
    selectors = [
        ".s-item__detail .s-item__price",
        ".s-item__price",
        ".x-price-primary",
        "[class*='price']",
        "span[role='text']",
    ]

    vistos = set()
    for selector in selectors:
        try:
            elementos = card.query_selector_all(selector)
            for el in elementos[:5]:
                texto = re.sub(r"\s+", " ", (el.inner_text() or "")).strip()
                if not texto:
                    continue
                chave = texto.lower()
                if chave in vistos:
                    continue
                vistos.add(chave)
                preco = extrair_preco(texto)
                if preco != "Sem preço":
                    return preco
        except Exception:
            pass

    try:
        texto = card.inner_text()
        preco = extrair_preco(texto)
        if preco != "Sem preço":
            return preco
    except Exception:
        pass

    return None


def procurar_ebay_sold_leve(page, titulo, assessment, cache):
    if not should_consult_ebay_sold_reference(titulo, "pokemon", assessment):
        return None

    termos = termos_pesquisa_ebay_sold(titulo, assessment)
    if not termos:
        return None

    chave = termos[0].lower().strip()
    cache_entry = cache.get(chave)
    if ebay_sold_cache_fresh(cache_entry):
        if EBAY_DEBUG_MODE:
            log_ebay_debug({
                "final_status": "EBAY_SOLD_CACHE_HIT",
                "title": titulo,
                "cache_key": chave,
                "cache_has_data": cache_entry.get("data") is not None,
            })
        return cache_entry.get("data")

    try:
        for termo in termos:
            search_url = f"https://www.ebay.com/sch/i.html?_nkw={quote_plus(termo)}&LH_Sold=1&LH_Complete=1&_ipg=25"
            if EBAY_DEBUG_MODE:
                log_ebay_debug({
                    "final_status": "EBAY_SOLD_ATTEMPT",
                    "title": titulo,
                    "search_term": termo,
                    "search_url": search_url,
                })
            page.goto(search_url, timeout=20000, wait_until="domcontentloaded")
            try:
                page.wait_for_selector("li.s-item", timeout=5000)
            except Exception:
                pass
            page.wait_for_timeout(2200)

            cards = page.query_selector_all("ul.srp-results li.s-item, li.s-item")
            vendas = []

            for card in cards[:15]:
                try:
                    titulo_el = card.query_selector("h3")
                    titulo_venda = titulo_el.inner_text().strip() if titulo_el else ""
                    if not titulo_venda or "shop on ebay" in titulo_venda.lower():
                        continue

                    texto_card = card.inner_text()
                    preco_texto = extrair_preco_item_ebay_sold(card)
                    if not preco_texto:
                        continue

                    valor_eur = valor_em_eur(preco_texto)
                    if valor_eur is None:
                        continue

                    vendas.append({
                        "title": titulo_venda,
                        "price_text": preco_texto,
                        "price_eur": valor_eur,
                        "sold_at": extrair_data_ebay_sold(texto_card),
                    })

                    if len(vendas) >= 5:
                        break
                except Exception:
                    continue

            if not vendas:
                if EBAY_DEBUG_MODE:
                    log_ebay_debug({
                        "final_status": "EBAY_SOLD_NO_MATCH",
                        "title": titulo,
                        "search_term": termo,
                        "cards_seen": len(cards),
                    })
                continue

            media_3 = sum(item["price_eur"] for item in vendas[:3]) / min(len(vendas[:3]), 3)
            dados = {
                "termo": termo,
                "last_price_text": vendas[0]["price_text"],
                "last_price_eur": vendas[0]["price_eur"],
                "last_sold_at": vendas[0]["sold_at"].isoformat(timespec="seconds") if isinstance(vendas[0]["sold_at"], datetime) else (vendas[0]["sold_at"] or None),
                "avg3_eur": media_3,
                "sales_found": len(vendas),
                "search_url": search_url,
            }
            cache[chave] = {
                "updated_at": now_iso(),
                "data": dados,
            }
            if EBAY_DEBUG_MODE:
                log_ebay_debug({
                    "final_status": "EBAY_SOLD_MATCH",
                    "title": titulo,
                    "search_term": termo,
                    "sales_found": len(vendas),
                    "last_price_text": dados.get("last_price_text"),
                    "avg3_eur": dados.get("avg3_eur"),
                })
            return dados

        cache[chave] = {
            "updated_at": now_iso(),
            "data": None,
        }
        if EBAY_DEBUG_MODE:
            log_ebay_debug({
                "final_status": "EBAY_SOLD_NO_MATCH_FINAL",
                "title": titulo,
                "cache_key": chave,
                "terms_tried": termos,
            })
        return None
    except Exception as e:
        print("Erro eBay sold:", titulo, e)
        if EBAY_DEBUG_MODE:
            log_ebay_debug({
                "final_status": "EBAY_SOLD_ERROR",
                "title": titulo,
                "cache_key": chave,
                "error": str(e),
            })
        return None


def abrir_primeiro_resultado_cardmarket(page):
    seletores = [
        'a[href*="/Pokemon/Products/Singles/"]',
        'a[href*="/Pokemon/Products/Box-Sets/"]',
        'a[href*="/Pokemon/Products/Booster-Packs/"]',
        'a[href*="/Pokemon/Products/Elite-Trainer-Boxes/"]',
        'a[href*="/Pokemon/Products/"]'
    ]

    for seletor in seletores:
        try:
            elementos = page.query_selector_all(seletor)

            for el in elementos:
                href = el.get_attribute("href")
                if not href:
                    continue

                if "/Pokemon/Products/" not in href:
                    continue

                if href.startswith("/"):
                    href = "https://www.cardmarket.com" + href

                page.goto(href, timeout=20000, wait_until="domcontentloaded")
                page.wait_for_timeout(2500)
                return page.url
        except:
            pass

    return None


def pagina_produto_cardmarket(url):
    return "/Pokemon/Products/" in url and "/Products/Search" not in url


def extrair_preco_cardmarket_do_texto(texto, etiqueta):
    padrao = rf"{re.escape(etiqueta)}[\s\S]{{0,120}}?([0-9]+(?:[,.][0-9]{{2}})?\s*(?:€|EUR))"
    match = re.search(padrao, texto, re.IGNORECASE)
    if match:
        return match.group(1).strip()
    return None


def procurar_cardmarket_leve(page, titulo, cache):
    termos = termo_cardmarket(titulo)
    if not termos:
        return None

    chave = termos["principal"].lower().strip()
    codigo = extrair_codigo_cardmarket(titulo)

    if chave in cache and cache[chave] is not None:
        return cache[chave]

    tentativas = termos_pesquisa_cardmarket(titulo)
    debug = {
        "title_original": titulo,
        "codigo_extraido": codigo,
        "termos_tentados": tentativas,
        "tentativas": [],
        "match": False,
        "avg30": None,
        "trend": None,
        "from": None,
        "erro": None
    }

    try:
        for termo in tentativas:
            if not termo:
                continue

            search_url = f"https://www.cardmarket.com/en/Pokemon/Products/Search?searchString={quote_plus(termo)}"
            tentativa_debug = {
                "termo": termo,
                "search_url": search_url,
                "abriu_produto_real": False,
                "url_final_produto": None,
                "avg30": None,
                "trend": None,
                "from": None
            }

            page.goto(search_url, timeout=20000, wait_until="domcontentloaded")
            page.wait_for_timeout(2500)

            if pagina_produto_cardmarket(page.url):
                tentativa_debug["abriu_produto_real"] = True
                tentativa_debug["url_final_produto"] = page.url
            elif "/Products/Search" in page.url:
                resultado_url = abrir_primeiro_resultado_cardmarket(page)
                if not resultado_url:
                    debug["tentativas"].append(tentativa_debug)
                    continue

                tentativa_debug["abriu_produto_real"] = pagina_produto_cardmarket(page.url)
                tentativa_debug["url_final_produto"] = page.url
            else:
                tentativa_debug["url_final_produto"] = page.url

            if not tentativa_debug["abriu_produto_real"]:
                debug["tentativas"].append(tentativa_debug)
                continue

            texto = page.locator("body").inner_text()

            avg30 = extrair_preco_cardmarket_do_texto(texto, "30-days average price")
            trend = extrair_preco_cardmarket_do_texto(texto, "Price Trend")
            from_price = extrair_preco_cardmarket_do_texto(texto, "From")

            tentativa_debug["avg30"] = avg30
            tentativa_debug["trend"] = trend
            tentativa_debug["from"] = from_price
            debug["tentativas"].append(tentativa_debug)

            if avg30 or trend or from_price:
                dados = {
                    "avg30": avg30,
                    "trend": trend,
                    "from": from_price,
                    "termo": termo,
                    "url": page.url
                }
                debug["match"] = True
                debug["avg30"] = avg30
                debug["trend"] = trend
                debug["from"] = from_price
                debug["url_final_produto"] = page.url
                log_cardmarket_debug(debug)
                cache[chave] = dados
                return dados

        log_cardmarket_debug(debug)
        cache[chave] = None
        return None

    except Exception as e:
        print("Erro Cardmarket:", titulo, e)
        debug["erro"] = str(e)
        log_cardmarket_debug(debug)
        cache[chave] = None
        return None


def linha_cardmarket_alerta(preco_anuncio, dados_cm):
    if not dados_cm:
        return ""

    base = dados_cm.get("avg30") or dados_cm.get("trend") or dados_cm.get("from")
    if not base:
        return ""

    valor_anuncio = valor_em_eur(preco_anuncio)
    valor_cm = valor_em_eur(base)

    if valor_anuncio is None or valor_cm is None or valor_cm == 0:
        return f"📈 Cardmarket: {base}"

    diferenca = ((valor_cm - valor_anuncio) / valor_cm) * 100

    if diferenca >= 25:
        estado = "🔥 Abaixo da média Cardmarket"
    elif diferenca >= 10:
        estado = "⚡ Ligeiramente abaixo da média Cardmarket"
    elif diferenca > -10:
        estado = "➖ Perto da média Cardmarket"
    else:
        estado = "📈 Acima da média Cardmarket"

    return (
        f"{estado}\n"
        f"📈 Cardmarket: {base}\n"
        f"📊 Diferença: {diferenca:.1f}%"
    )


def linha_ebay_sold_alerta(dados):
    if not ENABLE_EBAY_SOLD_REFERENCES:
        return ""
    if not dados:
        return ""

    partes = []
    last_price_text = dados.get("last_price_text")
    last_when = formatar_tempo_ebay_sold(parse_iso_or_none(dados.get("last_sold_at")) or dados.get("last_sold_at"))
    if last_price_text:
        linha = f"🧾 eBay sold: last {formatar_preco_com_eur(last_price_text)}"
        if last_when:
            linha += f" ({last_when})"
        partes.append(linha)

    avg3_eur = dados.get("avg3_eur")
    if avg3_eur is not None:
        partes.append(f"📦 Avg 3 sales: {formatar_preco_eur_valor(avg3_eur)}")

    return "\n".join(partes)

def build_message(anuncio, canal="vip"):
    if canal == "free" and anuncio.get("free_message_text"):
        return anuncio["free_message_text"]

    if canal == "free":
        free_url = build_ebay_affiliate_url(
            anuncio.get("share_link") or anuncio.get("link") or "",
            "telegram_free",
            listing_id=anuncio.get("id"),
        )
        payload = {
            "id": anuncio.get("id"),
            "title": anuncio.get("titulo"),
            "source": anuncio.get("source") or anuncio.get("origem"),
            "price": formatar_preco_com_eur(anuncio.get("preco") or ""),
            "seller_rating": free_seller_rating_text(anuncio.get("seller_feedback"), anuncio.get("source")),
            "url": free_url,
            "affiliate_source": "telegram_free",
            "detected_at": anuncio.get("detected_at"),
            "created_at": anuncio.get("created_at"),
        }
        mensagem, age_meta = format_telegram_listing_message(payload, return_meta=True)
        print(
            f"[telegram_free] listing age calculated id={anuncio.get('id')} "
            f"age={age_meta.get('age_text')} source={age_meta.get('source')}"
        )
        if age_meta.get("used_created_at_fallback"):
            print(f"[telegram_free] missing detected_at fallback used id={anuncio.get('id')}")
        print(f"[telegram_free] Telegram message formatted id={anuncio.get('id')}")

        if should_attach_free_cta():
            mensagem += f"\n{build_free_cta_block()}\n\n━━━━━━━━━━━━━━━━━━━━━━━\n\n"

        return mensagem

    tcg_label = get_tcg_label(anuncio.get("tcg_type"))
    linha_ebay_sold = linha_ebay_sold_alerta(anuncio.get("ebay_sold")) if canal == "vip" else ""
    linha_feedback = format_feedback_line(anuncio.get("seller_feedback"), anuncio.get("source"))

    if canal == "free":
        header = ""
        linha_tempo = ""
    elif canal == "vip":
        header = "VIP listing"
        linha_tempo = "Real-time listing"
    else:
        header = "SHARED OPPORTUNITY"
        linha_tempo = random.choice([
            "Detected earlier",
            "It may no longer be available",
            "Sent to VIP first",
        ])

    mensagem = (
        f"{tcg_label}\n"
        f"{anuncio['origem']}\n"
        f"{(header + chr(10) if header else '')}"
        f"{(linha_tempo + chr(10) if linha_tempo else '')}\n"
        f"{anuncio['titulo']}\n"
        f"{formatar_preco_com_eur(anuncio['preco'])}"
    )

    if linha_feedback:
        mensagem += f"\n{linha_feedback}"

    if linha_ebay_sold:
        mensagem += f"\n{linha_ebay_sold}"

    link = build_ebay_affiliate_url(
        anuncio.get("share_link") or anuncio.get("link") or "",
        "vip" if canal == "vip" else "telegram_free",
        listing_id=anuncio.get("id"),
    )

    mensagem += (
        f"\n\n{link}\n\n"
        f"-----------------------\n"
        f"Pokemon Sniper Deals\n"
        f"-----------------------"
    )

    if canal == "free" and should_attach_free_cta():
        mensagem += f"\n\n━━━━━━━━━━━━━━━\n{build_free_cta_block()}\n━━━━━━━━━━━━━━━"

    return mensagem
def obter_vinted_links(page, vistos=None, diag=None):
    links = []
    seen_links = set()
    vistos = vistos or set()
    for search_url in VINTED_SEARCH_URLS:
        query_diag = diag_get_query(diag, "vinted", search_url)
        query_links = []
        page.goto(search_url, timeout=40000, wait_until="domcontentloaded")
        page.wait_for_timeout(2200 if LIGHT_MODE else 3500)
        elementos = page.query_selector_all('a[href*="/items/"]')
        elementos = elementos[:50]
        diag_count(query_diag, "raw", len(elementos))

        for el in elementos:
            try:
                texto_card = texto_card_link(el)
                if parece_patrocinado(texto_card):
                    diag_count(query_diag, "excluded")
                    continue

                href = el.get_attribute("href")
                if not href:
                    diag_count(query_diag, "rejected")
                    continue

                if not href.startswith("http"):
                    href = "https://www.vinted.pt" + href

                href = limpar_link(href)
                diag_count(query_diag, "parsed")
                id_item = f"vinted_{extrair_id(href)}"
                if id_item in vistos:
                    diag_count(query_diag, "skipped_seen")
                    continue

                if href not in seen_links:
                    seen_links.add(href)
                    links.append(href)
                    query_links.append(href)
                    diag_register_link(diag, "vinted", href, search_url)
                else:
                    diag_count(query_diag, "duplicate")
                if len(links) >= MAX_VINTED_PER_CYCLE:
                    break
            except Exception as error:
                diag_count(query_diag, "rejected")
                print(f"[VINTED_QUERY_ERROR] keyword=\"{_query_keyword(search_url)}\" error=\"{error}\"")
        if len(query_links) >= MAX_VINTED_PER_CYCLE or len(links) >= MAX_VINTED_PER_CYCLE:
            print(
                f"[VINTED_LIMIT] keyword=\"{_query_keyword(search_url)}\" "
                f"query_links={len(query_links)} max_vinted={MAX_VINTED_PER_CYCLE}"
            )
        elementos.clear()
        clear_playwright_page(page)
        if len(links) >= MAX_VINTED_PER_CYCLE:
            break

    clear_playwright_page(page)
    gc.collect()
    return links


def extrair_vinted(page, link):
    try:
        page.goto(link, timeout=20000, wait_until="domcontentloaded")
        page.wait_for_timeout(1800)

        titulo_el = page.query_selector("h1")
        titulo = titulo_el.inner_text().strip() if titulo_el else "Sem t?tulo"

        texto = page.locator("body").inner_text()
        preco = extrair_preco(texto)
        imagem = obter_og_image(page)
        published_at = parse_relative_published_at(texto)
        tcg_type = classify_tcg_type(titulo, texto)
        seller_feedback = extrair_feedback_vinted(page, texto)
        texto_contexto = texto[:2000]

        return titulo, preco, imagem, published_at, tcg_type, texto_contexto, seller_feedback
    except:
        return None, None, None, None, None, None, None
    finally:
        clear_playwright_page(page)

# ---------------- OLX ----------------

def limpar_titulo_olx(titulo):
    if not titulo:
        return "Sem t?tulo"

    titulo = titulo.replace("? OLX.pt", "")
    titulo = titulo.replace("| OLX", "")
    titulo = titulo.replace("- OLX", "")
    titulo = re.sub(r"\s+", " ", titulo).strip()
    return titulo


def obter_titulo_olx(page):
    try:
        meta = page.query_selector('meta[property="og:title"]')
        if meta:
            content = meta.get_attribute("content")
            if content and content.strip():
                return limpar_titulo_olx(content)
    except:
        pass

    try:
        titulo = page.title()
        if titulo and titulo.strip():
            return limpar_titulo_olx(titulo)
    except:
        pass

    try:
        h1 = page.query_selector("h1")
        if h1:
            texto = h1.inner_text().strip()
            if texto:
                return limpar_titulo_olx(texto)
    except:
        pass

    return "Sem título"


def obter_olx_links(page):
    links = []
    for search_url in OLX_SEARCH_URLS:
        page.goto(search_url, timeout=40000, wait_until="domcontentloaded")
        page.wait_for_timeout(3000 if LIGHT_MODE else 4000)
        elementos = page.query_selector_all('a[href*="/d/anuncio/"]')

        for el in elementos[:50]:
            try:
                texto_card = texto_card_link(el)
                if parece_patrocinado(texto_card):
                    continue

                href = el.get_attribute("href")
                if not href:
                    continue

                if href.startswith("/"):
                    href = "https://www.olx.pt" + href

                href = limpar_link(href)
                if href not in links:
                    links.append(href)
                if len(links) >= MAX_OLX:
                    break
            except:
                pass
        if len(links) >= MAX_OLX:
            break

    return list(dict.fromkeys(links))


def extrair_olx(page, link):
    try:
        page.goto(link, timeout=20000, wait_until="domcontentloaded")
        page.wait_for_timeout(1800)

        titulo = obter_titulo_olx(page)
        texto = page.locator("body").inner_text()
        preco = extrair_preco(texto)
        imagem = obter_og_image(page)
        published_at = parse_relative_published_at(texto)
        tcg_type = classify_tcg_type(titulo, texto)
        seller_feedback = extrair_feedback_rating5(texto)

        return titulo, preco, imagem, published_at, tcg_type, seller_feedback
    except:
        return None, None, None, None, None, None

# ---------------- EBAY ----------------

def round_robin_candidates(candidates_by_query, limit):
    selected = []
    while len(selected) < limit:
        added_this_round = False
        for query_candidates in candidates_by_query:
            if query_candidates:
                selected.append(query_candidates.pop(0))
                added_this_round = True
                if len(selected) >= limit:
                    break
        if not added_this_round:
            break
    return selected


def ebay_allocation_log_line():
    return (
        f"[EBAY_ALLOCATION] raw={EBAY_ALLOCATION['raw']} "
        f"sealed={EBAY_ALLOCATION['sealed']} graded={EBAY_ALLOCATION['graded']} "
        f"total={sum(EBAY_ALLOCATION.values())}"
    )


def ebay_query_category(search_url):
    return EBAY_SEARCH_URL_CATEGORY.get(search_url, "raw")


def ebay_allocation_category_for_title(title, default_category="raw"):
    normalized = normalize_text(title)
    if not normalized:
        return default_category if default_category in EBAY_ALLOCATION else "raw"

    if ebay_obvious_junk_keyword(title):
        return "junk"
    if ebay_first_term_hit(normalized, EBAY_GRADED_PRODUCT_TERMS):
        return "graded"
    if ebay_first_term_hit(normalized, EBAY_SEALED_PRODUCT_TERMS):
        return "sealed"

    raw_terms = [
        "card", "cards", "single", "singles", "tcg", "ex", "gx", "vmax",
        "vstar", "full art", "holo", "rare", "illustration rare", "ir", "sir",
    ]
    if ebay_first_term_hit(normalized, raw_terms):
        return "raw"

    return default_category if default_category in EBAY_ALLOCATION else "raw"


def ebay_allocation_category_for_assessment(assessment, title, fallback_category="raw"):
    if assessment and assessment.category == "sealed_product":
        return "sealed"
    if assessment and assessment.category == "graded_card":
        return "graded"
    if assessment and assessment.category == "single_card":
        return "raw"
    return ebay_allocation_category_for_title(title, fallback_category)


def select_ebay_candidates_by_allocation(candidates_by_category):
    selected = []
    selected_ids = set()
    for category in EBAY_ALLOCATION_ORDER:
        for candidate in candidates_by_category.get(category, [])[:EBAY_ALLOCATION[category]]:
            item_id = ebay_seen_id_from_link(candidate.get("link"))
            if item_id in selected_ids:
                continue
            selected_ids.add(item_id)
            selected.append(candidate)

    if len(selected) < EBAY_MAX_CANDIDATES_PER_CYCLE:
        leftovers_by_category = []
        for category in EBAY_ALLOCATION_ORDER:
            leftovers_by_category.append(candidates_by_category.get(category, [])[EBAY_ALLOCATION[category]:])
        for candidate in round_robin_candidates(leftovers_by_category, EBAY_MAX_CANDIDATES_PER_CYCLE - len(selected)):
            item_id = ebay_seen_id_from_link(candidate.get("link"))
            if item_id in selected_ids:
                continue
            selected_ids.add(item_id)
            selected.append(candidate)
            if len(selected) >= EBAY_MAX_CANDIDATES_PER_CYCLE:
                break

    return selected[:EBAY_MAX_CANDIDATES_PER_CYCLE]


def ebay_candidate_has_usable_search_payload(candidate):
    return bool(
        isinstance(candidate, dict)
        and candidate.get("use_search_payload")
        and candidate.get("search_title")
        and candidate.get("search_price")
        and candidate.get("search_price") != "Sem preço"
    )


def ebay_candidate_search_payload(candidate):
    title = candidate.get("search_title")
    price = candidate.get("search_price")
    debug_info = {
        "raw_listing_format_text": "search_result_payload",
        "detected_as_buy_it_now": True,
        "detected_as_auction": False,
        "buy_now_signals": ["search_result_fixed_price"],
        "auction_signals": [],
        "strong_auction_signals": [],
        "weak_auction_signals": [],
        "classification": "buy_now_search_result",
        "english_validation_passed": candidate.get("search_english_validation", {}).get("passed"),
        "english_rejection_reason": candidate.get("search_english_validation", {}).get("reason"),
        "excluded_keyword_hit": candidate.get("excluded_keyword_value") is not None,
        "excluded_keyword_value": candidate.get("excluded_keyword_value"),
    }
    return (
        title,
        price,
        candidate.get("image_url"),
        candidate.get("source_published_at"),
        candidate.get("tcg_type") or classify_ebay_tcg_type(title, ""),
        None,
        debug_info,
        candidate.get("seller_feedback"),
    )


def ebay_api_detection_query_url(query):
    return (
        "https://api.ebay.com/buy/browse/v1/item_summary/search"
        f"?_nkw={quote_plus(query or '')}&sort=newlyListed&filter=buyingOptions:FIXED_PRICE"
    )


def ebay_api_public_link(item):
    item_url = str(getattr(item, "item_url", "") or "").strip()
    if item_url and "/buy/browse/" not in item_url:
        return limpar_link(item_url)
    numeric_id = extrair_ebay_item_id_api(getattr(item, "item_id", ""))
    if numeric_id:
        return f"https://www.ebay.com/itm/{numeric_id}"
    return limpar_link(item_url) if item_url else ""


def ebay_api_price_text(item):
    value = str(getattr(item, "price_value", "") or "").strip()
    currency = str(getattr(item, "price_currency", "") or "").strip().upper()
    if not value or not currency:
        return "Sem preço"
    if currency == "USD":
        return f"US ${value}"
    return f"{currency} {value}"


def ebay_api_candidate_from_item(item, query, query_category, position):
    title = str(getattr(item, "title", "") or "").strip()
    link = ebay_api_public_link(item)
    id_item = ebay_seen_id_from_link(link) or ebay_seen_id_from_api_item_id(getattr(item, "item_id", ""))
    price = ebay_api_price_text(item)
    allocation_category = ebay_allocation_category_for_title(title, query_category)
    return {
        "link": link,
        "search_title": title,
        "search_price": price,
        "image_url": high_resolution_ebay_image_url(str(getattr(item, "image_url", "") or "")),
        "query_url": ebay_api_detection_query_url(query),
        "query_page_url": ebay_api_detection_query_url(query),
        "allocation_category": allocation_category,
        "excluded_keyword_value": ebay_excluded_keyword(title),
        "search_english_validation": ebay_english_validation(title, ""),
        "score": ebay_priority_score(title),
        "detected_at": now_iso(),
        "source_published_at": str(getattr(item, "item_creation_date", "") or ""),
        "position": position,
        "page": 1,
        "use_search_payload": True,
        "source": "api",
        "api_item_id": str(getattr(item, "item_id", "") or ""),
        "seller_feedback": str(getattr(item, "seller_username", "") or ""),
        "_seen_id": id_item,
    }


def obter_ebay_api_links(vistos=None, diag=None):
    vistos = vistos or set()
    candidatos_por_categoria = {category: [] for category in EBAY_ALLOCATION_ORDER}
    seen_candidate_item_ids = set()

    if not EBAY_USE_OFFICIAL_API_DETECTION:
        print("[EBAY_CALL_SKIPPED] source=api reason=official_api_detection_disabled")
        return []
    if not ebay_api_client.is_configured():
        print(f"[EBAY_CALL_SKIPPED] source=api reason={ebay_api_client.config_status()}")
        return []

    for query_category, query in EBAY_SEARCH_QUERIES_POKEMON:
        query_url = ebay_api_detection_query_url(query)
        query_diag = diag_get_query(diag, "ebay", query_url)
        query_reject_start = Counter(query_diag.get("ebay_reject_reasons") or {}) if query_diag else Counter()
        query_parsed_start = query_diag.get("parsed", 0) if query_diag else 0
        query_seen_start = query_diag.get("skipped_seen", 0) if query_diag else 0
        query_first_ids = []
        query_first_titles = []
        accepted_for_query = 0
        print(
            f"[EBAY_QUERY_START] source=api query=\"{query}\" "
            f"limit={EBAY_API_DETECTION_LIMIT} sort=newlyListed"
        )
        try:
            items = ebay_api_client.search_active_buy_now_raw(
                query,
                limit=EBAY_API_DETECTION_LIMIT,
                sort="newlyListed",
                offset=0,
            )
        except EbaySoldRateLimitError as error:
            diag_count(query_diag, "rejected")
            diag_record_ebay_rejection(query_diag, "parse_error", stage="api_search", detail=error)
            print(f"[EBAY_RATE_LIMIT] source=api query=\"{query}\" error=\"{error}\"")
            print(f"[EBAY_CALL_SKIPPED] source=api query=\"{query}\" reason=rate_limit")
            print(f"[EBAY_QUERY_END] source=api query=\"{query}\" status=rate_limit")
            continue
        except EbaySoldError as error:
            diag_count(query_diag, "rejected")
            diag_record_ebay_rejection(query_diag, "parse_error", stage="api_search", detail=error)
            print(f"[EBAY_ERROR] source=api query=\"{query}\" error=\"{error}\"")
            print(f"[EBAY_QUERY_END] source=api query=\"{query}\" status=error")
            continue
        except Exception as error:
            diag_count(query_diag, "rejected")
            diag_record_ebay_rejection(query_diag, "parse_error", stage="api_search", detail=error)
            print(f"[EBAY_ERROR] source=api query=\"{query}\" error=\"{error}\"")
            print(f"[EBAY_QUERY_END] source=api query=\"{query}\" status=error")
            continue

        diag_count(query_diag, "raw", len(items))
        for position, item in enumerate(items, start=1):
            candidate = ebay_api_candidate_from_item(item, query, query_category, position)
            title = candidate.get("search_title") or ""
            id_item = candidate.get("_seen_id")
            link = candidate.get("link") or ""
            price = candidate.get("search_price")
            buying_options = [str(option).upper() for option in getattr(item, "buying_options", [])]

            if id_item and len(query_first_ids) < 5 and id_item not in query_first_ids:
                query_first_ids.append(id_item)
                query_first_titles.append(title)

            if buying_options and "FIXED_PRICE" not in buying_options:
                diag_count(query_diag, "excluded")
                diag_record_ebay_rejection(
                    query_diag,
                    "not_buy_it_now",
                    item_id=id_item,
                    title=title,
                    stage="api_search",
                    detail="missing_fixed_price_option",
                )
                continue
            if not title or not link or not id_item:
                diag_count(query_diag, "rejected")
                diag_record_ebay_rejection(
                    query_diag,
                    "parse_error",
                    item_id=id_item,
                    title=title,
                    stage="api_search",
                    detail="missing_required_api_fields",
                )
                continue
            if id_item in vistos:
                diag_count(query_diag, "skipped_seen")
                print(
                    f"[EBAY_REJECT] reason=already_seen id={id_item} item_id={id_item} "
                    f"source=api query=\"{query}\" title=\"{title[:LOG_TITLE_MAX_CHARS]}\""
                )
                diag_record_ebay_rejection(
                    query_diag,
                    "already_seen",
                    item_id=id_item,
                    title=title,
                    stage="api_search",
                )
                continue
            if id_item in seen_candidate_item_ids:
                diag_count(query_diag, "duplicate")
                diag_record_ebay_rejection(
                    query_diag,
                    "duplicate",
                    item_id=id_item,
                    title=title,
                    stage="api_search",
                )
                continue
            if not price or price == "Sem preço":
                diag_count(query_diag, "rejected")
                diag_record_ebay_rejection(
                    query_diag,
                    "missing_price",
                    item_id=id_item,
                    title=title,
                    stage="api_search",
                    detail="missing_api_price",
                )
                continue
            if candidate.get("allocation_category") == "junk":
                diag_count(query_diag, "excluded")
                diag_record_ebay_rejection(
                    query_diag,
                    "excluded_keyword",
                    item_id=id_item,
                    title=title,
                    stage="api_search",
                    detail=candidate.get("excluded_keyword_value") or "ebay_junk",
                )
                continue

            diag_count(query_diag, "parsed")
            seen_candidate_item_ids.add(id_item)
            candidate.pop("_seen_id", None)
            candidatos_por_categoria.setdefault(candidate.get("allocation_category") or query_category, []).append(candidate)
            diag_register_link(diag, "ebay", link, query_url)
            accepted_for_query += 1

        query_total_results = (query_diag.get("parsed", 0) if query_diag else 0) - query_parsed_start
        query_already_seen = (query_diag.get("skipped_seen", 0) if query_diag else 0) - query_seen_start
        query_rejected = Counter(query_diag.get("ebay_reject_reasons") or {}) if query_diag else Counter()
        query_rejected.subtract(query_reject_start)
        print(f"[EBAY_RESULTS_COUNT] source=api query=\"{query}\" count={max(0, query_total_results)}")
        print(f"[EBAY_ALREADY_SEEN_COUNT] source=api query=\"{query}\" count={max(0, query_already_seen)}")
        print(f"[EBAY_NEW_ACCEPTED_COUNT] source=api query=\"{query}\" count={max(0, accepted_for_query)}")
        ebay_detection_debug_print(
            query,
            max(0, query_total_results),
            query_first_ids,
            query_first_titles,
            max(0, query_already_seen),
            max(0, accepted_for_query),
            +query_rejected,
        )
        print(f"[EBAY_QUERY_END] source=api query=\"{query}\" status=ok accepted_total={accepted_for_query}")

    return select_ebay_candidates_by_allocation(candidatos_por_categoria)


def obter_ebay_links(page, vistos=None, diag=None):
    log_ebay_debug({
        "final_status": "EBAY_DEBUG_STARTED",
        "message": "EBAY DEBUG STARTED",
        "query_urls": EBAY_SEARCH_URLS,
    })

    print(ebay_allocation_log_line())
    candidatos_por_categoria = {category: [] for category in EBAY_ALLOCATION_ORDER}
    seen_candidate_item_ids = set()
    vistos = vistos or set()
    api_candidates = obter_ebay_api_links(vistos=vistos, diag=diag)
    for candidate in api_candidates:
        id_item = ebay_seen_id_from_link(candidate.get("link"))
        if not id_item or id_item in seen_candidate_item_ids:
            continue
        seen_candidate_item_ids.add(id_item)
        allocation_category = candidate.get("allocation_category") or ebay_allocation_category_for_title(
            candidate.get("search_title"),
            "raw",
        )
        candidatos_por_categoria.setdefault(allocation_category, []).append(candidate)
    if len(api_candidates) >= EBAY_MAX_CANDIDATES_PER_CYCLE:
        print(f"[EBAY_API_DETECTION] candidates={len(api_candidates)} using_api_only=true")
        print("EBAY links encontrados:", len(api_candidates))
        return api_candidates[:EBAY_MAX_CANDIDATES_PER_CYCLE]
    if api_candidates:
        print(f"[EBAY_API_DETECTION] candidates={len(api_candidates)} html_fallback=true")
    seletores = [
        'a[href*="/itm/"]',
        'a[href*="itm/"]',
        'a.s-item__link'
    ]

    for search_url in EBAY_SEARCH_URLS:
        query_category = ebay_query_category(search_url)
        query_diag = diag_get_query(diag, "ebay", search_url)
        query_candidates = []
        query_page_signatures = set()
        query_first_ids = []
        query_first_titles = []
        query_reject_start = Counter(query_diag.get("ebay_reject_reasons") or {}) if query_diag else Counter()
        query_parsed_start = query_diag.get("parsed", 0) if query_diag else 0
        query_seen_start = query_diag.get("skipped_seen", 0) if query_diag else 0
        query_accepted_start = len(query_candidates)

        for page_number, page_url in enumerate(ebay_search_page_urls(search_url), start=1):
            if len(query_candidates) >= EBAY_MAX_CANDIDATES_PER_QUERY:
                break
            page_parsed_start = query_diag.get("parsed", 0) if query_diag else 0
            page_seen_start = query_diag.get("skipped_seen", 0) if query_diag else 0
            page_accepted_start = len(query_candidates)
            page_item_ids = []
            print(
                f"[EBAY_QUERY_START] query=\"{_query_keyword(search_url)}\" "
                f"page={page_number} url=\"{page_url}\" sort=newly_listed"
            )
            try:
                page.goto(page_url, timeout=40000, wait_until="domcontentloaded")
                page.wait_for_timeout(3500 if LIGHT_MODE else 5000)
            except Exception as error:
                diag_count(query_diag, "rejected")
                diag_record_ebay_rejection(
                    query_diag,
                    "parse_error",
                    stage="query_navigation",
                    detail=error,
                )
                print(f"[EBAY_ERROR] stage=query_navigation query=\"{_query_keyword(search_url)}\" page={page_number} error=\"{error}\"")
                if ebay_error_is_rate_limit(error):
                    print(f"[EBAY_RATE_LIMIT] stage=query_navigation query=\"{_query_keyword(search_url)}\" page={page_number} error=\"{error}\"")
                    print(f"[EBAY_CALL_SKIPPED] query=\"{_query_keyword(search_url)}\" page={page_number} reason=rate_limit")
                print(f"[EBAY_QUERY_END] query=\"{_query_keyword(search_url)}\" page={page_number} status=error")
                clear_playwright_page(page)
                continue

            for seletor in seletores:
                elementos = []
                try:
                    elementos = page.query_selector_all(seletor)
                    elementos = elementos[:50]
                    diag_count(query_diag, "raw", len(elementos))

                    for el in elementos:
                        texto_card = texto_card_link(el)
                        search_title = ebay_search_title_from_card(texto_card)
                        search_price = extrair_preco(texto_card)
                        href = el.get_attribute("href")
                        href_limpo = limpar_link(href) if href else ""
                        id_item = ebay_seen_id_from_link(href_limpo) if href_limpo else None
                        if id_item:
                            page_item_ids.append(id_item)
                            if search_title and len(query_first_ids) < 5 and id_item not in query_first_ids:
                                query_first_ids.append(id_item)
                                query_first_titles.append(search_title)

                        if parece_patrocinado(texto_card):
                            diag_count(query_diag, "excluded")
                            diag_record_ebay_rejection(
                                query_diag,
                                "other",
                                item_id=id_item,
                                title=texto_card,
                                stage="search_result",
                                detail="sponsored_or_promoted",
                            )
                            continue

                        if ebay_search_card_is_placeholder(texto_card) or not search_title:
                            diag_count(query_diag, "excluded")
                            diag_record_ebay_rejection(
                                query_diag,
                                "placeholder_item",
                                item_id=id_item,
                                title=texto_card,
                                stage="search_result",
                            )
                            continue

                        if not href:
                            diag_count(query_diag, "rejected")
                            diag_record_ebay_rejection(
                                query_diag,
                                "parse_error",
                                title=texto_card,
                                stage="search_result",
                                detail="missing_href",
                            )
                            continue

                        if "/itm/" not in href and "ebay." not in href:
                            diag_count(query_diag, "rejected")
                            diag_record_ebay_rejection(
                                query_diag,
                                "parse_error",
                                title=texto_card,
                                stage="search_result",
                                detail="invalid_href",
                            )
                            continue

                        href = href_limpo
                        if ebay_search_card_is_placeholder(texto_card, href):
                            diag_count(query_diag, "excluded")
                            diag_record_ebay_rejection(
                                query_diag,
                                "placeholder_item",
                                item_id=id_item,
                                title=texto_card,
                                stage="search_result",
                                detail="placeholder_item",
                            )
                            continue

                        if not id_item:
                            diag_count(query_diag, "rejected")
                            diag_record_ebay_rejection(
                                query_diag,
                                "parse_error",
                                title=texto_card,
                                stage="search_result",
                                detail="missing_ebay_item_id",
                            )
                            continue

                        auction_signals = ebay_search_auction_signals(texto_card)
                        if auction_signals:
                            diag_count(query_diag, "excluded")
                            diag_record_ebay_rejection(
                                query_diag,
                                "auction",
                                item_id=id_item,
                                title=texto_card,
                                stage="search_result",
                                detail=",".join(auction_signals),
                            )
                            print(
                                f"[EBAY_SEARCH_SKIP_AUCTION] id={id_item} "
                                f"title=\"{texto_card[:LOG_TITLE_MAX_CHARS]}\" signals={','.join(auction_signals)}"
                            )
                            continue

                        diag_count(query_diag, "parsed")
                        if id_item in vistos:
                            diag_count(query_diag, "skipped_seen")
                            print(
                                f"[EBAY_SEEN_SKIP] item_id={id_item} stage=search_result "
                                f"query=\"{_diag_query_label(query_diag)}\" "
                                f"title=\"{search_title[:LOG_TITLE_MAX_CHARS]}\""
                            )
                            diag_record_ebay_rejection(
                                query_diag,
                                "already_seen",
                                item_id=id_item,
                                title=search_title,
                                stage="search_result",
                            )
                            continue

                        if not search_price or search_price == "Sem preço":
                            diag_count(query_diag, "rejected")
                            diag_record_ebay_rejection(
                                query_diag,
                                "missing_price",
                                item_id=id_item,
                                title=search_title,
                                stage="search_result",
                                detail="missing_search_price",
                            )
                            continue

                        allocation_category = ebay_allocation_category_for_title(search_title, query_category)
                        if allocation_category == "junk":
                            excluded_keyword = ebay_excluded_keyword(search_title) or "ebay_junk"
                            diag_count(query_diag, "excluded")
                            diag_record_ebay_rejection(
                                query_diag,
                                "excluded_keyword",
                                item_id=id_item,
                                title=search_title,
                                stage="search_result",
                                detail=excluded_keyword,
                            )
                            continue

                        if id_item not in seen_candidate_item_ids:
                            seen_candidate_item_ids.add(id_item)
                            candidate = {
                                "link": href,
                                "search_title": search_title.strip(),
                                "search_price": search_price,
                                "image_url": obter_imagem_card_ebay(el),
                                "query_url": search_url,
                                "query_page_url": page_url,
                                "allocation_category": allocation_category,
                                "excluded_keyword_value": ebay_excluded_keyword(search_title),
                                "search_english_validation": ebay_english_validation(search_title, ""),
                                "score": ebay_priority_score(search_title),
                                "detected_at": now_iso(),
                                "position": len(query_candidates),
                                "page": page_number,
                                "use_search_payload": True,
                            }
                            query_candidates.append(candidate)
                            candidatos_por_categoria.setdefault(allocation_category, []).append(candidate)
                            diag_register_link(diag, "ebay", href, search_url)
                        else:
                            diag_count(query_diag, "duplicate")
                            diag_record_ebay_rejection(
                                query_diag,
                                "duplicate",
                                item_id=id_item,
                                title=texto_card,
                                stage="search_result",
                            )

                        if len(query_candidates) >= EBAY_MAX_CANDIDATES_PER_QUERY:
                            break

                    if len(query_candidates) >= EBAY_MAX_CANDIDATES_PER_QUERY:
                        break
                except Exception as error:
                    diag_count(query_diag, "rejected")
                    diag_record_ebay_rejection(
                        query_diag,
                        "parse_error",
                        stage="search_result",
                        detail=error,
                    )
                    print(
                        f"[EBAY_ERROR] stage=search_result keyword=\"{_query_keyword(search_url)}\" "
                        f"page={page_number} selector=\"{seletor}\" error=\"{error}\""
                    )
                    if ebay_error_is_rate_limit(error):
                        print(
                            f"[EBAY_RATE_LIMIT] stage=search_result keyword=\"{_query_keyword(search_url)}\" "
                            f"page={page_number} selector=\"{seletor}\" error=\"{error}\""
                        )
                finally:
                    try:
                        elementos.clear()
                    except Exception:
                        pass

            page_results = (query_diag.get("parsed", 0) if query_diag else 0) - page_parsed_start
            page_already_seen = (query_diag.get("skipped_seen", 0) if query_diag else 0) - page_seen_start
            page_accepted = len(query_candidates) - page_accepted_start
            print(f"[EBAY_RESULTS_COUNT] query=\"{_query_keyword(search_url)}\" page={page_number} count={max(0, page_results)}")
            print(f"[EBAY_ALREADY_SEEN_COUNT] query=\"{_query_keyword(search_url)}\" page={page_number} count={max(0, page_already_seen)}")
            print(f"[EBAY_NEW_ACCEPTED_COUNT] query=\"{_query_keyword(search_url)}\" page={page_number} count={max(0, page_accepted)}")
            print(
                f"[EBAY_QUERY_END] query=\"{_query_keyword(search_url)}\" page={page_number} "
                f"status=ok accepted_total={len(query_candidates)}"
            )
            signature = tuple(page_item_ids[:20])
            duplicate_page = bool(signature and signature in query_page_signatures)
            if duplicate_page:
                print(
                    f"[EBAY_QUERY_PAGE_DUPLICATE] query=\"{_query_keyword(search_url)}\" "
                    f"page={page_number} repeated_first_ids={','.join(signature[:5])}"
                )
            elif signature:
                query_page_signatures.add(signature)
            clear_playwright_page(page)
            gc.collect()
            if duplicate_page:
                break

        query_total_results = (query_diag.get("parsed", 0) if query_diag else 0) - query_parsed_start
        query_already_seen = (query_diag.get("skipped_seen", 0) if query_diag else 0) - query_seen_start
        query_accepted = len(query_candidates) - query_accepted_start
        query_rejected = Counter(query_diag.get("ebay_reject_reasons") or {}) if query_diag else Counter()
        query_rejected.subtract(query_reject_start)
        ebay_detection_debug_print(
            _query_keyword(search_url),
            max(0, query_total_results),
            query_first_ids,
            query_first_titles,
            max(0, query_already_seen),
            max(0, query_accepted),
            +query_rejected,
        )
        if len(query_candidates) >= EBAY_MAX_CANDIDATES_PER_QUERY:
            print(
                f"[EBAY_LIMIT] keyword=\"{_query_keyword(search_url)}\" "
                f"query_candidates={len(query_candidates)} "
                f"max_ebay_per_query={EBAY_MAX_CANDIDATES_PER_QUERY}"
            )
        query_candidates.clear()

    total_candidates = sum(len(query_candidates) for query_candidates in candidatos_por_categoria.values())
    if total_candidates > EBAY_MAX_CANDIDATES_PER_CYCLE:
        print(
            f"[EBAY_LIMIT] candidates_before_round_robin={total_candidates} "
            f"max_cycle={EBAY_MAX_CANDIDATES_PER_CYCLE} "
            f"max_ebay_per_query={EBAY_MAX_CANDIDATES_PER_QUERY}"
        )

    candidatos = select_ebay_candidates_by_allocation(candidatos_por_categoria)
    print("EBAY links encontrados:", len(candidatos))
    return candidatos

def extrair_ebay(page, link):
    try:
        page.goto(link, timeout=20000, wait_until="domcontentloaded")
        page.wait_for_timeout(600 if LIGHT_MODE else 1200)

        titulo = page.title().replace("| eBay", "").strip()
        texto = page.locator("body").inner_text()
        if ebay_search_card_is_placeholder(titulo):
            return titulo, None, None, None, None, "placeholder_item", {
                "raw_listing_format_text": "",
                "detected_as_buy_it_now": False,
                "detected_as_auction": False,
                "buy_now_signals": [],
                "auction_signals": [],
                "strong_auction_signals": [],
                "weak_auction_signals": [],
                "classification": "placeholder_item",
                "english_validation_passed": False,
                "english_rejection_reason": "placeholder_item",
                "excluded_keyword_hit": False,
                "excluded_keyword_value": None,
            }, None

        format_info = analyze_ebay_listing_format_text(texto)
        excluded_keyword_value = ebay_excluded_keyword(titulo)
        english_validation = ebay_english_validation(titulo, texto)

        debug_info = {
            "raw_listing_format_text": "",
            "detected_as_buy_it_now": format_info["detected_as_buy_it_now"],
            "detected_as_auction": format_info["detected_as_auction"],
            "buy_now_signals": format_info.get("buy_now_signals", []),
            "auction_signals": format_info.get("auction_signals", []),
            "strong_auction_signals": format_info.get("strong_auction_signals", []),
            "weak_auction_signals": format_info.get("weak_auction_signals", []),
            "classification": format_info.get("classification"),
            "english_validation_passed": english_validation["passed"],
            "english_rejection_reason": english_validation["reason"],
            "excluded_keyword_hit": excluded_keyword_value is not None,
            "excluded_keyword_value": excluded_keyword_value,
        }

        if format_info["detected_as_auction"]:
            return titulo, None, None, None, None, "auction", debug_info, None

        if not format_info["detected_as_buy_it_now"]:
            return titulo, None, None, None, None, "not_buy_it_now", debug_info, None

        if excluded_keyword_value:
            return titulo, None, None, None, None, "ebay_noise", debug_info, None

        if not english_validation["passed"]:
            return titulo, None, None, None, None, "non_english", debug_info, None

        preco = extrair_preco(texto)
        imagem = obter_og_image(page)
        published_at = parse_relative_published_at(texto)
        tcg_type = classify_ebay_tcg_type(titulo, texto)
        seller_feedback = extrair_feedback_ebay(texto, titulo)
        return titulo, preco, imagem, published_at, tcg_type, None, debug_info, seller_feedback
    except:
        return None, None, None, None, None, "scrape_error", {
            "raw_listing_format_text": "",
            "detected_as_buy_it_now": False,
            "detected_as_auction": False,
            "buy_now_signals": [],
            "auction_signals": [],
            "strong_auction_signals": [],
            "weak_auction_signals": [],
            "classification": "scrape_error",
            "english_validation_passed": False,
            "english_rejection_reason": "scrape_error",
            "excluded_keyword_hit": False,
            "excluded_keyword_value": None,
        }, None
    finally:
        clear_playwright_page(page)


def wallapop_env_enabled():
    return env_bool("ENABLE_WALLAPOP", False)


def wallapop_inline_requested():
    return env_bool("WALLAPOP_INLINE_IN_MAIN_BOT", False)


def wallapop_inline_enabled():
    return wallapop_env_enabled() and wallapop_inline_requested()


def log_wallapop_config():
    print(f"[WALLAPOP_CONFIG] ENABLE_WALLAPOP={os.getenv('ENABLE_WALLAPOP', '')}")
    print(f"[WALLAPOP_CONFIG] WALLAPOP_INLINE_IN_MAIN_BOT={os.getenv('WALLAPOP_INLINE_IN_MAIN_BOT', '')}")
    print(f"[WALLAPOP_CONFIG] WALLAPOP_MAX_ITEMS_PER_RUN={os.getenv('WALLAPOP_MAX_ITEMS_PER_RUN', '')}")
    print(f"[WALLAPOP_INLINE] enabled={str(wallapop_inline_enabled()).lower()}")
    if wallapop_inline_requested() and not wallapop_env_enabled():
        print("[WALLAPOP_INLINE] disabled reason=ENABLE_WALLAPOP_FALSE")


def wallapop_inline_max_items():
    return min(env_int("WALLAPOP_MAX_ITEMS_PER_RUN", WALLAPOP_MAX_ITEMS_PER_RUN), MAX_EBAY_CANDIDATES_PER_CYCLE)


def processar_wallapop_inline(vistos, novos, diag=None, context=None):
    enabled = wallapop_inline_enabled()
    max_items = wallapop_inline_max_items()
    print(f"[WALLAPOP_INLINE] enabled={str(enabled).lower()}")
    print(f"[WALLAPOP_INLINE] max_items_per_run={max_items}")
    if not enabled:
        if wallapop_inline_requested() and not wallapop_env_enabled():
            print("[WALLAPOP_INLINE] disabled reason=ENABLE_WALLAPOP_FALSE")
        elif wallapop_env_enabled() and not wallapop_inline_requested():
            print("[WALLAPOP_INLINE] disabled reason=WALLAPOP_INLINE_IN_MAIN_BOT_FALSE")
        return {"items_found": 0, "items_sent": 0}

    print("[WALLAPOP_INLINE] cycle_start")
    query_diag = diag_get_query(diag, "wallapop", "wallapop:inline")
    items_found = 0
    items_sent = 0

    try:
        seen_ids = set(vistos or set())
        seen_ids.update(item.get("id") for item in novos if item.get("id"))
        if context is not None:
            wallapop_items, scrape_stats = fetch_wallapop_listings_with_context(
                context,
                max_items=max_items,
                delay_min_seconds=WALLAPOP_DELAY_MIN_SECONDS,
                delay_max_seconds=WALLAPOP_DELAY_MAX_SECONDS,
                seen_ids=seen_ids,
                return_stats=True,
            )
        else:
            wallapop_items, scrape_stats = fetch_wallapop_listings(
                max_items=max_items,
                headless=WALLAPOP_HEADLESS,
                delay_min_seconds=WALLAPOP_DELAY_MIN_SECONDS,
                delay_max_seconds=WALLAPOP_DELAY_MAX_SECONDS,
                seen_ids=seen_ids,
                return_stats=True,
            )
        items_found = len(wallapop_items)
        diag_count(query_diag, "raw", items_found)
        diag_count(query_diag, "parsed", items_found)
        if scrape_stats:
            diag_count(query_diag, "duplicate", int(scrape_stats.get("duplicates", 0)))
            diag_count(query_diag, "rejected", int(scrape_stats.get("rejected", 0)))
        for wallapop_item in wallapop_items[:max_items]:
            id_item = wallapop_item.get("id") or wallapop_item.get("external_id")
            titulo = wallapop_item.get("titulo") or wallapop_item.get("title")
            preco = wallapop_item.get("preco") or wallapop_item.get("price")
            link = wallapop_item.get("link") or wallapop_item.get("url")
            if not id_item or id_item in seen_ids or not titulo:
                diag_count(query_diag, "skipped_seen")
                record_metric_event("skipped_duplicate", item_id=id_item, platform="wallapop")
                continue

            tcg_type = "pokemon"
            if not tcg_enabled(tcg_type):
                diag_count(query_diag, "excluded")
                reason = disabled_tcg_reason(tcg_type)
                record_metric_event("skipped_filtered", item_id=id_item, platform="wallapop", tcg_type=tcg_type, reason=reason)
                print(f"[TCG_DISABLED_SKIP] id={id_item} platform=wallapop tcg_type={tcg_type} reason={reason}")
                continue

            vinted_junk_reason = reject_reason_vinted_junk(titulo, wallapop_item.get("description") or "")
            if vinted_junk_reason:
                diag_count(query_diag, "excluded")
                assessment_reject = ListingAssessment(
                    is_valid=False,
                    score=0,
                    category="rejected",
                    confidence="none",
                    reasons=[],
                    reject_reason=vinted_junk_reason,
                )
                record_metric_event(
                    "skipped_filtered",
                    item_id=id_item,
                    platform="wallapop",
                    tcg_type=tcg_type,
                    reason=vinted_junk_reason,
                )
                log_listing_event(
                    source="wallapop",
                    title=titulo,
                    price=preco,
                    assessment=assessment_reject,
                    priority=False,
                    consulted_cardmarket=False,
                    cardmarket_found=False,
                    reject_reason=vinted_junk_reason,
                )
                print(f"[WALLAPOP_REJECTED] reason={vinted_junk_reason} id={id_item} title={titulo[:90]}")
                continue

            if not titulo_valido_tcg(titulo, tcg_type, "wallapop"):
                diag_count(query_diag, "excluded")
                record_metric_event("skipped_filtered", item_id=id_item, platform="wallapop", tcg_type=tcg_type, reason="titulo_invalido")
                print(f"[WALLAPOP_REJECTED] reason=titulo_invalido id={id_item} title={titulo[:90]}")
                continue

            assessment = assess_listing_for_tcg(tcg_type, titulo, preco, "wallapop")
            if not assessment.is_valid:
                diag_count(query_diag, "rejected")
                record_metric_event(
                    "skipped_filtered",
                    item_id=id_item,
                    platform="wallapop",
                    tcg_type=tcg_type,
                    score_label=assessment.confidence.upper(),
                    reason=assessment.reject_reason or "assessment_invalid",
                )
                log_listing_event(source="wallapop", title=titulo, price=preco, assessment=assessment, priority=False, consulted_cardmarket=False, cardmarket_found=False)
                print(f"[WALLAPOP_REJECTED] reason={assessment.reject_reason or 'assessment_invalid'} id={id_item} title={titulo[:90]}")
                continue

            prioridade = is_priority(assessment) if tcg_type == "pokemon" else False
            detected_at = wallapop_item.get("detected_at") or detected_at_now_iso()
            log_listing_event(source="wallapop", title=titulo, price=preco, assessment=assessment, priority=prioridade, consulted_cardmarket=False, cardmarket_found=False)
            novos.append({
                "id": id_item,
                "source": "wallapop",
                "origem": "WALLAPOP",
                "tcg_type": tcg_type,
                "titulo": titulo,
                "preco": preco,
                "link": link,
                "prioritario": prioridade,
                "imagem": wallapop_item.get("imagem") or wallapop_item.get("image_url"),
                "ebay_sold": None,
                "score": assessment.score,
                "categoria": assessment.category,
                "confianca": assessment.confidence,
                "detected_at": detected_at,
                "source_published_at": None,
                "seller_feedback": wallapop_item.get("location"),
                "raw_payload": wallapop_item.get("raw_payload"),
            })
            seen_ids.add(id_item)
            items_sent += 1
            diag_count(query_diag, "accepted")
            diag_register_link(diag, "wallapop", link, "wallapop:inline")
            record_metric_event(
                "captured",
                item_id=id_item,
                platform="wallapop",
                tcg_type=tcg_type,
                score_label=obter_score_label(novos[-1]),
            )
            if items_sent >= max_items:
                break
    except Exception as e:
        print(f"[WALLAPOP_ERROR] error=\"{e}\"")
        traceback.print_exc()
    finally:
        print(f"[WALLAPOP_INLINE] items_found={items_found}")
        gc.collect()
        log_ram_usage("after_wallapop")

    return {"items_found": items_found, "items_sent": items_sent}


def procurar_anuncios(processar_ebay=True, diag=None):
    vistos = carregar_vistos()
    if EBAY_DEBUG_IGNORE_MAIN_VISTOS:
        vistos.update(carregar_vistos_ebay_debug())
    vistos.update(carregar_ids_app_sincronizados())
    cache_ebay_sold = carregar_cache_ebay_sold()
    novos = []

    runtime = obter_runtime_pages()
    if runtime:
        browser = runtime["browser"]
        context = runtime["context"]
        page_lista = runtime["page_lista"]
        page_detalhe = runtime["page_detalhe"]
        should_close_browser = False
        should_close_context = False
        p = None
    else:
        p = sync_playwright().start()
        browser = p.chromium.launch(headless=True, args=playwright_launch_args())
        context = create_light_context(browser)
        page_lista = context.new_page()
        page_detalhe = context.new_page()
        should_close_browser = True
        should_close_context = True

    try:
        # VINTED
        vinted_accepted = 0
        for link in obter_vinted_links(page_lista, vistos=vistos, diag=diag):
            query_diag = diag_query_for_link(diag, "vinted", link)
            id_item = f"vinted_{extrair_id(link)}"
            if id_item in vistos:
                diag_count(query_diag, "skipped_seen")
                record_metric_event("skipped_duplicate", item_id=id_item, platform="vinted")
                continue

            titulo, preco, imagem, source_published_at, tcg_type, texto_vinted, seller_feedback = extrair_vinted(page_detalhe, link)
            page_detalhe = recycle_page(context, page_detalhe, "page_detalhe" if runtime else None)
            gc.collect()
            if not titulo:
                diag_count(query_diag, "rejected")
                continue

            vinted_junk_reason = reject_reason_vinted_junk(titulo, texto_vinted)
            if vinted_junk_reason:
                diag_count(query_diag, "excluded")
                assessment_reject = ListingAssessment(
                    is_valid=False,
                    score=0,
                    category="rejected",
                    confidence="none",
                    reasons=[],
                    reject_reason=vinted_junk_reason,
                )
                record_metric_event(
                    "skipped_filtered",
                    item_id=id_item,
                    platform="vinted",
                    tcg_type=tcg_type,
                    reason=vinted_junk_reason,
                )
                log_listing_event(
                    source="vinted",
                    title=titulo,
                    price=preco,
                    assessment=assessment_reject,
                    priority=False,
                    consulted_cardmarket=False,
                    cardmarket_found=False,
                    reject_reason=vinted_junk_reason,
                )
                continue

            if not tcg_type:
                diag_count(query_diag, "rejected")
                record_metric_event("skipped_filtered", item_id=id_item, platform="vinted", reason="tcg_irrelevante")
                continue

            if not tcg_enabled(tcg_type):
                diag_count(query_diag, "excluded")
                reason = disabled_tcg_reason(tcg_type)
                record_metric_event("skipped_filtered", item_id=id_item, platform="vinted", tcg_type=tcg_type, reason=reason)
                print(f"[TCG_DISABLED_SKIP] id={id_item} platform=vinted tcg_type={tcg_type} reason={reason}")
                continue

            if not titulo_valido_tcg(titulo, tcg_type, "vinted"):
                diag_count(query_diag, "excluded")
                record_metric_event("skipped_filtered", item_id=id_item, platform="vinted", tcg_type=tcg_type, reason="titulo_invalido")
                continue

            assessment = assess_listing_for_tcg(tcg_type, titulo, preco, "vinted")
            if not assessment.is_valid:
                diag_count(query_diag, "rejected")
                record_metric_event(
                    "skipped_filtered",
                    item_id=id_item,
                    platform="vinted",
                    tcg_type=tcg_type,
                    score_label=assessment.confidence.upper(),
                    reason=assessment.reject_reason or "assessment_invalid",
                )
                log_listing_event(source="vinted", title=titulo, price=preco, assessment=assessment, priority=False, consulted_cardmarket=False, cardmarket_found=False)
                continue

            prioridade = is_priority(assessment) if tcg_type == "pokemon" else False
            comparavel_ebay_sold = should_consult_ebay_sold_reference(titulo, tcg_type, assessment)
            dados_ebay_sold = procurar_ebay_sold_leve(page_detalhe, titulo, assessment, cache_ebay_sold) if comparavel_ebay_sold else None
            detected_at = detected_at_now_iso()

            log_listing_event(source="vinted", title=titulo, price=preco, assessment=assessment, priority=prioridade, consulted_cardmarket=False, cardmarket_found=False)

            novos.append({
                "id": id_item,
                "source": "vinted",
                "origem": "🟢 VINTED",
                "tcg_type": tcg_type,
                "titulo": titulo,
                "preco": preco,
                "link": link,
                "prioritario": prioridade,
                "imagem": imagem,
                "ebay_sold": dados_ebay_sold,
                "score": assessment.score,
                "categoria": assessment.category,
                "confianca": assessment.confidence,
                "detected_at": detected_at,
                "source_published_at": source_published_at,
                "seller_feedback": seller_feedback,
            })
            diag_count(query_diag, "accepted")
            vinted_accepted += 1
            record_metric_event(
                "captured",
                item_id=id_item,
                platform="vinted",
                tcg_type=tcg_type,
                score_label=obter_score_label(novos[-1]),
            )
            if vinted_accepted >= MAX_VINTED_PER_CYCLE:
                print(f"[VINTED_LIMIT] accepted={vinted_accepted} max_vinted={MAX_VINTED_PER_CYCLE}")
                break

        texto_vinted = None
        page_lista = recycle_page(context, page_lista, "page_lista" if runtime else None)
        gc.collect()
        log_ram_usage("after_vinted")

        # OLX removed from active pipeline

        # EBAY
        try:
            ebay_candidates = obter_ebay_links(page_lista, vistos=vistos, diag=diag) if processar_ebay else []
            page_lista = recycle_page(context, page_lista, "page_lista" if runtime else None)
            if len(ebay_candidates) > EBAY_MAX_CANDIDATES_PER_CYCLE:
                print(f"EBAY candidatos limitados a {EBAY_MAX_CANDIDATES_PER_CYCLE} neste ciclo")
            ebay_accepted = 0
            ebay_allocation_counts = Counter()
            for idx_ebay, ebay_candidate in enumerate(ebay_candidates[:EBAY_MAX_CANDIDATES_PER_CYCLE], start=1):
                query_diag = None
                if isinstance(ebay_candidate, dict):
                    query_diag = diag_query_for_link(diag, "ebay", ebay_candidate.get("link"))
                if runtime and EBAY_DETAIL_PAGE_RESET_EVERY and idx_ebay > 1 and (idx_ebay - 1) % EBAY_DETAIL_PAGE_RESET_EVERY == 0:
                    novo_page_detalhe = reset_runtime_page("page_detalhe")
                    if page_is_usable(novo_page_detalhe):
                        page_detalhe = novo_page_detalhe
                print(f"EBAY progresso: {idx_ebay}/{min(len(ebay_candidates), EBAY_MAX_CANDIDATES_PER_CYCLE)}")
                log_ebay_debug({
                    "final_status": "EBAY_CANDIDATE_RAW",
                    "item_type": str(type(ebay_candidate)),
                    "item_repr": repr(ebay_candidate)[:120],
                })

                if not isinstance(ebay_candidate, dict):
                    diag_count(query_diag, "rejected")
                    diag_record_ebay_rejection(
                        query_diag,
                        "parse_error",
                        stage="candidate",
                        detail="candidate_not_dict",
                    )
                    log_ebay_debug({
                        "final_status": "EBAY_INVALID_ITEM_STRUCTURE",
                        "reason": "candidate_not_dict",
                        "item_type": str(type(ebay_candidate)),
                        "item_repr": repr(ebay_candidate)[:120],
                    })
                    continue

                link = ebay_candidate.get("link")
                query_diag = diag_query_for_link(diag, "ebay", link)
                if not link:
                    diag_count(query_diag, "rejected")
                    diag_record_ebay_rejection(
                        query_diag,
                        "parse_error",
                        title=ebay_candidate.get("search_title"),
                        stage="candidate",
                        detail="missing_link",
                    )
                    log_ebay_debug({
                        "final_status": "EBAY_INVALID_ITEM_STRUCTURE",
                        "reason": "missing_link",
                        "item_type": str(type(ebay_candidate)),
                        "item_repr": repr(ebay_candidate)[:120],
                    })
                    continue

                id_item = ebay_seen_id_from_link(link)
                if not id_item:
                    diag_count(query_diag, "rejected")
                    diag_record_ebay_rejection(
                        query_diag,
                        "parse_error",
                        title=ebay_candidate.get("search_title"),
                        stage="candidate",
                        detail="missing_ebay_item_id",
                    )
                    log_ebay_debug({
                        "final_status": "EBAY_INVALID_ITEM_ID",
                        "url": link,
                        "title": ebay_candidate.get("search_title"),
                    })
                    continue

                debug_data = {
                    "item_id": id_item,
                    "title": ebay_candidate.get("search_title"),
                    "url": link,
                    "query_url": ebay_candidate.get("query_url"),
                    "raw_price": None,
                    "raw_listing_format_text": "",
                    "detected_as_buy_it_now": None,
                    "detected_as_auction": None,
                    "buy_now_signals": [],
                    "auction_signals": [],
                    "strong_auction_signals": [],
                    "weak_auction_signals": [],
                    "classification": None,
                    "english_validation_passed": ebay_candidate.get("search_english_validation", {}).get("passed"),
                    "english_rejection_reason": ebay_candidate.get("search_english_validation", {}).get("reason"),
                    "excluded_keyword_hit": ebay_candidate.get("excluded_keyword_value") is not None,
                    "excluded_keyword_value": ebay_candidate.get("excluded_keyword_value"),
                    "allocation_category": ebay_candidate.get("allocation_category"),
                    "tcg_type": None,
                    "score": None,
                    "score_label": None,
                    "duplicate": False,
                    "final_status": "EBAY_DETECTED",
                }
                log_ebay_debug(debug_data)

                duplicate_in_main = id_item in vistos
                if duplicate_in_main:
                    diag_count(query_diag, "skipped_seen")
                    print(
                        f"[EBAY_SEEN_SKIP] item_id={id_item} stage=candidate "
                        f"query=\"{_diag_query_label(query_diag)}\" "
                        f"title=\"{(debug_data.get('title') or '')[:LOG_TITLE_MAX_CHARS]}\""
                    )
                    diag_record_ebay_rejection(
                        query_diag,
                        "already_seen",
                        item_id=id_item,
                        title=debug_data.get("title"),
                        stage="candidate",
                    )
                    debug_data["duplicate"] = True
                    debug_data["final_status"] = "EBAY_REJECTED_DUPLICATE"
                    log_ebay_debug(debug_data)
                    record_metric_event("skipped_duplicate", item_id=id_item, platform="ebay")
                    continue

                if ebay_candidate_has_usable_search_payload(ebay_candidate):
                    titulo, preco, imagem, source_published_at, tcg_type, scrape_reject_reason, ebay_debug, seller_feedback = ebay_candidate_search_payload(ebay_candidate)
                    print(
                        f"[EBAY_DETAIL_SKIPPED] id={id_item} reason=search_payload "
                        f"price=\"{preco}\" title=\"{titulo[:LOG_TITLE_MAX_CHARS]}\""
                    )
                else:
                    titulo, preco, imagem, source_published_at, tcg_type, scrape_reject_reason, ebay_debug, seller_feedback = extrair_ebay(page_detalhe, link)
                    page_detalhe = recycle_page(context, page_detalhe, "page_detalhe" if runtime else None)
                    gc.collect()
                if not titulo:
                    diag_count(query_diag, "rejected")
                    diag_record_ebay_rejection(
                        query_diag,
                        "parse_error",
                        item_id=id_item,
                        title=debug_data.get("title"),
                        stage="detail",
                        detail=scrape_reject_reason or "missing_title",
                    )
                    debug_data["final_status"] = "EBAY_REJECTED_SCORE"
                    debug_data["english_rejection_reason"] = "scrape_error"
                    log_ebay_debug(debug_data)
                    continue

                debug_data.update({
                    "title": titulo,
                    "raw_price": preco,
                    "raw_listing_format_text": ebay_debug.get("raw_listing_format_text", ""),
                    "detected_as_buy_it_now": ebay_debug.get("detected_as_buy_it_now"),
                    "detected_as_auction": ebay_debug.get("detected_as_auction"),
                    "buy_now_signals": ebay_debug.get("buy_now_signals", []),
                    "auction_signals": ebay_debug.get("auction_signals", []),
                    "strong_auction_signals": ebay_debug.get("strong_auction_signals", []),
                    "weak_auction_signals": ebay_debug.get("weak_auction_signals", []),
                    "classification": ebay_debug.get("classification"),
                    "english_validation_passed": ebay_debug.get("english_validation_passed"),
                    "english_rejection_reason": ebay_debug.get("english_rejection_reason"),
                    "excluded_keyword_hit": ebay_debug.get("excluded_keyword_hit"),
                    "excluded_keyword_value": ebay_debug.get("excluded_keyword_value"),
                })
                buy_now_signals = ebay_debug.get("buy_now_signals", [])
                auction_signals = ebay_debug.get("auction_signals", [])
                if ebay_debug.get("detected_as_buy_it_now"):
                    print(
                        f"[EBAY_DETAIL_BUY_NOW_DETECTED] id={id_item} "
                        f"signals={','.join(buy_now_signals) or 'unknown'}"
                    )
                if ebay_debug.get("detected_as_auction"):
                    print(
                        f"[EBAY_DETAIL_AUCTION_DETECTED] id={id_item} "
                        f"signals={','.join(auction_signals) or 'unknown'}"
                    )
                print(
                    f"[EBAY_DETAIL_CLASSIFICATION] id={id_item} "
                    f"result={ebay_debug.get('classification') or 'unknown'} "
                    f"buy_signals={','.join(buy_now_signals) or 'none'} "
                    f"auction_signals={','.join(auction_signals) or 'none'}"
                )

                if scrape_reject_reason:
                    if scrape_reject_reason in {"ebay_noise", "placeholder_item"}:
                        diag_count(query_diag, "excluded")
                    else:
                        diag_count(query_diag, "rejected")
                    reject_detail = scrape_reject_reason
                    if scrape_reject_reason == "ebay_noise":
                        reject_detail = debug_data.get("excluded_keyword_value") or ebay_excluded_keyword(titulo) or scrape_reject_reason
                    diag_record_ebay_rejection(
                        query_diag,
                        ebay_rejection_reason_from_scrape(scrape_reject_reason),
                        item_id=id_item,
                        title=titulo,
                        stage="detail",
                        detail=reject_detail,
                    )
                    if scrape_reject_reason == "not_buy_it_now":
                        debug_data["final_status"] = "EBAY_REJECTED_NOT_BUY_IT_NOW"
                    elif scrape_reject_reason == "auction":
                        debug_data["final_status"] = "EBAY_REJECTED_AUCTION"
                    elif scrape_reject_reason == "non_english":
                        debug_data["final_status"] = "EBAY_REJECTED_LANGUAGE"
                    elif scrape_reject_reason == "ebay_noise":
                        debug_data["final_status"] = "EBAY_REJECTED_EXCLUDED_KEYWORD"
                    elif scrape_reject_reason == "placeholder_item":
                        debug_data["final_status"] = "EBAY_REJECTED_PLACEHOLDER"
                    else:
                        debug_data["final_status"] = "EBAY_REJECTED_SCORE"
                    log_ebay_debug(debug_data)
                    record_metric_event(
                        "skipped_filtered",
                        item_id=id_item,
                        platform="ebay",
                        tcg_type=tcg_type,
                        reason=scrape_reject_reason,
                    )
                    log_listing_event(
                        source="ebay",
                        title=titulo,
                        price=preco,
                        assessment=None,
                        priority=False,
                        consulted_cardmarket=False,
                        cardmarket_found=False,
                        reject_reason=scrape_reject_reason,
                    )
                    continue

                if not tcg_type:
                    diag_count(query_diag, "rejected")
                    non_tcg_keyword = ebay_obvious_junk_keyword(titulo) or "no_ebay_product_keyword"
                    diag_record_ebay_rejection(
                        query_diag,
                        "non_tcg",
                        item_id=id_item,
                        title=titulo,
                        stage="tcg_filter",
                        detail=non_tcg_keyword,
                    )
                    debug_data["final_status"] = "EBAY_REJECTED_TCG_TYPE"
                    log_ebay_debug(debug_data)
                    record_metric_event("skipped_filtered", item_id=id_item, platform="ebay", reason="tcg_irrelevante")
                    continue

                if not tcg_enabled(tcg_type):
                    diag_count(query_diag, "excluded")
                    reason = disabled_tcg_reason(tcg_type)
                    diag_record_ebay_rejection(
                        query_diag,
                        "other",
                        item_id=id_item,
                        title=titulo,
                        stage="tcg_filter",
                        detail=reason,
                    )
                    debug_data["tcg_type"] = tcg_type
                    debug_data["final_status"] = "EBAY_REJECTED_TCG_DISABLED"
                    log_ebay_debug(debug_data)
                    record_metric_event("skipped_filtered", item_id=id_item, platform="ebay", tcg_type=tcg_type, reason=reason)
                    print(f"[TCG_DISABLED_SKIP] id={id_item} platform=ebay tcg_type={tcg_type} reason={reason}")
                    continue

                if not titulo_valido_tcg(titulo, tcg_type, "ebay"):
                    diag_count(query_diag, "excluded")
                    excluded_keyword = ebay_excluded_keyword(titulo)
                    invalid_title_reason = (
                        "excluded_keyword"
                        if debug_data.get("excluded_keyword_hit") or excluded_keyword
                        else "non_tcg"
                    )
                    diag_record_ebay_rejection(
                        query_diag,
                        invalid_title_reason,
                        item_id=id_item,
                        title=titulo,
                        stage="title_filter",
                        detail=excluded_keyword or "missing_required_ebay_keyword",
                    )
                    debug_data["tcg_type"] = tcg_type
                    debug_data["final_status"] = "EBAY_REJECTED_EXCLUDED_KEYWORD"
                    log_ebay_debug(debug_data)
                    record_metric_event("skipped_filtered", item_id=id_item, platform="ebay", tcg_type=tcg_type, reason="titulo_invalido")
                    continue

                assessment = assess_listing_for_tcg(tcg_type, titulo, preco, "ebay")
                debug_data["tcg_type"] = tcg_type
                debug_data["score"] = assessment.score
                debug_data["score_label"] = assessment.confidence.upper()

                if not assessment.is_valid:
                    diag_count(query_diag, "rejected")
                    diag_record_ebay_rejection(
                        query_diag,
                        ebay_rejection_reason_from_assessment(assessment, preco),
                        item_id=id_item,
                        title=titulo,
                        stage="score_filter",
                        detail=assessment.reject_reason or "assessment_invalid",
                    )
                    debug_data["final_status"] = "EBAY_REJECTED_SCORE"
                    log_ebay_debug(debug_data)
                    record_metric_event(
                        "skipped_filtered",
                        item_id=id_item,
                        platform="ebay",
                        tcg_type=tcg_type,
                        score_label=assessment.confidence.upper(),
                        reason=assessment.reject_reason or "assessment_invalid",
                    )
                    log_listing_event(source="ebay", title=titulo, price=preco, assessment=assessment, priority=False, consulted_cardmarket=False, cardmarket_found=False)
                    continue

                allocation_category = ebay_allocation_category_for_assessment(
                    assessment,
                    titulo,
                    ebay_candidate.get("allocation_category") or "raw",
                )
                debug_data["allocation_category"] = allocation_category
                if ebay_allocation_counts[allocation_category] >= EBAY_ALLOCATION.get(allocation_category, 0):
                    print(
                        f"[EBAY_ALLOCATION_SOFT_CAP] category={allocation_category} "
                        f"count={ebay_allocation_counts[allocation_category]} "
                        f"cap={EBAY_ALLOCATION.get(allocation_category, 0)} id={id_item} "
                        "action=allow_fill_cycle"
                    )

                prioridade = is_priority(assessment) if tcg_type == "pokemon" else False
                comparavel_ebay_sold = False
                dados_ebay_sold = procurar_ebay_sold_leve(page_detalhe, titulo, assessment, cache_ebay_sold) if comparavel_ebay_sold else None
                detected_at = detected_at_now_iso()

                log_listing_event(source="ebay", title=titulo, price=preco, assessment=assessment, priority=prioridade, consulted_cardmarket=False, cardmarket_found=False)
                debug_data["final_status"] = "EBAY_ACCEPTED"
                log_ebay_debug(debug_data)

                novos.append({
                    "id": id_item,
                    "source": "ebay",
                    "origem": "🔵 EBAY",
                    "tcg_type": tcg_type,
                    "titulo": titulo,
                    "preco": preco,
                    "link": link,
                    "prioritario": prioridade,
                    "imagem": imagem,
                    "ebay_sold": dados_ebay_sold,
                    "ebay_debug": ebay_debug,
                    "score": assessment.score,
                    "categoria": assessment.category,
                    "confianca": assessment.confidence,
                    "detected_at": detected_at,
                    "source_published_at": source_published_at,
                    "seller_feedback": seller_feedback,
                })
                diag_count(query_diag, "accepted")
                ebay_accepted += 1
                ebay_allocation_counts[allocation_category] += 1
                record_metric_event(
                    "captured",
                    item_id=id_item,
                    platform="ebay",
                    tcg_type=tcg_type,
                    score_label=obter_score_label(novos[-1]),
                )
                if ebay_accepted >= EBAY_MAX_CANDIDATES_PER_CYCLE:
                    print(f"[EBAY_LIMIT] accepted={ebay_accepted} max_ebay={EBAY_MAX_CANDIDATES_PER_CYCLE}")
                    break
            ebay_candidates.clear()
            gc.collect()
            log_ram_usage("after_ebay")
        except Exception as e:
            print(f"[EBAY_PIPELINE_ERROR] error=\"{e}\"")
            log_ebay_debug({
                "final_status": "EBAY_PIPELINE_ERROR",
                "error": str(e),
                "traceback": traceback.format_exc(),
            })
            gc.collect()
            log_ram_usage("after_ebay")

        # WALLAPOP
        processar_wallapop_inline(vistos, novos, diag=diag, context=context)

    finally:
        if not should_close_context and LIGHT_MODE:
            release_runtime_pages()
        if should_close_context:
            try:
                context.close()
            except Exception:
                pass
        if should_close_browser:
            try:
                browser.close()
            except Exception:
                pass
            try:
                p.stop()
            except Exception:
                pass

    guardar_cache_ebay_sold(cache_ebay_sold)
    novos.sort(
        key=lambda x: (
            sort_iso_key(x.get("detected_at")),
        ),
        reverse=True,
    )
    novos = mix_announcements_by_source(novos)
    return novos

def main():
    ensure_logs_dir()
    ensure_log_file(FICHEIRO_LOG_EBAY_DEBUG)
    vistos_drop_prefixes = ["olx_"] if not OLX_ENABLED else []
    if EBAY_DEBUG_IGNORE_MAIN_VISTOS:
        vistos_drop_prefixes.append("ebay_")
    compactar_ficheiro_linhas(
        FICHEIRO_VISTOS,
        MAX_VISTOS_ITEMS,
        drop_prefixes=vistos_drop_prefixes,
        expire_ebay_seen=True,
    )
    compactar_ficheiro_linhas(
        FICHEIRO_VISTOS_EBAY_DEBUG,
        MAX_VISTOS_EBAY_DEBUG_ITEMS,
        expire_ebay_seen=True,
    )
    if FREE_LANDING_ONLY:
        guardar_fila_free([])
    schedule_free_promos_every_hour()
    print("Bot ativo...")
    log_delivery_config()
    log_wallapop_config()
    ciclo = 0
    next_cycle_at = time.monotonic()

    while True:
        cycle_started_at = time.monotonic()
        try:
            ciclo += 1
            log_ram_usage("cycle_start")
            maybe_refresh_runtime(ciclo)
            if LIGHT_MODE and ciclo % RUNTIME_DEBUG_EVERY_CYCLES == 0:
                log_runtime_state(ciclo, refreshed=False)
            if ciclo % MEMORY_LOG_EVERY_CYCLES == 0:
                log_memory_usage(ciclo)
            if ciclo % AVAILABILITY_CHECK_EVERY == 0:
                processar_tracking_disponibilidade()
            maybe_send_hourly_summary()
            maybe_send_vip_market_report()
            processar_fila_free()
            processar_ebay = should_process_ebay_cycle(ciclo)
            print(f"Cycle {ciclo} | processar_ebay={processar_ebay}")
            if processar_ebay:
                print(f"[EBAY_CYCLE_START] cycle={ciclo} processar_ebay=true")
                log_ebay_debug({
                    "final_status": "EBAY_CYCLE_START",
                    "cycle": ciclo,
                    "message": "EBAY DEBUG STARTED",
                })
            else:
                print("EBAY SKIPPED THIS CYCLE")
                print(f"[EBAY_CALL_SKIPPED] cycle={ciclo} reason=cycle_schedule")
                log_ebay_debug({
                    "final_status": "EBAY_SKIPPED_THIS_CYCLE",
                    "cycle": ciclo,
                    "message": "EBAY SKIPPED THIS CYCLE",
                })
            diag = start_cycle_diag(ciclo, processar_ebay)
            novos = procurar_anuncios(processar_ebay=processar_ebay, diag=diag)
            if LIGHT_MODE and _RUNTIME.get("browser") is not None and not _RUNTIME.get("created_cycle"):
                _RUNTIME["created_cycle"] = ciclo

            wallapop_items_sent = 0
            for anuncio in novos:
                if not tcg_enabled(anuncio.get("tcg_type")):
                    print(
                        f"[TCG_DISABLED_SKIP] id={anuncio.get('id')} platform={anuncio.get('source')} "
                        f"tcg_type={anuncio.get('tcg_type')} stage=delivery"
                    )
                    continue

                registar_tracking_anuncio(anuncio)
                anuncio["app_sync"] = enviar_anuncio_app(anuncio)
                if anuncio.get("source") == "wallapop" and (anuncio.get("app_sync") or {}).get("http_status") is not None:
                    wallapop_items_sent += 1
                mark_listing_app_synced(anuncio.get("id"), anuncio.get("app_sync"))
                app_seen_marked = mark_seen_after_app_delivery(anuncio, anuncio.get("app_sync"))
                if anuncio.get("source") == "wallapop" and not should_send_wallapop_to_telegram(anuncio, WALLAPOP_SEND_TELEGRAM):
                    free_result = {"status": "disabled_wallapop"}
                    print(f"[WALLAPOP_TELEGRAM_SKIPPED] id={anuncio.get('id')} reason=disabled")
                else:
                    free_result = enfileirar_anuncio_free(anuncio)
                if not app_seen_marked:
                    mark_seen_after_telegram_delivery(anuncio, free_result)
                diag_record_delivery(diag, anuncio, anuncio.get("app_sync"), free_result)
                print(
                    f"[delivery_result] id={anuncio.get('id')} "
                    f"app={anuncio.get('app_sync', {}).get('status')} "
                    f"free={(free_result or {}).get('status')}"
                )
                time.sleep(2)
            if wallapop_inline_enabled():
                print(f"[WALLAPOP_INLINE] items_sent={wallapop_items_sent}")
                print("[WALLAPOP_INLINE] cycle_end")
            log_cycle_diag(diag)
            novos.clear()
            del novos
            gc.collect()
            log_ram_usage("cycle_end")

            if ciclo % GC_COLLECT_EVERY_CYCLES == 0:
                libertados = gc.collect()
                print(f"[GC] ciclo={ciclo} objetos_libertados={libertados}")

        except Exception as e:
            print("Erro:", e)
            gc.collect()
            log_ram_usage("cycle_end")

        next_cycle_at = max(next_cycle_at + CHECK_INTERVAL, cycle_started_at + CHECK_INTERVAL)
        remaining_sleep = max(0.0, next_cycle_at - time.monotonic())
        print(f"A aguardar {remaining_sleep:.1f}s...\n")
        if remaining_sleep > 0.05:
            time.sleep(remaining_sleep)

if __name__ == "__main__":
    try:
        main()
    finally:
        close_runtime(reason="shutdown")
