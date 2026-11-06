"""Post-transaction AML monitoring scenarios (batch, run by the worker).

Real-time rules live in ``services/risk.py``. These scenarios look at patterns over a window and raise
``FraudAlert`` rows for compliance review. At most one alert per user, per scenario, per UTC day.

Scenarios (thresholds are starting points for compliance to tune):
  * structuring        – ≥3 inbound payments in 24h each just below the user's per-transaction limit (90–100%)
  * rapid_movement     – ≥ GHS 5,000 received in 24h and ≥ 90% of it sent out again within the same 24h
  * fan_in             – ≥ 10 distinct senders into one wallet within 24h (possible mule account)
  * dormant_reactivation – no activity for ≥ 90 days, then ≥ GHS 2,000 out within 24h
"""

from __future__ import annotations

import csv
import io
import uuid
from datetime import datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.database import utcnow
from app.models.enums import TxnStatus
from app.models.ledger import Wallet
from app.models.ops import FraudAlert
from app.models.transaction import LimitRule, Transaction
from app.models.user import User

WINDOW = timedelta(hours=24)
STRUCTURING_COUNT = 3
STRUCTURING_BAND = Decimal("0.90")
RAPID_MIN_IN = Decimal("5000")
RAPID_OUT_RATIO = Decimal("0.90")
FAN_IN_SENDERS = 10
DORMANT_DAYS = 90
DORMANT_OUT = Decimal("2000")

INBOUND = ("deposit", "transfer", "refund")
OUTBOUND = ("withdrawal", "transfer", "payment")
OK = TxnStatus.SUCCESSFUL


def _wallet_owner(db: Session) -> dict[uuid.UUID, uuid.UUID]:
    return {w.id: w.user_id for w in db.scalars(select(Wallet).where(Wallet.user_id.isnot(None)))}


def _already_alerted(db: Session, user_id: uuid.UUID, rule: str, now: datetime) -> bool:
    day = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return bool(db.scalar(select(FraudAlert.id).where(FraudAlert.user_id == user_id, FraudAlert.rule == rule,
                                                      FraudAlert.created_at >= day)))


def _alert(db: Session, user_id, rule: str, severity: str, score: int, details: dict, now: datetime) -> bool:
    if _already_alerted(db, user_id, rule, now):
        return False
    db.add(FraudAlert(user_id=user_id, rule=rule, severity=severity, score=score,
                      details={"source": "aml_scan", **{k: str(v) for k, v in details.items()}}))
    return True


def run_scan(db: Session, now: datetime | None = None) -> dict:
    now = now or utcnow()
    since = now - WINDOW
    owner = _wallet_owner(db)
    raised = {"structuring": 0, "rapid_movement": 0, "fan_in": 0, "dormant_reactivation": 0}

    recent = db.scalars(select(Transaction).where(Transaction.status == OK, Transaction.created_at >= since,
                                                  Transaction.created_at <= now)).all()
    inbound: dict[uuid.UUID, list[Transaction]] = {}
    outbound: dict[uuid.UUID, list[Transaction]] = {}
    for t in recent:
        dst_user = owner.get(t.destination_wallet_id)
        src_user = owner.get(t.source_wallet_id)
        if dst_user and t.type in INBOUND and dst_user != src_user:
            inbound.setdefault(dst_user, []).append(t)
        if src_user and t.type in OUTBOUND and src_user != dst_user:
            outbound.setdefault(src_user, []).append(t)

    tier_max = {(r.kyc_tier, r.transaction_type): r.per_transaction_max
                for r in db.scalars(select(LimitRule).where(LimitRule.active.is_(True)))}
    users = {u.id: u for u in db.scalars(select(User).where(User.id.in_(set(inbound) | set(outbound))))}

    for uid, txns in inbound.items():
        user = users.get(uid)
        # structuring: amounts clustered just under the applicable per-transaction limit
        near = []
        for t in txns:
            limit = tier_max.get((user.kyc_tier, t.type)) if user else None
            if limit and limit * STRUCTURING_BAND <= t.amount < limit:
                near.append(t)
        if len(near) >= STRUCTURING_COUNT and _alert(db, uid, "structuring", "high", 70, {
                "count": len(near), "total": sum(t.amount for t in near)}, now):
            raised["structuring"] += 1
        # fan-in: many distinct senders
        senders = {t.source_wallet_id for t in txns if t.source_wallet_id} | \
                  {t.counterparty.get("msisdn") for t in txns if t.counterparty.get("msisdn")}
        if len(senders) >= FAN_IN_SENDERS and _alert(db, uid, "fan_in", "medium", 50,
                                                     {"distinct_senders": len(senders)}, now):
            raised["fan_in"] += 1
        # rapid movement: in and straight back out
        total_in = sum(t.amount for t in txns)
        total_out = sum(t.amount for t in outbound.get(uid, []))
        if total_in >= RAPID_MIN_IN and total_out >= total_in * RAPID_OUT_RATIO and _alert(
                db, uid, "rapid_movement", "high", 75, {"in": total_in, "out": total_out}, now):
            raised["rapid_movement"] += 1

    for uid, txns in outbound.items():
        total_out = sum(t.amount for t in txns)
        if total_out < DORMANT_OUT:
            continue
        wallet_ids = [w for w, u in owner.items() if u == uid]
        last_before = db.scalar(select(func.max(Transaction.created_at)).where(
            Transaction.created_at < since,
            (Transaction.source_wallet_id.in_(wallet_ids)) | (Transaction.destination_wallet_id.in_(wallet_ids))))
        if last_before is not None and now - last_before >= timedelta(days=DORMANT_DAYS) and _alert(
                db, uid, "dormant_reactivation", "medium", 55,
                {"dormant_days": (now - last_before).days, "out_24h": total_out}, now):
            raised["dormant_reactivation"] += 1

    db.commit()
    return raised


def export_alerts_csv(db: Session, start: datetime, end: datetime, statuses: list[str]) -> str:
    """Case summary for compliance / suspicious transaction reporting.

    The Financial Intelligence Centre (Ghana) receives STRs through goAML; this CSV is the working file a
    compliance officer reviews before filing. Generating goAML XML is a production follow-up.
    """
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["alert_id", "created_at", "rule", "severity", "score", "status", "customer_name", "customer_email",
                "customer_phone", "kyc_tier", "transaction_reference", "amount", "details", "notes"])
    rows = db.execute(
        select(FraudAlert, User, Transaction)
        .join(User, User.id == FraudAlert.user_id, isouter=True)
        .join(Transaction, Transaction.id == FraudAlert.transaction_id, isouter=True)
        .where(FraudAlert.created_at >= start, FraudAlert.created_at < end, FraudAlert.status.in_(statuses))
        .order_by(FraudAlert.created_at)).all()
    for a, u, t in rows:
        w.writerow([a.id, a.created_at.isoformat(), a.rule, a.severity, a.score, a.status,
                    u.full_name if u else "", u.email if u else "", u.phone if u else "", u.kyc_tier if u else "",
                    t.reference if t else "", t.amount if t else "", a.details, a.notes or ""])
    return buf.getvalue()
