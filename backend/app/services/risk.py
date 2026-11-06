"""Rules-based transaction risk scoring.

Scores >= ``BLOCK_SCORE`` stop the transaction; scores >= ``ALERT_SCORE`` raise a fraud alert for review.
This is a starting point – production should add device fingerprinting, sanctions/PEP screening and an
ML model fed by confirmed fraud outcomes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.ops import FraudAlert
from app.models.transaction import Transaction
from app.models.user import User

ALERT_SCORE = 40
BLOCK_SCORE = 90
LARGE_AMOUNT = Decimal("10000")
NEW_ACCOUNT_AMOUNT = Decimal("2000")
VELOCITY_WINDOW = timedelta(hours=1)
VELOCITY_COUNT = 10


@dataclass
class RiskAssessment:
    score: int = 0
    reasons: list[tuple[str, int, dict]] = field(default_factory=list)

    def add(self, rule: str, points: int, **details) -> None:
        self.score += points
        self.reasons.append((rule, points, details))

    @property
    def blocked(self) -> bool:
        return self.score >= BLOCK_SCORE

    @property
    def needs_review(self) -> bool:
        return self.score >= ALERT_SCORE


def assess(db: Session, user: User, txn_type: str, amount: Decimal, *, counterparty_key: str | None = None) -> RiskAssessment:
    ra = RiskAssessment()
    now = datetime.now(timezone.utc)

    if amount >= LARGE_AMOUNT:
        ra.add("large_amount", 40, amount=str(amount))

    created = user.created_at if user.created_at.tzinfo else user.created_at.replace(tzinfo=timezone.utc)
    if now - created < timedelta(hours=24) and amount >= NEW_ACCOUNT_AMOUNT:
        ra.add("new_account_high_value", 30, account_age_hours=round((now - created).total_seconds() / 3600, 1))

    recent = db.scalar(select(func.count()).select_from(Transaction).where(
        Transaction.initiated_by_id == user.id, Transaction.created_at >= now - VELOCITY_WINDOW,
        Transaction.type.in_(["withdrawal", "transfer", "payment"])))
    if recent >= VELOCITY_COUNT:
        ra.add("velocity", 40, transactions_last_hour=recent)

    if user.kyc_tier == 0 and txn_type == "withdrawal":
        ra.add("unverified_withdrawal", 10)

    return ra


def record_alerts(db: Session, ra: RiskAssessment, *, user_id, transaction_id=None) -> None:
    if not ra.needs_review:
        return
    severity = "critical" if ra.blocked else ("high" if ra.score >= 70 else "medium")
    for rule, points, details in ra.reasons:
        db.add(FraudAlert(user_id=user_id, transaction_id=transaction_id, rule=rule, severity=severity,
                          score=ra.score, details={**details, "points": points}))
