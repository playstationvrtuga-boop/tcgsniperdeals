from __future__ import annotations

import json

import requests

from config import FREE_CHAT_ID, TOKEN, VIP_CHAT_ID


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


def _build_inline_button(button_text: str, button_url: str) -> str:
    return json.dumps(
        {
            "inline_keyboard": [
                [
                    {
                        "text": button_text,
                        "url": button_url,
                    }
                ]
            ]
        },
        ensure_ascii=False,
    )


def send_message(
    message: str,
    chat_id: str,
    *,
    disable_preview: bool = False,
    button_text: str | None = None,
    button_url: str | None = None,
) -> bool:
    if not TOKEN or not chat_id:
        return False

    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": message,
        "disable_web_page_preview": disable_preview,
    }
    if button_text and button_url:
        payload["reply_markup"] = _build_inline_button(button_text, button_url)

    try:
        response = requests.post(
            url,
            data=payload,
            timeout=15,
        )
        data = response.json()
    except Exception:
        return False

    return bool(data.get("ok"))


def send_alert(message: str) -> bool:
    return send_message(message, VIP_CHAT_ID, disable_preview=False)


def send_free_alert(message: str, *, button_text: str | None = None, button_url: str | None = None) -> bool:
    return send_message(
        message,
        FREE_CHAT_ID,
        disable_preview=True,
        button_text=button_text,
        button_url=button_url,
    )
