from __future__ import annotations

import requests

from config import TOKEN, VIP_CHAT_ID


def format_alert(listing, result) -> str:
    title = getattr(listing, "title", "Unknown listing")
    price_display = getattr(listing, "price_display", "n/a")
    reference_price = f"{result.reference_price:.2f}" if result.reference_price is not None else "n/a"
    discount = f"{result.discount_percent:.1f}" if result.discount_percent is not None else "n/a"
    margin = f"{result.gross_margin:.2f}" if result.gross_margin is not None else "n/a"
    url = getattr(listing, "external_url", "")
    last_three = ", ".join(f"{price:.2f}€" for price in (result.comparable_prices or [])[:3]) or "n/a"

    return (
        "POSSIBLE DEAL DETECTED\n\n"
        f"Product: {title}\n"
        f"Listing price: {price_display}\n"
        f"Last 3 sales: {last_three}\n"
        f"Market reference: {reference_price} EUR\n"
        f"Discount: {discount}%\n"
        f"Potential profit: {margin} EUR\n"
        f"Score: {result.score}/100\n"
        f"Link: {url}"
    )


def send_alert(message: str) -> bool:
    if not TOKEN or not VIP_CHAT_ID:
        return False

    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    try:
        response = requests.post(
            url,
            data={"chat_id": VIP_CHAT_ID, "text": message, "disable_web_page_preview": False},
            timeout=15,
        )
        data = response.json()
    except Exception:
        return False

    return bool(data.get("ok"))
