"""Background worker: delivers merchant webhooks, polls in-flight provider transactions,
expires stale checkouts, and marks outbound messages as handed off.

Run one or more replicas: ``python -m app.cli worker``. Work items are claimed with
``FOR UPDATE SKIP LOCKED`` so replicas don't double-process.
"""

from __future__ import annotations

import logging
import signal
import time
from datetime import timedelta

import httpx
from sqlalchemy import select, update

from app.core.database import SessionLocal, utcnow
from app.core.logging import configure_logging
from app.models.business import PaymentRequest
from app.models.enums import PaymentStatus, TxnStatus
from app.models.transaction import Transaction
from app.models.user import OutboundMessage
from app.services import webhooks
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


def tick(client: httpx.Client) -> dict:
    with SessionLocal() as db:
        hooks = webhooks.deliver_due(db, client)
    return {"webhooks": hooks, "polled": poll_in_flight(), "expired": expire_checkouts(), "outbox": drain_outbox()}


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
                if any(v for v in stats.values() if not isinstance(v, dict)) or stats["webhooks"]["attempted"]:
                    log.info("worker tick", extra=stats)
            except Exception:
                log.exception("worker tick failed")
            if once:
                break
            time.sleep(interval)
    log.info("worker stopped")
