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
from pathlib import Path
from typing import Iterable
from urllib.parse import quote_plus, urljoin, urlsplit

from core.normalizer import normalize_text
from services.pokemon_title_parser import extract_card_signals


WALLAPOP_SOURCE = "wallapop"
WALLAPOP_PLATFORM = "Wallapop"
WALLAPOP_QUERIES = [
    "pokemon",
    "cartas pokemon",
    "pokemon tcg",
]
WALLAPOP_BASE_URL = "https://pt.wallapop.com/colecionismo?keywords={query}"
WALLAPOP_RESULTS_SELECTOR = 'a[href*="/item/"]'
WALLAPOP_GOTO_TIMEOUT_MS = 20000
WALLAPOP_RESULTS_TIMEOUT_MS = 9000
WALLAPOP_AFTER_GOTO_WAIT_MS = 2000
WALLAPOP_VISIBLE_CARD_SCAN_LIMIT = 12
WALLAPOP_SEARCH_LINK_SCAN_LIMIT = 50
WALLAPOP_MEMORY_LIMIT_MB = 400
_PLAYWRIGHT_INSTALL_LOGGED = False
WALLAPOP_PLAYWRIGHT_INSTALL_FLAG = "/tmp/playwright_installed"

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
    return _safe_int(os.getenv("WALLAPOP_MAX_ITEMS_PER_RUN"), default=1, minimum=1)


def wallapop_max_queries_per_run() -> int:
    return _safe_int(os.getenv("WALLAPOP_MAX_QUERIES_PER_RUN"), default=2, minimum=1)


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
    signals = extract_card_signals(text)
    pokemon_name = signals.get("pokemon_name") if isinstance(signals, dict) else getattr(signals, "pokemon_name", None)
    if "pokemon" not in text and not pokemon_name:
        return False, "missing_pokemon"
    if any(term in text for term in POSITIVE_TCG_TERMS):
        return True, "tcg_terms"
    full_number = signals.get("full_number") if isinstance(signals, dict) else getattr(signals, "full_number", None)
    card_number = signals.get("card_number") if isinstance(signals, dict) else getattr(signals, "card_number", None)
    if full_number or card_number:
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
    return {"accepted": 0, "rejected": 0, "duplicates": 0, "timeouts": 0, "query_errors": 0, "memory_high": 0}


def wallapop_rss_mb() -> int:
    try:
        import psutil

        return int(psutil.Process(os.getpid()).memory_info().rss / (1024 * 1024))
    except Exception:
        pass
    try:
        import resource

        rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        if sys.platform == "darwin":
            return int(rss / (1024 * 1024))
        return int(rss / 1024)
    except Exception:
        return 0


def _log_wallapop_memory(stage: str) -> int:
    rss_mb = wallapop_rss_mb()
    print(f"[WALLAPOP_MEMORY] rss_mb={rss_mb} {stage}", flush=True)
    return rss_mb


def wallapop_memory_over_limit(limit_mb: int = WALLAPOP_MEMORY_LIMIT_MB) -> bool:
    rss_mb = wallapop_rss_mb()
    return bool(rss_mb and rss_mb > limit_mb)


def filter_wallapop_candidates(
    candidates: Iterable[dict],
    seen_ids: set[str] | None = None,
    max_items: int = 2,
    stats: dict[str, int] | None = None,
) -> list[dict]:
    accepted = []
    seen = set(seen_ids or set())
    local_seen = set()
    max_items = _safe_int(max_items, default=6, minimum=1)
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
    blocked_markers = (
        "analytics",
        "doubleclick",
        "googletagmanager",
        "google-analytics",
        "facebook",
        "segment",
        "hotjar",
        "optimizely",
        "adservice",
        "adsystem",
        "/ads",
        "tracking",
    )
    if resource_type in {"image", "media", "font"} or any(marker in url for marker in blocked_markers):
        route.abort()
    else:
        route.continue_()


def _extract_items_from_page(page, source_query: str) -> list[dict]:
    items = []
    anchors = page.query_selector_all('a[href*="/item/"]')
    for anchor in anchors[:30]:
        try:
            item = _extract_wallapop_item_from_anchor(anchor, source_query)
        except Exception:
            item = None
        if not item:
            continue
        items.append(item)
        if len(items) >= WALLAPOP_VISIBLE_CARD_SCAN_LIMIT:
            break
    return items


