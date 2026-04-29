from datetime import datetime, timedelta, timezone
from hashlib import sha1
import json

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
    market_buy_now_min = db.Column(db.Float)
    market_buy_now_avg = db.Column(db.Float)
    market_buy_now_median = db.Column(db.Float)
    last_sold_prices_json = db.Column(db.Text)
    last_2_sales_json = db.Column(db.Text)
    sold_avg_price = db.Column(db.Float)
    sold_median_price = db.Column(db.Float)
    estimated_fair_value = db.Column(db.Float)
    pricing_basis = db.Column(db.String(40))
    confidence_score = db.Column(db.Integer)
    listing_type = db.Column(db.String(40))
    cardmarket_trending_score = db.Column(db.Integer)
    cardmarket_trend_rank = db.Column(db.Integer)
    cardmarket_trend_category = db.Column(db.String(40))
    ai_market_intel_verdict = db.Column(db.String(40))
    estimated_profit = db.Column(db.Float)
    discount_percent = db.Column(db.Float)
    profit_margin = db.Column(db.Float)
    gross_margin = db.Column(db.Float)
    pricing_score = db.Column(db.Integer)
    score_level = db.Column(db.String(40))
    pricing_reason = db.Column(db.String(255))
    pricing_analyzed_at = db.Column(db.DateTime(timezone=True))
    status = db.Column(db.String(40))
    status_updated_at = db.Column(db.DateTime(timezone=True))
    availability_checked_at = db.Column(db.DateTime(timezone=True))
    gone_detected_at = db.Column(db.DateTime(timezone=True))
    gone_alert_sent_at = db.Column(db.DateTime(timezone=True))
    sold_after_seconds = db.Column(db.Integer)
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
        db.Index("ix_listings_detected_at_id", "detected_at", "id"),
        db.Index("ix_listings_platform_detected_at", "platform", "detected_at"),
        db.Index("ix_listings_is_deal_detected_at", "is_deal", "detected_at"),
        db.Index("ix_listings_badge_label_detected_at", "badge_label", "detected_at"),
    )

    @staticmethod
    def derive_external_id(source: str, external_url: str, external_id: str | None = None) -> str:
        if external_id:
            return external_id.strip()
        digest = sha1((external_url or "").encode("utf-8")).hexdigest()
        return f"{source}-{digest[:20]}"

    @property
    def detected_at_iso(self):
        timestamp = self.detected_at
        if not timestamp:
            return ""
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=timezone.utc)
        return timestamp.isoformat()

    @property
    def is_pending_pricing(self):
        return (self.pricing_status or "").strip().lower() in {"", "pending"}

    @property
    def display_badge(self):
        if self.is_deal and self.badge_label:
            return self.badge_label
        return "Fresh"

    @property
    def display_alert_title(self):
        if self.alert_title:
            return self.alert_title
        if self.is_pending_pricing:
            return "Live listing"
        if self.is_deal:
            return "Deal ready"
        return "Tracked listing"

    @property
    def display_confidence(self):
        if self.score_level:
            return self.score_level.title()
        if self.confidence_label:
            return self.confidence_label
        if self.score_label:
            return self.score_label
        if self.is_pending_pricing:
            return "Pending"
        return "Tracked"

    @property
    def display_signal(self):
        if self.score_level:
            return self.score_level.lower()
        if self.deal_level:
            return self.deal_level
        if self.is_pending_pricing:
            return "tracking"
        if self.is_deal:
            return "good"
        return "watch"

    @property
    def display_microcopy(self):
        if self.is_deal:
            return "Below market"
        if self.is_pending_pricing:
            return "Just detected"

        detected_at = self.detected_at
        if detected_at:
            if detected_at.tzinfo is None:
                detected_at = detected_at.replace(tzinfo=timezone.utc)
            elapsed = utcnow() - detected_at
            if elapsed <= timedelta(minutes=5):
                return "Fast-moving"
        return ""

    @property
    def effective_profit(self):
        if self.estimated_profit is not None:
            return self.estimated_profit
        if self.profit_margin is not None:
            return self.profit_margin
        return self.gross_margin

    @property
    def last_sold_prices(self):
        try:
            values = json.loads(self.last_sold_prices_json or "[]")
            return [float(value) for value in values]
        except Exception:
            return []

    @property
    def last_2_sales(self):
        try:
            values = json.loads(self.last_2_sales_json or "[]")
            return [float(value) for value in values]
        except Exception:
            return []

    @property
    def comparable_results_count(self):
        reason = self.pricing_reason or ""
        if "comparable_results=" in reason:
            try:
                return int(reason.split("comparable_results=", 1)[1].split(";", 1)[0].strip())
            except (TypeError, ValueError):
                pass
        total = 0
        found = False
        for marker in ("sold_refs=", "buy_now_refs="):
            if marker in reason:
                found = True
                try:
                    total += int(reason.split(marker, 1)[1].split(";", 1)[0].strip())
                except (TypeError, ValueError):
                    pass
        if found:
            return total
        return len(self.last_sold_prices) + (1 if self.market_buy_now_median is not None else 0)

    @property
    def market_type_display(self):
        value = (self.listing_type or "unknown").strip().lower()
        labels = {
            "raw_card": "RAW",
            "graded_card": "GRADED",
            "sealed_product": "SEALED",
            "lot_bundle": "LOT",
        }
        return labels.get(value, "UNKNOWN")

    @property
    def effective_status(self):
        return (self.status or self.available_status or "available").strip().lower()

    @property
    def gone_timestamp(self):
        return self.gone_detected_at or self.status_updated_at or self.updated_at

    @property
    def gone_timestamp_iso(self):
        timestamp = self.gone_timestamp
        if not timestamp:
            return ""
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=timezone.utc)
        return timestamp.isoformat()

    @property
    def gone_after_label(self):
        seconds = self.sold_after_seconds
        if seconds is None and self.gone_detected_at and self.detected_at:
            gone_at = self.gone_detected_at
            detected_at = self.detected_at
            if gone_at.tzinfo is None:
                gone_at = gone_at.replace(tzinfo=timezone.utc)
            if detected_at.tzinfo is None:
                detected_at = detected_at.replace(tzinfo=timezone.utc)
            seconds = max(int((gone_at - detected_at).total_seconds()), 0)
        if seconds is None:
            return ""
        if seconds < 60:
            return f"Gone after {seconds}s"
        minutes = seconds // 60
        if minutes < 60:
            return f"Gone after {minutes} min"
        hours = minutes // 60
        return f"Gone after {hours}h"


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


