from __future__ import annotations

import json
import random
import threading
import time
from pathlib import Path

import requests

from config import (
    APP_PUBLIC_URL,
    FREE_CHAT_ID,
    FREE_PROMO_ENABLED,
    FREE_PROMO_FOLDER,
    FREE_PROMO_INTERVAL_MINUTES,
    TOKEN,
)
from services.app_links import app_live_deals_url


BASE_DIR = Path(__file__).resolve().parent.parent
STATE_FILE = BASE_DIR / "free_promo_state.json"
SUPPORTED_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}
_STATE_LOCK = threading.Lock()
_SCHEDULER_LOCK = threading.Lock()
_SCHEDULER_STARTED = False

PROMO_CAPTIONS = [
    "The best deals disappear fast. Stay ahead.",
    "Real-time deals. Better timing. Better chances.",
    "Missed one? Don’t miss the next.",
    "Live opportunities, updated fast.",
    "Good deals don’t wait. Neither should you.",
]

PROMO_BUTTON_TEXTS = [
    "Buy Now",
    "Open App",
    "Get Access",
    "View Deals",
    "Start Now",
    "Join Now",
]


def _default_state() -> dict:
    return {
        "last_image": "",
        "last_sent_at": "",
        "sent_count": 0,
    }


def _read_state() -> dict:
    if not STATE_FILE.exists():
        return _default_state()

    try:
        data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return _default_state()
    except Exception:
        return _default_state()

    state = _default_state()
    state.update({k: data.get(k, state[k]) for k in state})
    return state


def _write_state(state: dict) -> None:
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def _promo_directories() -> list[Path]:
    candidates: list[Path] = []

    configured = str(FREE_PROMO_FOLDER or "").strip()
    if configured:
        candidates.append(Path(configured))

    candidates.extend(
        [
            BASE_DIR / "vip_app" / "app" / "static" / "promos",
            BASE_DIR / "static" / "promos",
            BASE_DIR / "assets" / "promos",
        ]
    )

    seen = set()
    unique_candidates: list[Path] = []
    for path in candidates:
        resolved = path.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        unique_candidates.append(path)
    return unique_candidates


def _load_promo_images() -> list[Path]:
    for directory in _promo_directories():
        if not directory.exists() or not directory.is_dir():
            continue
        images = [
            path
            for path in sorted(directory.iterdir())
            if path.is_file() and path.suffix.lower() in SUPPORTED_EXTENSIONS
        ]
        if images:
            return images
    return []


def _pick_caption() -> str:
    return random.choice(PROMO_CAPTIONS)


def _pick_button_text() -> str:
    return random.choice(PROMO_BUTTON_TEXTS)


def _pick_image(images: list[Path]) -> Path | None:
    if not images:
        return None

    with _STATE_LOCK:
        state = _read_state()
        last_image = str(state.get("last_image") or "")

    available = [image for image in images if str(image) != last_image]
    pool = available or images
    return random.choice(pool)


def _build_reply_markup(button_text: str, app_url: str) -> str:
    return json.dumps(
        {
            "inline_keyboard": [
                [
                    {
                        "text": button_text,
                        "url": app_url,
                    }
                ]
            ]
        },
        ensure_ascii=False,
    )


def _send_photo_with_button(image_path: Path, caption: str, button_text: str, app_url: str, chat_id: str) -> bool:
    if not TOKEN:
        print("[free_promo] missing Telegram token")
        return False

    url = f"https://api.telegram.org/bot{TOKEN}/sendPhoto"
    payload = {
        "chat_id": chat_id,
        "caption": caption,
        "reply_markup": _build_reply_markup(button_text, app_url),
    }

    try:
        with image_path.open("rb") as image_file:
            response = requests.post(
                url,
                data=payload,
                files={"photo": image_file},
                timeout=60,
            )
        data = response.json()
        if not data.get("ok"):
            print(
                f"[free_promo] telegram rejected photo image={image_path.name} "
                f"error={data.get('description')}"
            )
            return False
        return True
    except Exception as exc:
        print(f"[free_promo] photo send failed image={image_path.name} error={exc}")
        return False


def _send_message_with_button(caption: str, button_text: str, app_url: str, chat_id: str) -> bool:
    if not TOKEN:
        print("[free_promo] missing Telegram token")
        return False

    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": caption,
        "reply_markup": _build_reply_markup(button_text, app_url),
    }

    try:
        response = requests.post(url, data=payload, timeout=20)
        data = response.json()
        if not data.get("ok"):
            print(f"[free_promo] telegram rejected text fallback error={data.get('description')}")
            return False
        return True
    except Exception as exc:
        print(f"[free_promo] text fallback failed error={exc}")
        return False


def send_random_free_promo(chat_id: str | None = None, app_url: str | None = None) -> bool:
    if not FREE_PROMO_ENABLED:
        print("[free_promo] disabled - skipping")
        return False

    target_chat_id = str(chat_id or FREE_CHAT_ID or "").strip()
    target_app_url = app_live_deals_url(app_url or APP_PUBLIC_URL)

    if not target_chat_id:
        print("[free_promo] missing FREE_CHAT_ID")
        return False
    if not target_app_url:
        print("[free_promo] missing APP_PUBLIC_URL")
        return False
    if not TOKEN:
        print("[free_promo] missing Telegram token")
        return False

    images = _load_promo_images()
    if not images:
        print(f"[free_promo] no promo images found under {FREE_PROMO_FOLDER}")
        return False

    image_path = _pick_image(images)
    if image_path is None:
        print("[free_promo] no image selected")
        return False

    caption = _pick_caption()
    button_text = _pick_button_text()

    sent = _send_photo_with_button(image_path, caption, button_text, target_app_url, target_chat_id)
    if not sent:
        sent = _send_message_with_button(caption, button_text, target_app_url, target_chat_id)

    if sent:
        with _STATE_LOCK:
            state = _read_state()
            state["last_image"] = str(image_path)
            state["last_sent_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
            state["sent_count"] = int(state.get("sent_count", 0) or 0) + 1
            _write_state(state)
        print(
            f"[free_promo] sent image={image_path.name} "
            f"caption={caption!r} button={button_text!r}"
        )
        return True

    print(f"[free_promo] failed image={image_path.name}")
    return False


def schedule_free_promos_every_hour() -> bool:
    global _SCHEDULER_STARTED

    if not FREE_PROMO_ENABLED:
        print("[free_promo] scheduler disabled")
        return False

    with _SCHEDULER_LOCK:
        if _SCHEDULER_STARTED:
            return False
        _SCHEDULER_STARTED = True

    def _worker() -> None:
        interval_minutes = max(int(FREE_PROMO_INTERVAL_MINUTES or 60), 1)
        sleep_seconds = interval_minutes * 60
        print(f"[free_promo] scheduler started interval={interval_minutes}m")

        while True:
            time.sleep(sleep_seconds)
            try:
                send_random_free_promo()
            except Exception as exc:
                print(f"[free_promo] scheduler error={exc}")

    thread = threading.Thread(target=_worker, name="free-promo-scheduler", daemon=True)
    thread.start()
    return True


def send_test_promo() -> bool:
    return send_random_free_promo()
