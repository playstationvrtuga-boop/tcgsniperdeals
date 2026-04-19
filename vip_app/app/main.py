from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from flask import Blueprint, Response, current_app, flash, jsonify, redirect, render_template, request, send_file, send_from_directory, url_for
from flask_login import current_user, login_required

from .decorators import vip_required
from .extensions import db
from .models import Favorite, Listing, Payment, PushSubscription
from .push import push_enabled


main_bp = Blueprint("main", __name__)


BILLING_PLANS = {
    "monthly": {
        "name": "Monthly",
        "price": "3.90\u20ac",
        "amount": Decimal("3.90"),
        "label": "Flexible access",
        "description": "Stay in the live stream with a flexible monthly plan.",
        "tag": "",
        "highlight": False,
    },
    "yearly": {
        "name": "Yearly",
        "price": "39.90\u20ac",
        "amount": Decimal("39.90"),
        "label": "Best value",
        "description": "The strongest value for buyers who want a full-year edge.",
        "tag": "Most popular",
        "highlight": True,
    },
    "lifetime": {
        "name": "Lifetime",
        "price": "79.90\u20ac",
        "amount": Decimal("79.90"),
        "label": "Locked-in access",
        "description": "A limited one-time unlock for long-term access without renewals.",
        "tag": "Limited",
        "highlight": False,
    },
}


BILLING_METHODS = [
    {
        "key": "revolut",
        "name": "Revolut",
        "description": "Fast payment with no fees.",
        "recommended": True,
        "links": {
            "monthly": "https://revolut.me/srgiojoeq",
            "yearly": "https://revolut.me/srgiojoeq",
            "lifetime": "https://revolut.me/srgiojoeq",
        },
    },
    {
        "key": "paypal",
        "name": "PayPal",
        "description": "Fast checkout with buyer-friendly familiarity.",
        "recommended": False,
        "links": {
            "monthly": "https://www.paypal.com/ncp/payment/PJVH9WVQQC326",
            "yearly": "https://www.paypal.com/ncp/payment/PJVH9WVQQC326",
            "lifetime": "https://www.paypal.com/ncp/payment/PJVH9WVQQC326",
        },
    },
    {
        "key": "skrill",
        "name": "Skrill",
        "description": "Use the exact payment link for the plan you select.",
        "recommended": False,
        "links": {
            "monthly": "https://skrill.me/rq/Sergio/3.9/EUR?key=JsRvn-KlKusSAqQZ9KhtD1n2RlB",
            "yearly": "https://skrill.me/rq/Sergio/39.9/EUR?key=oMfiyh88FluEyn4Ir-fbnUSOUUU",
            "lifetime": "https://skrill.me/rq/Sergio/79.9/EUR?key=z4adwupMWqQk80qxii-_QaNpVWl",
        },
    },
    {
        "key": "neteller",
        "name": "Neteller",
        "description": "Use the matching plan link and send your confirmation after payment.",
        "recommended": False,
        "links": {
            "monthly": "https://neteller.me/rq/Sergio/3.9/EUR?key=XoRbRMFLrffV8esA3WjFqXsbWuR",
            "yearly": "https://neteller.me/rq/Sergio/39.9/EUR?key=Kj3kZ7nL-ltlxgq4ymi-PVEUX0J",
            "lifetime": "https://neteller.me/rq/Sergio/79.9/EUR?key=LuG8OoCtAd40g5ksW0VXyHsTNVC",
        },
    },
]


def get_current_plan_key(user):
    latest_paid = (
        Payment.query.filter_by(user_id=user.id, status="paid")
        .order_by(Payment.paid_at.desc().nullslast(), Payment.created_at.desc())
        .first()
    )
    if latest_paid and latest_paid.plan in BILLING_PLANS:
        return latest_paid.plan
    if user.vip_active:
        return "yearly"
    return "yearly"


def newest_listing_order():
    return (
        db.func.coalesce(Listing.detected_at, Listing.created_at).desc(),
        Listing.created_at.desc(),
        Listing.id.desc(),
    )


def get_android_apk_path():
    project_root = Path(__file__).resolve().parents[2]
    return project_root / "vip_app_mobile" / "android" / "app" / "build" / "outputs" / "apk" / "debug" / "app-debug.apk"


