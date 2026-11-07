"""Reconciliation: ledger integrity, internal vs provider records, and merchant settlement reports."""

from __future__ import annotations

import csv
import io
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import ValidationFailed
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
                                statement: list[dict] | None = None, source: dict | None = None,
                                window: tuple[datetime, datetime] | None = None) -> ReconciliationRun:
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
    seen: set[uuid.UUID] = set()

    rows = statement if statement is not None else [
        {"provider": p.provider, "provider_reference": p.provider_reference, "amount": str(p.amount),
         "status": p.status} for p in records.values()]

    for row in rows:
        prov = row.get("provider", provider)
        ref = row.get("provider_reference")
        txn = None
        if ref:
            txn = db.scalar(select(Transaction).where(Transaction.provider == prov, Transaction.provider_reference == ref))
        if not txn and row.get("internal_reference"):
            txn = db.scalar(select(Transaction).where(Transaction.reference == row["internal_reference"]))
        if not txn:
            pt = records.get((prov, ref)) if ref else None
            txn = db.scalar(select(Transaction).where(Transaction.reference == pt.internal_reference)) if pt else None
        if not txn:
            discrepancies.append({"type": "missing_internal", "provider": prov, "provider_reference": ref,
                                  "internal_reference": row.get("internal_reference"), "amount": row.get("amount")})
            continue
        seen.add(txn.id)
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

    # Internal successes the provider's file doesn't know about (only meaningful for an uploaded file).
    if window and provider:
        missing = db.scalars(select(Transaction).where(
            Transaction.provider == provider, Transaction.status == TxnStatus.SUCCESSFUL,
            Transaction.created_at >= window[0], Transaction.created_at < window[1])).all()
        for t in missing:
            if t.id not in seen:
                discrepancies.append({"type": "missing_in_provider_file", "reference": t.reference,
                                      "provider_reference": t.provider_reference, "amount": str(t.amount)})

    # Stuck: internal transactions still processing with a provider.
    stuck = db.scalars(select(Transaction).where(Transaction.status == TxnStatus.PROCESSING,
                                                 Transaction.provider.notin_(["internal"]))).all()
    for t in stuck:
        discrepancies.append({"type": "in_flight", "reference": t.reference, "provider": t.provider,
                              "since": t.created_at.isoformat()})

    run = ReconciliationRun(kind="provider", provider=provider,
                            status="balanced" if not discrepancies else "discrepancies",
                            summary={"records": len(rows), "matched": matched, "discrepancies": len(discrepancies),
                                     **(source or {})},
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


# ---------------------------------------------------------------- settlement-file upload
STATUS_ALIASES = {
    "successful": "successful", "success": "successful", "succeeded": "successful", "completed": "successful",
    "complete": "successful", "paid": "successful", "approved": "successful",
    "failed": "failed", "failure": "failed", "rejected": "failed", "declined": "failed", "reversed": "failed",
    "cancelled": "failed", "timeout": "failed", "expired": "failed",
    "pending": "pending", "processing": "pending", "ongoing": "pending",
}
# Column aliases (lower-case). Provider-specific profiles are added here when real statement files are received.
COLUMN_ALIASES = {
    "provider_reference": {"provider_reference", "provider reference", "transaction id", "financial transaction id",
                           "transaction_id", "external_id_provider"},
    "internal_reference": {"internal_reference", "reference", "external transaction id", "external_id",
                           "merchant reference", "fincore reference"},
    "amount": {"amount", "transaction amount", "value"},
    "status": {"status", "transaction status", "state"},
    "date": {"date", "transaction date", "created_at", "timestamp", "date/time"},
}
MAX_FILE_BYTES = 5 * 1024 * 1024


def parse_settlement_csv(content: bytes) -> tuple[list[dict], tuple[datetime, datetime] | None]:
    """Normalise a provider CSV into reconciliation rows. Raises ValidationFailed with the offending line."""
    if len(content) > MAX_FILE_BYTES:
        raise ValidationFailed("Settlement files must be 5 MB or smaller")
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValidationFailed("File must be UTF-8 CSV") from exc
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        raise ValidationFailed("The file is empty")
    mapping: dict[str, str] = {}
    for col in reader.fieldnames:
        key = (col or "").strip().lower()
        for field, aliases in COLUMN_ALIASES.items():
            if key in aliases and field not in mapping:
                mapping[field] = col
    if "amount" not in mapping or "status" not in mapping or not ({"provider_reference", "internal_reference"} & mapping.keys()):
        raise ValidationFailed("CSV needs columns: amount, status and provider_reference (or reference)",
                               details={"found_columns": reader.fieldnames})
    rows, dates = [], []
    for n, raw in enumerate(reader, start=2):
        try:
            amount = Decimal(str(raw[mapping["amount"]]).replace(",", "").strip())
        except (InvalidOperation, AttributeError) as exc:
            raise ValidationFailed(f"Line {n}: invalid amount {raw.get(mapping['amount'])!r}") from exc
        status_raw = (raw[mapping["status"]] or "").strip().lower()
        if status_raw not in STATUS_ALIASES:
            raise ValidationFailed(f"Line {n}: unknown status {status_raw!r}")
        row = {"amount": str(amount), "status": STATUS_ALIASES[status_raw],
               "provider_reference": (raw.get(mapping.get("provider_reference", ""), "") or "").strip() or None,
               "internal_reference": (raw.get(mapping.get("internal_reference", ""), "") or "").strip() or None}
        if not (row["provider_reference"] or row["internal_reference"]):
            raise ValidationFailed(f"Line {n}: missing transaction reference")
        if "date" in mapping and raw.get(mapping["date"]):
            try:
                d = datetime.fromisoformat(raw[mapping["date"]].strip().replace("Z", "+00:00"))
                dates.append(d if d.tzinfo else d.replace(tzinfo=timezone.utc))
            except ValueError as exc:
                raise ValidationFailed(f"Line {n}: dates must be ISO format (YYYY-MM-DD[THH:MM])") from exc
        rows.append(row)
    if not rows:
        raise ValidationFailed("The file has no transactions")
    window = (min(dates), max(dates) + timedelta(seconds=1)) if len(dates) == len(rows) else None
    return rows, window


def reconcile_settlement_file(db: Session, provider: str, filename: str, content: bytes,
                              run_by: uuid.UUID | None) -> ReconciliationRun:
    rows, window = parse_settlement_csv(content)
    for r in rows:
        r["provider"] = provider
    return run_provider_reconciliation(
        db, provider, run_by, statement=rows, window=window,
        source={"file_name": filename[:120], "rows": len(rows),
                "period": [window[0].isoformat(), window[1].isoformat()] if window else None})
