"""Business-level transactions (what customers see) and supporting records."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base, Timestamps, UUIDPk
from app.models.enums import TxnStatus

MONEY = Numeric(20, 4)


class Transaction(UUIDPk, Timestamps, Base):
    __tablename__ = "transactions"

    reference: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    type: Mapped[str] = mapped_column(String(32), index=True)
    status: Mapped[str] = mapped_column(String(32), default=TxnStatus.PENDING, index=True)
    channel: Mapped[str] = mapped_column(String(32), default="wallet")
    amount: Mapped[Decimal] = mapped_column(MONEY)
    fee: Mapped[Decimal] = mapped_column(MONEY, default=Decimal("0"))
    currency: Mapped[str] = mapped_column(String(3))
    source_wallet_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("wallets.id"), index=True)
    destination_wallet_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("wallets.id"), index=True)
    initiated_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), index=True)
    business_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("businesses.id"), index=True)
    provider: Mapped[str | None] = mapped_column(String(32))
    provider_mode: Mapped[str] = mapped_column(String(16), default="sandbox")
    provider_reference: Mapped[str | None] = mapped_column(String(128), index=True)
    counterparty: Mapped[dict] = mapped_column(JSON, default=dict)
    description: Mapped[str] = mapped_column(Text, default="")
    # Ledger journals: the main posting, and (for two-phase flows) the settlement posting.
    ledger_transaction_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("ledger_transactions.id"))
    completion_ledger_transaction_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("ledger_transactions.id"))
    related_transaction_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("transactions.id"))
    failure_reason: Mapped[str | None] = mapped_column(Text)
    meta: Mapped[dict] = mapped_column("metadata", JSON, default=dict)
    risk_score: Mapped[int] = mapped_column(Integer, default=0)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Beneficiary(UUIDPk, Timestamps, Base):
    __tablename__ = "beneficiaries"
    __table_args__ = (UniqueConstraint("user_id", "type", "identifier", name="uq_beneficiary_identity"),)

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    type: Mapped[str] = mapped_column(String(32))  # wallet | mobile_money | bank
    name: Mapped[str] = mapped_column(String(200))
    nickname: Mapped[str | None] = mapped_column(String(100))
    identifier: Mapped[str] = mapped_column(String(64))  # wallet acct no., MSISDN or bank acct no.
    network: Mapped[str | None] = mapped_column(String(16))
    bank_code: Mapped[str | None] = mapped_column(String(16))
    favourite: Mapped[bool] = mapped_column(Boolean, default=False)


class FeeRule(UUIDPk, Timestamps, Base):
    __tablename__ = "fee_rules"

    name: Mapped[str] = mapped_column(String(120))
    transaction_type: Mapped[str] = mapped_column(String(32), index=True)
    channel: Mapped[str | None] = mapped_column(String(32))  # None = any channel
    currency: Mapped[str] = mapped_column(String(3), default="GHS")
    payer: Mapped[str] = mapped_column(String(16), default="customer")  # customer | merchant
    flat_fee: Mapped[Decimal] = mapped_column(MONEY, default=Decimal("0"))
    percent_fee: Mapped[Decimal] = mapped_column(Numeric(8, 6), default=Decimal("0"))  # 0.015 = 1.5%
    min_fee: Mapped[Decimal] = mapped_column(MONEY, default=Decimal("0"))
    max_fee: Mapped[Decimal | None] = mapped_column(MONEY)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class LimitRule(UUIDPk, Timestamps, Base):
    __tablename__ = "limit_rules"
    __table_args__ = (UniqueConstraint("kyc_tier", "transaction_type", "currency", name="uq_limit_rule"),)

    kyc_tier: Mapped[int] = mapped_column(Integer)
    transaction_type: Mapped[str] = mapped_column(String(32))  # or "*" for balance cap
    currency: Mapped[str] = mapped_column(String(3), default="GHS")
    per_transaction_max: Mapped[Decimal | None] = mapped_column(MONEY)
    daily_max: Mapped[Decimal | None] = mapped_column(MONEY)
    monthly_max: Mapped[Decimal | None] = mapped_column(MONEY)
    max_balance: Mapped[Decimal | None] = mapped_column(MONEY)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class ProviderTransaction(UUIDPk, Timestamps, Base):
    """What we sent to / heard from an external provider. Used for reconciliation."""

    __tablename__ = "provider_transactions"
    __table_args__ = (UniqueConstraint("provider", "provider_reference", name="uq_provider_ref"),)

    provider: Mapped[str] = mapped_column(String(32), index=True)
    mode: Mapped[str] = mapped_column(String(16), default="sandbox")
    direction: Mapped[str] = mapped_column(String(16))  # collection | disbursement
    provider_reference: Mapped[str] = mapped_column(String(128))
    internal_reference: Mapped[str] = mapped_column(String(64), index=True)
    amount: Mapped[Decimal] = mapped_column(MONEY)
    currency: Mapped[str] = mapped_column(String(3))
    status: Mapped[str] = mapped_column(String(32))
    raw: Mapped[dict] = mapped_column(JSON, default=dict)
