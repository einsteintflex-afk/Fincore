from __future__ import annotations

import secrets
import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.errors import Forbidden, NotFound, ValidationFailed
from app.core.money import ZERO
from app.models.business import Business
from app.models.enums import AccountType
from app.models.ledger import LedgerAccount, LedgerEntry, LedgerTransaction, Wallet
from app.models.transaction import Transaction
from app.models.user import User
from app.services.ledger import LedgerService


def luhn_check_digit(number: str) -> str:
    total = 0
    for i, ch in enumerate(reversed(number)):
        d = int(ch)
        if i % 2 == 0:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return str((10 - total % 10) % 10)


def is_valid_account_number(number: str) -> bool:
    return number.isdigit() and len(number) == 10 and luhn_check_digit(number[:-1]) == number[-1]


def generate_account_number(db: Session, prefix: str) -> str:
    for _ in range(20):
        body = prefix + "".join(secrets.choice("0123456789") for _ in range(9 - len(prefix)))
        number = body + luhn_check_digit(body)
        if not db.scalar(select(Wallet.id).where(Wallet.account_number == number)):
            return number
    raise RuntimeError("Could not allocate a unique account number")


def create_wallet(db: Session, *, user: User | None = None, business: Business | None = None,
                  currency: str = "GHS", label: str = "Main", is_default: bool = False) -> Wallet:
    if (user is None) == (business is None):
        raise ValueError("A wallet belongs to exactly one user or business")
    number = generate_account_number(db, "1" if user else "2")
    owner_name = user.full_name if user else business.name
    acct = LedgerService(db).create_account(
        code=f"WAL:{number}", name=f"{owner_name} – {label} ({currency})",
        type=AccountType.LIABILITY, currency=currency)
    wallet = Wallet(account_number=number, user_id=user.id if user else None,
                    business_id=business.id if business else None, ledger_account_id=acct.id,
                    currency=currency, label=label, is_default=is_default)
    db.add(wallet)
    db.flush()
    return wallet


def user_wallets(db: Session, user: User) -> list[Wallet]:
    return list(db.scalars(select(Wallet).where(Wallet.user_id == user.id).order_by(Wallet.created_at)))


def business_wallets(db: Session, business_id: uuid.UUID) -> list[Wallet]:
    return list(db.scalars(select(Wallet).where(Wallet.business_id == business_id).order_by(Wallet.created_at)))


def get_owned_wallet(db: Session, user: User, wallet_id: uuid.UUID) -> Wallet:
    wallet = db.get(Wallet, wallet_id)
    if not wallet or wallet.user_id != user.id:
        raise NotFound("Wallet not found")
    return wallet


def default_user_wallet(db: Session, user: User, currency: str = "GHS") -> Wallet:
    wallet = db.scalar(select(Wallet).where(Wallet.user_id == user.id, Wallet.currency == currency)
                       .order_by(Wallet.is_default.desc(), Wallet.created_at))
    if not wallet:
        raise NotFound(f"No {currency} wallet")
    return wallet


def default_business_wallet(db: Session, business_id: uuid.UUID, currency: str = "GHS") -> Wallet:
    wallet = db.scalar(select(Wallet).where(Wallet.business_id == business_id, Wallet.currency == currency)
                       .order_by(Wallet.is_default.desc(), Wallet.created_at))
    if not wallet:
        raise NotFound(f"Business has no {currency} wallet")
    return wallet


def wallet_by_number(db: Session, number: str) -> Wallet:
    if not is_valid_account_number(number):
        raise ValidationFailed("Invalid FinCore account number")
    wallet = db.scalar(select(Wallet).where(Wallet.account_number == number))
    if not wallet:
        raise NotFound("No FinCore account with that number")
    return wallet


def wallet_owner_name(db: Session, wallet: Wallet) -> str:
    if wallet.user_id:
        u = db.get(User, wallet.user_id)
        return u.full_name if u else "Unknown"
    b = db.get(Business, wallet.business_id)
    return (b.trading_name or b.name) if b else "Unknown"


def balance(db: Session, wallet: Wallet) -> Decimal:
    acct = db.get(LedgerAccount, wallet.ledger_account_id)
    db.refresh(acct)
    return acct.balance


def assert_wallet_active(wallet: Wallet) -> None:
    if wallet.status != "active":
        raise Forbidden("Wallet is not active", code="wallet_inactive")


def statement(db: Session, wallet: Wallet, start: datetime, end: datetime) -> dict:
    acct_id = wallet.ledger_account_id
    prior = db.scalar(select(LedgerEntry).where(LedgerEntry.account_id == acct_id, LedgerEntry.created_at < start)
                      .order_by(LedgerEntry.created_at.desc(), LedgerEntry.line.desc()).limit(1))
    opening = prior.balance_after if prior else ZERO
    rows = db.execute(
        select(LedgerEntry, LedgerTransaction)
        .join(LedgerTransaction, LedgerTransaction.id == LedgerEntry.transaction_id)
        .where(LedgerEntry.account_id == acct_id, LedgerEntry.created_at >= start, LedgerEntry.created_at < end)
        .order_by(LedgerEntry.created_at, LedgerEntry.line)
    ).all()
    lj_ids = [lt.id for _, lt in rows]
    txn_map: dict[uuid.UUID, Transaction] = {}
    if lj_ids:
        for t in db.scalars(select(Transaction).where(or_(Transaction.ledger_transaction_id.in_(lj_ids),
                                                          Transaction.completion_ledger_transaction_id.in_(lj_ids)))):
            if t.ledger_transaction_id:
                txn_map[t.ledger_transaction_id] = t
            if t.completion_ledger_transaction_id:
                txn_map[t.completion_ledger_transaction_id] = t
    lines = []
    total_in = total_out = ZERO
    for entry, lt in rows:
        t = txn_map.get(lt.id)
        credit = entry.direction == "credit"
        if credit:
            total_in += entry.amount
        else:
            total_out += entry.amount
        lines.append({
            "date": entry.created_at, "reference": t.reference if t else lt.reference,
            "description": (t.description if t and t.description else lt.description) or lt.kind,
            "type": t.type if t else lt.kind,
            "credit": entry.amount if credit else ZERO, "debit": ZERO if credit else entry.amount,
            "balance": entry.balance_after,
        })
    closing = lines[-1]["balance"] if lines else opening
    return {"account_number": wallet.account_number, "currency": wallet.currency, "period_start": start,
            "period_end": end, "opening_balance": opening, "closing_balance": closing,
            "total_credits": total_in, "total_debits": total_out, "lines": lines}
