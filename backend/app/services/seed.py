"""Reference data: fee schedule, KYC tier limits, system ledger accounts, system settings.

Values are PLACEHOLDERS chosen to be realistic for a Ghanaian e-money product. Compliance must confirm
limits against the current Bank of Ghana e-money / payment-service-provider guidelines before go-live,
and the business owner must approve the fee schedule.
"""

from __future__ import annotations

from decimal import Decimal as D

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.ops import SystemSetting
from app.models.transaction import FeeRule, LimitRule
from app.services.ledger import LedgerService, SystemAccount

FEES = [
    # name, type, channel, payer, flat, percent, min, max
    ("Wallet-to-wallet transfer", "transfer", "wallet", "customer", "0", "0", "0", None),
    ("Mobile money deposit", "deposit", "mobile_money", "customer", "0", "0", "0", None),
    ("Withdrawal to mobile money", "withdrawal", "mobile_money", "customer", "0", "0.0075", "0.50", "15.00"),
    ("Withdrawal to bank", "withdrawal", "bank", "customer", "2.00", "0", "2.00", "2.00"),
    ("Merchant payment (MDR)", "payment", None, "merchant", "0", "0.0150", "0.10", "200.00"),
    ("Settlement to bank", "settlement", "bank", "merchant", "0", "0", "0", None),
    ("Settlement to mobile money", "settlement", "mobile_money", "merchant", "0", "0.0050", "0.50", "10.00"),
]

LIMITS = {
    # tier: (max_balance, {type: (per_txn, daily, monthly)})
    0: ("500", {"deposit": ("200", "500", "1000"), "transfer": ("100", "200", "1000"),
                "withdrawal": ("100", "200", "1000"), "payment": ("200", "500", "1000")}),
    1: ("5000", {"deposit": ("2000", "3000", "15000"), "transfer": ("2000", "3000", "15000"),
                 "withdrawal": ("2000", "3000", "15000"), "payment": ("2000", "3000", "15000")}),
    2: ("25000", {"deposit": ("10000", "10000", "75000"), "transfer": ("10000", "10000", "75000"),
                  "withdrawal": ("10000", "10000", "75000"), "payment": ("10000", "10000", "75000")}),
    3: ("100000", {"deposit": ("50000", "50000", "500000"), "transfer": ("50000", "50000", "500000"),
                   "withdrawal": ("50000", "50000", "500000"), "payment": ("50000", "50000", "500000")}),
}

SETTINGS = {
    "maintenance_mode": ({"enabled": False, "message": ""}, "Block all money movement with a banner message"),
    "signup_enabled": ({"enabled": True}, "Allow new customer registrations"),
    "support_contact": ({"email": "support@fincore.example", "phone": "+233 30 000 0000"}, "Customer support contacts"),
}


def seed_reference_data(db: Session) -> dict:
    created = {"fees": 0, "limits": 0, "accounts": 0, "settings": 0}
    for name, ttype, channel, payer, flat, pct, mn, mx in FEES:
        exists = db.scalar(select(FeeRule.id).where(FeeRule.transaction_type == ttype, FeeRule.channel.is_(channel)
                                                    if channel is None else FeeRule.channel == channel,
                                                    FeeRule.payer == payer, FeeRule.currency == "GHS"))
        if not exists:
            db.add(FeeRule(name=name, transaction_type=ttype, channel=channel, payer=payer, currency="GHS",
                           flat_fee=D(flat), percent_fee=D(pct), min_fee=D(mn), max_fee=D(mx) if mx else None))
            created["fees"] += 1
    for tier, (max_bal, rules) in LIMITS.items():
        if not db.scalar(select(LimitRule.id).where(LimitRule.kyc_tier == tier, LimitRule.transaction_type == "*")):
            db.add(LimitRule(kyc_tier=tier, transaction_type="*", currency="GHS", max_balance=D(max_bal)))
            created["limits"] += 1
        for ttype, (per, daily, monthly) in rules.items():
            if not db.scalar(select(LimitRule.id).where(LimitRule.kyc_tier == tier, LimitRule.transaction_type == ttype)):
                db.add(LimitRule(kyc_tier=tier, transaction_type=ttype, currency="GHS", per_transaction_max=D(per),
                                 daily_max=D(daily), monthly_max=D(monthly)))
                created["limits"] += 1
    ledger = LedgerService(db)
    for purpose in (SystemAccount.FEE_REVENUE, SystemAccount.PENDING_PAYOUTS, SystemAccount.SUSPENSE,
                    SystemAccount.ADJUSTMENTS, SystemAccount.EQUITY, SystemAccount.clearing("sandbox")):
        ledger.system_account(purpose, "GHS")
    for key, (value, desc) in SETTINGS.items():
        if not db.get(SystemSetting, key):
            db.add(SystemSetting(key=key, value=value, description=desc))
            created["settings"] += 1
    db.commit()
    return created
