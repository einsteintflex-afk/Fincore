"""Background worker: delivers merchant webhooks, polls in-flight provider transactions,
expires stale checkouts, and marks outbound messages as handed off.

Run one or more replicas: ``python -m app.cli worker``. Work items are claimed with
``FOR UPDATE SKIP LOCKED`` so replicas don't double-process.
"""

from __future__ import annotations

import logging
import signal
import time
from datetime import datetime, timedelta

import httpx
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

from app.core.database import SessionLocal, utcnow
from app.core.errors import ValidationFailed
from app.core.logging import configure_logging
from app.models.business import Business, PaymentRequest
from app.models.enums import BusinessStatus, PaymentStatus, TxnStatus
from app.models.ledger import IdempotencyRecord
from app.models.transaction import Transaction
from app.models.user import OutboundMessage
from app.services import aml, webhooks
from app.services.payments import PaymentService
from app.services.transactions import TransactionService

log = logging.getLogger("fincore.worker")
POLL_AFTER = timedelta(minutes=2)
_running = True


def poll_in_flight(limit: int = 50) -> int:
    """Ask providers for the status of transactions stuck in PROCESSING."""
    n = 0
    with SessionLocal() as db:
        txns = db.scalars(select(Transaction).where(
            Transaction.status == TxnStatus.PROCESSING, Transaction.provider.notin_(["internal", "sandbox"]),
            Transaction.provider_reference.isnot(None), Transaction.updated_at < utcnow() - POLL_AFTER)
            .limit(limit).with_for_update(skip_locked=True)).all()
        svc = TransactionService(db)
        for t in txns:
            try:
                svc.refresh_from_provider(t)
                n += 1
            except Exception:  # keep going; one bad provider response mustn't stall the queue
                db.rollback()
                log.exception("status poll failed", extra={"reference": t.reference})
    return n


def expire_checkouts() -> int:
    with SessionLocal() as db:
        res = db.execute(update(PaymentRequest).where(PaymentRequest.status == PaymentStatus.PENDING,
                                                      PaymentRequest.expires_at < utcnow())
                         .values(status=PaymentStatus.EXPIRED))
        db.commit()
        return res.rowcount or 0


def drain_outbox(limit: int = 100) -> int:
    """Placeholder delivery: logs messages. Replace with SMTP / SMS gateway (see docs/OPERATIONS.md)."""
    with SessionLocal() as db:
        msgs = db.scalars(select(OutboundMessage).where(OutboundMessage.status == "queued").limit(limit)
                          .with_for_update(skip_locked=True)).all()
        for m in msgs:
            log.info("outbound message", extra={"channel": m.channel, "to": m.recipient, "subject": m.subject})
            m.status, m.sent_at = "logged", utcnow()
        db.commit()
        return len(msgs)


def settlement_period(schedule: str, now: datetime) -> str | None:
    """Period key for a schedule, or None if nothing is due today (weekly runs on Mondays, UTC)."""
    if schedule == "daily":
        return now.date().isoformat()
    if schedule == "weekly" and now.weekday() == 0:
        year, week, _ = now.isocalendar()
        return f"{year}-W{week:02d}"
    return None


def run_scheduled_settlements(now: datetime | None = None) -> dict:
    """Settle every active business on a daily/weekly schedule, at most once per period.

    A row in ``idempotency_records`` (scope ``auto-settlement:<business>``, key = period) is claimed
    first, so concurrent workers or repeated ticks can never settle the same period twice.
    """
    now = now or utcnow()
    stats = {"settled": 0, "skipped": 0, "failed": 0}
    with SessionLocal() as db:
        due = db.scalars(select(Business).where(Business.status == BusinessStatus.ACTIVE,
                                                Business.settlement_schedule.in_(["daily", "weekly"]))).all()
        for biz in due:
            period = settlement_period(biz.settlement_schedule, now)
            if not period or not (biz.settlement_destination or {}).get("channel"):
                stats["skipped"] += 1
                continue
            try:
                db.add(IdempotencyRecord(scope=f"auto-settlement:{biz.id}", key=period, request_hash="-",
                                         completed=True, owner_id=biz.id, note="scheduled settlement"))
                db.commit()
            except IntegrityError:
                db.rollback()
                stats["skipped"] += 1  # already handled this period
                continue
            try:
                PaymentService(db).settle(biz, None, note=f"Scheduled {biz.settlement_schedule} settlement ({period})")
                stats["settled"] += 1
            except ValidationFailed:
                db.rollback()
                stats["skipped"] += 1  # nothing to settle
            except Exception:
                # Failed before any money moved (settle() commits the hold before the provider call and
                # handles provider errors itself), so release the claim and let the next tick retry.
                db.rollback()
                claim = db.scalar(select(IdempotencyRecord).where(
                    IdempotencyRecord.scope == f"auto-settlement:{biz.id}", IdempotencyRecord.key == period))
                if claim:
                    db.delete(claim)
                    db.commit()
                stats["failed"] += 1
                log.exception("scheduled settlement failed", extra={"business": str(biz.id)})
    return stats


AML_INTERVAL = timedelta(minutes=15)
_last_aml: datetime | None = None


def maybe_run_aml() -> dict | None:
    global _last_aml
    now = utcnow()
    if _last_aml and now - _last_aml < AML_INTERVAL:
        return None
    _last_aml = now
    with SessionLocal() as db:
        return aml.run_scan(db, now)


def tick(client: httpx.Client) -> dict:
    with SessionLocal() as db:
        hooks = webhooks.deliver_due(db, client)
    return {"webhooks": hooks, "polled": poll_in_flight(), "expired": expire_checkouts(), "outbox": drain_outbox(),
            "settlements": run_scheduled_settlements(), "aml": maybe_run_aml()}


def run_forever(interval: float = 5.0, once: bool = False) -> None:
    configure_logging()

    def stop(*_):
        global _running
        _running = False

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    log.info("worker started", extra={"interval": interval})
    with httpx.Client() as client:
        while _running:
            try:
                stats = tick(client)
                if any(v for v in stats.values() if isinstance(v, int)) or stats["webhooks"]["attempted"] \
                        or stats["settlements"]["settled"] or any((stats["aml"] or {}).values()):
                    log.info("worker tick", extra=stats)
            except Exception:
                log.exception("worker tick failed")
            if once:
                break
            time.sleep(interval)
    log.info("worker stopped")
