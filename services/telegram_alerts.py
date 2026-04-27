from __future__ import annotations

import json

import requests

from config import FREE_CHAT_ID, TOKEN, VIP_CHAT_ID


def format_alert(listing, result) -> str:
    title = getattr(listing, "title", "Unknown listing")
    price_display = getattr(listing, "price_display", "n/a")
    fair_value = getattr(result, "estimated_fair_value", None) or result.reference_price
    fair_value_text = f"{fair_value:.2f}" if fair_value is not None else "n/a"
    buy_now_min = getattr(result, "market_buy_now_min", None)
    buy_now_median = getattr(result, "market_buy_now_median", None)
    if buy_now_min is not None and buy_now_median is not None:
        buy_now_range = f"{buy_now_min:.2f}-{buy_now_median:.2f}"
    elif buy_now_median is not None:
        buy_now_range = f"{buy_now_median:.2f}"
    else:
        buy_now_range = "n/a"
    last_2_sales = " / ".join(
        f"{price:.2f}" for price in (getattr(result, "last_2_sales", []) or [])[:2]
    ) or "n/a"
    discount = f"{result.discount_percent:.1f}" if result.discount_percent is not None else "n/a"
    margin = f"{result.gross_margin:.2f}" if result.gross_margin is not None else "n/a"
    confidence_score = getattr(result, "confidence_score", 0) or 0
    pricing_basis = getattr(result, "pricing_basis", None) or result.price_source or "unknown"
    url = getattr(listing, "external_url", "")

    return (
        "DEAL DETECTED\n\n"
        f"Product: {title}\n"
        f"Listing Price: {price_display}\n\n"
        f"Market / Buy Now: EUR {buy_now_range}\n"
        f"Last 2 Sales: EUR {last_2_sales}\n"
        f"Estimated Fair Value: EUR {fair_value_text}\n\n"
        f"Potential Profit: +EUR {margin} ({discount}%)\n"
        f"Confidence: {confidence_score}/100\n"
        f"Basis: {pricing_basis}\n\n"
        "Fast movers disappear quickly.\n\n"
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
