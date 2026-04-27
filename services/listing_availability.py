from __future__ import annotations

from dataclasses import dataclass

import requests


MAX_RESPONSE_BYTES = 250_000
DEFAULT_TIMEOUT_SECONDS = 8

GONE_TEXT_MARKERS = {
    "vinted": [
        "this item is no longer available",
        "item is no longer available",
        "item sold",
        "sold",
        "vendido",
        "vendida",
        "reservado",
        "reservada",
        "reserved",
        "indisponivel",
        "indisponible",
        "indisponível",
        "article vendu",
        "vendu",
        "annonce supprim",
        "supprimé",
        "supprime",
        "not found",
    ],
    "ebay": [
        "this listing was ended",
        "listing was ended",
        "this item is no longer available",
        "item is no longer available",
        "this item is out of stock",
        "out of stock",
        "ended",
        "was sold",
        "sold",
        "no longer available",
    ],
}


@dataclass(frozen=True)
class AvailabilityResult:
    status: str
    is_gone: bool
    reason: str
    http_status: int | None = None


def _platform_key(platform: str | None, url: str | None) -> str:
    value = f"{platform or ''} {url or ''}".lower()
    if "vinted" in value:
        return "vinted"
    if "ebay" in value:
        return "ebay"
    return "generic"


def _read_limited_response(response: requests.Response) -> str:
    chunks: list[bytes] = []
    total = 0
    for chunk in response.iter_content(chunk_size=16384):
        if not chunk:
            continue
        remaining = MAX_RESPONSE_BYTES - total
        chunks.append(chunk[:remaining])
        total += min(len(chunk), remaining)
        if total >= MAX_RESPONSE_BYTES:
            break
    return b"".join(chunks).decode(response.encoding or "utf-8", errors="ignore").lower()


def check_listing_availability(
    url: str | None,
    *,
    platform: str | None = None,
    session: requests.Session | None = None,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> AvailabilityResult:
    if not url:
        return AvailabilityResult(status="unknown", is_gone=False, reason="missing_url")

    client = session or requests.Session()
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9,pt;q=0.8,fr;q=0.7,es;q=0.7",
    }

    try:
        response = client.get(url, headers=headers, timeout=timeout, stream=True, allow_redirects=True)
    except requests.Timeout:
        return AvailabilityResult(status="unknown", is_gone=False, reason="timeout")
    except requests.RequestException as exc:
        return AvailabilityResult(status="unknown", is_gone=False, reason=f"request_error:{type(exc).__name__}")

    status_code = response.status_code
    if status_code in {404, 410}:
        return AvailabilityResult(status="removed", is_gone=True, reason=f"http_{status_code}", http_status=status_code)
    if status_code in {401, 403, 429}:
        return AvailabilityResult(status="unknown", is_gone=False, reason=f"http_{status_code}", http_status=status_code)
    if status_code >= 500:
        return AvailabilityResult(status="unknown", is_gone=False, reason=f"http_{status_code}", http_status=status_code)

    body = _read_limited_response(response)
    platform_key = _platform_key(platform, url)
    markers = GONE_TEXT_MARKERS.get(platform_key, [])
    markers += GONE_TEXT_MARKERS["vinted"] if platform_key == "generic" else []
    markers += GONE_TEXT_MARKERS["ebay"] if platform_key == "generic" else []

    for marker in markers:
        if marker in body:
            status = "sold" if "sold" in marker or "vend" in marker or "item sold" in body else "unavailable"
            return AvailabilityResult(status=status, is_gone=True, reason=f"text_marker:{marker}", http_status=status_code)

    if status_code == 200:
        return AvailabilityResult(status="available", is_gone=False, reason="http_200_no_gone_marker", http_status=status_code)

    return AvailabilityResult(status="unknown", is_gone=False, reason=f"http_{status_code}", http_status=status_code)
