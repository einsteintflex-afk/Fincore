"""Public merchant API, authenticated with secret API keys (``Authorization: Bearer sk_test_...``).

Sandbox keys (``sk_test_``) create simulated charges that never touch real balances.
Live keys (``sk_live_``) only work once the business is approved AND live payments are enabled.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Header, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import ApiContext, IdempotencyKey, api_context, require_app_permission, run_idempotent
from app.api.v1.businesses import pr_out
from app.core.database import get_db
from app.core.errors import NotFound
from app.models.business import PaymentRequest
from app.models.developer import AppSubscriber
from app.models.enums import AppPermission
from app.schemas.common import ChargeIn, GatewayRefundIn, Page, PaymentRequestOut, PayoutIn, RefundOut, SandboxResolveIn
from app.services import payouts, subscribers, withdrawal_fee
from app.services.payments import PaymentService
from app.services.wallets import balance, business_wallets

router = APIRouter(prefix="/gateway", tags=["Payment gateway API (API key)"])
SubscriberToken = Header(default=None, alias="X-Subscriber-Token",
                         description="Required when the application only serves verified subscribers")


def _subscriber(db: Session, ctx: ApiContext, token: str | None) -> AppSubscriber | None:
    """Verified-subscriber gate: enforced when the app requires it, validated whenever a token is sent."""
    if ctx.app.require_verified_subscribers or token:
        return subscribers.check_token(db, ctx.app, token)
    return None


def _charge(db: Session, ctx: ApiContext, reference: str) -> PaymentRequest:
    # Scoped to the calling application: one app can never read or refund another app's charges,
    # even when both belong to the same business.
    pr = db.scalar(select(PaymentRequest).where(
        PaymentRequest.app_id == ctx.app.id, PaymentRequest.environment == ctx.environment,
        (PaymentRequest.reference == reference) | (PaymentRequest.merchant_reference == reference)))
    if not pr:
        raise NotFound("Charge not found")
    return pr


@router.post("/charges", response_model=PaymentRequestOut, status_code=201,
             summary="Create a charge. With `phone`, a mobile money prompt is sent immediately; "
                     "otherwise redirect the customer to `checkout_url`.")
def create_charge(body: ChargeIn, idempotency_key: str | None = IdempotencyKey,
                  x_subscriber_token: str | None = SubscriberToken,
                  ctx: ApiContext = Depends(api_context), db: Session = Depends(get_db)):
    require_app_permission(ctx, AppPermission.COLLECTIONS)
    subscriber = _subscriber(db, ctx, x_subscriber_token)

    def go():
        svc = PaymentService(db)
        pr = svc.create_request(ctx.business, amount=body.amount, currency=body.currency, description=body.description,
                                customer_email=body.email, customer_phone=body.phone,
                                customer_name=body.customer_name, environment=ctx.environment, app_id=ctx.app.id,
                                merchant_reference=body.reference, callback_url=body.callback_url,
                                metadata={**(body.metadata or {}),
                                          **({"subscriber_id": str(subscriber.id)} if subscriber else {})})
        db.commit()
        if body.phone:
            pr = svc.pay_with_mobile_money(pr, body.phone)
        return pr_out(pr)
    return run_idempotent(db, f"key:{ctx.key.id}:charge", idempotency_key, body.model_dump(), go)


@router.get("/charges", response_model=Page[PaymentRequestOut])
def list_charges(page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100), status: str | None = None,
                 ctx: ApiContext = Depends(api_context), db: Session = Depends(get_db)):
    require_app_permission(ctx, AppPermission.COLLECTIONS)
    q = select(PaymentRequest).where(PaymentRequest.app_id == ctx.app.id,
                                     PaymentRequest.environment == ctx.environment)
    if status:
        q = q.where(PaymentRequest.status == status)
    total = db.scalar(select(func.count()).select_from(q.subquery()))
    rows = db.scalars(q.order_by(PaymentRequest.created_at.desc()).offset((page - 1) * page_size).limit(page_size))
    return Page(items=[pr_out(p) for p in rows], total=total, page=page, page_size=page_size)


@router.get("/charges/{reference}", response_model=PaymentRequestOut, summary="Verify a charge")
def verify_charge(reference: str, ctx: ApiContext = Depends(api_context), db: Session = Depends(get_db)):
    require_app_permission(ctx, AppPermission.COLLECTIONS)
    return pr_out(_charge(db, ctx, reference))


@router.post("/refunds", response_model=RefundOut, status_code=201)
def create_refund(body: GatewayRefundIn, idempotency_key: str | None = IdempotencyKey,
                  ctx: ApiContext = Depends(api_context), db: Session = Depends(get_db)):
    require_app_permission(ctx, AppPermission.REFUNDS)
    pr = _charge(db, ctx, body.charge_reference)
    return run_idempotent(db, f"key:{ctx.key.id}:refund", idempotency_key, body.model_dump(),
                          lambda: RefundOut.model_validate(PaymentService(db).refund(pr, None, body.amount, body.reason)))


@router.get("/balance")
def get_balance(ctx: ApiContext = Depends(api_context), db: Session = Depends(get_db)):
    require_app_permission(ctx, AppPermission.BALANCE)
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


# ---------------------------------------------------------------- payouts (disbursements)
@router.get("/payouts/quote", summary="Withdrawal fee breakdown for a payout: fee %, fee, net to recipient, "
            "total debited")
def payout_quote(amount: str, currency: str = "GHS", ctx: ApiContext = Depends(api_context),
                 db: Session = Depends(get_db)):
    require_app_permission(ctx, AppPermission.PAYOUTS)
    return withdrawal_fee.quote(db, amount, currency.upper())


@router.post("/payouts", status_code=201,
             summary="Pay out to a mobile money number from your application's balance. The withdrawal fee is "
                     "deducted from `amount`; the recipient receives `net_amount`. Final status comes from the "
                     "provider (poll GET /gateway/payouts/{reference} or use the payout.* webhooks).")
def create_payout(body: PayoutIn, idempotency_key: str | None = IdempotencyKey,
                  x_subscriber_token: str | None = SubscriberToken,
                  ctx: ApiContext = Depends(api_context), db: Session = Depends(get_db)):
    require_app_permission(ctx, AppPermission.PAYOUTS)
    subscriber = _subscriber(db, ctx, x_subscriber_token)
    if ctx.environment == "sandbox":
        # Sandbox keys never move money: return the exact breakdown, clearly marked as a simulation.
        q = withdrawal_fee.quote(db, body.amount, body.currency)
        return {"reference": body.reference, "livemode": False, "status": "successful", "simulated": True,
                "amount": q["requested_amount"], "fee": q["fee_amount"], "fee_percent": q["fee_percent"],
                "net_amount": q["net_amount"], "currency": body.currency,
                "note": "Sandbox key: no money moved. Use a live key for real payouts."}

    def go():
        txn = payouts.create_payout(db, ctx, body, subscriber)
        return payouts.payout_out(txn)
    return run_idempotent(db, f"key:{ctx.key.id}:payout", idempotency_key, body.model_dump(), go)


@router.get("/payouts/{reference}", summary="Payout status (refreshed from the provider while processing)")
def get_payout(reference: str, ctx: ApiContext = Depends(api_context), db: Session = Depends(get_db)):
    require_app_permission(ctx, AppPermission.PAYOUTS)
    return payouts.payout_out(payouts.refresh(db, payouts.get_app_payout(db, ctx, reference)))
