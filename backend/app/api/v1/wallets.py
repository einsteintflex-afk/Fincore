from __future__ import annotations

import csv
import io
import uuid
from datetime import date, datetime, time, timedelta, timezone

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response, StreamingResponse
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.api.deps import IdempotencyKey, current_user, money_movement_allowed, run_idempotent
from app.core.config import settings
from app.core.database import get_db
from app.core.errors import Conflict, Forbidden, NotFound, ValidationFailed
from app.models.ledger import Wallet
from app.models.transaction import Beneficiary, Transaction
from app.models.user import User
from app.providers import get_provider, route
from app.providers.base import ProviderResult
from app.schemas.common import (
    BeneficiaryIn,
    BeneficiaryOut,
    DepositIn,
    LookupOut,
    Message,
    Page,
    TransactionOut,
    TransferIn,
    WalletCreateIn,
    WalletOut,
    WithdrawIn,
)
from app.services import pdf
from app.services import wallets as wsvc
from app.services.audit import audit
from app.services.ghana import BANKS, NETWORK_NAMES, detect_network, normalize_msisdn, validate_bank
from app.services.transactions import TransactionService

router = APIRouter(tags=["Wallets & transactions"])


def pdf_response(content: bytes, filename: str) -> Response:
    return Response(content=content, media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="{filename}"', "Cache-Control": "no-store"})


def wallet_out(db: Session, w: Wallet) -> WalletOut:
    return WalletOut(id=w.id, account_number=w.account_number, currency=w.currency, label=w.label,
                     is_default=w.is_default, status=w.status, balance=wsvc.balance(db, w), created_at=w.created_at)


def txn_out(t: Transaction, wallet_ids: set[uuid.UUID] | None = None) -> TransactionOut:
    out = TransactionOut.model_validate(t)
    if wallet_ids is not None:
        if t.destination_wallet_id in wallet_ids and t.source_wallet_id not in wallet_ids:
            out.direction = "in"
            out.description = wsvc.incoming_description(t) or out.description
            out.fee = pdf.payer_fee(t, is_sender=False)
        elif t.source_wallet_id in wallet_ids:
            out.direction = "out"
            out.fee = pdf.payer_fee(t, is_sender=True)
    return out


# ---------------------------------------------------------------- wallets
@router.get("/wallets", response_model=list[WalletOut])
def list_wallets(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return [wallet_out(db, w) for w in wsvc.user_wallets(db, user)]


@router.post("/wallets", response_model=WalletOut, status_code=201)
def create_wallet(body: WalletCreateIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    if body.currency not in settings.supported_currencies:
        raise ValidationFailed(f"Currency {body.currency} is not available yet")
    if len(wsvc.user_wallets(db, user)) >= 5:
        raise Conflict("You can have at most 5 wallets")
    w = wsvc.create_wallet(db, user=user, currency=body.currency, label=body.label)
    audit(db, "wallet.created", actor_id=user.id, target_type="wallet", target_id=w.account_number)
    db.commit()
    return wallet_out(db, w)


@router.get("/wallets/lookup", response_model=LookupOut)
def lookup_wallet(account_number: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    try:
        w = wsvc.wallet_by_number(db, account_number)
    except (NotFound, ValidationFailed) as exc:
        return LookupOut(valid=False, message=exc.message)
    return LookupOut(valid=w.status == "active", account_name=wsvc.wallet_owner_name(db, w))


@router.get("/wallets/lookup-momo", response_model=LookupOut)
def lookup_momo(phone: str, user: User = Depends(current_user)):
    msisdn = normalize_msisdn(phone)
    network = detect_network(msisdn)
    res = route("mobile_money", network.value).lookup_account(msisdn=msisdn)
    return LookupOut(valid=res.valid, account_name=res.account_name, network=network.value,
                     message=res.message or NETWORK_NAMES[network])


@router.get("/wallets/lookup-bank", response_model=LookupOut)
def lookup_bank(bank_code: str, account_number: str, user: User = Depends(current_user)):
    code, acct = validate_bank(bank_code, account_number)
    res = route("bank").lookup_account(bank_code=code, account_number=acct)
    return LookupOut(valid=res.valid, account_name=res.account_name, message=res.message)


@router.get("/banks")
def banks():
    return [{"code": k, "name": v} for k, v in sorted(BANKS.items(), key=lambda kv: kv[1])]


@router.get("/wallets/{wallet_id}", response_model=WalletOut)
def get_wallet(wallet_id: uuid.UUID, user: User = Depends(current_user), db: Session = Depends(get_db)):
    return wallet_out(db, wsvc.get_owned_wallet(db, user, wallet_id))


def _period(start: date | None, end: date | None) -> tuple[datetime, datetime]:
    today = datetime.now(timezone.utc).date()
    end = end or today
    start = start or (end - timedelta(days=30))
    if start > end:
        raise ValidationFailed("start must be before end")
    if (end - start).days > 366:
        raise ValidationFailed("Statement period cannot exceed one year")
    return (datetime.combine(start, time.min, tzinfo=timezone.utc),
            datetime.combine(end + timedelta(days=1), time.min, tzinfo=timezone.utc))


@router.get("/wallets/{wallet_id}/statement")
def statement(wallet_id: uuid.UUID, start: date | None = None, end: date | None = None,
              format: str = Query("json", pattern="^(json|csv|pdf)$"), user: User = Depends(current_user),
              db: Session = Depends(get_db)):
    w = wsvc.get_owned_wallet(db, user, wallet_id)
    s, e = _period(start, end)
    data = wsvc.statement(db, w, s, e)
    if format == "json":
        return {**data, "account_name": user.full_name}
    if format == "pdf":
        name = f"fincore-statement-{w.account_number}-{s.date()}-{(e - timedelta(days=1)).date()}.pdf"
        return pdf_response(pdf.statement_pdf(data, user.full_name), name)
    buf = io.StringIO()
    wr = csv.writer(buf)
    wr.writerow(["FinCore statement", w.account_number, user.full_name])
    wr.writerow(["Period", s.date().isoformat(), (e - timedelta(days=1)).date().isoformat()])
    wr.writerow(["Opening balance", data["opening_balance"]])
    wr.writerow([])
    wr.writerow(["Date", "Reference", "Description", "Type", "Debit", "Credit", "Balance"])
    for ln in data["lines"]:
        wr.writerow([ln["date"].isoformat(), ln["reference"], ln["description"], ln["type"], ln["debit"],
                     ln["credit"], ln["balance"]])
    wr.writerow([])
    wr.writerow(["Closing balance", data["closing_balance"]])
    buf.seek(0)
    name = f"fincore-statement-{w.account_number}-{s.date()}-{(e - timedelta(days=1)).date()}.csv"
    return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv",
                             headers={"Content-Disposition": f'attachment; filename="{name}"'})


# ---------------------------------------------------------------- money movement
@router.post("/deposits", response_model=TransactionOut, status_code=201,
             dependencies=[Depends(money_movement_allowed)])
def deposit(body: DepositIn, idempotency_key: str | None = IdempotencyKey, user: User = Depends(current_user),
            db: Session = Depends(get_db)):
    def go():
        t = TransactionService(db).deposit_mobile_money(user, body.wallet_id, body.amount, body.phone,
                                                        body.description or "")
        return txn_out(t, {body.wallet_id})
    return run_idempotent(db, f"user:{user.id}:deposit", idempotency_key, body.model_dump(), go)


@router.post("/withdrawals", response_model=TransactionOut, status_code=201,
             dependencies=[Depends(money_movement_allowed)])
def withdraw(body: WithdrawIn, idempotency_key: str | None = IdempotencyKey, user: User = Depends(current_user),
             db: Session = Depends(get_db)):
    def go():
        t = TransactionService(db).withdraw(
            user, body.wallet_id, body.amount, channel=body.channel, phone=body.phone, bank_code=body.bank_code,
            account_number=body.account_number, account_name=body.account_name, description=body.description or "")
        db.refresh(t)
        return txn_out(t, {body.wallet_id})
    return run_idempotent(db, f"user:{user.id}:withdrawal", idempotency_key, body.model_dump(), go)


@router.post("/transfers", response_model=TransactionOut, status_code=201,
             dependencies=[Depends(money_movement_allowed)])
def transfer(body: TransferIn, idempotency_key: str | None = IdempotencyKey, user: User = Depends(current_user),
             db: Session = Depends(get_db)):
    def go():
        t = TransactionService(db).transfer(user, body.wallet_id, body.destination_account, body.amount,
                                            body.narration or "")
        return txn_out(t, {body.wallet_id})
    return run_idempotent(db, f"user:{user.id}:transfer", idempotency_key, body.model_dump(), go)


# ---------------------------------------------------------------- history
@router.get("/transactions", response_model=Page[TransactionOut])
def list_transactions(
    page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100), type: str | None = None,
    status: str | None = None, wallet_id: uuid.UUID | None = None, search: str | None = None,
    start: date | None = None, end: date | None = None, user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    ids = {w.id for w in wsvc.user_wallets(db, user)}
    scope = {wallet_id} & ids if wallet_id else ids
    if not scope:
        return Page(items=[], total=0, page=page, page_size=page_size)
    q = select(Transaction).where(or_(Transaction.source_wallet_id.in_(scope),
                                      Transaction.destination_wallet_id.in_(scope)))
    if type:
        q = q.where(Transaction.type == type)
    if status:
        q = q.where(Transaction.status == status)
    if search:
        like = f"%{search.strip()}%"
        q = q.where(or_(Transaction.reference.ilike(like), Transaction.description.ilike(like)))
    if start:
        q = q.where(Transaction.created_at >= datetime.combine(start, time.min, tzinfo=timezone.utc))
    if end:
        q = q.where(Transaction.created_at < datetime.combine(end + timedelta(days=1), time.min, tzinfo=timezone.utc))
    total = db.scalar(select(func.count()).select_from(q.subquery()))
    rows = db.scalars(q.order_by(Transaction.created_at.desc()).offset((page - 1) * page_size).limit(page_size))
    return Page(items=[txn_out(t, ids) for t in rows], total=total, page=page, page_size=page_size)


def _owned_txn(db: Session, user: User, ref_or_id: str) -> Transaction:
    try:
        t = db.get(Transaction, uuid.UUID(ref_or_id))
    except ValueError:
        t = db.scalar(select(Transaction).where(Transaction.reference == ref_or_id))
    ids = {w.id for w in wsvc.user_wallets(db, user)}
    if not t or not ({t.source_wallet_id, t.destination_wallet_id} & ids or t.initiated_by_id == user.id):
        raise NotFound("Transaction not found")
    return t


@router.get("/transactions/{ref}", response_model=TransactionOut)
def get_transaction(ref: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    t = _owned_txn(db, user, ref)
    return txn_out(t, {w.id for w in wsvc.user_wallets(db, user)})


@router.get("/transactions/{ref}/receipt.pdf", response_class=Response)
def transaction_receipt(ref: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    t = _owned_txn(db, user, ref)
    return pdf_response(pdf.transaction_receipt(t, {w.id for w in wsvc.user_wallets(db, user)}),
                        f"fincore-receipt-{t.reference}.pdf")


@router.post("/transactions/{ref}/refresh", response_model=TransactionOut)
def refresh_transaction(ref: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    t = _owned_txn(db, user, ref)
    TransactionService(db).refresh_from_provider(t)
    return txn_out(t, {w.id for w in wsvc.user_wallets(db, user)})


@router.post("/transactions/{ref}/simulate", response_model=TransactionOut,
             summary="Sandbox only: resolve a pending simulated transaction")
def simulate(ref: str, outcome: str = Query(pattern="^(successful|failed)$"), user: User = Depends(current_user),
             db: Session = Depends(get_db)):
    if settings.is_production and settings.live_payments_enabled:
        raise Forbidden("Simulation is disabled in live production")
    t = _owned_txn(db, user, ref)
    if t.provider != "sandbox":
        raise Forbidden("Only sandbox transactions can be simulated")
    provider = get_provider("sandbox")
    event = provider.parse_webhook({"provider_reference": t.provider_reference or t.reference, "status": outcome,
                                    "reference": t.reference})
    TransactionService(db).apply_provider_result(
        t, ProviderResult(status=event.status, provider_reference=event.provider_reference, message="Simulated"))
    db.commit()
    return txn_out(t, {w.id for w in wsvc.user_wallets(db, user)})



# ---------------------------------------------------------------- beneficiaries
@router.get("/beneficiaries", response_model=list[BeneficiaryOut])
def list_beneficiaries(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return db.scalars(select(Beneficiary).where(Beneficiary.user_id == user.id)
                      .order_by(Beneficiary.favourite.desc(), Beneficiary.name)).all()


@router.post("/beneficiaries", response_model=BeneficiaryOut, status_code=201)
def add_beneficiary(body: BeneficiaryIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    network = bank_code = None
    identifier = body.identifier.strip()
    if body.type == "wallet":
        wsvc.wallet_by_number(db, identifier)
    elif body.type == "mobile_money":
        identifier = normalize_msisdn(identifier)
        network = detect_network(identifier).value
    else:
        bank_code, identifier = validate_bank(body.bank_code or "", identifier)
    if db.scalar(select(Beneficiary.id).where(Beneficiary.user_id == user.id, Beneficiary.type == body.type,
                                              Beneficiary.identifier == identifier)):
        raise Conflict("Beneficiary already saved")
    b = Beneficiary(user_id=user.id, type=body.type, name=body.name, nickname=body.nickname, identifier=identifier,
                    network=network, bank_code=bank_code)
    db.add(b)
    db.commit()
    return b


@router.post("/beneficiaries/{beneficiary_id}/favourite", response_model=BeneficiaryOut)
def toggle_favourite(beneficiary_id: uuid.UUID, user: User = Depends(current_user), db: Session = Depends(get_db)):
    b = db.get(Beneficiary, beneficiary_id)
    if not b or b.user_id != user.id:
        raise NotFound("Beneficiary not found")
    b.favourite = not b.favourite
    db.commit()
    return b


@router.delete("/beneficiaries/{beneficiary_id}", response_model=Message)
def delete_beneficiary(beneficiary_id: uuid.UUID, user: User = Depends(current_user), db: Session = Depends(get_db)):
    b = db.get(Beneficiary, beneficiary_id)
    if not b or b.user_id != user.id:
        raise NotFound("Beneficiary not found")
    db.delete(b)
    db.commit()
    return {"message": "Beneficiary removed"}