def get_android_apk_download():
    external_url = (current_app.config.get("ANDROID_APK_URL") or "").strip()
    if external_url:
        return {
            "available": True,
            "url": external_url,
            "is_external": True,
            "size_mb": None,
            "updated_at": None,
        }

    apk_path = get_android_apk_path()
    if not apk_path.exists():
        return {
            "available": False,
            "url": None,
            "is_external": False,
            "size_mb": None,
            "updated_at": None,
        }

    stat = apk_path.stat()
    return {
        "available": True,
        "url": url_for("main.download_android_apk"),
        "is_external": False,
        "size_mb": round(stat.st_size / (1024 * 1024), 1),
        "updated_at": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc),
    }


@main_bp.route("/")
def index():
    if current_user.is_authenticated:
        return redirect(url_for("main.feed"))
    return render_template("landing.html")


@main_bp.route("/download-app")
def download_app():
    apk_download = get_android_apk_download()

    return render_template(
        "download_app.html",
        apk_available=apk_download["available"],
        apk_size_mb=apk_download["size_mb"],
        apk_updated_at=apk_download["updated_at"],
        apk_url=apk_download["url"],
        apk_is_external=apk_download["is_external"],
    )


@main_bp.route("/download-app/android")
def download_android_apk():
    external_url = (current_app.config.get("ANDROID_APK_URL") or "").strip()
    if external_url:
        return redirect(external_url)

    apk_path = get_android_apk_path()
    if not apk_path.exists():
        return redirect(url_for("main.download_app"))
    return send_file(
        apk_path,
        as_attachment=True,
        download_name="TCG-Sniper-Deals-Android.apk",
        mimetype="application/vnd.android.package-archive",
    )


@main_bp.route("/feed")
@vip_required
def feed():
    query = Listing.query

    search = request.args.get("q", "").strip()
    platform = request.args.get("platform", "").strip()
    badge = request.args.get("badge", "").strip()

    if search:
        query = query.filter(Listing.title.ilike(f"%{search}%"))
    if platform:
        query = query.filter(Listing.platform == platform)
    if badge:
        query = query.filter(Listing.badge_label == badge)

    live_deals_count = query.count()
    listings = query.order_by(*newest_listing_order()).limit(60).all()
    favorite_ids = {
        favorite.listing_id
        for favorite in Favorite.query.filter_by(user_id=current_user.id).all()
    }
    platforms = [row[0] for row in db.session.query(Listing.platform).distinct().all()]
    badges = [row[0] for row in db.session.query(Listing.badge_label).distinct().all()]
    alerts_active = False
    if push_enabled():
        alerts_active = PushSubscription.query.filter_by(user_id=current_user.id).first() is not None

    live_stats = {
        "count": live_deals_count,
        "last_detected_at": listings[0].feed_timestamp if listings else None,
        "alerts_active": alerts_active,
    }

    return render_template(
        "feed.html",
        listings=listings,
        favorite_ids=favorite_ids,
        push_enabled=push_enabled(),
        platforms=platforms,
        badges=badges,
        search=search,
        selected_platform=platform,
        selected_badge=badge,
        live_stats=live_stats,
    )


@main_bp.route("/billing", methods=["GET", "POST"])
@main_bp.route("/vip-access", methods=["GET", "POST"])
@login_required
def billing():
    current_plan_key = get_current_plan_key(current_user)
    selected_plan = request.values.get("plan", current_plan_key)
    if selected_plan not in BILLING_PLANS:
        selected_plan = "yearly"

    selected_method = request.values.get("payment_method", "revolut")
    method_keys = {method["key"] for method in BILLING_METHODS}
    if selected_method not in method_keys:
        selected_method = "revolut"

    if request.method == "POST":
        note = request.form.get("note", "").strip() or None
        telegram_username = request.form.get("telegram_username", "").strip() or None
        chosen_plan = request.form.get("plan", selected_plan).strip()
        chosen_method = request.form.get("payment_method", selected_method).strip()

        if chosen_plan not in BILLING_PLANS:
            flash("Choose a valid plan before sending confirmation.", "error")
            return redirect(url_for("main.billing"))

        if chosen_method not in method_keys:
            flash("Choose a valid payment method before sending confirmation.", "error")
            return redirect(url_for("main.billing", plan=chosen_plan))

        if telegram_username:
            current_user.telegram_username = telegram_username

        payment = Payment(
            user_id=current_user.id,
            plan=chosen_plan,
            amount=BILLING_PLANS[chosen_plan]["amount"],
            method=chosen_method.title(),
            status="pending_confirmation",
            notes=note,
        )
        db.session.add(payment)
        db.session.commit()
        flash("Payment confirmation received. Access is delivered shortly after review.", "success")
        return redirect(url_for("main.billing", plan=chosen_plan, payment_method=chosen_method))

    latest_payment = (
        Payment.query.filter_by(user_id=current_user.id)
        .order_by(Payment.created_at.desc())
        .first()
    )

    return render_template(
        "billing.html",
        plans=BILLING_PLANS,
        payment_methods=BILLING_METHODS,
        selected_plan=selected_plan,
        selected_method=selected_method,
        current_plan_key=current_plan_key,
        latest_payment=latest_payment,
    )


