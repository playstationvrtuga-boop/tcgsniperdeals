"""Lightweight Wallapop feed scraper for Pokemon TCG listings.

The scraper intentionally extracts from search result pages only. It keeps the
runtime small for Render workers and returns app-ready dictionaries that can go
through the existing Vinted/eBay pipeline.
"""

from __future__ import annotations

import hashlib
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from html import unescape
from typing import Iterable
from urllib.parse import quote_plus, urljoin, urlsplit

from core.normalizer import normalize_text
from services.pokemon_title_parser import extract_card_signals


WALLAPOP_SOURCE = "wallapop"
WALLAPOP_PLATFORM = "Wallapop"
WALLAPOP_QUERIES = [
    "pokemon cartas",
    "pokemon tcg",
    "cartas pokemon",
    "charizard pokemon",
    "pokemon booster",
    "pokemon etb",
]
WALLAPOP_BASE_URL = "https://es.wallapop.com/app/search?keywords={query}"
WALLAPOP_RESULTS_SELECTOR = (
    'a[href*="/item/"], a[href*="/app/item"], a[href*="/product/"], '
    'a[href*="/app/search"], article, li, [data-testid], [data-item-id], [data-product-id], '
    '[class*="ItemCard"], [class*="Card"]'
)
WALLAPOP_GOTO_TIMEOUT_MS = 20000
WALLAPOP_RESULTS_TIMEOUT_MS = 9000
WALLAPOP_AFTER_GOTO_WAIT_MS = 2000
WALLAPOP_VISIBLE_CARD_SCAN_LIMIT = 5