class FreeGoneAlertState(TimestampMixin, db.Model):
    __tablename__ = "free_gone_alert_state"

    id = db.Column(db.Integer, primary_key=True)
    state_date = db.Column(db.Date, nullable=False, unique=True, index=True)
    daily_target_count = db.Column(db.Integer, nullable=False, default=0)
    daily_posted_count = db.Column(db.Integer, nullable=False, default=0)
    window_plan_json = db.Column(db.Text, nullable=False, default="{}")
    window_posted_json = db.Column(db.Text, nullable=False, default="{}")
    window_schedule_json = db.Column(db.Text, nullable=False, default="{}")
    used_listing_ids_json = db.Column(db.Text, nullable=False, default="[]")
    last_posted_at = db.Column(db.DateTime(timezone=True))
    next_post_at = db.Column(db.DateTime(timezone=True))

    def window_plan(self) -> dict:
        try:
            return json.loads(self.window_plan_json or "{}")
        except Exception:
            return {}

    def window_posted(self) -> dict:
        try:
            return json.loads(self.window_posted_json or "{}")
        except Exception:
            return {}

    def window_schedule(self) -> dict:
        try:
            return json.loads(self.window_schedule_json or "{}")
        except Exception:
            return {}

    def used_listing_ids(self) -> list[int]:
        try:
            values = json.loads(self.used_listing_ids_json or "[]")
            return [int(value) for value in values]
        except Exception:
            return []

    def set_window_plan(self, value: dict) -> None:
        self.window_plan_json = json.dumps(value, ensure_ascii=False, sort_keys=True)

    def set_window_posted(self, value: dict) -> None:
        self.window_posted_json = json.dumps(value, ensure_ascii=False, sort_keys=True)

    def set_window_schedule(self, value: dict) -> None:
        self.window_schedule_json = json.dumps(value, ensure_ascii=False, sort_keys=True)

    def set_used_listing_ids(self, values: list[int]) -> None:
        self.used_listing_ids_json = json.dumps(sorted({int(value) for value in values}), ensure_ascii=False)


class CardmarketTrend(TimestampMixin, db.Model):
    __tablename__ = "cardmarket_trends"

    id = db.Column(db.Integer, primary_key=True)
    category = db.Column(db.String(40), nullable=False, index=True)
    rank = db.Column(db.Integer, nullable=False)
    product_name = db.Column(db.String(255), nullable=False)
    expansion = db.Column(db.String(120))
    card_number = db.Column(db.String(40))
    price = db.Column(db.Float)
    currency = db.Column(db.String(8), default="EUR", nullable=False)
    image_url = db.Column(db.String(1000))
    image_data_url = db.Column(db.Text)
    product_url = db.Column(db.String(1000))
    source_url = db.Column(db.String(1000), nullable=False, default="https://www.cardmarket.com/en/Pokemon")
    collected_at = db.Column(db.DateTime(timezone=True), nullable=False, index=True)
    raw_payload_json = db.Column(db.Text)

    __table_args__ = (
        db.Index("ix_cardmarket_trends_category_collected_rank", "category", "collected_at", "rank"),
        db.Index("ix_cardmarket_trends_product_name", "product_name"),
    )

    @property
    def set_or_number(self) -> str:
        parts = [value for value in (self.expansion, self.card_number) if value]
        return " ".join(parts)

    @property
    def display_image_url(self) -> str | None:
        return self.image_data_url or self.image_url

    @property
    def liquidity_label(self) -> str:
        if self.rank <= 3:
            return "FAST"
        if self.rank <= 7:
            return "MEDIUM"
        return "SLOW"
