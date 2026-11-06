"""Operational models: audit log, fraud alerts, support, system settings, reconciliation."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base, Timestamps, UUIDPk, utcnow


class AuditLog(UUIDPk, Base):
    """Append-only (enforced by DB trigger)."""

    __tablename__ = "audit_logs"

    actor_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, index=True)
    actor_type: Mapped[str] = mapped_column(String(16), default="user")  # user|staff|system|api_key
    action: Mapped[str] = mapped_column(String(80), index=True)
    target_type: Mapped[str | None] = mapped_column(String(40), index=True)
    target_id: Mapped[str | None] = mapped_column(String(64), index=True)
    ip_address: Mapped[str | None] = mapped_column(String(64))
    request_id: Mapped[str | None] = mapped_column(String(64))
    details: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=func.now(), index=True
    )


class FraudAlert(UUIDPk, Timestamps, Base):
    __tablename__ = "fraud_alerts"

    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), index=True)
    transaction_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("transactions.id"), index=True)
    rule: Mapped[str] = mapped_column(String(64), index=True)
    severity: Mapped[str] = mapped_column(String(16))  # low|medium|high|critical
    score: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(16), default="open", index=True)
    details: Mapped[dict] = mapped_column(JSON, default=dict)
    notes: Mapped[str | None] = mapped_column(Text)
    assigned_to_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SupportTicket(UUIDPk, Timestamps, Base):
    __tablename__ = "support_tickets"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    subject: Mapped[str] = mapped_column(String(200))
    category: Mapped[str] = mapped_column(String(32), default="general")
    priority: Mapped[str] = mapped_column(String(16), default="normal")
    status: Mapped[str] = mapped_column(String(16), default="open", index=True)
    transaction_reference: Mapped[str | None] = mapped_column(String(64))
    assigned_to_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))


class TicketMessage(UUIDPk, Timestamps, Base):
    __tablename__ = "ticket_messages"

    ticket_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("support_tickets.id", ondelete="CASCADE"), index=True)
    author_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    body: Mapped[str] = mapped_column(Text)
    internal: Mapped[bool] = mapped_column(default=False)


class SystemSetting(Timestamps, Base):
    __tablename__ = "system_settings"

    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    value: Mapped[dict] = mapped_column(JSON)
    description: Mapped[str | None] = mapped_column(Text)
    updated_by_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)


class ReconciliationRun(UUIDPk, Timestamps, Base):
    __tablename__ = "reconciliation_runs"

    kind: Mapped[str] = mapped_column(String(32))  # ledger_integrity | provider
    provider: Mapped[str | None] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(16))  # balanced | discrepancies
    summary: Mapped[dict] = mapped_column(JSON, default=dict)
    discrepancies: Mapped[list] = mapped_column(JSON, default=list)
    run_by_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)


class ApprovalRequest(UUIDPk, Timestamps, Base):
    """Maker-checker: a sensitive staff action waiting for a second, different staff member."""

    __tablename__ = "approval_requests"

    action: Mapped[str] = mapped_column(String(32), index=True)  # adjustment | reversal
    payload: Mapped[dict] = mapped_column(JSON)
    amount: Mapped[str | None] = mapped_column(String(32))
    reason: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    requested_by_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    reviewed_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    review_note: Mapped[str | None] = mapped_column(Text)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    result: Mapped[dict] = mapped_column(JSON, default=dict)
