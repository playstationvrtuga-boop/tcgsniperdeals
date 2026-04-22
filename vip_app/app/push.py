import json

from flask import current_app
from pywebpush import WebPushException, webpush

from services.alert_formatter import format_vip_alert
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


def _notification_body_for_deal(listing, result):
    title = (listing.title or "").strip()
    if len(title) > 72:
        title = f"{title[:69].rstrip()}..."

    price = (listing.price_display or "").strip()
    reference = f"{result.reference_price:.2f} EUR" if result.reference_price is not None else ""

    if price and reference:
        return f"Deal spotted: {title} - {price} vs {reference}"
    if price:
        return f"Deal spotted: {title} - {price}"
    return f"Deal spotted: {title}"


def _send_push_payload(payload):
    if not push_enabled():
        return {"sent": 0, "enabled": False}

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


def send_new_listing_push(listing):
    payload = {
        "title": "TCG Sniper Deals",
        "body": _notification_body_for_listing(listing),
        "url": f"/listings/{listing.id}",
        "tag": f"listing-{listing.id}",
    }
    return _send_push_payload(payload)


def send_deal_push(listing, result):
    payload_data = format_vip_alert(
        {
            "title": listing.title,
            "platform": listing.platform,
            "listing_price": result.listing_price,
            "listing_price_text": listing.price_display,
            "market_price": result.reference_price,
            "discount_percent": result.discount_percent,
            "potential_profit": result.gross_margin,
            "score": result.score,
            "detected_at": listing.detected_at,
            "direct_link": listing.external_url,
            "image_url": listing.image_url,
            "confidence": getattr(listing, "confidence_label", None),
        }
    )
    payload = {
        "title": payload_data["push_title"],
        "body": payload_data["push_body"],
        "url": f"/listings/{listing.id}",
        "tag": f"deal-{listing.id}",
    }
    return _send_push_payload(payload)
