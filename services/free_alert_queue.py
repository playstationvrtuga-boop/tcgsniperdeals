from __future__ import annotations

import json
import os
import random
from datetime import datetime, timedelta
from pathlib import Path

from config import FREE_ALERT_DELAY_MAX_MINUTES, FREE_ALERT_DELAY_MIN_MINUTES, FREE_ALERT_DELAY_MINUTES


QUEUE_PATH = Path(__file__).resolve().parent.parent / "free_queue.json"


def _now():
    return datetime.now().astimezone()


def _read_queue():
    if not QUEUE_PATH.exists():
        return []
    try:
        with QUEUE_PATH.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _write_queue(items):
    QUEUE_PATH.parent.mkdir(parents=True, exist_ok=True)
    temp_path = QUEUE_PATH.with_suffix(".tmp")
    with temp_path.open("w", encoding="utf-8") as handle:
        json.dump(items, handle, ensure_ascii=False, indent=2)
    os.replace(temp_path, QUEUE_PATH)


def enqueue_free_alert(alert_payload: dict, delay_minutes: int | None = None) -> str:
    queue = _read_queue()
    listing_id = alert_payload.get("listing_id")
    if listing_id and any(item.get("listing_id") == listing_id for item in queue):
        existing = next(item for item in queue if item.get("listing_id") == listing_id)
        return existing.get("eligible_at")

    if delay_minutes is not None:
        delay = int(delay_minutes)
    else:
        delay_min = min(FREE_ALERT_DELAY_MIN_MINUTES, FREE_ALERT_DELAY_MAX_MINUTES)
        delay_max = max(FREE_ALERT_DELAY_MIN_MINUTES, FREE_ALERT_DELAY_MAX_MINUTES)
        delay = random.randint(delay_min, delay_max) if delay_max > delay_min else delay_min
        if delay <= 0:
            delay = max(FREE_ALERT_DELAY_MINUTES, 1)
    eligible_at = (_now() + timedelta(minutes=delay)).isoformat(timespec="seconds")
    queue.append(
        {
            "type": "deal_alert",
            "listing_id": listing_id,
            "eligible_at": eligible_at,
            "detected_at": alert_payload.get("detected_at"),
            "anuncio": {
                "id": f"deal_{listing_id}" if listing_id is not None else None,
                "source": alert_payload.get("platform", "app"),
                "tcg_type": alert_payload.get("tcg_type", "pokemon"),
                "free_message_text": alert_payload.get("free_message_text", ""),
                "imagem": None,
                "titulo": alert_payload.get("partial_title") or "Deal teaser",
                "preco": alert_payload.get("listing_price_text") or "",
            },
        }
    )
    queue.sort(key=lambda item: (item.get("eligible_at") or "", item.get("listing_id") or 0))
    _write_queue(queue)
    return eligible_at
