import json

from flask import current_app
from pywebpush import WebPushException, webpush

from .extensions import db
from .models import PushSubscription, User


def push_enabled() -> bool:
    return bool(current_app.config.get("VAPID_PUBLIC_KEY") and current_app.config.get("VAPID_PRIVATE_KEY"))


def _notification_body_for_listing(listing):
    title = (listing.title or "").strip()
    if len(title) > 78:
        title = f"{title[:75].rstrip()}..."

    price = (listing.price_display or "").strip()
    platform = (listing.platform or "").strip()
    prefix = "New Pokemon deal"
    if platform:
        prefix = f"New {platform} deal"

    if price:
        return f"{prefix}: {title} - {price}"
    return f"{prefix}: {title}"


def send_new_listing_push(listing):
    if not push_enabled():
        return {"sent": 0, "enabled": False}

    payload = {
        "title": "TCG Sniper Deals",
        "body": _notification_body_for_listing(listing),
        "url": f"/listings/{listing.id}",
        "tag": f"listing-{listing.id}",
    }
    subscriptions = PushSubscription.query.join(User).all()
    sent = 0

    for subscription in subscriptions:
        if not (subscription.user and (subscription.user.is_admin or subscription.user.vip_active)):
            continue
        try:
            webpush(
                subscription_info={
                    "endpoint": subscription.endpoint,
                    "keys": {
                        "p256dh": subscription.p256dh,
                        "auth": subscription.auth,
                    },
                },
                data=json.dumps(payload),
                vapid_private_key=current_app.config["VAPID_PRIVATE_KEY"],
                vapid_claims={"sub": current_app.config["VAPID_SUBJECT"]},
            )
            sent += 1
        except WebPushException as error:
            current_app.logger.warning("Removing invalid push subscription %s after web push error: %s", subscription.id, error)
            db.session.delete(subscription)
        except Exception as error:
            current_app.logger.warning("Push delivery failed for subscription %s: %s", subscription.id, error)

    db.session.commit()
    return {"sent": sent, "enabled": True}
