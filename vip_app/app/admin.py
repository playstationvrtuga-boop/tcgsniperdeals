from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation

from sqlalchemy import or_
from flask import Blueprint, flash, redirect, render_template, request, url_for

from .decorators import admin_required
from .extensions import db
from services.cardmarket_screenshot_import import import_cardmarket_trends_from_screenshots

from .models import CardmarketTrend, Listing, Payment, User, utcnow


admin_bp = Blueprint("admin", __name__)


def newest_listing_order():
    return (
        db.func.coalesce(Listing.detected_at, Listing.created_at).desc(),
        Listing.created_at.desc(),
        Listing.id.desc(),
    )


def parse_date(value: str):
    if not value:
        return None
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def latest_cardmarket_trends():
    return (
        CardmarketTrend.query.order_by(
            CardmarketTrend.collected_at.desc(),
            CardmarketTrend.category.asc(),
            CardmarketTrend.rank.asc(),
        )
        .limit(24)
        .all()
    )


@admin_bp.route("/admin")
@admin_required
def dashboard():
    search = request.args.get("q", "").strip()
    payment_status = request.args.get("payment_status", "").strip()
    payment_method = request.args.get("payment_method", "").strip()

    users_query = User.query.order_by(User.created_at.desc())
    if search:
        users_query = users_query.filter(
            (User.email.ilike(f"%{search}%")) | (User.telegram_username.ilike(f"%{search}%"))
        )

    payments_query = Payment.query.order_by(Payment.created_at.desc())
    if payment_status:
        payments_query = payments_query.filter(Payment.status == payment_status)
    if payment_method:
        payments_query = payments_query.filter(Payment.method == payment_method)

    users = users_query.limit(100).all()
    listings = Listing.query.order_by(*newest_listing_order()).limit(20).all()
    payments = payments_query.limit(20).all()

    total_users = User.query.count()
    vip_live = User.query.filter(
        or_(
            User.is_admin.is_(True),
            (User.is_vip.is_(True) & (User.vip_expires_at.is_(None) | (User.vip_expires_at >= utcnow()))),
        )
    ).count()
    overview = {
        "total_users": total_users,
        "vip_live": vip_live,
        "pending_payments": Payment.query.filter(Payment.status.in_(["pending", "pending_confirmation"])).count(),
        "listings_24h": Listing.query.filter(
            db.func.coalesce(Listing.detected_at, Listing.created_at) >= utcnow() - timedelta(days=1)
        ).count(),
    }

    payment_methods = [row[0] for row in db.session.query(Payment.method).distinct().order_by(Payment.method).all() if row[0]]

    return render_template(
        "admin/dashboard.html",
        users=users,
        listings=listings,
        payments=payments,
        search=search,
        payment_status=payment_status,
        payment_method=payment_method,
        payment_methods=payment_methods,
        overview=overview,
    )


@admin_bp.route("/admin/market-intel-import", methods=["GET", "POST"])
@admin_required
def market_intel_import():
    if request.method == "POST":
        screenshot = request.files.get("screenshot")
        sellers_screenshot = request.files.get("sellers_screenshot")
        bargains_screenshot = request.files.get("bargains_screenshot")
        pasted_text = request.form.get("pasted_text", "")
        if not any(file and file.filename for file in (screenshot, sellers_screenshot, bargains_screenshot)):
            flash("Upload a Cardmarket screenshot first.", "error")
            return redirect(url_for("admin.market_intel_import"))
        try:
            count = import_cardmarket_trends_from_screenshots(
                combined_screenshot=screenshot,
                sellers_screenshot=sellers_screenshot,
                bargains_screenshot=bargains_screenshot,
                pasted_text=pasted_text,
            )
        except Exception as error:
            flash(f"Market Intel import failed: {error}", "error")
            return redirect(url_for("admin.market_intel_import"))
        flash(f"AI Market Intel updated with {count} screenshot trend cards.", "success")
        return redirect(url_for("admin.market_intel_import"))

    return render_template(
        "admin/market_intel_import.html",
        trends=latest_cardmarket_trends(),
    )


@admin_bp.route("/admin/users/<int:user_id>/vip", methods=["POST"])
@admin_required
def update_vip(user_id):
    user = db.session.get(User, user_id)
    if not user:
        flash("Member not found.", "error")
        return redirect(url_for("admin.dashboard"))

    email = request.form.get("email", "").strip().lower()
    telegram_username = request.form.get("telegram_username", "").strip() or None
    password = request.form.get("password", "").strip()
    is_admin = request.form.get("is_admin") == "on"
    user.is_vip = request.form.get("is_vip") == "on"
    user.telegram_username = telegram_username
    expiration = request.form.get("vip_expires_at", "").strip()
    user.vip_expires_at = parse_date(expiration) if expiration else None

    if email:
        existing = User.query.filter(User.email == email, User.id != user.id).first()
        if existing:
            flash("That email is already in use.", "error")
            return redirect(url_for("admin.dashboard"))
        user.email = email

    if password:
        if len(password) < 8:
            flash("Use at least 8 characters for a new password.", "error")
            return redirect(url_for("admin.dashboard"))
        user.set_password(password)

    if not is_admin and user.is_admin:
        other_admin_exists = User.query.filter(User.is_admin.is_(True), User.id != user.id).first() is not None
        if not other_admin_exists:
            flash("Keep at least one admin account active.", "error")
            return redirect(url_for("admin.dashboard"))

    user.is_admin = is_admin
    db.session.commit()
    flash(f"VIP access updated for {user.email}.", "success")
    return redirect(url_for("admin.dashboard"))


@admin_bp.route("/admin/payments", methods=["POST"])
@admin_required
def add_payment():
    user_id = request.form.get("user_id", type=int)
    plan = request.form.get("plan", "monthly").strip()
    amount_raw = request.form.get("amount", "").strip()
    method = request.form.get("method", "").strip()
    status = request.form.get("status", "pending").strip()
    notes = request.form.get("notes", "").strip() or None

    user = db.session.get(User, user_id)
    if not user:
        flash("Select a valid member.", "error")
        return redirect(url_for("admin.dashboard"))

    try:
        amount = Decimal(amount_raw)
    except (InvalidOperation, TypeError):
        flash("Enter a valid payment amount.", "error")
        return redirect(url_for("admin.dashboard"))

    payment = Payment(
        user_id=user.id,
        plan=plan,
        amount=amount,
        method=method or "Manual",
        status=status,
        notes=notes,
        paid_at=utcnow() if status == "paid" else None,
    )
    db.session.add(payment)

    if status == "paid":
        user.apply_paid_plan(plan)

    db.session.commit()
    flash(f"Payment recorded for {user.email}.", "success")
    return redirect(url_for("admin.dashboard"))


@admin_bp.route("/admin/payments/<int:payment_id>/status", methods=["POST"])
@admin_required
def update_payment_status(payment_id):
    payment = db.session.get(Payment, payment_id)
    if not payment:
        flash("Payment record not found.", "error")
        return redirect(url_for("admin.dashboard"))

    status = request.form.get("status", "").strip()
    if status not in {"paid", "failed", "pending", "pending_confirmation"}:
        flash("Choose a valid payment status.", "error")
        return redirect(url_for("admin.dashboard"))

    payment.status = status
    if status == "paid":
        payment.paid_at = utcnow()
        payment.user.apply_paid_plan(payment.plan)
    db.session.commit()
    flash(f"Payment status updated for {payment.user.email}.", "success")
    return redirect(url_for("admin.dashboard", payment_status=request.args.get("payment_status", ""), payment_method=request.args.get("payment_method", ""), q=request.args.get("q", "")))
