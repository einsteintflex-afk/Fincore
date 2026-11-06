"""Aggregations for dashboards. All amounts returned as Decimal (serialised as strings)."""

from __future__ import annotations

import uuid
from datetime import timedelta
from decimal import Decimal

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.core.database import utcnow
from app.models.business import Business, PaymentRequest
from app.models.enums import AccountType, TxnStatus
from app.models.ledger import LedgerAccount, Wallet
from app.models.ops import FraudAlert, SupportTicket
from app.models.transaction import Transaction
from app.models.user import KycSubmission, User


def _d(v) -> Decimal:
    return Decimal(v or 0)


def platform_overview(db: Session, days: int = 30) -> dict:
    since = utcnow() - timedelta(days=days)
    by_type = db.execute(
        select(Transaction.type, func.count().label("n"),
               func.coalesce(func.sum(case((Transaction.status == TxnStatus.SUCCESSFUL, Transaction.amount),
                                           else_=0)), 0).label("volume"),
               func.coalesce(func.sum(case((Transaction.status == TxnStatus.SUCCESSFUL, Transaction.fee),
                                           else_=0)), 0).label("fees"),
               func.sum(case((Transaction.status == TxnStatus.FAILED, 1), else_=0)).label("failed"))
        .where(Transaction.created_at >= since).group_by(Transaction.type)).all()
    day = func.date_trunc("day", Transaction.created_at)
    daily = db.execute(
        select(day.label("day"), func.count().label("n"),
               func.coalesce(func.sum(case((Transaction.status == TxnStatus.SUCCESSFUL, Transaction.amount),
                                           else_=0)), 0).label("volume"))
        .where(Transaction.created_at >= since).group_by(day).order_by(day)).all()
    customer_funds = _d(db.scalar(select(func.sum(LedgerAccount.balance)).join(
        Wallet, Wallet.ledger_account_id == LedgerAccount.id).where(Wallet.user_id.isnot(None))))
    merchant_funds = _d(db.scalar(select(func.sum(LedgerAccount.balance)).join(
        Wallet, Wallet.ledger_account_id == LedgerAccount.id).where(Wallet.business_id.isnot(None))))
    revenue = _d(db.scalar(select(func.sum(LedgerAccount.balance)).where(
        LedgerAccount.type == AccountType.REVENUE, LedgerAccount.is_system.is_(True))))
    total = sum(r.n for r in by_type)
    failed = sum(int(r.failed or 0) for r in by_type)
    return {
        "period_days": days,
        "users": db.scalar(select(func.count()).select_from(User)),
        "new_users": db.scalar(select(func.count()).select_from(User).where(User.created_at >= since)),
        "businesses": db.scalar(select(func.count()).select_from(Business)),
        "pending_businesses": db.scalar(select(func.count()).select_from(Business).where(Business.status == "pending")),
        "pending_kyc": db.scalar(select(func.count()).select_from(KycSubmission).where(KycSubmission.status == "pending")),
        "open_fraud_alerts": db.scalar(select(func.count()).select_from(FraudAlert).where(FraudAlert.status.in_(["open", "investigating"]))),
        "open_tickets": db.scalar(select(func.count()).select_from(SupportTicket).where(SupportTicket.status.in_(["open", "pending"]))),
        "wallets": db.scalar(select(func.count()).select_from(Wallet)),
        "customer_funds": customer_funds,
        "merchant_funds": merchant_funds,
        "fee_revenue_total": revenue,
        "transactions": total,
        "failure_rate": round(failed / total, 4) if total else 0.0,
        "by_type": [{"type": r.type, "count": r.n, "volume": _d(r.volume), "fees": _d(r.fees),
                     "failed": int(r.failed or 0)} for r in by_type],
        "daily": [{"day": r.day.date().isoformat(), "count": r.n, "volume": _d(r.volume)} for r in daily],
    }


def failure_analysis(db: Session, days: int = 30) -> dict:
    since = utcnow() - timedelta(days=days)
    rows = db.execute(
        select(Transaction.type, Transaction.provider, Transaction.failure_reason, func.count().label("n"))
        .where(Transaction.created_at >= since, Transaction.status == TxnStatus.FAILED)
        .group_by(Transaction.type, Transaction.provider, Transaction.failure_reason)
        .order_by(func.count().desc()).limit(50)).all()
    by_provider = db.execute(
        select(Transaction.provider, func.count().label("n"),
               func.sum(case((Transaction.status == TxnStatus.FAILED, 1), else_=0)).label("failed"))
        .where(Transaction.created_at >= since, Transaction.provider.notin_(["internal"]))
        .group_by(Transaction.provider)).all()
    return {
        "reasons": [{"type": r.type, "provider": r.provider, "reason": r.failure_reason or "unknown", "count": r.n}
                    for r in rows],
        "providers": [{"provider": r.provider, "total": r.n, "failed": int(r.failed or 0),
                       "failure_rate": round(int(r.failed or 0) / r.n, 4) if r.n else 0.0} for r in by_provider],
    }


