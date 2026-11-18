from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base, Timestamps, UUIDPk


class DeveloperApp(UUIDPk, Timestamps, Base):
    __tablename__ = "developer_apps"

    owner_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    business_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("businesses.id"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), default="active")
    # What this application may do through the API (see AppPermission). Payouts must be granted explicitly.
    permissions: Mapped[list] = mapped_column(JSON, default=lambda: ["collections", "refunds", "balance",
                                                                     "subscribers"])
    # When on, collection and payout calls must carry a valid X-Subscriber-Token for a verified, active subscriber.
    require_verified_subscribers: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")


class ApiKey(UUIDPk, Timestamps, Base):
    __tablename__ = "api_keys"

    app_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("developer_apps.id", ondelete="CASCADE"), index=True)
    environment: Mapped[str] = mapped_column(String(16))
    public_key: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    secret_prefix: Mapped[str] = mapped_column(String(24), unique=True, index=True)
    secret_hash: Mapped[str] = mapped_column(String(64))
    last4: Mapped[str] = mapped_column(String(4))
    status: Mapped[str] = mapped_column(String(16), default="active")
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class WebhookEndpoint(UUIDPk, Timestamps, Base):
    __tablename__ = "webhook_endpoints"

    app_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("developer_apps.id", ondelete="CASCADE"), index=True)
    url: Mapped[str] = mapped_column(String(500))
    environment: Mapped[str] = mapped_column(String(16), default="sandbox")
    secret_enc: Mapped[str] = mapped_column(Text)
    events: Mapped[list] = mapped_column(JSON, default=list)  # empty = all events
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    description: Mapped[str | None] = mapped_column(String(200))


class WebhookDelivery(UUIDPk, Timestamps, Base):
    __tablename__ = "webhook_deliveries"

    endpoint_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("webhook_endpoints.id", ondelete="CASCADE"), index=True)
    event_id: Mapped[str] = mapped_column(String(64), index=True)
    event_type: Mapped[str] = mapped_column(String(64), index=True)
    payload: Mapped[dict] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    last_response_code: Mapped[int | None] = mapped_column(Integer)
    last_error: Mapped[str | None] = mapped_column(Text)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ApiRequestLog(UUIDPk, Timestamps, Base):
    __tablename__ = "api_request_logs"

    app_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("developer_apps.id", ondelete="CASCADE"), index=True)
    api_key_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("api_keys.id", ondelete="SET NULL"))
    environment: Mapped[str] = mapped_column(String(16))
    method: Mapped[str] = mapped_column(String(8))
    path: Mapped[str] = mapped_column(String(300))
    status_code: Mapped[int] = mapped_column(Integer)
    latency_ms: Mapped[int] = mapped_column(Integer)
    ip_address: Mapped[str | None] = mapped_column(String(64))
    meta: Mapped[dict] = mapped_column("metadata", JSON, default=dict)


class AppSubscriber(UUIDPk, Timestamps, Base):
    """A customer of a connected application (e.g. a Nurses & Midwives Hub subscriber).

    Not a FinCore dashboard user: subscribers never sign in to FinCore and do not count toward the dashboard seats.
    """

    __tablename__ = "app_subscribers"
    __table_args__ = (UniqueConstraint("app_id", "external_id", name="uq_subscriber_app_external"),)

    app_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("developer_apps.id", ondelete="CASCADE"), index=True)
    external_id: Mapped[str] = mapped_column(String(128))  # the application's own user id
    display_name: Mapped[str | None] = mapped_column(String(200))
    phone: Mapped[str | None] = mapped_column(String(20))
    email: Mapped[str | None] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    verification_method: Mapped[str | None] = mapped_column(String(32))  # sms_code | admin
    # Bumped whenever access is withdrawn: every subscriber token issued before becomes invalid at once.
    token_version: Mapped[int] = mapped_column(Integer, default=1)
    deactivated_reason: Mapped[str | None] = mapped_column(Text)


class SubscriberVerification(UUIDPk, Timestamps, Base):
    __tablename__ = "subscriber_verifications"

    subscriber_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("app_subscribers.id", ondelete="CASCADE"), index=True)
    code_hash: Mapped[str] = mapped_column(String(64))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
