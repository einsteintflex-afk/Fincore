"""Public merchant API, authenticated with secret API keys (``Authorization: Bearer sk_test_...``).

Sandbox keys (``sk_test_``) create simulated charges that never touch real balances.
Live keys (``sk_live_``) only work once the business is approved AND live payments are enabled.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import ApiContext, IdempotencyKey, api_context, run_idempotent
from app.api.v1.businesses import pr_out
from app.core.database import get_db
from app.core.errors import NotFound
from app.models.business import PaymentRequest
from app.schemas.common import ChargeIn, GatewayRefundIn, Page, PaymentRequestOut, RefundOut, SandboxResolveIn
from app.services.payments import PaymentService
from app.services.wallets import balance, business_wallets

router = APIRouter(prefix="/gateway", tags=["Payment gateway API (API key)"])


def _charge(db: Session, ctx: ApiContext, reference: str) -> PaymentRequest:
    pr = db.scalar(select(PaymentRequest).where(
        PaymentRequest.business_id == ctx.business.id, PaymentRequest.environment == ctx.environment,
        (PaymentRequest.reference == reference) | (PaymentRequest.merchant_reference == reference)))
    if not pr:
        raise NotFound("Charge not found")
    return pr


@router.post("/charges", response_model=PaymentRequestOut, status_code=201,
             summary="Create a charge. With `phone`, a mobile money prompt is sent immediately; "
                     "otherwise redirect the customer to `checkout_url`.")
def create_charge(body: ChargeIn, idempotency_key: str | None = IdempotencyKey,
                  ctx: ApiContext = Depends(api_context), db: Session = Depends(get_db)):
    def go():
        svc = PaymentService(db)
        pr = svc.create_request(ctx.business, amount=body.amount, currency=body.currency, description=body.description,
                                customer_email=body.email, customer_phone=body.phone,
                                customer_name=body.customer_name, environment=ctx.environment, app_id=ctx.app.id,
                                merchant_reference=body.reference, callback_url=body.callback_url,
                                metadata=body.metadata)
        db.commit()
        if body.phone:
            pr = svc.pay_with_mobile_money(pr, body.phone)
        return pr_out(pr)
    return run_idempotent(db, f"key:{ctx.key.id}:charge", idempotency_key, body.model_dump(), go)


@router.get("/charges", response_model=Page[PaymentRequestOut])
def list_charges(page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100), status: str | None = None,
                 ctx: ApiContext = Depends(api_context), db: Session = Depends(get_db)):
    q = select(PaymentRequest).where(PaymentRequest.business_id == ctx.business.id,
                                     PaymentRequest.environment == ctx.environment)
    if status:
        q = q.where(PaymentRequest.status == status)
    total = db.scalar(select(func.count()).select_from(q.subquery()))
    rows = db.scalars(q.order_by(PaymentRequest.created_at.desc()).offset((page - 1) * page_size).limit(page_size))
    return Page(items=[pr_out(p) for p in rows], total=total, page=page, page_size=page_size)


@router.get("/charges/{reference}", response_model=PaymentRequestOut, summary="Verify a charge")
def verify_charge(reference: str, ctx: ApiContext = Depends(api_context), db: Session = Depends(get_db)):
    return pr_out(_charge(db, ctx, reference))


@router.post("/refunds", response_model=RefundOut, status_code=201)
def create_refund(body: GatewayRefundIn, idempotency_key: str | None = IdempotencyKey,
                  ctx: ApiContext = Depends(api_context), db: Session = Depends(get_db)):
    pr = _charge(db, ctx, body.charge_reference)
    return run_idempotent(db, f"key:{ctx.key.id}:refund", idempotency_key, body.model_dump(),
                          lambda: RefundOut.model_validate(PaymentService(db).refund(pr, None, body.amount, body.reason)))


@router.get("/balance")
def get_balance(ctx: ApiContext = Depends(api_context), db: Session = Depends(get_db)):
    if ctx.environment == "sandbox":
        return {"livemode": False, "balances": [{"currency": "GHS", "available": "0.00",
                                                 "note": "Sandbox charges do not affect balances"}]}
    return {"livemode": True, "balances": [{"currency": w.currency, "available": balance(db, w),
                                            "account_number": w.account_number}
                                           for w in business_wallets(db, ctx.business.id)]}


@router.post("/sandbox/charges/{reference}/resolve", response_model=PaymentRequestOut,
             summary="Sandbox only: approve or decline a charge awaiting the customer's approval")
def resolve_sandbox(reference: str, body: SandboxResolveIn, ctx: ApiContext = Depends(api_context),
                    db: Session = Depends(get_db)):
    pr = _charge(db, ctx, reference)
    return pr_out(PaymentService(db).resolve_sandbox_pending(pr, body.status))
