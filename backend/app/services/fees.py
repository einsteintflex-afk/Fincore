from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import cache
from app.core.money import ZERO, round_money
from app.models.transaction import FeeRule


def _active_rules(db: Session, txn_type: str, currency: str, payer: str) -> list[SimpleNamespace]:
    def load():
        return [SimpleNamespace(channel=r.channel, flat_fee=r.flat_fee, percent_fee=r.percent_fee,
                                min_fee=r.min_fee, max_fee=r.max_fee)
                for r in db.scalars(select(FeeRule).where(
                    FeeRule.active.is_(True), FeeRule.transaction_type == txn_type,
                    FeeRule.currency == currency, FeeRule.payer == payer).order_by(FeeRule.created_at))]
    return cache.get_or_load(("fee_rules", txn_type, currency, payer), load)


def find_rule(db: Session, txn_type: str, channel: str | None, currency: str, payer: str) -> SimpleNamespace | None:
    rules = _active_rules(db, txn_type, currency, payer)
    # Prefer a channel-specific rule over a generic (channel = NULL) one.
    specific = [r for r in rules if r.channel and r.channel == channel]
    generic = [r for r in rules if r.channel is None]
    return (specific or generic or [None])[0]


def compute_fee(db: Session, txn_type: str, amount: Decimal, currency: str, *, channel: str | None = None,
                payer: str = "customer") -> Decimal:
    rule = find_rule(db, txn_type, channel, currency, payer)
    if not rule:
        return ZERO
    fee = rule.flat_fee + amount * rule.percent_fee
    if fee < rule.min_fee:
        fee = rule.min_fee
    if rule.max_fee is not None and fee > rule.max_fee:
        fee = rule.max_fee
    fee = round_money(fee, currency)
    return min(fee, amount) if payer == "merchant" else fee
