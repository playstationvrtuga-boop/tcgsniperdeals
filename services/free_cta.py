from __future__ import annotations

import json
import random
from pathlib import Path
from threading import Lock

from config import FREE_CTA_APP_LINK, FREE_CTA_EVERY_N_POSTS


BASE_DIR = Path(__file__).resolve().parent.parent
STATE_FILE = BASE_DIR / "free_cta_state.json"
_STATE_LOCK = Lock()

CTA_VARIANTS = [
    "⚡ Real-time deals — before they disappear:\n[APP LINK]",
    "⚡ See deals the moment they go live:\n[APP LINK]",
    "⚡ Most deals are gone within minutes.\nGet them in real time:\n[APP LINK]",
    "⚡ Full live stream available in the app:\n[APP LINK]",
    "⚡ Faster alerts. Better deals. Real time:\n[APP LINK]",
]


def _default_state() -> dict:
    return {"sent_count": 0}


def _read_state() -> dict:
    if not STATE_FILE.exists():
        return _default_state()

    try:
        data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return _default_state()
    except Exception:
        return _default_state()

    data.setdefault("sent_count", 0)
    return data


def _write_state(state: dict) -> None:
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def get_free_cta_sent_count() -> int:
    with _STATE_LOCK:
        return int(_read_state().get("sent_count", 0) or 0)


def should_attach_free_cta(next_post_index: int | None = None) -> bool:
    if not FREE_CTA_APP_LINK:
        return False

    every_n = max(int(FREE_CTA_EVERY_N_POSTS or 20), 1)
    current_count = get_free_cta_sent_count()
    candidate_index = next_post_index if next_post_index is not None else current_count + 1
    return candidate_index % every_n == 0


def build_free_cta_block() -> str:
    if not FREE_CTA_APP_LINK:
        return ""

    return random.choice(CTA_VARIANTS).replace("[APP LINK]", FREE_CTA_APP_LINK)


def record_free_cta_sent() -> int:
    with _STATE_LOCK:
        state = _read_state()
        state["sent_count"] = int(state.get("sent_count", 0) or 0) + 1
        _write_state(state)
        return state["sent_count"]
