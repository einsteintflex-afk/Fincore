"""Merchant payments: payment requests (charges), hosted checkout, payment links, refunds, settlements.

Sandbox payment requests (created with sandbox API keys) are fully simulated: they never create
ledger postings or ``Transaction`` rows, so test traffic cannot affect real balances.
"""

from __future__ import annotations

import re
import secrets
import uuid
from datetime import timedelta
from decimal import Decimal

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import utcnow
from app.core.errors import AppError, Conflict, Forbidden, NotFound, ValidationFailed
from app.core.money import ZERO, validate_amount
from app.core.security import generate_reference
from app.models.business import Business, PaymentLink, PaymentRequest, Refund, Settlement
from app.models.enums import BusinessStatus, Channel, PaymentStatus, TxnStatus, TxnType
from app.models.ledger import Wallet
from app.models.transaction import Transaction
from app.models.user import User
from app.providers import card_acquirer, get_provider, route
from app.providers.base import CollectionRequest, ProviderResult
from app.services import fees, forms, limits, risk, webhooks
from app.services.audit import audit
from app.services.ghana import NETWORK_NAMES, detect_network, normalize_msisdn
from app.services.ledger import CR, DR, Line, SystemAccount
from app.services.notifications import notify
from app.services.restrictions import ensure_business_can_debit, ensure_user_can_debit
from app.services.transactions import TransactionService, _record_provider_txn
from app.services.wallets import assert_wallet_active, default_business_wallet, get_owned_wallet

CHECKOUT_TTL = timedelta(hours=24)
PAYABLE = {PaymentStatus.PENDING, PaymentStatus.FAILED}


def charge_view(pr: PaymentRequest) -> dict:
    return {
        "reference": pr.reference, "merchant_reference": pr.merchant_reference, "amount": pr.amount,
        "currency": pr.currency, "fee": pr.fee, "status": pr.status, "environment": pr.environment,
        "livemode": pr.environment == "live", "channel": pr.channel, "network": pr.network,
        "description": pr.description, "customer_email": pr.customer_email, "customer_phone": pr.customer_phone,
        "amount_refunded": pr.amount_refunded, "paid_at": pr.paid_at, "created_at": pr.created_at,
        "metadata": pr.meta, "failure_reason": pr.failure_reason,
    }