def merchant_performance(db: Session, days: int = 30, limit: int = 20) -> list[dict]:
    since = utcnow() - timedelta(days=days)
    rows = db.execute(
        select(Business.id, Business.name, Business.merchant_code, func.count(PaymentRequest.id).label("n"),
               func.coalesce(func.sum(case((PaymentRequest.paid_at.isnot(None), PaymentRequest.amount), else_=0)), 0).label("volume"),
               func.coalesce(func.sum(case((PaymentRequest.paid_at.isnot(None), PaymentRequest.fee), else_=0)), 0).label("fees"),
               func.sum(case((PaymentRequest.paid_at.isnot(None), 1), else_=0)).label("paid"))
        .join(PaymentRequest, PaymentRequest.business_id == Business.id)
        .where(PaymentRequest.created_at >= since, PaymentRequest.environment == "live")
        .group_by(Business.id).order_by(func.sum(PaymentRequest.amount).desc()).limit(limit)).all()
    return [{"business_id": str(r.id), "name": r.name, "merchant_code": r.merchant_code, "charges": r.n,
             "successful": int(r.paid or 0), "conversion": round(int(r.paid or 0) / r.n, 4) if r.n else 0.0,
             "volume": _d(r.volume), "fees": _d(r.fees)} for r in rows]


def merchant_overview(db: Session, business_id: uuid.UUID, environment: str = "live", days: int = 30) -> dict:
    since = utcnow() - timedelta(days=days)
    base = (PaymentRequest.business_id == business_id, PaymentRequest.environment == environment,
            PaymentRequest.created_at >= since)
    paid = PaymentRequest.paid_at.isnot(None)
    agg = db.execute(select(
        func.count().label("n"),
        func.sum(case((paid, 1), else_=0)).label("paid"),
        func.coalesce(func.sum(case((paid, PaymentRequest.amount), else_=0)), 0).label("volume"),
        func.coalesce(func.sum(case((paid, PaymentRequest.fee), else_=0)), 0).label("fees"),
        func.coalesce(func.sum(PaymentRequest.amount_refunded), 0).label("refunded")).where(*base)).one()
    day = func.date_trunc("day", PaymentRequest.created_at)
    daily = db.execute(select(day.label("day"), func.coalesce(func.sum(case((paid, PaymentRequest.amount), else_=0)), 0).label("volume"),
                              func.count().label("n")).where(*base).group_by(day).order_by(day)).all()
    channels = db.execute(select(PaymentRequest.channel, PaymentRequest.network, func.count().label("n"))
                          .where(*base, paid).group_by(PaymentRequest.channel, PaymentRequest.network)).all()
    n = agg.n or 0
    return {"environment": environment, "period_days": days, "charges": n, "successful": int(agg.paid or 0),
            "conversion": round(int(agg.paid or 0) / n, 4) if n else 0.0, "volume": _d(agg.volume),
            "fees": _d(agg.fees), "refunded": _d(agg.refunded),
            "daily": [{"day": r.day.date().isoformat(), "volume": _d(r.volume), "count": r.n} for r in daily],
            "channels": [{"channel": r.channel, "network": r.network, "count": r.n} for r in channels]}


def customer_summary(db: Session, user: User, days: int = 30) -> dict:
    since = utcnow() - timedelta(days=days)
    wallet_ids = [w for w in db.scalars(select(Wallet.id).where(Wallet.user_id == user.id))]
    if not wallet_ids:
        return {"money_in": Decimal(0), "money_out": Decimal(0), "by_type": []}
    ok = Transaction.status == TxnStatus.SUCCESSFUL
    money_in = _d(db.scalar(select(func.sum(Transaction.amount - case((Transaction.type == "deposit", Transaction.fee), else_=0)))
                            .where(Transaction.destination_wallet_id.in_(wallet_ids), ok, Transaction.created_at >= since)))
    money_out = _d(db.scalar(select(func.sum(Transaction.amount + case((Transaction.type == "payment", 0), else_=Transaction.fee)))
                             .where(Transaction.source_wallet_id.in_(wallet_ids), ok, Transaction.created_at >= since)))
    by_type = db.execute(select(Transaction.type, func.sum(Transaction.amount).label("total"), func.count().label("n"))
                         .where(Transaction.source_wallet_id.in_(wallet_ids), ok, Transaction.created_at >= since)
                         .group_by(Transaction.type)).all()
    return {"period_days": days, "money_in": money_in, "money_out": money_out,
            "by_type": [{"type": r.type, "total": _d(r.total), "count": r.n} for r in by_type]}
