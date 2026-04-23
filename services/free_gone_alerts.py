from __future__ import annotations

import json
import random
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Iterable

from sqlalchemy import func, or_

from config import (
    FREE_GONE_MAX_AGE_HOURS,
    FREE_GONE_MAX_PER_DAY,
    FREE_GONE_MIN_PER_DAY,
    FREE_GONE_PREFERRED_AGE_HOURS,
    FREE_GONE_WINDOWS,
)
from services.alert_formatter import format_free_gone_alert_text
from services.telegram_alerts import send_free_alert
from vip_app.app.extensions import db
from vip_app.app.models import FreeGoneAlertState, Listing


@dataclass(frozen=True)
class WindowSpec:
    key: str
    start_hour: int
    start_minute: int
    end_hour: int
    end_minute: int

    @property
    def label(self) -> str:
        return f"{self.start_hour:02d}:{self.start_minute:02d}-{self.end_hour:02d}:{self.end_minute:02d}"


def _now_local() -> datetime:
    return datetime.now().astimezone()


def _localize(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc).astimezone()
    return value.astimezone()


def _state_day(value: datetime | None = None) -> date:
    return _now_local().date() if value is None else _localize(value).date()


def parse_windows(value: str) -> list[WindowSpec]:
    windows: list[WindowSpec] = []
    for index, chunk in enumerate((value or "").split(","), start=1):
        part = chunk.strip()
        if not part or "-" not in part:
            continue
        start_text, end_text = [segment.strip() for segment in part.split("-", 1)]
        try:
            start_hour, start_minute = [int(component) for component in start_text.split(":", 1)]
            end_hour, end_minute = [int(component) for component in end_text.split(":", 1)]
        except Exception:
            continue
        windows.append(
            WindowSpec(
                key=f"window_{index}",
                start_hour=start_hour,
                start_minute=start_minute,
                end_hour=end_hour,
                end_minute=end_minute,
            )
        )
    return windows


def _window_bounds(day: date, window: WindowSpec) -> tuple[datetime, datetime]:
    start = datetime(day.year, day.month, day.day, window.start_hour, window.start_minute, tzinfo=_now_local().tzinfo)
    end = datetime(day.year, day.month, day.day, window.end_hour, window.end_minute, tzinfo=_now_local().tzinfo)
    if end <= start:
        end += timedelta(days=1)
    return start, end


def _random_time_within(start: datetime, end: datetime) -> datetime:
    total_seconds = max(int((end - start).total_seconds()), 1)
    lower = int(total_seconds * 0.15)
    upper = int(total_seconds * 0.85)
    if upper <= lower:
        upper = total_seconds
    offset = random.randint(lower, max(lower, upper))
    return start + timedelta(seconds=offset)