class PaymentService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.txns = TransactionService(db)
        self.ledger = self.txns.ledger

    # ================================================================ payment requests
    def create_request(self, business: Business, *, amount: object, currency: str = "GHS",
                       description: str | None = None, customer_email: str | None = None,
                       customer_phone: str | None = None, customer_name: str | None = None,
                       environment: str = "live", app_id: uuid.UUID | None = None,
                       merchant_reference: str | None = None, callback_url: str | None = None,
                       metadata: dict | None = None, payment_link: PaymentLink | None = None) -> PaymentRequest:
        db = self.db
        amount = validate_amount(amount, currency)
        if environment == "live" and business.status != BusinessStatus.ACTIVE:
            raise Forbidden("Business must be approved before accepting live payments", code="business_not_active")
        if merchant_reference:
            dup = db.scalar(select(PaymentRequest.id).where(PaymentRequest.business_id == business.id,
                                                            PaymentRequest.merchant_reference == merchant_reference,
                                                            PaymentRequest.environment == environment))
            if dup:
                raise Conflict("A charge with this merchant reference already exists", code="duplicate_reference")
        fee = fees.compute_fee(db, TxnType.PAYMENT, amount, currency, payer="merchant")
        pr = PaymentRequest(
            reference=generate_reference("PAY"), merchant_reference=merchant_reference, business_id=business.id,
            app_id=app_id, payment_link_id=payment_link.id if payment_link else None, environment=environment,
            amount=amount, currency=currency, fee=fee, status=PaymentStatus.PENDING, description=description,
            customer_email=customer_email, customer_name=customer_name,
            customer_phone=normalize_msisdn(customer_phone) if customer_phone else None,
            callback_url=callback_url, meta=metadata or {}, expires_at=utcnow() + CHECKOUT_TTL)
        db.add(pr)
        db.flush()
        return pr

    def get_request(self, reference: str) -> PaymentRequest:
        pr = self.db.scalar(select(PaymentRequest).where(PaymentRequest.reference == reference))
        if not pr:
            raise NotFound("Payment not found")
        return pr

    def _assert_payable(self, pr: PaymentRequest) -> None:
        if pr.channel == Channel.CARD and pr.status == PaymentStatus.PROCESSING:
            self._abandon_card_attempt(pr)  # payer left the card page and is trying again (any method)
        if pr.status not in PAYABLE:
            raise Conflict(f"This payment is {pr.status}", code="not_payable")
        expires = pr.expires_at if pr.expires_at.tzinfo else pr.expires_at.replace(tzinfo=utcnow().tzinfo)
        if expires < utcnow():
            pr.status = PaymentStatus.EXPIRED
            self.db.commit()
            raise Conflict("This payment request has expired", code="expired")

    # ---------------------------------------------------------------- pay with FinCore wallet
    def pay_with_wallet(self, pr: PaymentRequest, payer: User, wallet_id: uuid.UUID) -> PaymentRequest:
        db = self.db
        self._assert_payable(pr)
        if pr.environment != "live":
            raise ValidationFailed("Sandbox payments can only be paid with sandbox mobile money")
        wallet = get_owned_wallet(db, payer, wallet_id)
        assert_wallet_active(wallet)
        if wallet.currency != pr.currency:
            raise ValidationFailed("Wallet currency does not match payment currency")
        ensure_user_can_debit(db, payer)
        limits.check_limits(db, payer, TxnType.PAYMENT, pr.amount, pr.currency)
        ra = risk.assess(db, payer, TxnType.PAYMENT, pr.amount)
        if ra.blocked:
            risk.record_alerts(db, ra, user_id=payer.id)
            db.commit()
            raise Forbidden("This payment has been held for review", code="risk_blocked")
        merchant_wallet = default_business_wallet(db, pr.business_id, pr.currency)
        biz = db.get(Business, pr.business_id)
        txn = Transaction(
            reference=generate_reference("TXN"), type=TxnType.PAYMENT, status=TxnStatus.PENDING,
            channel=Channel.WALLET, amount=pr.amount, fee=pr.fee, currency=pr.currency, source_wallet_id=wallet.id,
            destination_wallet_id=merchant_wallet.id, initiated_by_id=payer.id, business_id=pr.business_id,
            provider="internal", provider_mode="internal", risk_score=ra.score,
            counterparty={"merchant": biz.trading_name or biz.name, "merchant_code": biz.merchant_code},
            description=pr.description or f"Payment to {biz.trading_name or biz.name}",
            meta={"payment_reference": pr.reference})
        db.add(txn)
        db.flush()
        lines = [Line(wallet.ledger_account_id, DR, pr.amount),
                 Line(merchant_wallet.ledger_account_id, CR, pr.amount - pr.fee)]
        if pr.fee > 0:
            lines.append(Line(self.ledger.system_account(SystemAccount.FEE_REVENUE, pr.currency).id, CR, pr.fee))
        lj = self.ledger.post(kind="payment", lines=lines, reference=f"{txn.reference}:POST",
                              description=txn.description)
        txn.ledger_transaction_id = lj.id
        txn.status = TxnStatus.SUCCESSFUL
        txn.completed_at = utcnow()
        pr.channel, pr.payer_user_id, pr.transaction_id = Channel.WALLET, payer.id, txn.id
        pr.customer_email = pr.customer_email or payer.email
        pr.customer_name = pr.customer_name or payer.full_name
        risk.record_alerts(db, ra, user_id=payer.id, transaction_id=txn.id)
        self._mark_paid(pr)
        notify(db, payer.id, "payment", "Payment successful",
               f"You paid {pr.currency} {pr.amount:,.2f} to {biz.trading_name or biz.name}. Ref {txn.reference}")
        db.commit()
        return pr

    # ---------------------------------------------------------------- pay with mobile money
    def pay_with_mobile_money(self, pr: PaymentRequest, phone: str) -> PaymentRequest:
        db = self.db
        self._assert_payable(pr)
        msisdn = normalize_msisdn(phone)
        network = detect_network(msisdn)
        sandbox = pr.environment != "live"
        provider = route(Channel.MOBILE_MONEY, network.value, sandbox=sandbox)
        pr.fee = fees.compute_fee(db, TxnType.PAYMENT, pr.amount, pr.currency, channel=Channel.MOBILE_MONEY,
                                  payer="merchant")
        pr.channel, pr.network, pr.customer_phone, pr.provider = Channel.MOBILE_MONEY, network.value, msisdn, provider.code
        pr.status = PaymentStatus.PROCESSING
        pr.failure_reason = None
        txn = None
        if not sandbox:
            merchant_wallet = default_business_wallet(db, pr.business_id, pr.currency)
            txn = Transaction(
                reference=generate_reference("TXN"), type=TxnType.PAYMENT, status=TxnStatus.PENDING,
                channel=Channel.MOBILE_MONEY, amount=pr.amount, fee=pr.fee, currency=pr.currency,
                destination_wallet_id=merchant_wallet.id, business_id=pr.business_id, provider=provider.code,
                provider_mode=provider.mode, counterparty={"msisdn": msisdn, "network": network.value},
                description=pr.description or f"Payment via {NETWORK_NAMES[network]}",
                meta={"payment_reference": pr.reference})
            db.add(txn)
            db.flush()
            pr.transaction_id = txn.id
        db.commit()

        ref = txn.reference if txn else pr.reference + "-" + secrets.token_hex(3).upper()
        try:
            result = provider.collect(CollectionRequest(reference=ref, amount=pr.amount, currency=pr.currency,
                                                        msisdn=msisdn, network=network.value,
                                                        email=pr.customer_email, description=pr.description or ""))
        except (httpx.TimeoutException, httpx.NetworkError):
            return pr  # stays processing; resolved by callback / status poll
        except AppError as exc:
            pr.status, pr.failure_reason = PaymentStatus.FAILED, exc.message
            if txn:
                txn.status, txn.failure_reason = TxnStatus.FAILED, exc.message
            db.commit()
            raise
        pr.provider_reference = result.provider_reference
        if txn:
            _record_provider_txn(db, provider.code, provider.mode, "collection", txn, result)
            self.txns.apply_provider_result(txn, result)  # posts ledger + calls on_transaction_final
        else:
            self._apply_sandbox_result(pr, result.status, result.message)
        db.commit()
        return pr

    # ---------------------------------------------------------------- pay by card (acquirer hosted page)
    def start_card_payment(self, pr: PaymentRequest) -> str:
        """Create a hosted card session and return the URL to send the payer to."""
        db = self.db
        self._assert_payable(pr)
        sandbox = pr.environment != "live"
        acquirer = card_acquirer(sandbox=sandbox)
        pr.fee = fees.compute_fee(db, TxnType.PAYMENT, pr.amount, pr.currency, channel=Channel.CARD, payer="merchant")
        session = acquirer.create_session(
            reference=pr.reference, amount=pr.amount, currency=pr.currency, description=pr.description or "Payment",
            return_url=f"{settings.frontend_base_url}/checkout/{pr.reference}?card_return=1",
            customer_email=pr.customer_email)
        pr.channel, pr.network, pr.provider, pr.provider_reference = Channel.CARD, None, acquirer.code, session.session_id
        pr.status, pr.failure_reason = PaymentStatus.PROCESSING, None
        if not sandbox:
            merchant_wallet = default_business_wallet(db, pr.business_id, pr.currency)
            txn = Transaction(
                reference=generate_reference("TXN"), type=TxnType.PAYMENT, status=TxnStatus.PROCESSING,
                channel=Channel.CARD, amount=pr.amount, fee=pr.fee, currency=pr.currency,
                destination_wallet_id=merchant_wallet.id, business_id=pr.business_id, provider=acquirer.code,
                provider_mode=acquirer.mode, provider_reference=session.session_id, counterparty={},
                description=pr.description or "Card payment", meta={"payment_reference": pr.reference})
            db.add(txn)
            db.flush()
            pr.transaction_id = txn.id
        db.commit()
        return session.redirect_url

    def _abandon_card_attempt(self, pr: PaymentRequest) -> None:
        """Before a new card attempt: settle the old session if the acquirer already decided it; otherwise
        retire it. A simulated session is failed outright. A real acquirer session is left *processing* so the
        status poller still records it if the bank captures late (then finance refunds the duplicate)."""
        self.complete_card_payment(pr)
        if pr.status != PaymentStatus.PROCESSING or pr.channel != Channel.CARD:
            return
        old = self.db.get(Transaction, pr.transaction_id) if pr.transaction_id else None
        if old and old.provider == "sandbox_card" and old.status == TxnStatus.PROCESSING:
            old.status, old.failure_reason, old.completed_at = TxnStatus.FAILED, "Abandoned card attempt", utcnow()
        pr.status, pr.failure_reason = PaymentStatus.FAILED, "Previous card attempt was not completed"
        self.db.flush()

    def apply_card_result(self, pr: PaymentRequest, status: str, message: str, *, card: dict | None = None,
                          provider_reference: str | None = None) -> PaymentRequest:
        """Apply an acquirer outcome (callback, status query or the simulated page). Idempotent."""
        db = self.db
        if card:
            pr.meta = {**(pr.meta or {}), "card": card}
        if pr.environment != "live":
            if pr.status == PaymentStatus.PROCESSING:
                self._apply_sandbox_result(pr, status, message)
            db.commit()
            return pr
        txn = db.get(Transaction, pr.transaction_id) if pr.transaction_id else None
        if txn and txn.status not in (TxnStatus.SUCCESSFUL, TxnStatus.FAILED, TxnStatus.REVERSED):
            if card:
                txn.counterparty = {"card": card.get("label"), "label": card.get("label")}
            result = ProviderResult(status=status, provider_reference=provider_reference or txn.provider_reference,
                                    message=message, raw={"card": card} if card else {})
            _record_provider_txn(db, txn.provider, txn.provider_mode, "collection", txn, result)
            self.txns.apply_provider_result(txn, result)  # ledger + on_transaction_final
        db.commit()
        return pr

    def complete_card_payment(self, pr: PaymentRequest) -> PaymentRequest:
        """Payer came back from the hosted page: ask the acquirer for the outcome (never trust the redirect)."""
        if pr.channel != Channel.CARD or pr.status != PaymentStatus.PROCESSING or not pr.provider_reference:
            return pr
        result = get_provider(pr.provider).check_status(pr.provider_reference, "collection")
        if result.status == "pending":
            return pr
        return self.apply_card_result(pr, result.status, result.message, provider_reference=result.provider_reference)

    def _apply_sandbox_result(self, pr: PaymentRequest, status: str, message: str) -> None:
        if status == "successful":
            self._mark_paid(pr)
        elif status == "failed":
            pr.status, pr.failure_reason = PaymentStatus.FAILED, message
            webhooks.emit(self.db, pr.business_id, "charge.failed", charge_view(pr), environment=pr.environment)
        else:
            pr.status = PaymentStatus.PROCESSING

    def _mark_paid(self, pr: PaymentRequest) -> None:
        pr.status = PaymentStatus.SUCCESSFUL
        pr.paid_at = utcnow()
        pr.failure_reason = None
        if pr.payment_link_id:
            link = self.db.get(PaymentLink, pr.payment_link_id)
            link.payments_count += 1
            if link.single_use:
                link.active = False
        webhooks.emit(self.db, pr.business_id, "charge.success", charge_view(pr), environment=pr.environment)
        biz = self.db.get(Business, pr.business_id)
        notify(self.db, biz.owner_user_id, "payment_received", "Payment received",
               f"{pr.currency} {pr.amount:,.2f} received ({pr.reference})"
               + (" [sandbox]" if pr.environment != "live" else ""))

    def resolve_sandbox_pending(self, pr: PaymentRequest, status: str) -> PaymentRequest:
        if pr.environment == "live":
            raise Forbidden("Only sandbox payments can be simulated")
        if pr.status != PaymentStatus.PROCESSING:
            raise Conflict("Payment is not awaiting approval")
        self._apply_sandbox_result(pr, status, "Simulated outcome")
        self.db.commit()
        return pr

    # ================================================================ refunds
    def refund(self, pr: PaymentRequest, actor: User | None, amount: object | None, reason: str | None) -> Refund:
        db = self.db
        if pr.status not in (PaymentStatus.SUCCESSFUL, PaymentStatus.PARTIALLY_REFUNDED):
            raise Conflict("Only successful payments can be refunded")
        remaining = pr.amount - pr.amount_refunded
        amount = validate_amount(amount, pr.currency) if amount is not None else remaining
        if amount > remaining:
            raise ValidationFailed(f"Refund exceeds refundable amount {pr.currency} {remaining:,.2f}")
        refund = Refund(reference=generate_reference("RFD"), payment_request_id=pr.id, business_id=pr.business_id,
                        amount=amount, currency=pr.currency, reason=reason, status="pending",
                        created_by_id=actor.id if actor else None)
        db.add(refund)
        db.flush()

        if pr.environment != "live":
            refund.status = "successful"
            self._apply_refund_amount(pr, amount)
            webhooks.emit(db, pr.business_id, "refund.processed", self.refund_view(refund, pr),
                          environment=pr.environment)
            db.commit()
            return refund

        biz = db.get(Business, pr.business_id)
        merchant_wallet = default_business_wallet(db, pr.business_id, pr.currency)
        original = db.get(Transaction, pr.transaction_id)
        if pr.channel == Channel.WALLET:
            payer_wallet = db.get(Wallet, original.source_wallet_id)
            txn = Transaction(
                reference=generate_reference("RFD"), type=TxnType.REFUND, status=TxnStatus.PENDING,
                channel=Channel.WALLET, amount=amount, fee=ZERO, currency=pr.currency,
                source_wallet_id=merchant_wallet.id, destination_wallet_id=payer_wallet.id,
                initiated_by_id=actor.id if actor else None, business_id=pr.business_id, provider="internal",
                provider_mode="internal", related_transaction_id=original.id,
                description=f"Refund from {biz.trading_name or biz.name}",
                meta={"payment_reference": pr.reference, "refund_reference": refund.reference})
            db.add(txn)
            db.flush()
            lj = self.ledger.post(kind="refund", reference=f"{txn.reference}:POST", description=txn.description,
                                  lines=[Line(merchant_wallet.ledger_account_id, DR, amount),
                                         Line(payer_wallet.ledger_account_id, CR, amount)])
            txn.ledger_transaction_id = lj.id
            txn.status = TxnStatus.SUCCESSFUL
            txn.completed_at = utcnow()
            refund.transaction_id = txn.id
            refund.status = "successful"
            self._apply_refund_amount(pr, amount)
            if payer_wallet.user_id:
                notify(db, payer_wallet.user_id, "refund", "Refund received",
                       f"{biz.trading_name or biz.name} refunded {pr.currency} {amount:,.2f}.")
            webhooks.emit(db, pr.business_id, "refund.processed", self.refund_view(refund, pr), environment="live")
            audit(db, "payment.refunded", actor_id=actor.id if actor else None, target_type="payment",
                  target_id=pr.reference, details={"amount": amount, "refund": refund.reference})
            db.commit()
            return refund

        if pr.channel == Channel.CARD:
            # Card refund: two-phase hold on the merchant wallet, then the acquirer refunds the original card.
            provider = get_provider(pr.provider)
            card = (pr.meta or {}).get("card", {})
            txn = Transaction(
                reference=generate_reference("RFD"), type=TxnType.REFUND, status=TxnStatus.PENDING,
                channel=Channel.CARD, amount=amount, fee=ZERO, currency=pr.currency,
                source_wallet_id=merchant_wallet.id, initiated_by_id=actor.id if actor else None,
                business_id=pr.business_id, provider=provider.code, provider_mode=provider.mode,
                related_transaction_id=original.id if original else None,
                counterparty={"card": card.get("label"), "label": card.get("label") or "original card"},
                description=f"Refund {pr.reference} to card",
                meta={"payment_reference": pr.reference, "refund_reference": refund.reference,
                      "original_provider_reference": original.provider_reference if original else None})
            db.add(txn)
            db.flush()
            self.txns._hold(txn, merchant_wallet)
            refund.transaction_id, refund.status = txn.id, "processing"
            audit(db, "payment.refund_initiated", actor_id=actor.id if actor else None, target_type="payment",
                  target_id=pr.reference, details={"amount": amount, "refund": refund.reference, "channel": "card"})
            db.commit()
            self.txns._send_payout(txn)
            db.refresh(refund)
            return refund

        # Mobile money refund: two-phase payout from the merchant wallet back to the payer's number.
        provider = route(Channel.MOBILE_MONEY, pr.network)
        txn = Transaction(
            reference=generate_reference("RFD"), type=TxnType.REFUND, status=TxnStatus.PENDING,
            channel=Channel.MOBILE_MONEY, amount=amount, fee=ZERO, currency=pr.currency,
            source_wallet_id=merchant_wallet.id, initiated_by_id=actor.id if actor else None,
            business_id=pr.business_id, provider=provider.code, provider_mode=provider.mode,
            related_transaction_id=original.id if original else None,
            counterparty={"msisdn": pr.customer_phone, "network": pr.network, "label": pr.customer_phone},
            description=f"Refund {pr.reference}",
            meta={"payment_reference": pr.reference, "refund_reference": refund.reference})
        db.add(txn)
        db.flush()
        self.txns._hold(txn, merchant_wallet)
        refund.transaction_id = txn.id
        refund.status = "processing"
        audit(db, "payment.refund_initiated", actor_id=actor.id if actor else None, target_type="payment",
              target_id=pr.reference, details={"amount": amount, "refund": refund.reference})
        db.commit()
        self.txns._send_payout(txn)
        db.refresh(refund)
        return refund

    def _apply_refund_amount(self, pr: PaymentRequest, amount: Decimal) -> None:
        pr.amount_refunded += amount
        pr.status = PaymentStatus.REFUNDED if pr.amount_refunded >= pr.amount else PaymentStatus.PARTIALLY_REFUNDED

    @staticmethod
    def refund_view(refund: Refund, pr: PaymentRequest) -> dict:
        return {"reference": refund.reference, "payment_reference": pr.reference, "amount": refund.amount,
                "currency": refund.currency, "status": refund.status, "reason": refund.reason,
                "created_at": refund.created_at}

    # ================================================================ settlements
    def settle(self, business: Business, actor: User | None, amount: object | None = None,
               note: str | None = None) -> Settlement:
        """Pay out the merchant wallet. ``actor=None`` means a scheduled (system) settlement."""
        actor_id = actor.id if actor else None
        db = self.db
        ensure_business_can_debit(business)
        dest = business.settlement_destination or {}
        if not dest.get("channel"):
            raise ValidationFailed("Set a settlement bank or mobile money account first")
        wallet = default_business_wallet(db, business.id, "GHS")
        available = self.ledger.get_account(wallet.ledger_account_id).balance
        channel = dest["channel"]
        if amount is None:
            fee = fees.compute_fee(db, TxnType.SETTLEMENT, available, wallet.currency, channel=channel,
                                   payer="merchant")
            amount = available - fee
        else:
            amount = validate_amount(amount, wallet.currency)
            fee = fees.compute_fee(db, TxnType.SETTLEMENT, amount, wallet.currency, channel=channel, payer="merchant")
        if amount <= 0:
            raise ValidationFailed("No funds available to settle")
        network = detect_network(dest["msisdn"]).value if channel == Channel.MOBILE_MONEY else None
        provider = route(channel, network)
        label = (f"{dest.get('bank_code')} ****{dest.get('account_number', '')[-4:]}" if channel == "bank"
                 else dest.get("msisdn"))
        settlement = Settlement(reference=generate_reference("STL"), business_id=business.id, amount=amount, fee=fee,
                                currency=wallet.currency, status="processing", destination=dest,
                                initiated_by_id=actor_id, note=note)
        db.add(settlement)
        db.flush()
        txn = Transaction(
            reference=generate_reference("STL"), type=TxnType.SETTLEMENT, status=TxnStatus.PENDING, channel=channel,
            amount=amount, fee=fee, currency=wallet.currency, source_wallet_id=wallet.id, initiated_by_id=actor_id,
            business_id=business.id, provider=provider.code, provider_mode=provider.mode,
            counterparty={**dest, "name": dest.get("account_name"), "msisdn": dest.get("msisdn"),
                          "network": network, "label": label},
            description=f"Settlement to {label}", meta={"settlement_reference": settlement.reference})
        db.add(txn)
        db.flush()
        self.txns._hold(txn, wallet)  # raises InsufficientFunds if balance is too low
        settlement.transaction_id = txn.id
        audit(db, "business.settlement_initiated", actor_id=actor_id, actor_type="user" if actor else "system",
              target_type="business",
              target_id=business.id, details={"amount": amount, "fee": fee, "settlement": settlement.reference})
        db.commit()
        self.txns._send_payout(txn)
        db.refresh(settlement)
        return settlement

    # ================================================================ payment links
    def create_link(self, business: Business, actor: User, *, title: str, amount: object | None,
                    description: str | None, currency: str = "GHS", single_use: bool = False,
                    redirect_url: str | None = None, slug: str | None = None,
                    fields: list[dict] | None = None) -> PaymentLink:
        db = self.db
        amt = validate_amount(amount, currency) if amount not in (None, "") else None
        base = re.sub(r"[^a-z0-9]+", "-", (slug or title).lower()).strip("-")[:40] or "pay"
        candidate = base
        while db.scalar(select(PaymentLink.id).where(PaymentLink.slug == candidate)):
            candidate = f"{base}-{secrets.token_hex(3)}"
        link = PaymentLink(business_id=business.id, slug=candidate, title=title, description=description, amount=amt,
                           currency=currency, single_use=single_use, redirect_url=redirect_url,
                           fields=forms.normalise_fields(fields or []))
        db.add(link)
        audit(db, "payment_link.created", actor_id=actor.id, target_type="business", target_id=business.id,
              details={"slug": candidate})
        db.commit()
        return link

    def start_link_payment(self, link: PaymentLink, *, amount: object | None, customer_email: str | None,
                           customer_name: str | None, customer_phone: str | None,
                           answers: dict[str, str] | None = None) -> PaymentRequest:
        if not link.active:
            raise Conflict("This payment link is no longer active", code="link_inactive")
        biz = self.db.get(Business, link.business_id)
        if link.amount is None and amount in (None, ""):
            raise ValidationFailed("Enter an amount")
        form = forms.validate_answers(link.fields or [], answers or {})
        typed = {a["type"]: a["value"] for a in reversed(form)}  # first phone/email answer doubles as contact
        pr = self.create_request(biz, amount=link.amount if link.amount is not None else amount,
                                 currency=link.currency, description=link.title,
                                 customer_email=customer_email or typed.get("email"),
                                 customer_name=customer_name, customer_phone=customer_phone or typed.get("phone"),
                                 environment="live", payment_link=link, metadata={"form": form} if form else None)
        self.db.commit()
        return pr