@main_bp.route("/listings/<int:listing_id>")
@vip_required
def listing_detail(listing_id):
    listing = db.session.get(Listing, listing_id)
    if not listing:
        return redirect(url_for("main.feed"))
    favorite = Favorite.query.filter_by(user_id=current_user.id, listing_id=listing_id).first() is not None
    return render_template("listing_detail.html", listing=listing, favorite=favorite, push_enabled=push_enabled())


@main_bp.route("/favorites", methods=["GET"])
@vip_required
def favorites():
    favorites = (
        Favorite.query.filter_by(user_id=current_user.id)
        .join(Listing)
        .order_by(*newest_listing_order())
        .all()
    )
    listings = [favorite.listing for favorite in favorites]
    favorite_ids = {listing.id for listing in listings}
    return render_template(
        "favorites.html",
        listings=listings,
        favorite_ids=favorite_ids,
        push_enabled=push_enabled(),
        saved_count=len(listings),
    )


@main_bp.route("/favorites/<int:listing_id>", methods=["POST"])
@vip_required
def toggle_favorite(listing_id):
    listing = db.session.get(Listing, listing_id)
    if not listing:
        return jsonify({"ok": False, "message": "Listing not found"}), 404

    favorite = Favorite.query.filter_by(user_id=current_user.id, listing_id=listing_id).first()
    if favorite:
        db.session.delete(favorite)
        db.session.commit()
        return jsonify({"ok": True, "saved": False})

    favorite = Favorite(user_id=current_user.id, listing_id=listing_id)
    db.session.add(favorite)
    db.session.commit()
    return jsonify({"ok": True, "saved": True})


@main_bp.route("/profile")
@login_required
def profile():
    saved_count = Favorite.query.filter_by(user_id=current_user.id).count()
    return render_template("profile.html", saved_count=saved_count)


@main_bp.route("/vip-pending")
@login_required
def vip_pending():
    if current_user.is_admin or current_user.vip_active:
        return redirect(url_for("main.feed"))
    return render_template("vip_pending.html")


@main_bp.route("/manifest.webmanifest")
def manifest():
    return send_from_directory(current_app.static_folder, "manifest.webmanifest", mimetype="application/manifest+json")


@main_bp.route("/service-worker.js")
def service_worker():
    return send_from_directory(current_app.static_folder, "service-worker.js", mimetype="application/javascript")


@main_bp.route("/offline")
def offline():
    return render_template("offline.html")


@main_bp.route("/health")
def health():
    return Response("ok", mimetype="text/plain")


@main_bp.route("/push-info")
@login_required
def push_info():
    return jsonify(
        {
            "enabled": push_enabled(),
            "publicKey": current_app.config["VAPID_PUBLIC_KEY"],
        }
    )


@main_bp.route("/push-subscriptions", methods=["POST", "DELETE"])
@vip_required
def save_push_subscription():
    payload = request.get_json(silent=True) or {}
    if request.method == "DELETE":
        endpoint = str(payload.get("endpoint") or "").strip()
        query = PushSubscription.query.filter_by(user_id=current_user.id)
        if endpoint:
            query = query.filter_by(endpoint=endpoint)
        removed = query.delete(synchronize_session=False)
        db.session.commit()
        return jsonify({"ok": True, "removed": removed, "active": False})

    endpoint = payload.get("endpoint")
    keys = payload.get("keys") or {}
    p256dh = keys.get("p256dh")
    auth = keys.get("auth")

    if not endpoint or not p256dh or not auth:
        return jsonify({"ok": False, "message": "Invalid subscription payload"}), 400

    subscription = PushSubscription.query.filter_by(endpoint=endpoint).first()
    if subscription is None:
        subscription = PushSubscription(
            endpoint=endpoint,
            p256dh=p256dh,
            auth=auth,
            user_id=current_user.id,
            user_agent=request.headers.get("User-Agent", "")[:255],
        )
        db.session.add(subscription)
    else:
        subscription.p256dh = p256dh
        subscription.auth = auth
        subscription.user_id = current_user.id
        subscription.user_agent = request.headers.get("User-Agent", "")[:255]

    db.session.commit()
    return jsonify({"ok": True, "active": True})
