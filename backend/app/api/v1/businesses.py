"""Merchant dashboard API: business profile, team, collections, payment links, refunds, settlements, reports."""

from __future__ import annotations

import uuid
from datetime import date, datetime, time, timedelta, timezone

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.api.deps import IdempotencyKey, current_user, money_movement_allowed, run_idempotent
from app.api.v1.wallets import pdf_response, txn_out, wallet_out
from app.core.config import settings
from app.core.database import get_db
from app.core.errors import NotFound
from app.core.money import validate_amount
from app.models.business import BusinessMember, PaymentLink, PaymentRequest, Refund, Settlement
from app.models.transaction import Transaction
from app.models.user import User
from app.schemas.common import (
    BusinessIn,
    BusinessOut,
    BusinessUpdateIn,
    MemberIn,
    MemberOut,
    MemberUpdateIn,
    Page,
    PaymentLinkIn,
    PaymentLinkOut,
    PaymentLinkUpdateIn,
    PaymentRequestIn,
    PaymentRequestOut,
    RefundIn,
    RefundOut,
    SettlementDestinationIn,
    SettlementIn,
    SettlementOut,
    TransactionOut,
    WalletOut,
)
from app.services import analytics, forms, pdf
from app.services import business as bsvc
from app.services.audit import audit
from app.services.payments import PaymentService
from app.services.reconciliation import settlement_report
from app.services.wallets import business_wallets

router = APIRouter(prefix="/businesses", tags=["Businesses & merchants"])


def biz_out(b, role: str | None = None) -> BusinessOut:
    out = BusinessOut.model_validate(b)
    out.my_role = role
    return out


def pr_out(pr: PaymentRequest) -> PaymentRequestOut:
    out = PaymentRequestOut.model_validate(pr)
    out.checkout_url = f"{settings.frontend_base_url}/checkout/{pr.reference}"
    return out


def link_out(link: PaymentLink) -> PaymentLinkOut:
    out = PaymentLinkOut.model_validate(link)
    out.url = f"{settings.frontend_base_url}/pay/{link.slug}"
    return out


def _range(start: date | None, end: date | None, default_days: int = 30) -> tuple[datetime, datetime]:
    end = end or datetime.now(timezone.utc).date()
    start = start or end - timedelta(days=default_days)
    return (datetime.combine(start, time.min, tzinfo=timezone.utc),
            datetime.combine(end + timedelta(days=1), time.min, tzinfo=timezone.utc))


