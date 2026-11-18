"""The withdrawal fee: a configurable percentage (default 15%) DEDUCTED from the requested amount.

    fee          = round(requested × rate)        (half-up, to the currency's minor unit)
    net payout   = requested − fee                (what the recipient receives)
    total debit  = requested                      (what leaves the wallet)

Applies only to withdrawals (wallet withdrawals and application payouts). It is never applied to collections,
internal transfers, merchant settlements, refunds, reversals or reconciliation adjustments.

Each withdrawal stores the rate it was charged at (``transactions.fee_rate``) and its net payout, so changing the
setting never alters history. The fee is recognised as revenue only when the payout succeeds; a failed payout
returns the full requested amount and no fee is kept.
"""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy.orm import Session

from app.core import cache
from app.core.errors import Conflict, ValidationFailed
from app.core.money import round_money, to_api_str, validate_amount
from app.models.ops import SystemSetting
from app.models.user import User
from app.services.audit import audit

SETTING_KEY = "withdrawal_fee"
DEFAULT_PERCENT = Decimal("15")
MAX_PERCENT = Decimal("50")  # a sanity ceiling; change deliberately in code if ever needed


def current_percent(db: Session) -> Decimal:
    def load():
        s = db.get(SystemSetting, SETTING_KEY)
        return str((s.value or {}).get("percent", DEFAULT_PERCENT)) if s else str(DEFAULT_PERCENT)
    return Decimal(cache.get_or_load(("setting", SETTING_KEY), load, ttl=10))


def current_rate(db: Session) -> Decimal:
    return current_percent(db) / Decimal(100)


def calculate(amount: Decimal, rate: Decimal, currency: str) -> tuple[Decimal, Decimal]:
    """Return (fee, net). Pure function — unit tested with the 100 → 15 / 85 example."""
    fee = round_money(amount * rate, currency)
    net = amount - fee
    if net <= 0:
        raise ValidationFailed("The amount is too small to cover the withdrawal fee", code="amount_too_small")
    return fee, net


def quote(db: Session, amount: object, currency: str) -> dict:
    amount = validate_amount(amount, currency)
    pct = current_percent(db)
    fee, net = calculate(amount, pct / Decimal(100), currency)
    return {"currency": currency, "requested_amount": to_api_str(amount),
            "fee_percent": format(pct.normalize(), "f"), "fee_amount": to_api_str(fee),
            "net_amount": to_api_str(net), "total_debit": to_api_str(amount)}


def check_expected(db: Session, expected_percent: object | None) -> None:
    """If the client showed the user a fee percentage, refuse to proceed when the setting changed since."""
    if expected_percent is None:
        return
    try:
        expected = Decimal(str(expected_percent))
    except Exception as exc:  # noqa: BLE001
        raise ValidationFailed("expected_fee_percent must be a number") from exc
    if expected != current_percent(db):
        raise Conflict("The withdrawal fee changed since you saw it. Review the new amounts and confirm again.",
                       code="fee_changed", details={"fee_percent": format(current_percent(db).normalize(), "f")})


def set_percent(db: Session, staff: User, percent: object) -> Decimal:
    try:
        pct = Decimal(str(percent))
    except Exception as exc:  # noqa: BLE001
        raise ValidationFailed("percent must be a number") from exc
    if not pct.is_finite() or pct < 0 or pct > MAX_PERCENT or pct.as_tuple().exponent < -2:
        raise ValidationFailed(f"The fee must be between 0 and {MAX_PERCENT}% with at most 2 decimal places")
    old = current_percent(db)
    s = db.get(SystemSetting, SETTING_KEY) or SystemSetting(key=SETTING_KEY, value={})
    s.value = {"percent": format(pct.normalize(), "f")}
    s.updated_by_id = staff.id
    s.description = "Withdrawal fee (% of the requested amount, deducted from the payout)"
    db.merge(s)
    audit(db, "settings.withdrawal_fee_changed", actor_id=staff.id, actor_type="staff", target_type="setting",
          target_id=SETTING_KEY, details={"from": str(old), "to": str(pct)})
    db.commit()
    cache.clear()
    return pct
