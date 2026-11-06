"""Reconciliation: ledger integrity, internal vs provider records, and merchant settlement reports."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.business import PaymentRequest, Refund, Settlement
from app.models.enums import TxnStatus
from app.models.ops import ReconciliationRun
from app.models.transaction import ProviderTransaction, Transaction
from app.services.ledger import LedgerService

PROVIDER_TO_TXN = {"successful": TxnStatus.SUCCESSFUL, "failed": TxnStatus.FAILED}


def run_ledger_integrity(db: Session, run_by: uuid.UUID | None = None) -> ReconciliationRun:
    result = LedgerService(db).verify_integrity()
    run = ReconciliationRun(kind="ledger_integrity", status="balanced" if result["balanced"] else "discrepancies",
                            summary={k: v for k, v in result.items() if k != "problems"},
                            discrepancies=result["problems"], run_by_id=run_by)
    db.add(run)
    db.commit()
    return run


def run_provider_reconciliation(db: Session, provider: str | None = None, run_by: uuid.UUID | None = None,
                                statement: list[dict] | None = None) -> ReconciliationRun:
    """Compare provider records with internal transactions.

    ``statement`` optionally supplies the provider's settlement file rows
    (``{"provider_reference", "amount", "status"}``); otherwise our stored provider responses are used.
    """
    q = select(ProviderTransaction)
    if provider:
        q = q.where(ProviderTransaction.provider == provider)
    records = {(p.provider, p.provider_reference): p for p in db.scalars(q)}
    discrepancies: list[dict] = []
    matched = 0

    rows = statement if statement is not None else [
        {"provider": p.provider, "provider_reference": p.provider_reference, "amount": str(p.amount),
         "status": p.status} for p in records.values()]

    for row in rows:
        prov = row.get("provider", provider)
        ref = row["provider_reference"]
        txn = db.scalar(select(Transaction).where(Transaction.provider == prov, Transaction.provider_reference == ref))
        if not txn:
            pt = records.get((prov, ref))
            txn = db.scalar(select(Transaction).where(Transaction.reference == pt.internal_reference)) if pt else None
        if not txn:
            discrepancies.append({"type": "missing_internal", "provider": prov, "provider_reference": ref})
            continue
        if Decimal(str(row["amount"])) != txn.amount:
            discrepancies.append({"type": "amount_mismatch", "reference": txn.reference, "provider_amount": row["amount"],
                                  "internal_amount": str(txn.amount)})
            continue
        expected = PROVIDER_TO_TXN.get(row["status"])
        if expected and txn.status != expected and not (expected == TxnStatus.SUCCESSFUL and txn.status == TxnStatus.REVERSED):
            discrepancies.append({"type": "status_mismatch", "reference": txn.reference, "provider_status": row["status"],
                                  "internal_status": txn.status})
            continue
        matched += 1

    # Stuck: internal transactions still processing with a provider.
    stuck = db.scalars(select(Transaction).where(Transaction.status == TxnStatus.PROCESSING,
                                                 Transaction.provider.notin_(["internal"]))).all()
    for t in stuck:
        discrepancies.append({"type": "in_flight", "reference": t.reference, "provider": t.provider,
                              "since": t.created_at.isoformat()})

    run = ReconciliationRun(kind="provider", provider=provider,
                            status="balanced" if not discrepancies else "discrepancies",
                            summary={"records": len(rows), "matched": matched, "discrepancies": len(discrepancies)},
                            discrepancies=discrepancies, run_by_id=run_by)
    db.add(run)
    db.commit()
    return run


def settlement_report(db: Session, business_id: uuid.UUID, start: datetime, end: datetime) -> dict:
    def total(col, *where):
        return Decimal(db.scalar(select(func.coalesce(func.sum(col), 0)).where(*where)))

    live = (PaymentRequest.business_id == business_id, PaymentRequest.environment == "live",
            PaymentRequest.paid_at >= start, PaymentRequest.paid_at < end)
    gross = total(PaymentRequest.amount, *live)
    fees = total(PaymentRequest.fee, *live)
    count = db.scalar(select(func.count()).select_from(PaymentRequest).where(*live))
    refunds = total(Refund.amount, Refund.business_id == business_id, Refund.status == "successful",
                    Refund.created_at >= start, Refund.created_at < end)
    settled = total(Settlement.amount, Settlement.business_id == business_id, Settlement.status == "paid",
                    Settlement.created_at >= start, Settlement.created_at < end)
    settle_fees = total(Settlement.fee, Settlement.business_id == business_id, Settlement.status == "paid",
                        Settlement.created_at >= start, Settlement.created_at < end)
    return {"period_start": start, "period_end": end, "payments_count": count, "gross_volume": gross,
            "fees": fees, "refunds": refunds, "net_volume": gross - fees - refunds, "settled": settled,
            "settlement_fees": settle_fees, "currency": "GHS",
            "settlements": [
                {"reference": s.reference, "amount": s.amount, "fee": s.fee, "status": s.status,
                 "created_at": s.created_at, "paid_at": s.paid_at, "destination": s.destination}
                for s in db.scalars(select(Settlement).where(Settlement.business_id == business_id,
                                                             Settlement.created_at >= start,
                                                             Settlement.created_at < end)
                                    .order_by(Settlement.created_at.desc()))
            ]}