def _wallapop_required_title(title: str) -> bool:
    normalized = normalize_text(title or "")
    return any(term in normalized for term in ("pokemon", "carta", "cartas", "tcg", "booster", "etb"))


def _visible_text_from_element(element) -> str:
    try:
        return (element.inner_text() or "").strip()
    except Exception:
        return ""


def _wallapop_card_root(anchor):
    try:
        return anchor.query_selector(
            "xpath=ancestor::*[self::article or self::li or @data-testid or @data-item-id or @data-product-id or contains(@class, 'Card')][1]"
        ) or anchor
    except Exception:
        return anchor


def _wallapop_title_from_lines(lines: list[str], price: str) -> str:
    for line in lines:
        cleaned = " ".join(line.split()).strip()
        if not cleaned or cleaned == price or len(cleaned) <= 2:
            continue
        lowered = normalize_text(cleaned)
        if any(marker in lowered for marker in ("envio disponivel", "perfil top", "reservado", "destacado")):
            continue
        if _wallapop_required_title(cleaned):
            return cleaned
    for line in lines:
        cleaned = " ".join(line.split()).strip()
        if cleaned and cleaned != price and len(cleaned) > 2:
            return cleaned
    return ""


def _extract_wallapop_item_from_anchor(anchor, source_query: str) -> dict | None:
    href = anchor.get_attribute("href") or ""
    url = normalize_wallapop_url(href)
    if not url:
        return None
    root = _wallapop_card_root(anchor)
    text = _visible_text_from_element(root) or _visible_text_from_element(anchor)
    if not text:
        return None
    price = _wallapop_price_from_text(text)
    if not price:
        return None
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if len(lines) <= 1:
        lines = [part.strip() for part in re.split(r"\s{2,}", text) if part.strip()]
    title = _wallapop_title_from_lines(lines, price)
    if not title or not _wallapop_required_title(title):
        return None
    image_url = ""
    try:
        image = root.query_selector("img") or anchor.query_selector("img")
        if image:
            image_url = (image.get_attribute("currentSrc") or image.get_attribute("src") or "").strip()
    except Exception:
        image_url = ""
    print(f"[WALLAPOP_DOM_EXTRACT] title={title[:90]} price={price}", flush=True)
    return {
        "title": title,
        "price": price,
        "url": url,
        "image_url": image_url,
        "location": "",
        "source_query": source_query,
        "description": text[:1200],
    }


def _texto_card_wallapop_link(element) -> str:
    try:
        return _visible_text_from_element(_wallapop_card_root(element)).lower()
    except Exception:
        return ""


def _extract_wallapop_link_urls_from_html(html_text: str) -> list[str]:
    urls = []
    seen = set()
    pattern = re.compile(r'href=[\"\'](?P<href>[^\"\']*(?:/item/|/app/item/)[^\"\']*)[\"\']', flags=re.I)
    for match in pattern.finditer(html_text or ""):
        url = normalize_wallapop_url(unescape(match.group("href")))
        if not url or url in seen:
            continue
        seen.add(url)
        urls.append(url)
        if len(urls) >= WALLAPOP_SEARCH_LINK_SCAN_LIMIT:
            break
    return urls


def _extract_wallapop_link_urls_from_page_html(page, query: str) -> list[str]:
    try:
        return _extract_wallapop_link_urls_from_html(page.content())
    except Exception as exc:
        print(f"[WALLAPOP_HTML_LINK_FALLBACK_SKIPPED] level=warning query={query} error={_brief_error(exc)}", flush=True)
        return []


def _wallapop_link_id(url: str) -> str:
    return derive_wallapop_external_id(url)


