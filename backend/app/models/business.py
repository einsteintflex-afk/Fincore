from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base, Timestamps, UUIDPk
from app.models.enums import BusinessStatus, PaymentStatus

MONEY = Numeric(20, 4)


class Business(UUIDPk, Timestamps, Base):
    __tablename__ = "businesses"

    name: Mapped[str] = mapped_column(String(200))
    trading_name: Mapped[str | None] = mapped_column(String(200))
    registration_number: Mapped[str | None] = mapped_column(String(64))  # ORC registration no.
    tin: Mapped[str | None] = mapped_column(String(32))  # GRA Taxpayer Identification Number
    business_type: Mapped[str] = mapped_column(String(32))
    industry: Mapped[str | None] = mapped_column(String(64))
    email: Mapped[str] = mapped_column(String(255))
    phone: Mapped[str | None] = mapped_column(String(20))
    address: Mapped[str | None] = mapped_column(Text)
    website: Mapped[str | None] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(16), default=BusinessStatus.PENDING, index=True)
    review_note: Mapped[str | None] = mapped_column(Text)
    owner_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    merchant_code: Mapped[str] = mapped_column(String(16), unique=True, index=True)
    settlement_schedule: Mapped[str] = mapped_column(String(16), default="manual")  # daily|weekly|manual
    settlement_destination: Mapped[dict] = mapped_column(JSON, default=dict)


class BusinessMember(UUIDPk, Timestamps, Base):
    __tablename__ = "business_members"
    __table_args__ = (UniqueConstraint("business_id", "user_id", name="uq_business_member"),)

    business_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("businesses.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(16), default="active")


class PaymentLink(UUIDPk, Timestamps, Base):
    __tablename__ = "payment_links"

    business_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("businesses.id", ondelete="CASCADE"), index=True)
    slug: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)
    amount: Mapped[Decimal | None] = mapped_column(MONEY)  # None = payer chooses amount
    currency: Mapped[str] = mapped_column(String(3), default="GHS")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    single_use: Mapped[bool] = mapped_column(Boolean, default=False)
    redirect_url: Mapped[str | None] = mapped_column(String(500))
    payments_count: Mapped[int] = mapped_column(Integer, default=0)


class PaymentRequest(UUIDPk, Timestamps, Base):
    """A charge a merchant wants collected (checkout, API charge or payment-link payment)."""

    __tablename__ = "payment_requests"

    reference: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    merchant_reference: Mapped[str | None] = mapped_column(String(100), index=True)
    business_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("businesses.id"), index=True)
    app_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("developer_apps.id"), index=True)
    payment_link_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("payment_links.id"), index=True)
    environment: Mapped[str] = mapped_column(String(16), default="live", index=True)
    amount: Mapped[Decimal] = mapped_column(MONEY)
    currency: Mapped[str] = mapped_column(String(3), default="GHS")
    fee: Mapped[Decimal] = mapped_column(MONEY, default=Decimal("0"))
    amount_refunded: Mapped[Decimal] = mapped_column(MONEY, default=Decimal("0"))
    status: Mapped[str] = mapped_column(String(32), default=PaymentStatus.PENDING, index=True)
    description: Mapped[str | None] = mapped_column(Text)
    customer_name: Mapped[str | None] = mapped_column(String(200))
    customer_email: Mapped[str | None] = mapped_column(String(255))
    customer_phone: Mapped[str | None] = mapped_column(String(20))
    channel: Mapped[str | None] = mapped_column(String(32))
    network: Mapped[str | None] = mapped_column(String(16))
    provider: Mapped[str | None] = mapped_column(String(32))
    provider_reference: Mapped[str | None] = mapped_column(String(128), index=True)
    payer_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    transaction_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("transactions.id"))
    callback_url: Mapped[str | None] = mapped_column(String(500))
    failure_reason: Mapped[str | None] = mapped_column(Text)
    meta: Mapped[dict] = mapped_column("metadata", JSON, default=dict)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Refund(UUIDPk, Timestamps, Base):
    __tablename__ = "refunds"

    reference: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    payment_request_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("payment_requests.id"), index=True)
    business_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("businesses.id"), index=True)
    amount: Mapped[Decimal] = mapped_column(MONEY)
    currency: Mapped[str] = mapped_column(String(3))
    reason: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), default="pending")
    transaction_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("transactions.id"))
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))


class Settlement(UUIDPk, Timestamps, Base):
    __tablename__ = "settlements"

    reference: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    business_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("businesses.id"), index=True)
    amount: Mapped[Decimal] = mapped_column(MONEY)
    fee: Mapped[Decimal] = mapped_column(MONEY, default=Decimal("0"))
    currency: Mapped[str] = mapped_column(String(3))
    status: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    destination: Mapped[dict] = mapped_column(JSON, default=dict)
    transaction_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("transactions.id"))
    initiated_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    note: Mapped[str | None] = mapped_column(Text)
