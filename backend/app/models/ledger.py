"""Double-entry ledger.

* ``LedgerAccount``    – a balance-carrying account (customer wallet, provider clearing, fee revenue ...).
* ``LedgerTransaction`` – a balanced journal; immutable once written.
* ``LedgerEntry``       – one debit or credit line; immutable once written.

Immutability is enforced at the database level by triggers (see ``app/models/guards.py``).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base, Timestamps, UUIDPk, utcnow

MONEY = Numeric(20, 4)


class LedgerAccount(UUIDPk, Timestamps, Base):
    __tablename__ = "ledger_accounts"
    __table_args__ = (
        CheckConstraint("type in ('asset','liability','equity','revenue','expense')", name="ck_ledger_account_type"),
        CheckConstraint("allow_negative OR balance >= 0", name="ck_ledger_account_non_negative"),
    )

    code: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(200))
    type: Mapped[str] = mapped_column(String(16))
    currency: Mapped[str] = mapped_column(String(3), index=True)
    # Cached running balance in the account's normal direction. Source of truth is ledger_entries;
    # the reconciliation job verifies they agree.
    balance: Mapped[Decimal] = mapped_column(MONEY, default=Decimal("0"))
    allow_negative: Mapped[bool] = mapped_column(Boolean, default=False)
    is_system: Mapped[bool] = mapped_column(Boolean, default=False)
    debits_blocked: Mapped[bool] = mapped_column(Boolean, default=False)
    credits_blocked: Mapped[bool] = mapped_column(Boolean, default=False)
    version: Mapped[int] = mapped_column(Integer, default=0)


class LedgerTransaction(UUIDPk, Base):
    __tablename__ = "ledger_transactions"

    reference: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    kind: Mapped[str] = mapped_column(String(32), index=True)
    description: Mapped[str] = mapped_column(Text, default="")
    meta: Mapped[dict] = mapped_column("metadata", JSON, default=dict)
    # A transaction can be reversed at most once (unique).
    reversal_of_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("ledger_transactions.id"), unique=True, nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=func.now(), index=True
    )

    entries: Mapped[list[LedgerEntry]] = relationship(back_populates="transaction", order_by="LedgerEntry.line")


class LedgerEntry(UUIDPk, Base):
    __tablename__ = "ledger_entries"
    __table_args__ = (
        CheckConstraint("amount > 0", name="ck_ledger_entry_positive"),
        CheckConstraint("direction in ('debit','credit')", name="ck_ledger_entry_direction"),
    )

    transaction_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("ledger_transactions.id"), index=True)
    account_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("ledger_accounts.id"), index=True)
    line: Mapped[int] = mapped_column(Integer)
    direction: Mapped[str] = mapped_column(String(6))
    amount: Mapped[Decimal] = mapped_column(MONEY)
    currency: Mapped[str] = mapped_column(String(3))
    balance_after: Mapped[Decimal] = mapped_column(MONEY)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=func.now(), index=True
    )

    transaction: Mapped[LedgerTransaction] = relationship(back_populates="entries")
    account: Mapped[LedgerAccount] = relationship()


class Wallet(UUIDPk, Timestamps, Base):
    """Customer- or business-facing wallet. Its money lives in exactly one ledger account."""

    __tablename__ = "wallets"

    account_number: Mapped[str] = mapped_column(String(20), unique=True, index=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), index=True)
    business_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("businesses.id"), index=True)
    ledger_account_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("ledger_accounts.id"), unique=True)
    currency: Mapped[str] = mapped_column(String(3))
    label: Mapped[str] = mapped_column(String(100), default="Main")
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(16), default="active")

    ledger_account: Mapped[LedgerAccount] = relationship(lazy="joined")


class IdempotencyRecord(UUIDPk, Timestamps, Base):
    __tablename__ = "idempotency_records"
    __table_args__ = (UniqueConstraint("scope", "key", name="uq_idempotency_scope_key"),)

    scope: Mapped[str] = mapped_column(String(80), index=True)
    key: Mapped[str] = mapped_column(String(128))
    request_hash: Mapped[str] = mapped_column(String(64))
    status_code: Mapped[int | None] = mapped_column(Integer)
    response_body: Mapped[dict | None] = mapped_column(JSON)
    owner_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    completed: Mapped[bool] = mapped_column(Boolean, default=False)
    note: Mapped[str | None] = mapped_column(Text)