def _obter_wallapop_links(
    context,
    queries: Iterable[str],
    seen_ids: set[str],
    max_items: int,
    stats: dict[str, int],
    delay_ms: int,
) -> list[dict]:
    candidates = []
    seen_links = set()
    seen_ids = set(seen_ids or set())
    for query in queries:
        if len(candidates) >= max_items:
            break
        search_url = WALLAPOP_BASE_URL.format(query=quote_plus(query))
        print(f"[WALLAPOP_CATEGORY_URL] url={search_url}", flush=True)
        page = None
        try:
            page = context.new_page()
            page.goto(search_url, timeout=WALLAPOP_GOTO_TIMEOUT_MS, wait_until="domcontentloaded")
            page.wait_for_timeout(delay_ms)
            results_ready = _wait_for_wallapop_results(page, query)
            dom_items = _extract_items_from_page(page, query) if results_ready else []
            print(f"[WALLAPOP_CANDIDATES] count={len(dom_items)} query={query}", flush=True)
            for item in dom_items:
                item_id = _wallapop_link_id(item["url"])
                print(
                    f"[WALLAPOP_CANDIDATE] title={item['title'][:90]} price={item['price']} url={item['url']}",
                    flush=True,
                )
                if item_id in seen_ids:
                    stats["duplicates"] += 1
                    stats["rejected"] += 1
                    print(f"[WALLAPOP_DUPLICATE] external_id={item_id} title={item['title'][:90]}", flush=True)
                    print(f"[WALLAPOP_REJECTED] reason=duplicate title={item['title'][:90]}", flush=True)
                    continue
                if item["url"] not in seen_links:
                    seen_links.add(item["url"])
                    item["external_id"] = item_id
                    candidates.append(item)
                else:
                    stats["duplicates"] += 1
                    stats["rejected"] += 1
                if len(candidates) >= max_items:
                    break
            if not dom_items:
                fallback_urls = _extract_wallapop_link_urls_from_page_html(page, query)
                if fallback_urls:
                    print(f"[WALLAPOP_HTML_FALLBACK] query={query} links={len(fallback_urls)}", flush=True)
                    print(f"[WALLAPOP_CANDIDATES] count={len(fallback_urls)} query={query} source=html", flush=True)
                for url in fallback_urls:
                    item_id = _wallapop_link_id(url)
                    if item_id in seen_ids:
                        stats["duplicates"] += 1
                        stats["rejected"] += 1
                        print(f"[WALLAPOP_DUPLICATE] external_id={item_id} url={url}", flush=True)
                        print(f"[WALLAPOP_REJECTED] reason=duplicate url={url}", flush=True)
                        continue
                    if url not in seen_links:
                        seen_links.add(url)
                        candidates.append({"url": url, "external_id": item_id})
                    if len(candidates) >= max_items:
                        break
                if not results_ready and not fallback_urls:
                    stats["timeouts"] += 1
        except Exception as exc:
            brief = _brief_error(exc)
            if "timeout" in brief.lower():
                stats["timeouts"] += 1
                print(f"[WALLAPOP_QUERY_TIMEOUT] level=warning query={query} error={brief}", flush=True)
            else:
                stats["query_errors"] += 1
                print(f"[WALLAPOP_QUERY_SKIPPED] level=warning query={query} error={brief}", flush=True)
            continue
        finally:
            _clear_wallapop_page(page)
            _close_wallapop_page(page, query)
        if wallapop_memory_over_limit():
            stats["memory_high"] = 1
            rss_mb = _log_wallapop_memory("query_memory_limit")
            print(f"[WALLAPOP_MEMORY_LIMIT] rss_mb={rss_mb} action=stop_queries", flush=True)
            break
    return candidates


def _get_meta_content(page, selector: str) -> str:
    try:
        element = page.query_selector(selector)
        if element:
            return (element.get_attribute("content") or "").strip()
    except Exception:
        pass
    return ""


def _wallapop_title_from_page(page) -> str:
    for selector in ("h1", '[data-testid*="title" i]'):
        try:
            element = page.query_selector(selector)
            if element:
                text = _visible_text_from_element(element)
                if text:
                    return text
        except Exception:
            pass
    title = _get_meta_content(page, 'meta[property="og:title"]')
    if title:
        return title
    try:
        return (page.title() or "").replace("| Wallapop", "").strip()
    except Exception:
        return ""


def _wallapop_price_from_text(text: str) -> str:
    match = re.search(r"\d+(?:[,.]\d{1,2})?\s*(?:€|eur)", text or "", flags=re.I)
    return match.group(0).strip() if match else ""


def _extrair_wallapop(page, link: str) -> dict | None:
    try:
        page.goto(link, timeout=WALLAPOP_GOTO_TIMEOUT_MS, wait_until="domcontentloaded")
        page.wait_for_timeout(1800)
        title = _wallapop_title_from_page(page)
        body_text = _read_wallapop_body_text(page, link)
        price = _wallapop_price_from_text(body_text)
        image_url = _get_meta_content(page, 'meta[property="og:image"]')
        if not title:
            return None
        return {
            "title": title,
            "price": price,
            "url": link,
            "image_url": image_url,
            "location": "",
            "source_query": link,
            "description": body_text[:1200],
        }
    except Exception as exc:
        print(f"[WALLAPOP_QUERY_SKIPPED] level=warning query=detail error={_brief_error(exc)}", flush=True)
        return None
    finally:
        _clear_wallapop_page(page)