POSITIVE_TCG_TERMS = {
    "pokemon",
    "tcg",
    "carta",
    "cartas",
    "card",
    "cards",
    "booster",
    "etb",
    "elite trainer box",
    "slab",
    "graded",
    "psa",
    "bgs",
    "cgc",
    "sealed",
    "blister",
    "display",
    "tin",
}
JUNK_TERMS = {
    "camiseta",
    "camisa",
    "ropa",
    "tshirt",
    "sudadera",
    "funko",
    "peluche",
    "plush",
    "poster",
    "lamina",
    "decoracion",
    "decoracao",
    "nintendo switch",
    "switch",
    "consola",
    "console",
    "juego",
    "videojuego",
    "gameboy",
    "ds",
}
BLOCKED_TEXT_MARKERS = {
    "captcha",
    "verify you are human",
    "verifica que eres humano",
    "access denied",
    "too many requests",
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_int(value, default: int = 2, minimum: int = 1) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(minimum, parsed)


def wallapop_enabled() -> bool:
    return str(os.getenv("ENABLE_WALLAPOP", "false")).strip().lower() in {"1", "true", "yes", "on"}


def wallapop_max_items() -> int:
    return _safe_int(os.getenv("WALLAPOP_MAX_ITEMS_PER_RUN"), default=2, minimum=1)


def should_send_wallapop_to_telegram(listing: dict | None = None, send_enabled: bool | None = None) -> bool:
    if send_enabled is None:
        send_enabled = str(os.getenv("WALLAPOP_SEND_TELEGRAM", "false")).strip().lower() in {"1", "true", "yes", "on"}
    if not listing:
        return bool(send_enabled)
    source = str(listing.get("source") or listing.get("platform") or "").strip().lower()
    if source == WALLAPOP_SOURCE or source == WALLAPOP_PLATFORM.lower():
        return bool(send_enabled)
    return True


def normalize_wallapop_url(url: str) -> str:
    if not url:
        return ""
    cleaned = url.strip()
    if cleaned.startswith("//"):
        cleaned = "https:" + cleaned
    if cleaned.startswith("/"):
        cleaned = urljoin("https://es.wallapop.com", cleaned)
    parsed = urlsplit(cleaned)
    if "wallapop" not in parsed.netloc.lower():
        return cleaned
    return parsed._replace(query="", fragment="").geturl()


def derive_wallapop_external_id(url: str, title: str = "", price: str = "") -> str:
    normalized_url = normalize_wallapop_url(url)
    match = re.search(r"/item/([^/?#]+)", normalized_url)
    if match:
        return f"wallapop_{match.group(1)}"
    if normalized_url:
        digest_source = normalized_url
    else:
        digest_source = f"{title}|{price}|{WALLAPOP_SOURCE}"
    digest = hashlib.sha1(digest_source.encode("utf-8", errors="ignore")).hexdigest()[:16]
    return f"wallapop_{digest}"


def wallapop_candidate_reason(title: str, description: str = "") -> tuple[bool, str]:
    text = normalize_text(f"{title or ''} {description or ''}")
    if not text.strip():
        return False, "empty_title"
    for junk in JUNK_TERMS:
        if junk in text:
            return False, f"junk:{junk}"
    if "pokemon" not in text and not extract_card_signals(text).get("pokemon_name"):
        return False, "missing_pokemon"
    if any(term in text for term in POSITIVE_TCG_TERMS):
        return True, "tcg_terms"
    signals = extract_card_signals(text)
    if signals.get("full_number") or signals.get("card_number"):
        return True, "card_signals"
    return False, "weak_tcg_signal"


def _clean_price(raw: str) -> str:
    text = " ".join(str(raw or "").split())
    match = re.search(r"(\d+(?:[,.]\d{1,2})?)\s*(?:eur|€)", text, flags=re.I)
    if match:
        return f"{match.group(1).replace('.', ',')} €"
    return text[:60]


def normalize_wallapop_candidate(candidate: dict) -> dict:
    title = str(candidate.get("title") or candidate.get("titulo") or "").strip()
    price = _clean_price(str(candidate.get("price") or candidate.get("preco") or ""))
    url = normalize_wallapop_url(str(candidate.get("url") or candidate.get("link") or ""))
    image_url = str(candidate.get("image_url") or candidate.get("imagem") or "").strip() or None
    location = str(candidate.get("location") or "").strip() or None
    external_id = str(candidate.get("external_id") or candidate.get("id") or "").strip()
    if not external_id:
        external_id = derive_wallapop_external_id(url, title, price)
    raw_payload = {
        "location": location,
        "source_query": candidate.get("source_query"),
    }
    return {
        "id": external_id,
        "external_id": external_id,
        "source": WALLAPOP_SOURCE,
        "platform": WALLAPOP_PLATFORM,
        "origem": "WALLAPOP",
        "titulo": title,
        "title": title,
        "preco": price,
        "price": price,
        "link": url,
        "url": url,
        "imagem": image_url,
        "image_url": image_url,
        "location": location,
        "detected_at": candidate.get("detected_at") or _now_iso(),
        "raw_payload": {key: value for key, value in raw_payload.items() if value},
    }


def _new_wallapop_stats() -> dict[str, int]:
    return {"accepted": 0, "rejected": 0, "duplicates": 0, "timeouts": 0, "query_errors": 0}


def filter_wallapop_candidates(
    candidates: Iterable[dict],
    seen_ids: set[str] | None = None,
    max_items: int = 2,
    stats: dict[str, int] | None = None,
) -> list[dict]:
    accepted = []
    seen = set(seen_ids or set())
    local_seen = set()
    max_items = _safe_int(max_items, default=2, minimum=1)
    for candidate in candidates:
        item = normalize_wallapop_candidate(candidate)
        title = item["title"]
        reason_ok, reason = wallapop_candidate_reason(title, candidate.get("description", ""))
        print(f"[WALLAPOP_CANDIDATE] title={title[:90]} external_id={item['external_id']}", flush=True)
        print(f"[WALLAPOP_DETECTED] title={title[:90]} external_id={item['external_id']}", flush=True)
        if not reason_ok:
            if stats is not None:
                stats["rejected"] = stats.get("rejected", 0) + 1
            print(f"[WALLAPOP_REJECTED] reason={reason} title={title[:90]}", flush=True)
            continue
        dedupe_keys = {
            item["external_id"],
            derive_wallapop_external_id(item["url"], item["title"], item["price"]),
            hashlib.sha1(f"{item['title']}|{item['price']}|{WALLAPOP_SOURCE}".encode("utf-8", errors="ignore")).hexdigest()[:16],
        }
        if (dedupe_keys & seen) or (dedupe_keys & local_seen):
            if stats is not None:
                stats["duplicates"] = stats.get("duplicates", 0) + 1
                stats["rejected"] = stats.get("rejected", 0) + 1
            print(f"[WALLAPOP_DUPLICATE] external_id={item['external_id']} title={title[:90]}", flush=True)
            print(f"[WALLAPOP_REJECTED] reason=duplicate title={title[:90]}", flush=True)
            continue
        local_seen.update(dedupe_keys)
        print(f"[WALLAPOP_ACCEPTED] external_id={item['external_id']} title={title[:90]}", flush=True)
        accepted.append(item)
        if stats is not None:
            stats["accepted"] = stats.get("accepted", 0) + 1
        if len(accepted) >= max_items:
            break
    return accepted


def _route_light_resources(route):
    resource_type = route.request.resource_type
    url = route.request.url.lower()
    if resource_type in {"image", "media", "font"} or any(marker in url for marker in ("analytics", "doubleclick", "googletagmanager")):
        route.abort()
    else:
        route.continue_()


def _extract_items_from_page(page, source_query: str) -> list[dict]:
    return page.evaluate(
        """
        ({ sourceQuery, limit }) => {
          const nodes = [...document.querySelectorAll('article, li, [data-testid], [data-item-id], [data-product-id], [class*="ItemCard"], [class*="Card"], a[href*="/item/"], a[href*="/app/item"], a[href*="/product/"], a[href*="/app/search"]')];
          return nodes.slice(0, 30).map((node) => {
            const anchor = node.matches && node.matches('a[href]') ? node : node.querySelector('a[href]');
            const root = node.closest('article, li, [data-testid], [data-item-id], [data-product-id], .ItemCard, .ItemCardList__item, [class*="ItemCard"], [class*="Card"]') || node;
            const text = (root.innerText || (anchor && anchor.innerText) || '').trim();
            const lines = text.split('\\n').map((line) => line.trim()).filter(Boolean);
            const priceLine = lines.find((line) => /\\d+[,.]?\\d*\\s*(€|eur)/i.test(line)) || '';
            const titleLine = lines.find((line) => {
              if (line === priceLine || line.length <= 2) return false;
              if (/^\\d+\\s*\\/\\s*\\d+$/.test(line)) return false;
              if (/destacado/i.test(line)) return false;
              return true;
            }) || (anchor && anchor.getAttribute('title')) || root.getAttribute('title') || root.getAttribute('aria-label') || '';
            const img = root.querySelector('img');
            return {
              title: titleLine,
              price: priceLine,
              url: anchor ? anchor.href : (root.getAttribute('data-url') || root.getAttribute('href') || ''),
              image_url: img ? (img.currentSrc || img.src || '') : '',
              location: '',
              source_query: sourceQuery
            };
          }).filter((item) => item.title && item.price && item.url).slice(0, limit);
        }
        """,
        {"sourceQuery": source_query, "limit": WALLAPOP_VISIBLE_CARD_SCAN_LIMIT},
    )


def _strip_html(text: str) -> str:
    text = re.sub(r"<[^>]+>", " ", text or "")
    return " ".join(unescape(text).split())


def _extract_items_from_html(html_text: str, source_query: str) -> list[dict]:
    items = []
    seen_urls = set()
    anchor_pattern = re.compile(
        r"<a\b(?=[^>]*href=[\"'](?P<href>[^\"']*(?:/item/|/app/item/)[^\"']*)[\"'])[^>]*>(?P<body>.*?)</a>",
        flags=re.I | re.S,
    )
    price_pattern = re.compile(r"\d+(?:[,.]\d{1,2})?\s*(?:€|eur)", flags=re.I)
    for match in anchor_pattern.finditer(html_text or ""):
        url = normalize_wallapop_url(unescape(match.group("href")))
        if not url or url in seen_urls:
            continue
        seen_urls.add(url)
        text = _strip_html(match.group("body"))
        price_match = price_pattern.search(text)
        price = price_match.group(0) if price_match else ""
        if not price:
            continue
        title = text
        if price:
            title = " ".join(text.replace(price, " ").split())
        title = title[:140].strip()
        if not title:
            title = urlsplit(url).path.rsplit("/", 1)[-1].replace("-", " ")[:140].strip()
        items.append(
            {
                "title": title,
                "price": price,
                "url": url,
                "image_url": "",
                "location": "",
                "source_query": source_query,
            }
        )
        if len(items) >= WALLAPOP_VISIBLE_CARD_SCAN_LIMIT:
            break
    return items


def _extract_items_from_page_html(page, query: str) -> list[dict]:
    try:
        return _extract_items_from_html(page.content(), query)
    except Exception as exc:
        print(f"[WALLAPOP_HTML_FALLBACK_SKIPPED] level=warning query={query} error={_brief_error(exc)}", flush=True)
        return []


def _close_wallapop_page(page, query: str) -> None:
    if page is None:
        return
    try:
        page.close()
    except Exception as exc:
        print(f"[WALLAPOP_PAGE_CLOSE_SKIPPED] level=warning query={query} error={_brief_error(exc)}", flush=True)


def _brief_error(exc: Exception, limit: int = 180) -> str:
    message = str(exc).splitlines()[0].strip()
    return (message or exc.__class__.__name__)[:limit]


def _wait_for_wallapop_results(page, query: str) -> bool:
    try:
        page.wait_for_selector(WALLAPOP_RESULTS_SELECTOR, timeout=WALLAPOP_RESULTS_TIMEOUT_MS)
        return True
    except Exception as exc:
        print(
            f"[WALLAPOP_RESULTS_WAIT_SKIPPED] level=warning query={query} "
            f"timeout_ms={WALLAPOP_RESULTS_TIMEOUT_MS} reason=results_timeout error={_brief_error(exc)}",
            flush=True,
        )
        return False


def _read_wallapop_body_text(page, query: str) -> str:
    try:
        return str(page.evaluate("() => document.body ? document.body.innerText : ''") or "").lower()
    except Exception as exc:
        print(f"[WALLAPOP_TEXT_SKIPPED] level=warning query={query} error={_brief_error(exc)}", flush=True)
        return ""


def _playwright_browser_missing(exc: Exception) -> bool:
    message = str(exc).lower()
    return (
        "executable doesn't exist" in message
        or "browser executable" in message
        or "playwright install" in message
    )


def _auto_install_playwright_browser() -> bool:
    enabled = str(os.getenv("WALLAPOP_AUTO_INSTALL_PLAYWRIGHT", "true")).strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    if not enabled:
        print("[WALLAPOP_PLAYWRIGHT_INSTALL] status=disabled", flush=True)
        return False
    try:
        print("[WALLAPOP_PLAYWRIGHT_INSTALL] status=starting command=playwright_install_chromium", flush=True)
        result = subprocess.run(
            [sys.executable, "-m", "playwright", "install", "chromium"],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=180,
        )
        output_tail = (result.stdout or "")[-300:].replace("\n", " ")
        if result.returncode == 0:
            print("[WALLAPOP_PLAYWRIGHT_INSTALL] status=ok", flush=True)
            return True
        print(
            f"[WALLAPOP_PLAYWRIGHT_INSTALL] status=failed returncode={result.returncode} output={output_tail}",
            flush=True,
        )
    except Exception as exc:
        print(f"[WALLAPOP_PLAYWRIGHT_INSTALL] status=error error={exc}", flush=True)
    return False


def _launch_wallapop_browser(playwright, headless: bool):
    return playwright.chromium.launch(
        headless=headless,
        args=["--disable-dev-shm-usage", "--no-sandbox", "--disable-gpu"],
    )


def fetch_wallapop_listings(
    *,
    max_items: int | None = None,
    headless: bool | None = None,
    delay_min_seconds: float | None = None,
    delay_max_seconds: float | None = None,
    queries: Iterable[str] | None = None,
    seen_ids: set[str] | None = None,
    return_stats: bool = False,
):
    max_items = max_items if max_items is not None else wallapop_max_items()
    max_items = _safe_int(max_items, default=2, minimum=1)
    headless = headless if headless is not None else str(os.getenv("WALLAPOP_HEADLESS", "true")).strip().lower() not in {"0", "false", "no", "off"}
    delay_min_seconds = float(delay_min_seconds if delay_min_seconds is not None else os.getenv("WALLAPOP_DELAY_MIN_SECONDS", "2"))
    delay_max_seconds = float(delay_max_seconds if delay_max_seconds is not None else os.getenv("WALLAPOP_DELAY_MAX_SECONDS", "5"))
    if delay_max_seconds < delay_min_seconds:
        delay_max_seconds = delay_min_seconds
    selected_queries = list(queries or WALLAPOP_QUERIES)
    print(f"[WALLAPOP_RUN_START] max_items={max_items} queries={len(selected_queries)}", flush=True)
    stats = _new_wallapop_stats()

    try:
        from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
        from playwright.sync_api import sync_playwright
    except Exception as exc:
        print(f"[WALLAPOP_ERROR] reason=playwright_unavailable error={_brief_error(exc)}", flush=True)
        return ([], stats) if return_stats else []

    accepted: list[dict] = []
    try:
        with sync_playwright() as p:
            try:
                browser = _launch_wallapop_browser(p, headless)
            except Exception as launch_exc:
                if _playwright_browser_missing(launch_exc) and _auto_install_playwright_browser():
                    browser = _launch_wallapop_browser(p, headless)
                else:
                    raise
            context = browser.new_context(
                viewport={"width": 1280, "height": 720},
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122 Safari/537.36"
                ),
            )
            context.route("**/*", _route_light_resources)
            try:
                for query in selected_queries:
                    if len(accepted) >= max_items:
                        break
                    page = None
                    url = WALLAPOP_BASE_URL.format(query=quote_plus(query))
                    try:
                        page = context.new_page()
                        page.set_default_timeout(10000)
                        page.goto(url, wait_until="domcontentloaded", timeout=WALLAPOP_GOTO_TIMEOUT_MS)
                        page.wait_for_timeout(WALLAPOP_AFTER_GOTO_WAIT_MS)
                        results_ready = _wait_for_wallapop_results(page, query)
                        body_text = _read_wallapop_body_text(page, query)
                        if any(marker in body_text for marker in BLOCKED_TEXT_MARKERS):
                            if "too many requests" in body_text:
                                print(f"[WALLAPOP_RATE_LIMITED] query={query}", flush=True)
                            print(f"[WALLAPOP_BLOCKED_OR_CAPTCHA] query={query}", flush=True)
                            break
                        extracted = _extract_items_from_page(page, query) if results_ready else []
                        if not extracted:
                            fallback_items = _extract_items_from_page_html(page, query)
                            if fallback_items:
                                print(f"[WALLAPOP_HTML_FALLBACK] query={query} candidates={len(fallback_items)}", flush=True)
                            extracted = fallback_items
                        if not results_ready and not extracted:
                            stats["timeouts"] += 1
                            continue
                        accepted.extend(
                            filter_wallapop_candidates(
                                extracted,
                                seen_ids=set(seen_ids or set()) | {item["external_id"] for item in accepted},
                                max_items=max_items - len(accepted),
                                stats=stats,
                            )
                        )
                        if len(accepted) >= max_items:
                            break
                    except PlaywrightTimeoutError as exc:
                        stats["timeouts"] += 1
                        print(f"[WALLAPOP_QUERY_TIMEOUT] level=warning query={query} error={_brief_error(exc)}", flush=True)
                        continue
                    except Exception as exc:
                        stats["query_errors"] += 1
                        print(f"[WALLAPOP_QUERY_SKIPPED] level=warning query={query} error={_brief_error(exc)}", flush=True)
                        continue
                    finally:
                        _close_wallapop_page(page, query)
            finally:
                context.close()
                browser.close()
    except Exception as exc:
        print(f"[WALLAPOP_ERROR] reason=browser_failed error={_brief_error(exc)}", flush=True)
        return (accepted[:max_items], stats) if return_stats else accepted[:max_items]

    print(
        f"[WALLAPOP_RUN_DONE accepted={len(accepted)} rejected={stats['rejected']} "
        f"duplicates={stats['duplicates']} timeouts={stats['timeouts']} query_errors={stats['query_errors']}]",
        flush=True,
    )
    time.sleep(0)
    return (accepted[:max_items], stats) if return_stats else accepted[:max_items]