# ---------------------------------------------------------------- profile
@router.post("", response_model=BusinessOut, status_code=201)
def create(body: BusinessIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    return biz_out(bsvc.create_business(db, user, body.model_dump()), "owner")


@router.get("", response_model=list[BusinessOut])
def mine(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return [biz_out(b, m.role) for b, m in bsvc.memberships(db, user)]


@router.get("/{business_id}", response_model=BusinessOut)
def get(business_id: uuid.UUID, user: User = Depends(current_user), db: Session = Depends(get_db)):
    b = bsvc.require_permission(db, user, business_id, "business:view")
    role = bsvc.member_role(db, user, business_id)
    out = biz_out(b, role)
    return out


@router.get("/{business_id}/permissions")
def permissions(business_id: uuid.UUID, user: User = Depends(current_user), db: Session = Depends(get_db)):
    bsvc.require_permission(db, user, business_id, "business:view")
    role = bsvc.member_role(db, user, business_id)
    return {"role": role, "permissions": sorted(bsvc.ROLE_PERMISSIONS.get(role, set()))}


@router.patch("/{business_id}", response_model=BusinessOut)
def update(business_id: uuid.UUID, body: BusinessUpdateIn, user: User = Depends(current_user),
           db: Session = Depends(get_db)):
    b = bsvc.require_permission(db, user, business_id, "business:manage")
    return biz_out(bsvc.update_business(db, b, user, body.model_dump(exclude_none=True)),
                   bsvc.member_role(db, user, business_id))


@router.put("/{business_id}/settlement-destination", response_model=BusinessOut)
def settlement_destination(business_id: uuid.UUID, body: SettlementDestinationIn, user: User = Depends(current_user),
                           db: Session = Depends(get_db)):
    b = bsvc.require_permission(db, user, business_id, "business:manage")
    return biz_out(bsvc.set_settlement_destination(db, b, user, body.model_dump()),
                   bsvc.member_role(db, user, business_id))


# ---------------------------------------------------------------- team
@router.get("/{business_id}/members", response_model=list[MemberOut])
def members(business_id: uuid.UUID, user: User = Depends(current_user), db: Session = Depends(get_db)):
    bsvc.require_permission(db, user, business_id, "business:view")
    rows = db.execute(select(BusinessMember, User).join(User, User.id == BusinessMember.user_id)
                      .where(BusinessMember.business_id == business_id, BusinessMember.status == "active")).all()
    return [MemberOut(id=m.id, user_id=u.id, email=u.email, full_name=u.full_name, role=m.role, status=m.status,
                      created_at=m.created_at) for m, u in rows]


@router.post("/{business_id}/members", response_model=MemberOut, status_code=201)
def add_member(business_id: uuid.UUID, body: MemberIn, user: User = Depends(current_user),
               db: Session = Depends(get_db)):
    b = bsvc.require_permission(db, user, business_id, "members:manage")
    m = bsvc.add_member(db, b, user, body.email, body.role)
    u = db.get(User, m.user_id)
    return MemberOut(id=m.id, user_id=u.id, email=u.email, full_name=u.full_name, role=m.role, status=m.status,
                     created_at=m.created_at)


@router.patch("/{business_id}/members/{member_id}", response_model=MemberOut)
def update_member(business_id: uuid.UUID, member_id: uuid.UUID, body: MemberUpdateIn,
                  user: User = Depends(current_user), db: Session = Depends(get_db)):
    b = bsvc.require_permission(db, user, business_id, "members:manage")
    m = bsvc.update_member(db, b, user, member_id, body.role, body.remove)
    u = db.get(User, m.user_id)
    return MemberOut(id=m.id, user_id=u.id, email=u.email, full_name=u.full_name, role=m.role, status=m.status,
                     created_at=m.created_at)


# ---------------------------------------------------------------- balances & transactions
@router.get("/{business_id}/wallets", response_model=list[WalletOut])
def wallets(business_id: uuid.UUID, user: User = Depends(current_user), db: Session = Depends(get_db)):
    bsvc.require_permission(db, user, business_id, "payments:view")
    return [wallet_out(db, w) for w in business_wallets(db, business_id)]


@router.get("/{business_id}/transactions", response_model=Page[TransactionOut])
def transactions(business_id: uuid.UUID, page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
                 type: str | None = None, status: str | None = None, search: str | None = None,
                 user: User = Depends(current_user), db: Session = Depends(get_db)):
    bsvc.require_permission(db, user, business_id, "payments:view")
    ids = {w.id for w in business_wallets(db, business_id)}
    q = select(Transaction).where(or_(Transaction.source_wallet_id.in_(ids), Transaction.destination_wallet_id.in_(ids)))
    if type:
        q = q.where(Transaction.type == type)
    if status:
        q = q.where(Transaction.status == status)
    if search:
        q = q.where(or_(Transaction.reference.ilike(f"%{search}%"), Transaction.description.ilike(f"%{search}%")))
    total = db.scalar(select(func.count()).select_from(q.subquery()))
    rows = db.scalars(q.order_by(Transaction.created_at.desc()).offset((page - 1) * page_size).limit(page_size))
    return Page(items=[txn_out(t, ids) for t in rows], total=total, page=page, page_size=page_size)


@router.get("/{business_id}/analytics")
def merchant_analytics(business_id: uuid.UUID, environment: str = Query("live", pattern="^(live|sandbox)$"),
                       days: int = Query(30, ge=1, le=365), user: User = Depends(current_user),
                       db: Session = Depends(get_db)):
    bsvc.require_permission(db, user, business_id, "reports:view")
    return analytics.merchant_overview(db, business_id, environment, days)


@router.get("/{business_id}/reports/settlement")
def report(business_id: uuid.UUID, start: date | None = None, end: date | None = None,
           user: User = Depends(current_user), db: Session = Depends(get_db)):
    bsvc.require_permission(db, user, business_id, "reports:view")
    s, e = _range(start, end)
    return settlement_report(db, business_id, s, e)


# ---------------------------------------------------------------- payment requests
@router.post("/{business_id}/payment-requests", response_model=PaymentRequestOut, status_code=201)
def create_payment_request(business_id: uuid.UUID, body: PaymentRequestIn, user: User = Depends(current_user),
                           db: Session = Depends(get_db)):
    b = bsvc.require_permission(db, user, business_id, "payments:create")
    svc = PaymentService(db)
    pr = svc.create_request(b, amount=body.amount, currency=body.currency, description=body.description,
                            customer_email=body.customer_email, customer_phone=body.customer_phone,
                            customer_name=body.customer_name, merchant_reference=body.merchant_reference,
                            callback_url=body.callback_url, metadata=body.metadata, environment="live")
    db.commit()
    return pr_out(pr)


@router.get("/{business_id}/payment-requests", response_model=Page[PaymentRequestOut])
def list_payment_requests(business_id: uuid.UUID, page: int = Query(1, ge=1), page_size: int = Query(20, le=100),
                          status: str | None = None, environment: str = Query("live", pattern="^(live|sandbox)$"),
                          search: str | None = None, user: User = Depends(current_user), db: Session = Depends(get_db)):
    bsvc.require_permission(db, user, business_id, "payments:view")
    q = select(PaymentRequest).where(PaymentRequest.business_id == business_id,
                                     PaymentRequest.environment == environment)
    if status:
        q = q.where(PaymentRequest.status == status)
    if search:
        like = f"%{search}%"
        q = q.where(or_(PaymentRequest.reference.ilike(like), PaymentRequest.merchant_reference.ilike(like),
                        PaymentRequest.customer_email.ilike(like), PaymentRequest.customer_phone.ilike(like)))
    total = db.scalar(select(func.count()).select_from(q.subquery()))
    rows = db.scalars(q.order_by(PaymentRequest.created_at.desc()).offset((page - 1) * page_size).limit(page_size))
    return Page(items=[pr_out(p) for p in rows], total=total, page=page, page_size=page_size)


def _pr(db: Session, business_id: uuid.UUID, reference: str) -> PaymentRequest:
    pr = db.scalar(select(PaymentRequest).where(PaymentRequest.reference == reference,
                                                PaymentRequest.business_id == business_id))
    if not pr:
        raise NotFound("Payment not found")
    return pr


@router.get("/{business_id}/payment-requests/{reference}", response_model=PaymentRequestOut)
def get_payment_request(business_id: uuid.UUID, reference: str, user: User = Depends(current_user),
                        db: Session = Depends(get_db)):
    bsvc.require_permission(db, user, business_id, "payments:view")
    return pr_out(_pr(db, business_id, reference))


@router.get("/{business_id}/payment-requests/{reference}/receipt.pdf", response_class=Response)
def payment_receipt(business_id: uuid.UUID, reference: str, user: User = Depends(current_user),
                    db: Session = Depends(get_db)):
    b = bsvc.require_permission(db, user, business_id, "payments:view")
    pr = _pr(db, business_id, reference)
    return pdf_response(pdf.payment_receipt(pr, b.trading_name or b.name, b.merchant_code, mask_customer=False),
                        f"fincore-payment-{pr.reference}.pdf")


@router.post("/{business_id}/payment-requests/{reference}/cancel", response_model=PaymentRequestOut)
def cancel_payment_request(business_id: uuid.UUID, reference: str, user: User = Depends(current_user),
                           db: Session = Depends(get_db)):
    bsvc.require_permission(db, user, business_id, "payments:create")
    pr = _pr(db, business_id, reference)
    if pr.status == "pending":
        pr.status = "cancelled"
        db.commit()
    return pr_out(pr)


@router.post("/{business_id}/payment-requests/{reference}/refunds", response_model=RefundOut, status_code=201,
             dependencies=[Depends(money_movement_allowed)])
def refund(business_id: uuid.UUID, reference: str, body: RefundIn, idempotency_key: str | None = IdempotencyKey,
           user: User = Depends(current_user), db: Session = Depends(get_db)):
    bsvc.require_permission(db, user, business_id, "refunds:create")
    pr = _pr(db, business_id, reference)
    return run_idempotent(db, f"biz:{business_id}:refund", idempotency_key, {"ref": reference, **body.model_dump()},
                          lambda: RefundOut.model_validate(PaymentService(db).refund(pr, user, body.amount, body.reason)))


@router.get("/{business_id}/refunds", response_model=list[RefundOut])
def refunds(business_id: uuid.UUID, user: User = Depends(current_user), db: Session = Depends(get_db)):
    bsvc.require_permission(db, user, business_id, "payments:view")
    return db.scalars(select(Refund).where(Refund.business_id == business_id).order_by(Refund.created_at.desc())
                      .limit(200)).all()


# ---------------------------------------------------------------- settlements
@router.post("/{business_id}/settlements", response_model=SettlementOut, status_code=201,
             dependencies=[Depends(money_movement_allowed)])
def settle(business_id: uuid.UUID, body: SettlementIn, idempotency_key: str | None = IdempotencyKey,
           user: User = Depends(current_user), db: Session = Depends(get_db)):
    b = bsvc.require_permission(db, user, business_id, "settlements:create")
    return run_idempotent(db, f"biz:{business_id}:settlement", idempotency_key, body.model_dump(),
                          lambda: SettlementOut.model_validate(PaymentService(db).settle(b, user, body.amount)))


@router.get("/{business_id}/settlements", response_model=list[SettlementOut])
def settlements(business_id: uuid.UUID, user: User = Depends(current_user), db: Session = Depends(get_db)):
    bsvc.require_permission(db, user, business_id, "payments:view")
    return db.scalars(select(Settlement).where(Settlement.business_id == business_id)
                      .order_by(Settlement.created_at.desc()).limit(200)).all()


# ---------------------------------------------------------------- payment links
@router.post("/{business_id}/payment-links", response_model=PaymentLinkOut, status_code=201)
def create_link(business_id: uuid.UUID, body: PaymentLinkIn, user: User = Depends(current_user),
                db: Session = Depends(get_db)):
    b = bsvc.require_permission(db, user, business_id, "payments:create")
    link = PaymentService(db).create_link(b, user, title=body.title, amount=body.amount, description=body.description,
                                          currency=body.currency, single_use=body.single_use,
                                          redirect_url=body.redirect_url, slug=body.slug,
                                          fields=[f.model_dump() for f in body.fields])
    return link_out(link)


@router.get("/{business_id}/payment-links", response_model=list[PaymentLinkOut])
def links(business_id: uuid.UUID, user: User = Depends(current_user), db: Session = Depends(get_db)):
    bsvc.require_permission(db, user, business_id, "payments:view")
    return [link_out(lk) for lk in db.scalars(select(PaymentLink).where(PaymentLink.business_id == business_id)
                                              .order_by(PaymentLink.created_at.desc()))]


@router.patch("/{business_id}/payment-links/{link_id}", response_model=PaymentLinkOut)
def update_link(business_id: uuid.UUID, link_id: uuid.UUID, body: PaymentLinkUpdateIn,
                user: User = Depends(current_user), db: Session = Depends(get_db)):
    bsvc.require_permission(db, user, business_id, "payments:create")
    link = db.get(PaymentLink, link_id)
    if not link or link.business_id != business_id:
        raise NotFound("Payment link not found")
    data = body.model_dump(exclude_none=True)
    if "fields" in data:
        data["fields"] = forms.normalise_fields(data["fields"])
    if "amount" in data:
        data["amount"] = validate_amount(data["amount"], link.currency)
    for k, v in data.items():
        setattr(link, k, v)
    audit(db, "payment_link.updated", actor_id=user.id, target_type="business", target_id=business_id,
          details={"slug": link.slug, "changes": list(data)})
    db.commit()
    return link_out(link)
