from datetime import datetime, timezone


def _coerce_datetime(value):
    if not value:
        return None

    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value)
        except ValueError:
            return None

    if not isinstance(value, datetime):
        return None

    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)

    return value.astimezone()


def datetime_format(value, fmt="%d %b %Y %H:%M"):
    dt = _coerce_datetime(value)
    if not dt:
        return "unknown"
    return dt.strftime(fmt)


def relative_time(value):
    dt = _coerce_datetime(value)
    if not dt:
        return "unknown"

    now = datetime.now().astimezone()
    delta = now - dt
    seconds = max(int(delta.total_seconds()), 0)

    if seconds < 60:
        return "just now"

    minutes = seconds // 60
    if minutes < 60:
        return "1 min ago" if minutes == 1 else f"{minutes} min ago"

    hours = minutes // 60
    if hours < 24:
        return "1 hour ago" if hours == 1 else f"{hours} hours ago"

    days = hours // 24
    if days == 1:
        return "yesterday"

    return f"{days} days ago"


def urgency_hint(value):
    dt = _coerce_datetime(value)
    if not dt:
        return "recently"

    now = datetime.now().astimezone()
    minutes = max(int((now - dt).total_seconds() // 60), 0)

    if minutes <= 1:
        return "Just added"
    if minutes <= 10:
        return "Likely to move fast"
    if minutes <= 30:
        return "Fresh on the board"
    if minutes <= 60:
        return "Still early"
    if minutes <= 24 * 60:
        return "Watching the market"
    return "Recently tracked"


def register_template_filters(app):
    filters = {
        "datetime_format": datetime_format,
        "relative_time": relative_time,
        "urgency_hint": urgency_hint,
    }
    app.jinja_env.filters.update(filters)

    for name, func in filters.items():
        app.add_template_filter(func, name)
