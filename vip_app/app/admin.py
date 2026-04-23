from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation

from sqlalchemy import or_
from flask import Blueprint, flash, redirect, render_template, request, url_for

from .decorators import admin_required
from .extensions import db
from .models import Listing, Payment, User, utcnow


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


@admin_bp.route("/admin/users/<int:user_id>/vip", methods=["POST"])
@admin_required
def update_vip(user_id):
    user = db.session.get(User, user_id)
    if not user:
        flash("Member not found.", "error")
        return redirect(url_for("admin.dashboard"))

    user.is_vip = request.form.get("is_vip") == "on"
    user.telegram_username = request.form.get("telegram_username", "").strip() or None
    expiration = request.form.get("vip_expires_at", "").strip()
    user.vip_expires_at = parse_date(expiration) if expiration else None
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