def _close_wallapop_page(page, query: str) -> None:
    if page is None:
        return
    try:
        page.close()
    except Exception as exc:
        print(f"[WALLAPOP_PAGE_CLOSE_SKIPPED] level=warning query={query} error={_brief_error(exc)}", flush=True)


def _clear_wallapop_page(page) -> None:
    if page is None:
        return
    try:
        page.evaluate("() => { window.stop(); document.documentElement.innerHTML = ''; }")
    except Exception:
        pass
    try:
        page.goto("about:blank", timeout=5000, wait_until="load")
    except Exception:
        pass


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


def _playwright_install_flag_path() -> Path:
    return Path(os.getenv("WALLAPOP_PLAYWRIGHT_INSTALL_FLAG", WALLAPOP_PLAYWRIGHT_INSTALL_FLAG))


def _auto_install_playwright_browser() -> bool:
    global _PLAYWRIGHT_INSTALL_LOGGED
    flag_path = _playwright_install_flag_path()
    if flag_path.exists():
        print("[WALLAPOP_PLAYWRIGHT_INSTALL] status=skipped_cached", flush=True)
        return True
    enabled = str(os.getenv("WALLAPOP_AUTO_INSTALL_PLAYWRIGHT", "true")).strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    if not enabled:
        if not _PLAYWRIGHT_INSTALL_LOGGED:
            print("[WALLAPOP_PLAYWRIGHT_INSTALL] status=disabled", flush=True)
            _PLAYWRIGHT_INSTALL_LOGGED = True
        return False
    try:
        if not _PLAYWRIGHT_INSTALL_LOGGED:
            print("[WALLAPOP_PLAYWRIGHT_INSTALL] status=starting", flush=True)
            _PLAYWRIGHT_INSTALL_LOGGED = True
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
            try:
                flag_path.parent.mkdir(parents=True, exist_ok=True)
                flag_path.write_text(str(int(time.time())), encoding="utf-8")
            except Exception as flag_exc:
                print(f"[WALLAPOP_PLAYWRIGHT_INSTALL] status=cache_write_failed error={_brief_error(flag_exc)}", flush=True)
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
        args=[
            "--disable-dev-shm-usage",
            "--no-sandbox",
            "--disable-gpu",
            "--disable-software-rasterizer",
            "--disable-extensions",
            "--disable-default-apps",
            "--disable-background-networking",
            "--disable-background-timer-throttling",
            "--disable-renderer-backgrounding",
            "--disable-sync",
            "--disable-component-update",
            "--disable-features=Translate,BackForwardCache,AcceptCHFrame,MediaRouter,OptimizationHints",
            "--blink-settings=imagesEnabled=false",
            "--aggressive-cache-discard",
            "--disk-cache-size=1",
            "--media-cache-size=1",
            "--renderer-process-limit=1",
            "--metrics-recording-only",
            "--mute-audio",
            "--no-first-run",
            "--no-default-browser-check",
        ],
    )