# ==================================================================== transaction lifecycle hook
def on_transaction_final(db: Session, txn: Transaction) -> None:
    """Propagate a final Transaction status to the merchant-facing records that depend on it."""
    meta = txn.meta or {}
    if txn.type == TxnType.PAYMENT and meta.get("payment_reference"):
        pr = db.scalar(select(PaymentRequest).where(PaymentRequest.reference == meta["payment_reference"]))
        if pr and pr.status in (PaymentStatus.PENDING, PaymentStatus.PROCESSING, PaymentStatus.FAILED):
            svc = PaymentService(db)
            if txn.status == TxnStatus.SUCCESSFUL:
                svc._mark_paid(pr)
            elif txn.status == TxnStatus.FAILED:
                pr.status, pr.failure_reason = PaymentStatus.FAILED, txn.failure_reason
                webhooks.emit(db, pr.business_id, "charge.failed", charge_view(pr), environment=pr.environment)
    elif txn.type == TxnType.REFUND and meta.get("refund_reference"):
        refund = db.scalar(select(Refund).where(Refund.reference == meta["refund_reference"]))
        pr = db.get(PaymentRequest, refund.payment_request_id) if refund else None
        if refund and refund.status in ("pending", "processing"):
            if txn.status == TxnStatus.SUCCESSFUL:
                refund.status = "successful"
                PaymentService(db)._apply_refund_amount(pr, refund.amount)
                webhooks.emit(db, pr.business_id, "refund.processed", PaymentService.refund_view(refund, pr),
                              environment="live")
            elif txn.status == TxnStatus.FAILED:
                refund.status = "failed"
                webhooks.emit(db, pr.business_id, "refund.failed", PaymentService.refund_view(refund, pr),
                              environment="live")
    elif txn.type == TxnType.SETTLEMENT and meta.get("settlement_reference"):
        s = db.scalar(select(Settlement).where(Settlement.reference == meta["settlement_reference"]))
        if s and s.status in ("pending", "processing"):
            if txn.status == TxnStatus.SUCCESSFUL:
                s.status, s.paid_at = "paid", utcnow()
                event = "settlement.paid"
            else:
                s.status, s.note = "failed", txn.failure_reason
                event = "settlement.failed"
            webhooks.emit(db, s.business_id, event, {"reference": s.reference, "amount": s.amount, "fee": s.fee,
                                                     "currency": s.currency, "status": s.status},
                          environment="live")
