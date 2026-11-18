"""Application payouts: a connected application sends money from its business balance to a mobile money number.

A payout is a withdrawal (``TxnType.WITHDRAWAL``) from the application's business wallet, so it uses the same
two-phase ledger flow and the same configurable withdrawal fee (deducted from the requested amount):

    hold      DR business wallet  amount          / CR PENDING_PAYOUTS  amount
    success   DR PENDING_PAYOUTS  amount          / CR provider clearing  net  + CR FEE_REVENUE  fee
    failure   compensating reversal of the hold   (the full amount returns; no fee is kept)

A submitted payout is not a successful payout: it stays ``processing`` until the provider confirms it.
"""

from __future__ import annotations

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.api.deps import ApiContext
from app.core.errors import Conflict, NotFound, ValidationFailed
from app.core.money import to_api_str
from app.models.developer import AppSubscriber
from app.models.enums import Channel, TxnStatus, TxnType
from app.models.transaction import Transaction
from app.schemas.common import PayoutIn
from app.services.transactions import TransactionService, payout_amount
from app.services.wallets import default_business_wallet


def _existing(db: Session, ctx: ApiContext, merchant_reference: str) -> Transaction | None:
    return db.scalar(select(Transaction).where(
        Transaction.app_id == ctx.app.id, Transaction.type == TxnType.WITHDRAWAL,
        Transaction.meta["merchant_reference"].as_string() == merchant_reference))


def create_payout(db: Session, ctx: ApiContext, body: PayoutIn, subscriber: AppSubscriber | None) -> Transaction:
    if body.currency != "GHS":
        raise ValidationFailed("Only GHS payouts are supported")
    # Serialise payouts with the same reference for this app, then refuse duplicates (one payout, one fee).
    db.execute(text("SELECT pg_advisory_xact_lock(hashtext(:k))"),
               {"k": f"payout:{ctx.app.id}:{body.reference}"})
    if _existing(db, ctx, body.reference):
        db.rollback()
        raise Conflict("A payout with this reference already exists", code="duplicate_reference")
    wallet = default_business_wallet(db, ctx.business.id, body.currency)
    if not wallet:
        raise ValidationFailed("This application's business has no balance to pay out from")
    svc = TransactionService(db)
    meta = {"merchant_reference": body.reference, "api_key_id": str(ctx.key.id)}
    if subscriber:
        meta["subscriber_id"] = str(subscriber.id)
    return svc.withdraw_from_wallet(None, wallet, body.amount, channel=Channel.MOBILE_MONEY, phone=body.phone,
                                    account_name=body.account_name, description=body.description or "",
                                    expected_fee_percent=body.expected_fee_percent, app_id=ctx.app.id,
                                    business_id=ctx.business.id, meta=meta)


def get_app_payout(db: Session, ctx: ApiContext, reference: str) -> Transaction:
    txn = db.scalar(select(Transaction).where(
        Transaction.app_id == ctx.app.id, Transaction.type == TxnType.WITHDRAWAL,
        (Transaction.reference == reference) | (Transaction.meta["merchant_reference"].as_string() == reference)))
    if not txn:
        raise NotFound("Payout not found")
    return txn


def refresh(db: Session, txn: Transaction) -> Transaction:
    if txn.status == TxnStatus.PROCESSING:
        TransactionService(db).refresh_from_provider(txn)
    return txn


def payout_out(txn: Transaction) -> dict:
    meta = txn.meta or {}
    rate = txn.fee_rate
    return {
        "reference": txn.reference, "merchant_reference": meta.get("merchant_reference"), "livemode": True,
        "status": txn.status, "outcome": meta.get("provider_outcome"),
        "amount": to_api_str(txn.amount), "fee": to_api_str(txn.fee),
        "fee_percent": format((rate * 100).normalize(), "f") if rate is not None else None,
        "net_amount": to_api_str(payout_amount(txn)), "currency": txn.currency,
        "recipient": (txn.counterparty or {}).get("label"), "provider": txn.provider,
        "provider_mode": txn.provider_mode, "failure_reason": txn.failure_reason,
        "created_at": txn.created_at.isoformat() if txn.created_at else None,
        "completed_at": txn.completed_at.isoformat() if txn.completed_at else None,
    }