def fetch_wallapop_listings_with_context(
    context,
    *,
    max_items: int | None = None,
    delay_min_seconds: float | None = None,
    delay_max_seconds: float | None = None,
    queries: Iterable[str] | None = None,
    seen_ids: set[str] | None = None,
    return_stats: bool = False,
):
    max_items = max_items if max_items is not None else wallapop_max_items()
    max_items = _safe_int(max_items, default=6, minimum=1)
    delay_min_seconds = float(delay_min_seconds if delay_min_seconds is not None else os.getenv("WALLAPOP_DELAY_MIN_SECONDS", "2"))
    delay_max_seconds = float(delay_max_seconds if delay_max_seconds is not None else os.getenv("WALLAPOP_DELAY_MAX_SECONDS", "5"))
    if delay_max_seconds < delay_min_seconds:
        delay_max_seconds = delay_min_seconds
    search_delay_ms = max(WALLAPOP_AFTER_GOTO_WAIT_MS, int(delay_min_seconds * 1000))
    selected_queries = list(queries or WALLAPOP_QUERIES)[:wallapop_max_queries_per_run()]
    print(f"[WALLAPOP_RUN_START] max_items={max_items} queries={len(selected_queries)} mode=existing_context", flush=True)
    stats = _new_wallapop_stats()
    before_rss = _log_wallapop_memory("before_run")
    if before_rss and before_rss > WALLAPOP_MEMORY_LIMIT_MB:
        stats["memory_high"] = 1
        print(f"[WALLAPOP_MEMORY_LIMIT] rss_mb={before_rss} action=skip_run", flush=True)
        _log_wallapop_memory("after_cleanup")
        return ([], stats) if return_stats else []

    accepted: list[dict] = []
    try:
        try:
            context.set_default_timeout(WALLAPOP_RESULTS_TIMEOUT_MS)
            context.set_default_navigation_timeout(WALLAPOP_GOTO_TIMEOUT_MS)
        except Exception as exc:
            print(f"[WALLAPOP_CONTEXT_TIMEOUT_SKIPPED] level=warning error={_brief_error(exc)}", flush=True)
        candidates = _obter_wallapop_links(
            context,
            selected_queries,
            seen_ids=set(seen_ids or set()),
            max_items=max_items,
            stats=stats,
            delay_ms=search_delay_ms,
        )
        current_seen_ids = set(seen_ids or set())
        for candidate in candidates:
            if len(accepted) >= max_items:
                break
            if wallapop_memory_over_limit():
                stats["memory_high"] = 1
                rss_mb = _log_wallapop_memory("detail_memory_limit")
                print(f"[WALLAPOP_MEMORY_LIMIT] rss_mb={rss_mb} action=stop_details", flush=True)
                break
            if candidate.get("title") and candidate.get("price"):
                item = candidate
            else:
                page_detalhe = None
                try:
                    page_detalhe = context.new_page()
                    item = _extrair_wallapop(page_detalhe, candidate["url"])
                finally:
                    _close_wallapop_page(page_detalhe, "detail")
            if not item:
                stats["rejected"] += 1
                continue
            new_items = filter_wallapop_candidates(
                [item],
                seen_ids=current_seen_ids | {existing["external_id"] for existing in accepted},
                max_items=max_items - len(accepted),
                stats=stats,
            )
            accepted.extend(new_items)
            for new_item in new_items:
                current_seen_ids.add(new_item["external_id"])
            if len(accepted) >= max_items:
                break
    except Exception as exc:
        print(f"[WALLAPOP_ERROR] reason=existing_context_failed error={_brief_error(exc)}", flush=True)
        _log_wallapop_memory("after_cleanup")
        return (accepted[:max_items], stats) if return_stats else accepted[:max_items]

    after_rss = _log_wallapop_memory("after_cleanup")
    if after_rss and after_rss > WALLAPOP_MEMORY_LIMIT_MB:
        stats["memory_high"] = 1
        print(f"[WALLAPOP_MEMORY_LIMIT] rss_mb={after_rss} action=cycle_done", flush=True)
    print(
        f"[WALLAPOP_RUN_DONE accepted={len(accepted)} rejected={stats['rejected']} "
        f"duplicates={stats['duplicates']} timeouts={stats['timeouts']} query_errors={stats['query_errors']}]",
        flush=True,
    )
    time.sleep(0)
    return (accepted[:max_items], stats) if return_stats else accepted[:max_items]


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
    max_items = _safe_int(max_items, default=6, minimum=1)
    headless = headless if headless is not None else str(os.getenv("WALLAPOP_HEADLESS", "true")).strip().lower() not in {"0", "false", "no", "off"}
    delay_min_seconds = float(delay_min_seconds if delay_min_seconds is not None else os.getenv("WALLAPOP_DELAY_MIN_SECONDS", "2"))
    delay_max_seconds = float(delay_max_seconds if delay_max_seconds is not None else os.getenv("WALLAPOP_DELAY_MAX_SECONDS", "5"))
    if delay_max_seconds < delay_min_seconds:
        delay_max_seconds = delay_min_seconds
    search_delay_ms = max(WALLAPOP_AFTER_GOTO_WAIT_MS, int(delay_min_seconds * 1000))
    selected_queries = list(queries or WALLAPOP_QUERIES)[:wallapop_max_queries_per_run()]
    print(f"[WALLAPOP_RUN_START] max_items={max_items} queries={len(selected_queries)}", flush=True)
    stats = _new_wallapop_stats()
    before_rss = _log_wallapop_memory("before_run")
    if before_rss and before_rss > WALLAPOP_MEMORY_LIMIT_MB:
        stats["memory_high"] = 1
        print(f"[WALLAPOP_MEMORY_LIMIT] rss_mb={before_rss} action=skip_run", flush=True)
        _log_wallapop_memory("after_cleanup")
        return ([], stats) if return_stats else []

    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:
        print(f"[WALLAPOP_ERROR] reason=playwright_unavailable error={_brief_error(exc)}", flush=True)
        return ([], stats) if return_stats else []

    accepted: list[dict] = []
    try:
        with sync_playwright() as p:
            browser = None
            context = None
            try:
                browser = _launch_wallapop_browser(p, headless)
            except Exception as launch_exc:
                if _playwright_browser_missing(launch_exc) and _auto_install_playwright_browser():
                    browser = _launch_wallapop_browser(p, headless)
                else:
                    raise
            try:
                context = browser.new_context(
                    viewport={"width": 1280, "height": 900},
                    locale="en-US",
                    color_scheme="light",
                    reduced_motion="reduce",
                    service_workers="block",
                    user_agent=(
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122 Safari/537.36"
                    ),
                )
                context.set_default_timeout(WALLAPOP_RESULTS_TIMEOUT_MS)
                context.set_default_navigation_timeout(WALLAPOP_GOTO_TIMEOUT_MS)
                context.route("**/*", _route_light_resources)
                candidates = _obter_wallapop_links(
                    context,
                    selected_queries,
                    seen_ids=set(seen_ids or set()),
                    max_items=max_items,
                    stats=stats,
                    delay_ms=search_delay_ms,
                )
                current_seen_ids = set(seen_ids or set())
                for candidate in candidates:
                    if len(accepted) >= max_items:
                        break
                    if wallapop_memory_over_limit():
                        stats["memory_high"] = 1
                        rss_mb = _log_wallapop_memory("detail_memory_limit")
                        print(f"[WALLAPOP_MEMORY_LIMIT] rss_mb={rss_mb} action=stop_details", flush=True)
                        break
                    if candidate.get("title") and candidate.get("price"):
                        item = candidate
                    else:
                        page_detalhe = None
                        try:
                            page_detalhe = context.new_page()
                            item = _extrair_wallapop(page_detalhe, candidate["url"])
                        finally:
                            _close_wallapop_page(page_detalhe, "detail")
                    if not item:
                        stats["rejected"] += 1
                        continue
                    new_items = filter_wallapop_candidates(
                        [item],
                        seen_ids=current_seen_ids | {existing["external_id"] for existing in accepted},
                        max_items=max_items - len(accepted),
                        stats=stats,
                    )
                    accepted.extend(new_items)
                    for new_item in new_items:
                        current_seen_ids.add(new_item["external_id"])
                    if len(accepted) >= max_items:
                        break
            finally:
                if context is not None:
                    try:
                        context.close()
                    except Exception as exc:
                        print(f"[WALLAPOP_CONTEXT_CLOSE_SKIPPED] level=warning error={_brief_error(exc)}", flush=True)
                if browser is not None:
                    try:
                        browser.close()
                    except Exception as exc:
                        print(f"[WALLAPOP_BROWSER_CLOSE_SKIPPED] level=warning error={_brief_error(exc)}", flush=True)
    except Exception as exc:
        print(f"[WALLAPOP_ERROR] reason=browser_failed error={_brief_error(exc)}", flush=True)
        _log_wallapop_memory("after_cleanup")
        return (accepted[:max_items], stats) if return_stats else accepted[:max_items]

    after_rss = _log_wallapop_memory("after_cleanup")
    if after_rss and after_rss > WALLAPOP_MEMORY_LIMIT_MB:
        stats["memory_high"] = 1
        print(f"[WALLAPOP_MEMORY_LIMIT] rss_mb={after_rss} action=cycle_done", flush=True)
    print(
        f"[WALLAPOP_RUN_DONE accepted={len(accepted)} rejected={stats['rejected']} "
        f"duplicates={stats['duplicates']} timeouts={stats['timeouts']} query_errors={stats['query_errors']}]",
        flush=True,
    )
    time.sleep(0)
    return (accepted[:max_items], stats) if return_stats else accepted[:max_items]
