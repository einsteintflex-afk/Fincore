"""Tiered transaction limits (per transaction, daily, monthly, maximum balance) by KYC tier."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import LimitExceeded
from app.core.money import ZERO
from app.models.enums import TxnStatus
from app.models.transaction import LimitRule, Transaction
from app.models.user import User

COUNTED_STATUSES = (TxnStatus.PENDING, TxnStatus.PROCESSING, TxnStatus.SUCCESSFUL)


def _rule(db: Session, tier: int, txn_type: str, currency: str) -> LimitRule | None:
    return db.scalar(select(LimitRule).where(
        LimitRule.kyc_tier == tier, LimitRule.transaction_type == txn_type,
        LimitRule.currency == currency, LimitRule.active.is_(True)))


def _used(db: Session, user: User, txn_type: str, currency: str, since: datetime) -> Decimal:
    total = db.scalar(select(func.coalesce(func.sum(Transaction.amount), 0)).where(
        Transaction.initiated_by_id == user.id, Transaction.type == txn_type, Transaction.currency == currency,
        Transaction.status.in_(COUNTED_STATUSES), Transaction.created_at >= since))
    return Decimal(total)


def check_limits(db: Session, user: User, txn_type: str, amount: Decimal, currency: str) -> None:
    rule = _rule(db, user.kyc_tier, txn_type, currency)
    if not rule:
        return
    if rule.per_transaction_max is not None and amount > rule.per_transaction_max:
        raise LimitExceeded(f"Amount exceeds your per-transaction limit of {currency} {rule.per_transaction_max:,.2f}",
                            details={"limit": "per_transaction", "max": str(rule.per_transaction_max)})
    now = datetime.now(timezone.utc)
    if rule.daily_max is not None:
        used = _used(db, user, txn_type, currency, now.replace(hour=0, minute=0, second=0, microsecond=0))
        if used + amount > rule.daily_max:
            raise LimitExceeded(f"This would exceed your daily {txn_type} limit of {currency} {rule.daily_max:,.2f}",
                                details={"limit": "daily", "max": str(rule.daily_max), "used": str(used)})
    if rule.monthly_max is not None:
        used = _used(db, user, txn_type, currency, now.replace(day=1, hour=0, minute=0, second=0, microsecond=0))
        if used + amount > rule.monthly_max:
            raise LimitExceeded(
                f"This would exceed your monthly {txn_type} limit of {currency} {rule.monthly_max:,.2f}",
                details={"limit": "monthly", "max": str(rule.monthly_max), "used": str(used)})


def check_balance_cap(db: Session, user: User | None, current_balance: Decimal, incoming: Decimal,
                      currency: str) -> None:
    """Wallets of individuals are capped by KYC tier (``transaction_type='*'`` rule)."""
    if user is None:
        return
    rule = _rule(db, user.kyc_tier, "*", currency)
    if rule and rule.max_balance is not None and current_balance + incoming > rule.max_balance:
        raise LimitExceeded(
            f"This would take the wallet above its maximum balance of {currency} {rule.max_balance:,.2f}. "
            "Upgrade your verification level to raise the limit.",
            details={"limit": "max_balance", "max": str(rule.max_balance)})


def limits_summary(db: Session, user: User, currency: str = "GHS") -> list[dict]:
    rules = db.scalars(select(LimitRule).where(LimitRule.kyc_tier == user.kyc_tier,
                                               LimitRule.currency == currency, LimitRule.active.is_(True))).all()
    now = datetime.now(timezone.utc)
    out = []
    for r in rules:
        item = {"transaction_type": r.transaction_type, "per_transaction_max": r.per_transaction_max,
                "daily_max": r.daily_max, "monthly_max": r.monthly_max, "max_balance": r.max_balance,
                "daily_used": ZERO, "monthly_used": ZERO}
        if r.transaction_type != "*":
            item["daily_used"] = _used(db, user, r.transaction_type, currency,
                                       now.replace(hour=0, minute=0, second=0, microsecond=0))
            item["monthly_used"] = _used(db, user, r.transaction_type, currency,
                                         now.replace(day=1, hour=0, minute=0, second=0, microsecond=0))
        out.append(item)
    return out

