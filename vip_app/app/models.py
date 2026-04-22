from datetime import datetime, timedelta, timezone
from hashlib import sha1

from flask_login import UserMixin
from werkzeug.security import check_password_hash, generate_password_hash

from .extensions import db, login_manager


def utcnow():
    return datetime.now(timezone.utc)


class TimestampMixin:
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at = db.Column(db.DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)


class User(UserMixin, TimestampMixin, db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    telegram_username = db.Column(db.String(80))
    is_admin = db.Column(db.Boolean, default=False, nullable=False)
    is_vip = db.Column(db.Boolean, default=False, nullable=False)
    vip_expires_at = db.Column(db.DateTime(timezone=True))
    last_login_at = db.Column(db.DateTime(timezone=True))

    favorites = db.relationship("Favorite", back_populates="user", cascade="all, delete-orphan")
    payments = db.relationship("Payment", back_populates="user", cascade="all, delete-orphan")
    push_subscriptions = db.relationship("PushSubscription", back_populates="user", cascade="all, delete-orphan")

    def set_password(self, password: str) -> None:
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)

    @property
    def vip_active(self) -> bool:
        if self.is_admin:
            return True
        if not self.is_vip:
            return False
        if not self.vip_expires_at:
            return False
        expires = self.vip_expires_at
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
        return expires >= utcnow()

    def apply_paid_plan(self, plan: str):
        base = utcnow()
        if self.vip_expires_at:
            current_expiry = self.vip_expires_at
            if current_expiry.tzinfo is None:
                current_expiry = current_expiry.replace(tzinfo=timezone.utc)
            if current_expiry > base:
                base = current_expiry

        if plan == "yearly":
            self.vip_expires_at = base + timedelta(days=365)
        elif plan == "lifetime":
            self.vip_expires_at = base + timedelta(days=36500)
        else:
            self.vip_expires_at = base + timedelta(days=30)
        self.is_vip = True


@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))


class Listing(TimestampMixin, db.Model):
    __tablename__ = "listings"

    id = db.Column(db.Integer, primary_key=True)
    source = db.Column(db.String(40), nullable=False, index=True)
    external_id = db.Column(db.String(255), nullable=False)
    external_url = db.Column(db.String(1000), nullable=False)
    normalized_url = db.Column(db.String(1000), index=True)
    image_url = db.Column(db.String(1000))
    title = db.Column(db.String(500), nullable=False, index=True)
    price_display = db.Column(db.String(120), nullable=False)
    platform = db.Column(db.String(40), nullable=False)
    badge_label = db.Column(db.String(80), default="Strong", nullable=False)
    score_label = db.Column(db.String(40))
    score = db.Column(db.Float)
    category = db.Column(db.String(80))
    tcg_type = db.Column(db.String(40), default="pokemon")
    available_status = db.Column(db.String(40), default="available", nullable=False)
    pricing_status = db.Column(db.String(40), default="pending", nullable=False, index=True)
    pricing_checked_at = db.Column(db.DateTime(timezone=True))
    pricing_error = db.Column(db.String(255))
    reference_price = db.Column(db.Float)
    discount_percent = db.Column(db.Float)
    gross_margin = db.Column(db.Float)
    pricing_score = db.Column(db.Integer)
    is_deal = db.Column(db.Boolean, default=False, nullable=False)
    deal_alert_sent_at = db.Column(db.DateTime(timezone=True))
    alert_title = db.Column(db.String(80))
    partial_title = db.Column(db.String(255))
    confidence_label = db.Column(db.String(40))
    deal_level = db.Column(db.String(40))
    is_vip_only = db.Column(db.Boolean, default=True, nullable=False)
    free_send_at = db.Column(db.DateTime(timezone=True))
    free_sent = db.Column(db.Boolean, default=False, nullable=False)
    free_message_variant = db.Column(db.String(16))
    detected_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False, index=True)
    posted_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False, index=True)
    source_published_at = db.Column(db.DateTime(timezone=True))
    raw_payload = db.Column(db.Text)

    favorites = db.relationship("Favorite", back_populates="listing", cascade="all, delete-orphan")

    __table_args__ = (
        db.UniqueConstraint("source", "external_id", name="uq_listing_source_external"),
    )

    @staticmethod
    def derive_external_id(source: str, external_url: str, external_id: str | None = None) -> str:
        if external_id:
            return external_id.strip()
        digest = sha1((external_url or "").encode("utf-8")).hexdigest()
        return f"{source}-{digest[:20]}"

    @property
    def feed_timestamp(self):
        return self.detected_at or self.created_at or self.posted_at


class Favorite(TimestampMixin, db.Model):
    __tablename__ = "favorites"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    listing_id = db.Column(db.Integer, db.ForeignKey("listings.id"), nullable=False, index=True)

    user = db.relationship("User", back_populates="favorites")
    listing = db.relationship("Listing", back_populates="favorites")

    __table_args__ = (
        db.UniqueConstraint("user_id", "listing_id", name="uq_user_favorite_listing"),
    )


class Payment(TimestampMixin, db.Model):
    __tablename__ = "payments"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    plan = db.Column(db.String(40), nullable=False)
    amount = db.Column(db.Numeric(10, 2), nullable=False)
    method = db.Column(db.String(40), nullable=False)
    status = db.Column(db.String(40), nullable=False, default="pending")
    notes = db.Column(db.String(255))
    paid_at = db.Column(db.DateTime(timezone=True))

    user = db.relationship("User", back_populates="payments")


class PushSubscription(TimestampMixin, db.Model):
    __tablename__ = "push_subscriptions"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    endpoint = db.Column(db.String(1000), nullable=False, unique=True)
    p256dh = db.Column(db.String(255), nullable=False)
    auth = db.Column(db.String(255), nullable=False)
    user_agent = db.Column(db.String(255))

    user = db.relationship("User", back_populates="push_subscriptions")
