"""Hosted checkout and payment-link pages (public, no merchant credentials)."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import current_user, money_movement_allowed
from app.api.v1.wallets import pdf_response
from app.core.database import get_db
from app.core.errors import NotFound
from app.models.business import Business, PaymentLink, PaymentRequest
from app.models.user import User
from app.schemas.common import CheckoutPayMomoIn, CheckoutPayWalletIn, LinkPayIn
from app.services import pdf
from app.services.payments import PaymentService

router = APIRouter(tags=["Checkout (public)"])


def _mask_email(email: str | None) -> str | None:
    if not email or "@" not in email:
        return None
    name, domain = email.split("@", 1)
    return f"{name[:2]}***@{domain}"


def public_view(db: Session, pr: PaymentRequest) -> dict:
    biz = db.get(Business, pr.business_id)
    link = db.get(PaymentLink, pr.payment_link_id) if pr.payment_link_id else None
    return {
        "reference": pr.reference, "amount": pr.amount, "currency": pr.currency, "status": pr.status,
        "description": pr.description, "merchant_name": biz.trading_name or biz.name,
        "merchant_code": biz.merchant_code, "livemode": pr.environment == "live",
        "customer_email": _mask_email(pr.customer_email), "channel": pr.channel, "failure_reason": pr.failure_reason,
        "expires_at": pr.expires_at, "paid_at": pr.paid_at,
        "redirect_url": (link.redirect_url if link else None) or pr.callback_url,
    }


@router.get("/checkout/{reference}")
def get_checkout(reference: str, db: Session = Depends(get_db)):
    return public_view(db, PaymentService(db).get_request(reference))


@router.get("/checkout/{reference}/receipt.pdf", response_class=Response)
def checkout_receipt(reference: str, db: Session = Depends(get_db)):
    """Customer receipt for a completed checkout (customer details masked: the link may be shared)."""
    pr = PaymentService(db).get_request(reference)
    if pr.status not in ("successful", "refunded", "partially_refunded"):
        raise NotFound("A receipt is available once the payment succeeds")
    biz = db.get(Business, pr.business_id)
    return pdf_response(pdf.payment_receipt(pr, biz.trading_name or biz.name, biz.merchant_code, mask_customer=True),
                        f"receipt-{pr.reference}.pdf")


@router.post("/checkout/{reference}/mobile-money", dependencies=[Depends(money_movement_allowed)])
def pay_momo(reference: str, body: CheckoutPayMomoIn, db: Session = Depends(get_db)):
    svc = PaymentService(db)
    return public_view(db, svc.pay_with_mobile_money(svc.get_request(reference), body.phone))


@router.post("/checkout/{reference}/wallet", dependencies=[Depends(money_movement_allowed)])
def pay_wallet(reference: str, body: CheckoutPayWalletIn, user: User = Depends(current_user),
               db: Session = Depends(get_db)):
    svc = PaymentService(db)
    return public_view(db, svc.pay_with_wallet(svc.get_request(reference), user, body.wallet_id))


@router.get("/pay/{slug}")
def get_link(slug: str, db: Session = Depends(get_db)):
    link = db.scalar(select(PaymentLink).where(PaymentLink.slug == slug))
    if not link:
        raise NotFound("Payment link not found")
    biz = db.get(Business, link.business_id)
    return {"slug": link.slug, "title": link.title, "description": link.description, "amount": link.amount,
            "currency": link.currency, "active": link.active and biz.status == "active",
            "merchant_name": biz.trading_name or biz.name}


@router.post("/pay/{slug}")
def start_link_payment(slug: str, body: LinkPayIn, db: Session = Depends(get_db)):
    link = db.scalar(select(PaymentLink).where(PaymentLink.slug == slug))
    if not link:
        raise NotFound("Payment link not found")
    pr = PaymentService(db).start_link_payment(link, amount=body.amount, customer_email=body.customer_email,
                                               customer_name=body.customer_name, customer_phone=body.customer_phone)
    return public_view(db, pr)
