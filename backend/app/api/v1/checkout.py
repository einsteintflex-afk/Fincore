"""Hosted checkout and payment-link pages (public, no merchant credentials)."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import current_user, money_movement_allowed
from app.api.v1.wallets import pdf_response
from app.core.config import settings
from app.core.database import get_db
from app.core.errors import Forbidden, NotFound
from app.models.business import Business, PaymentLink, PaymentRequest
from app.models.user import User
from app.providers.cards import TEST_CARDS, card_brand, read_sandbox_token, sandbox_outcome
from app.schemas.common import CheckoutPayMomoIn, CheckoutPayWalletIn, LinkPayIn, Sandbox3dsIn, SandboxCardIn
from app.services import forms, pdf
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
        "merchant_code": biz.merchant_code, "livemode": pr.environment == "live" and settings.live_payments_enabled,
        "customer_email": _mask_email(pr.customer_email), "channel": pr.channel, "failure_reason": pr.failure_reason,
        "expires_at": pr.expires_at, "paid_at": pr.paid_at, "card": (pr.meta or {}).get("card", {}).get("label"),
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


@router.post("/checkout/{reference}/card", dependencies=[Depends(money_movement_allowed)])
def pay_card(reference: str, db: Session = Depends(get_db)):
    """Start a card payment: returns the acquirer's hosted card page to redirect the payer to."""
    svc = PaymentService(db)
    return {"redirect_url": svc.start_card_payment(svc.get_request(reference))}


@router.post("/checkout/{reference}/card/complete")
def complete_card(reference: str, db: Session = Depends(get_db)):
    """Called when the payer returns from the card page. The outcome comes from the acquirer, not the browser."""
    svc = PaymentService(db)
    return public_view(db, svc.complete_card_payment(svc.get_request(reference)))


def _sandbox_card_payment(db: Session, token: str) -> tuple[PaymentRequest, dict]:
    data = read_sandbox_token(token)
    pr = PaymentService(db).get_request(data["ref"])
    if pr.provider != "sandbox_card" or pr.provider_reference != data["sid"]:
        raise Forbidden("This test card session is no longer valid")
    return pr, data


@router.get("/sandbox/card/{token}")
def sandbox_card_page(token: str, db: Session = Depends(get_db)):
    pr, data = _sandbox_card_payment(db, token)
    biz = db.get(Business, pr.business_id)
    return {"merchant_name": biz.trading_name or biz.name, "amount": pr.amount, "currency": pr.currency,
            "description": pr.description, "status": pr.status, "return_url": data["ret"],
            "awaiting_3ds": bool((pr.meta or {}).get("card_3ds")),
            "test_cards": [{"number": n, "result": r} for n, (r, _) in TEST_CARDS.items()]}


@router.post("/sandbox/card/{token}")
def sandbox_card_submit(token: str, body: SandboxCardIn, db: Session = Depends(get_db)):
    """Simulated acquirer page. Only the brand and last four digits are kept; the number is discarded."""
    pr, data = _sandbox_card_payment(db, token)
    if pr.status != "processing":
        return {"status": pr.status, "message": "This payment is already complete", "return_url": data["ret"]}
    outcome, message = sandbox_outcome(body.number, body.expiry, body.cvc)
    digits = "".join(c for c in body.number if c.isdigit())
    card = {"brand": card_brand(digits), "last4": digits[-4:], "label": f"{card_brand(digits)} •••• {digits[-4:]}"}
    if outcome == "requires_3ds":
        pr.meta = {**(pr.meta or {}), "card_3ds": card}
        db.commit()
        return {"status": "requires_3ds", "message": message, "return_url": data["ret"]}
    PaymentService(db).apply_card_result(pr, outcome, message, card=card)
    return {"status": outcome, "message": message, "return_url": data["ret"]}


@router.post("/sandbox/card/{token}/3ds")
def sandbox_card_3ds(token: str, body: Sandbox3dsIn, db: Session = Depends(get_db)):
    pr, data = _sandbox_card_payment(db, token)
    card = (pr.meta or {}).get("card_3ds")
    if not card or pr.status != "processing":
        raise Forbidden("No authentication pending for this payment")
    pr.meta = {k: v for k, v in (pr.meta or {}).items() if k != "card_3ds"}
    status, message = ("successful", "Approved after authentication") if body.approve else \
        ("failed", "Cardholder authentication failed")
    PaymentService(db).apply_card_result(pr, status, message, card=card)
    return {"status": status, "message": message, "return_url": data["ret"]}


@router.get("/verify-receipt")
def verify_receipt(reference: str, code: str, db: Session = Depends(get_db)):
    """Public receipt check for offices: genuine only if the reference exists, was paid, and the code matches."""
    pr = db.scalar(select(PaymentRequest).where(PaymentRequest.reference == reference.strip().upper()))
    if not pr or not forms.check_receipt_code(pr.reference, code):
        return {"valid": False, "message": "No genuine FinCore receipt matches this reference and code."}
    biz = db.get(Business, pr.business_id)
    paid = pr.status in ("successful", "partially_refunded")
    return {
        "valid": paid,
        "message": "Genuine and paid." if paid else f"Receipt found but the payment is {pr.status.replace('_', ' ')}.",
        "reference": pr.reference, "status": pr.status, "amount": pr.amount, "currency": pr.currency,
        "amount_refunded": pr.amount_refunded, "paid_at": pr.paid_at, "description": pr.description,
        "merchant_name": biz.trading_name or biz.name, "payer_name": pr.customer_name,
        "form": [{"label": a["label"], "value": a["value"]} for a in (pr.meta or {}).get("form", [])],
        "livemode": pr.environment == "live" and settings.live_payments_enabled,
    }


@router.get("/pay/{slug}")
def get_link(slug: str, db: Session = Depends(get_db)):
    link = db.scalar(select(PaymentLink).where(PaymentLink.slug == slug))
    if not link:
        raise NotFound("Payment link not found")
    biz = db.get(Business, link.business_id)
    return {"slug": link.slug, "title": link.title, "description": link.description, "amount": link.amount,
            "currency": link.currency, "active": link.active and biz.status == "active",
            "merchant_name": biz.trading_name or biz.name,
            "fields": [{k: f[k] for k in ("key", "label", "type", "required", "options")} for f in link.fields or []]}


@router.post("/pay/{slug}")
def start_link_payment(slug: str, body: LinkPayIn, db: Session = Depends(get_db)):
    link = db.scalar(select(PaymentLink).where(PaymentLink.slug == slug))
    if not link:
        raise NotFound("Payment link not found")
    pr = PaymentService(db).start_link_payment(link, amount=body.amount, customer_email=body.customer_email,
                                               customer_name=body.customer_name, customer_phone=body.customer_phone,
                                               answers=body.answers)
    return public_view(db, pr)
