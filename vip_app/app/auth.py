from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required, login_user, logout_user
from sqlalchemy.orm import defer

from .extensions import db
from .models import Listing
from .models import User, utcnow


auth_bp = Blueprint("auth", __name__)


def _login_preview_listing():
    return (
        Listing.query.options(defer(Listing.raw_payload))
        .filter(
            Listing.image_url.isnot(None),
            Listing.image_url != "",
            Listing.image_url.notlike("%example.com%"),
        )
        .order_by(Listing.detected_at.desc().nullslast(), Listing.id.desc())
        .first()
    )


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("main.feed"))

    preview_listing = _login_preview_listing()

    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        user = User.query.filter_by(email=email).first()

        if not user or not user.check_password(password):
            flash("That login did not match our VIP records.", "error")
            return render_template("auth/login.html", preview_listing=preview_listing)

        user.last_login_at = utcnow()
        db.session.commit()
        login_user(user, remember=True)
        flash("You are in. Fresh deals are waiting.", "success")
        return redirect(url_for("main.feed"))

    return render_template("auth/login.html", preview_listing=preview_listing)


@auth_bp.route("/register", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("main.feed"))

    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        telegram_username = request.form.get("telegram_username", "").strip() or None
        password = request.form.get("password", "")
        confirm_password = request.form.get("confirm_password", "")

        if not email or "@" not in email:
            flash("Enter a valid email to claim access.", "error")
            return render_template("auth/register.html")
        if len(password) < 8:
            flash("Use at least 8 characters for your password.", "error")
            return render_template("auth/register.html")
        if password != confirm_password:
            flash("Passwords do not match yet.", "error")
            return render_template("auth/register.html")
        if User.query.filter_by(email=email).first():
            flash("That email already has an account.", "error")
            return render_template("auth/register.html")

        user = User(
            email=email,
            telegram_username=telegram_username,
        )
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        login_user(user, remember=True)
        flash("Account created. Your VIP access will switch on as soon as payment is confirmed.", "success")
        return redirect(url_for("main.vip_pending"))

    return render_template("auth/register.html")


@auth_bp.route("/logout", methods=["POST"])
@login_required
def logout():
    logout_user()
    flash("You have signed out of the VIP stream.", "info")
    return redirect(url_for("main.index"))