def _generate_window_schedule(day: date, window: WindowSpec, count: int) -> list[str]:
    if count <= 0:
        return []

    start, end = _window_bounds(day, window)
    total_seconds = max(int((end - start).total_seconds()), 1)
    slot_seconds = max(total_seconds // count, 1)
    schedule: list[str] = []

    for index in range(count):
        slot_start = start + timedelta(seconds=slot_seconds * index)
        slot_end = end if index == count - 1 else start + timedelta(seconds=slot_seconds * (index + 1))
        moment = _random_time_within(slot_start, slot_end)
        schedule.append(moment.isoformat(timespec="seconds"))

    schedule.sort()
    return schedule


def _normalize_counts(plan: dict[str, int], total: int, windows: list[WindowSpec]) -> dict[str, int]:
    counts = {window.key: 0 for window in windows}
    if total <= 0 or not windows:
        return counts

    ordered_windows = windows[:]
    random.shuffle(ordered_windows)

    base = min(total, len(ordered_windows))
    for index in range(base):
        counts[ordered_windows[index].key] += 1

    remaining = total - base
    keys = [window.key for window in windows]
    while remaining > 0 and keys:
        counts[random.choice(keys)] += 1
        remaining -= 1

    return counts


def build_daily_plan(day: date, windows: list[WindowSpec]) -> dict:
    min_per_day = min(FREE_GONE_MIN_PER_DAY, FREE_GONE_MAX_PER_DAY)
    max_per_day = max(FREE_GONE_MIN_PER_DAY, FREE_GONE_MAX_PER_DAY)
    if max_per_day <= 0:
        target = 0
    elif max_per_day == min_per_day:
        target = max(0, min_per_day)
    else:
        target = random.randint(max(0, min_per_day), max_per_day)

    counts = _normalize_counts({}, target, windows)
    schedule = {
        window.key: _generate_window_schedule(day, window, counts.get(window.key, 0))
        for window in windows
    }
    window_posted = {window.key: 0 for window in windows}
    next_post_at = None
    for items in schedule.values():
        if items:
            moment = items[0]
            if next_post_at is None or moment < next_post_at:
                next_post_at = moment

    return {
        "state_date": day.isoformat(),
        "daily_target_count": target,
        "daily_posted_count": 0,
        "window_plan": counts,
        "window_posted": window_posted,
        "window_schedule": schedule,
        "used_listing_ids": [],
        "next_post_at": next_post_at,
    }


def _json_load(value: str | None, default):
    if not value:
        return default
    try:
        parsed = json.loads(value)
        return parsed if parsed is not None else default
    except Exception:
        return default


def get_or_create_state(day: date | None = None) -> FreeGoneAlertState:
    current_day = day or _state_day()
    state = FreeGoneAlertState.query.filter_by(state_date=current_day).first()
    if state:
        return state

    windows = parse_windows(FREE_GONE_WINDOWS)
    plan = build_daily_plan(current_day, windows)
    state = FreeGoneAlertState(
        state_date=current_day,
        daily_target_count=plan["daily_target_count"],
        daily_posted_count=plan["daily_posted_count"],
        next_post_at=datetime.fromisoformat(plan["next_post_at"]) if plan["next_post_at"] else None,
    )
    state.set_window_plan(plan["window_plan"])
    state.set_window_posted(plan["window_posted"])
    state.set_window_schedule(plan["window_schedule"])
    state.set_used_listing_ids(plan["used_listing_ids"])
    db.session.add(state)
    db.session.commit()
    return state


def _is_pokemon_tcg_clause():
    tcg_type = func.lower(func.coalesce(Listing.tcg_type, ""))
    title = func.lower(func.coalesce(Listing.title, ""))
    return or_(
        tcg_type.in_(["pokemon", "pokemon_tcg", "tcg"]),
        title.like("%pokemon%"),
        title.like("%tcg%"),
    )


def _age_clause(cutoff: datetime):
    return or_(Listing.updated_at >= cutoff, Listing.detected_at >= cutoff)


def _candidate_query(cutoff: datetime, used_listing_ids: Iterable[int]):
    status_value = func.lower(func.coalesce(Listing.available_status, ""))
    query = (
        Listing.query.filter(
            _is_pokemon_tcg_clause(),
            status_value.in_(["unavailable", "removed", "sold"]),
            ~Listing.id.in_(list(used_listing_ids) or [-1]),
            _age_clause(cutoff),
        )
        .order_by(
            Listing.updated_at.desc(),
            func.coalesce(Listing.score, -1).desc(),
            func.coalesce(Listing.gross_margin, -1).desc(),
            Listing.detected_at.desc(),
            Listing.id.desc(),
        )
        .limit(50)
    )
    return query


def find_next_gone_candidate(state: FreeGoneAlertState, now: datetime | None = None) -> Listing | None:
    current = _localize(now or _now_local())
    used_ids = state.used_listing_ids()

    preferred_cutoff = current - timedelta(hours=FREE_GONE_PREFERRED_AGE_HOURS)
    max_cutoff = current - timedelta(hours=FREE_GONE_MAX_AGE_HOURS)

    candidate = _candidate_query(preferred_cutoff, used_ids).first()
    if candidate:
        return candidate

    if FREE_GONE_MAX_AGE_HOURS > FREE_GONE_PREFERRED_AGE_HOURS:
        return _candidate_query(max_cutoff, used_ids).first()

    return None


def _active_window_for_now(windows: list[WindowSpec], now: datetime) -> WindowSpec | None:
    current = _localize(now)
    for window in windows:
        start, end = _window_bounds(current.date(), window)
        if start <= current <= end:
            return window
    return None


def next_due_window_slot(state: FreeGoneAlertState, now: datetime | None = None) -> tuple[WindowSpec | None, datetime | None]:
    current = _localize(now or _now_local())
    windows = parse_windows(FREE_GONE_WINDOWS)
    active_window = _active_window_for_now(windows, current)
    if not active_window:
        return None, None

    schedule = _json_load(state.window_schedule_json, {})
    posted = _json_load(state.window_posted_json, {})
    planned = _json_load(state.window_plan_json, {})
    window_slots = schedule.get(active_window.key) or []
    current_posted = int(posted.get(active_window.key, 0))
    planned_count = int(planned.get(active_window.key, 0))
    if current_posted >= planned_count:
        return None, None

    try:
        next_slot = datetime.fromisoformat(window_slots[current_posted])
    except Exception:
        return active_window, current

    return active_window, next_slot


def record_gone_alert_post(state: FreeGoneAlertState, listing: Listing, *, sent_at: datetime | None = None) -> None:
    current = _localize(sent_at or _now_local())
    used_ids = set(state.used_listing_ids())
    used_ids.add(int(listing.id))
    state.set_used_listing_ids(sorted(used_ids))

    plan = _json_load(state.window_plan_json, {})
    posted = _json_load(state.window_posted_json, {})
    schedule = _json_load(state.window_schedule_json, {})
    active_window = _active_window_for_now(parse_windows(FREE_GONE_WINDOWS), current)
    if active_window:
        posted[active_window.key] = int(posted.get(active_window.key, 0)) + 1
        state.set_window_posted(posted)
        schedule_for_window = schedule.get(active_window.key) or []
        if posted[active_window.key] < int(plan.get(active_window.key, 0)) and len(schedule_for_window) > posted[active_window.key]:
            state.next_post_at = datetime.fromisoformat(schedule_for_window[posted[active_window.key]])
        else:
            next_candidates = []
            for window_key, slot_times in schedule.items():
                if int(posted.get(window_key, 0)) < int(plan.get(window_key, 0)):
                    slot_index = int(posted.get(window_key, 0))
                    if len(slot_times) > slot_index:
                        next_candidates.append(datetime.fromisoformat(slot_times[slot_index]))
            state.next_post_at = min(next_candidates) if next_candidates else None

    state.daily_posted_count = int(state.daily_posted_count or 0) + 1
    state.last_posted_at = current
    db.session.commit()


def format_gone_alert_payload(listing: Listing) -> dict:
    return {
        "listing_id": listing.id,
        "title": listing.title,
        "full_name": listing.title,
        "platform": listing.platform,
        "listing_price": listing.price_display,
        "listing_price_text": listing.price_display,
        "detected_at": listing.detected_at,
        "updated_at": listing.updated_at,
        "partial_title": listing.partial_title,
        "score": listing.score or listing.pricing_score or 0,
    }


def post_gone_alert(listing: Listing, *, variant: int = 0) -> bool:
    message = format_free_gone_alert_text(format_gone_alert_payload(listing), variant=variant)
    return send_free_alert(message)
