"""Customer money movement: deposits, withdrawals, wallet transfers, reversals, adjustments.

Two-phase flows (anything that leaves the platform) follow this pattern:

1. Persist a ``Transaction`` and, for outflows, a *hold* journal
   (DR customer wallet / CR PENDING_PAYOUTS) and COMMIT before calling the provider.
2. Call the provider.
3. On success post the completion journal (DR PENDING_PAYOUTS / CR provider clearing + fee revenue).
   On failure post a compensating reversal of the hold.

So a crash at any point leaves the books balanced, and an in-flight payout can always be resolved
from the provider's status.
"""

from __future__ import annotations

import logging
import uuid

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import utcnow
from app.core.errors import AppError, Conflict, Forbidden, NotFound, ValidationFailed
from app.core.money import ZERO, validate_amount
from app.core.security import generate_reference
from app.models.enums import Channel, TxnStatus, TxnType
from app.models.ledger import Wallet
from app.models.transaction import ProviderTransaction, Transaction
from app.models.user import User
from app.providers import get_provider, route
from app.providers.base import CollectionRequest, DisbursementRequest, ProviderResult
from app.services import fees, limits, risk
from app.services.audit import audit
from app.services.ghana import BANKS, NETWORK_NAMES, detect_network, normalize_msisdn, validate_bank
from app.services.ledger import CR, DR, LedgerService, Line, SystemAccount
from app.services.notifications import notify
from app.services.restrictions import ensure_user_can_credit, ensure_user_can_debit, ensure_wallet_can_receive
from app.services.wallets import (
    assert_wallet_active,
    balance,
    get_owned_wallet,
    wallet_by_number,
    wallet_owner_name,
)

log = logging.getLogger("fincore.transactions")
FINAL = {TxnStatus.SUCCESSFUL, TxnStatus.FAILED, TxnStatus.REVERSED}


def _record_provider_txn(db: Session, provider_code: str, mode: str, direction: str, txn: Transaction,
                         result: ProviderResult) -> None:
    existing = db.scalar(select(ProviderTransaction).where(
        ProviderTransaction.provider == provider_code,
        ProviderTransaction.provider_reference == result.provider_reference))
    if existing:
        existing.status = result.status
        existing.raw = result.raw
        return
    db.add(ProviderTransaction(provider=provider_code, mode=mode, direction=direction,
                               provider_reference=result.provider_reference, internal_reference=txn.reference,
                               amount=txn.amount, currency=txn.currency, status=result.status, raw=result.raw))


class TransactionService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.ledger = LedgerService(db)

    # ================================================================ deposits
    def deposit_mobile_money(self, user: User, wallet_id: uuid.UUID, amount: object, phone: str,
                             description: str = "") -> Transaction:
        db = self.db
        wallet = get_owned_wallet(db, user, wallet_id)
        assert_wallet_active(wallet)
        amount = validate_amount(amount, wallet.currency)
        ensure_user_can_credit(db, user)
        msisdn = normalize_msisdn(phone)
        network = detect_network(msisdn)
        limits.check_limits(db, user, TxnType.DEPOSIT, amount, wallet.currency)
        limits.check_balance_cap(db, user, balance(db, wallet), amount, wallet.currency)
        fee = fees.compute_fee(db, TxnType.DEPOSIT, amount, wallet.currency, channel=Channel.MOBILE_MONEY)
        if fee >= amount:
            raise ValidationFailed("Amount is too small to cover the deposit fee")
        provider = route(Channel.MOBILE_MONEY, network)

        txn = Transaction(
            reference=generate_reference("DEP"), type=TxnType.DEPOSIT, status=TxnStatus.PENDING,
            channel=Channel.MOBILE_MONEY, amount=amount, fee=fee, currency=wallet.currency,
            destination_wallet_id=wallet.id, initiated_by_id=user.id, provider=provider.code,
            provider_mode=provider.mode, counterparty={"msisdn": msisdn, "network": network.value},
            description=description or f"Deposit from {NETWORK_NAMES[network]}")
        db.add(txn)
        db.flush()
        audit(db, "wallet.deposit.initiated", actor_id=user.id, target_type="transaction", target_id=txn.reference,
              details={"amount": amount, "provider": provider.code})
        db.commit()

        try:
            result = provider.collect(CollectionRequest(
                reference=txn.reference, amount=amount, currency=wallet.currency, msisdn=msisdn,
                network=network.value, email=user.email, description=txn.description))
        except (httpx.TimeoutException, httpx.NetworkError):
            log.warning("deposit provider call timed out", extra={"reference": txn.reference})
            txn.status = TxnStatus.PROCESSING
            db.commit()
            return txn
        except AppError as exc:
            txn.status = TxnStatus.FAILED
            txn.failure_reason = exc.message
            db.commit()
            raise
        _record_provider_txn(db, provider.code, provider.mode, "collection", txn, result)
        self.apply_provider_result(txn, result)
        db.commit()
        return txn

    def _complete_deposit(self, txn: Transaction) -> None:
        wallet = self.db.get(Wallet, txn.destination_wallet_id)
        clearing = self.ledger.system_account(SystemAccount.clearing(txn.provider), txn.currency)
        lines = [Line(clearing.id, DR, txn.amount), Line(wallet.ledger_account_id, CR, txn.amount - txn.fee)]
        if txn.fee > 0:
            lines.append(Line(self.ledger.system_account(SystemAccount.FEE_REVENUE, txn.currency).id, CR, txn.fee))
        lj = self.ledger.post(kind=txn.type, lines=lines, reference=f"{txn.reference}:POST",
                              description=txn.description)
        txn.ledger_transaction_id = lj.id
        txn.status = TxnStatus.SUCCESSFUL
        txn.completed_at = utcnow()
        if wallet.user_id and txn.type == TxnType.DEPOSIT:
            notify(self.db, wallet.user_id, "deposit", "Deposit received",
                   f"{txn.currency} {txn.amount - txn.fee:,.2f} has been added to your wallet. Ref {txn.reference}",
                   {"reference": txn.reference})

    # ================================================================ withdrawals
    def withdraw(self, user: User, wallet_id: uuid.UUID, amount: object, *, channel: str,
                 phone: str | None = None, bank_code: str | None = None, account_number: str | None = None,
                 account_name: str | None = None, description: str = "") -> Transaction:
        db = self.db
        wallet = get_owned_wallet(db, user, wallet_id)
        assert_wallet_active(wallet)
        amount = validate_amount(amount, wallet.currency)
        ensure_user_can_debit(db, user)
        counterparty, network = self._payout_destination(channel, phone, bank_code, account_number, account_name)
        limits.check_limits(db, user, TxnType.WITHDRAWAL, amount, wallet.currency)
        ra = risk.assess(db, user, TxnType.WITHDRAWAL, amount)
        if ra.blocked:
            risk.record_alerts(db, ra, user_id=user.id)
            db.commit()
            raise Forbidden("This transaction has been held for review. Please contact support.", code="risk_blocked")
        fee = fees.compute_fee(db, TxnType.WITHDRAWAL, amount, wallet.currency, channel=channel)
        provider = route(channel, network)

        txn = Transaction(
            reference=generate_reference("WDR"), type=TxnType.WITHDRAWAL, status=TxnStatus.PENDING,
            channel=channel, amount=amount, fee=fee, currency=wallet.currency, source_wallet_id=wallet.id,
            initiated_by_id=user.id, provider=provider.code, provider_mode=provider.mode,
            counterparty=counterparty, risk_score=ra.score,
            description=description or f"Withdrawal to {counterparty.get('label')}")
        db.add(txn)
        db.flush()
        self._hold(txn, wallet)  # raises InsufficientFunds -> nothing committed
        risk.record_alerts(db, ra, user_id=user.id, transaction_id=txn.id)
        audit(db, "wallet.withdrawal.initiated", actor_id=user.id, target_type="transaction",
              target_id=txn.reference, details={"amount": amount, "fee": fee, "channel": channel})
        db.commit()
        self._send_payout(txn)
        return txn

    def _payout_destination(self, channel: str, phone, bank_code, account_number, account_name):
        if channel == Channel.MOBILE_MONEY:
            if not phone:
                raise ValidationFailed("Phone number is required for mobile money withdrawals")
            msisdn = normalize_msisdn(phone)
            network = detect_network(msisdn)
            return ({"msisdn": msisdn, "network": network.value, "name": account_name,
                     "label": f"{NETWORK_NAMES[network]} {msisdn}"}, network.value)
        if channel == Channel.BANK:
            if not (bank_code and account_number):
                raise ValidationFailed("Bank code and account number are required for bank withdrawals")
            code, acct = validate_bank(bank_code, account_number)
            return ({"bank_code": code, "account_number": acct, "name": account_name,
                     "label": f"{BANKS[code]} ****{acct[-4:]}"}, None)
        raise ValidationFailed("Unsupported withdrawal channel")

    def _hold(self, txn: Transaction, wallet: Wallet) -> None:
        pending = self.ledger.system_account(SystemAccount.PENDING_PAYOUTS, txn.currency)
        total = txn.amount + txn.fee
        lj = self.ledger.post(kind=f"{txn.type}_hold", reference=f"{txn.reference}:HOLD", description=txn.description,
                              lines=[Line(wallet.ledger_account_id, DR, total), Line(pending.id, CR, total)])
        txn.ledger_transaction_id = lj.id
        txn.status = TxnStatus.PROCESSING

    def _send_payout(self, txn: Transaction) -> None:
        db = self.db
        provider = get_provider(txn.provider)
        cp = txn.counterparty
        try:
            result = provider.disburse(DisbursementRequest(
                reference=txn.reference, amount=txn.amount, currency=txn.currency, channel=txn.channel,
                msisdn=cp.get("msisdn"), network=cp.get("network"), bank_code=cp.get("bank_code"),
                account_number=cp.get("account_number"), account_name=cp.get("name"),
                description=txn.description))
        except (httpx.TimeoutException, httpx.NetworkError):
            # Outcome unknown: leave PROCESSING; the status poller / provider callback resolves it.
            log.warning("payout provider call timed out", extra={"reference": txn.reference})
            return
        except AppError as exc:
            self._fail_outflow(txn, exc.message)
            db.commit()
            return
        _record_provider_txn(db, provider.code, provider.mode, "disbursement", txn, result)
        self.apply_provider_result(txn, result)
        db.commit()

    def _complete_outflow(self, txn: Transaction) -> None:
        pending = self.ledger.system_account(SystemAccount.PENDING_PAYOUTS, txn.currency)
        clearing = self.ledger.system_account(SystemAccount.clearing(txn.provider), txn.currency)
        lines = [Line(pending.id, DR, txn.amount + txn.fee), Line(clearing.id, CR, txn.amount)]
        if txn.fee > 0:
            lines.append(Line(self.ledger.system_account(SystemAccount.FEE_REVENUE, txn.currency).id, CR, txn.fee))
        lj = self.ledger.post(kind=f"{txn.type}_complete", lines=lines, reference=f"{txn.reference}:DONE",
                              description=txn.description)
        txn.completion_ledger_transaction_id = lj.id
        txn.status = TxnStatus.SUCCESSFUL
        txn.completed_at = utcnow()
        if txn.initiated_by_id and txn.type == TxnType.WITHDRAWAL:
            notify(self.db, txn.initiated_by_id, "withdrawal", "Withdrawal successful",
                   f"{txn.currency} {txn.amount:,.2f} sent to {txn.counterparty.get('label')}. Ref {txn.reference}",
                   {"reference": txn.reference})

    def _fail_outflow(self, txn: Transaction, reason: str) -> None:
        if txn.ledger_transaction_id:
            lj = self.ledger.reverse(txn.ledger_transaction_id, reason=f"Payout failed: {reason}",
                                     kind=f"{txn.type}_release")
            txn.completion_ledger_transaction_id = lj.id
        txn.status = TxnStatus.FAILED
        txn.failure_reason = reason
        txn.completed_at = utcnow()
        if txn.initiated_by_id and txn.type == TxnType.WITHDRAWAL:
            notify(self.db, txn.initiated_by_id, "withdrawal", "Withdrawal failed",
                   f"Your withdrawal {txn.reference} failed ({reason}). The funds have been returned to your wallet.",
                   {"reference": txn.reference})

    # ================================================================ provider outcomes
    def apply_provider_result(self, txn: Transaction, result: ProviderResult) -> None:
        """Idempotently move a transaction to the state reported by its provider."""
        if txn.status in FINAL:
            return
        txn.provider_reference = result.provider_reference
        inflow = txn.type in (TxnType.DEPOSIT, TxnType.PAYMENT)
        if result.status == "successful":
            if inflow:
                self._complete_deposit(txn)
            else:
                self._complete_outflow(txn)
        elif result.status == "failed":
            if inflow:
                txn.status = TxnStatus.FAILED
                txn.failure_reason = result.message
                txn.completed_at = utcnow()
            else:
                self._fail_outflow(txn, result.message or "Provider rejected payout")
        else:
            txn.status = TxnStatus.PROCESSING
        if txn.status in FINAL:
            from app.services.payments import on_transaction_final  # local import avoids a cycle

            on_transaction_final(self.db, txn)

    def refresh_from_provider(self, txn: Transaction) -> Transaction:
        if txn.status in FINAL or not txn.provider_reference:
            return txn
        provider = get_provider(txn.provider)
        direction = "collection" if txn.type in (TxnType.DEPOSIT, TxnType.PAYMENT) else "disbursement"
        result = provider.check_status(txn.provider_reference, direction)
        self.apply_provider_result(txn, result)
        self.db.commit()
        return txn

    # ================================================================ transfers
    def transfer(self, user: User, source_wallet_id: uuid.UUID, destination_account: str, amount: object,
                 narration: str = "") -> Transaction:
        db = self.db
        src = get_owned_wallet(db, user, source_wallet_id)
        assert_wallet_active(src)
        dst = wallet_by_number(db, destination_account)
        if dst.id == src.id:
            raise ValidationFailed("Cannot transfer to the same wallet")
        if dst.currency != src.currency:
            raise ValidationFailed("Cross-currency transfers are not supported yet")
        amount = validate_amount(amount, src.currency)
        ensure_user_can_debit(db, user)
        ensure_wallet_can_receive(db, dst)
        limits.check_limits(db, user, TxnType.TRANSFER, amount, src.currency)
        if dst.user_id:
            recipient = db.get(User, dst.user_id)
            limits.check_balance_cap(db, recipient, balance(db, dst), amount, dst.currency)
        ra = risk.assess(db, user, TxnType.TRANSFER, amount)
        if ra.blocked:
            risk.record_alerts(db, ra, user_id=user.id)
            db.commit()
            raise Forbidden("This transfer has been held for review. Please contact support.", code="risk_blocked")
        fee = fees.compute_fee(db, TxnType.TRANSFER, amount, src.currency, channel=Channel.WALLET)
        recipient_name = wallet_owner_name(db, dst)
        txn = Transaction(
            reference=generate_reference("TRF"), type=TxnType.TRANSFER, status=TxnStatus.PENDING,
            channel=Channel.WALLET, amount=amount, fee=fee, currency=src.currency, source_wallet_id=src.id,
            destination_wallet_id=dst.id, initiated_by_id=user.id, provider="internal", provider_mode="internal",
            counterparty={"account_number": dst.account_number, "name": recipient_name},
            description=narration or f"Transfer to {recipient_name}", risk_score=ra.score)
        db.add(txn)
        db.flush()
        lines = [Line(src.ledger_account_id, DR, amount + fee), Line(dst.ledger_account_id, CR, amount)]
        if fee > 0:
            lines.append(Line(self.ledger.system_account(SystemAccount.FEE_REVENUE, src.currency).id, CR, fee))
        lj = self.ledger.post(kind="transfer", lines=lines, reference=f"{txn.reference}:POST",
                              description=txn.description)
        txn.ledger_transaction_id = lj.id
        txn.status = TxnStatus.SUCCESSFUL
        txn.completed_at = utcnow()
        risk.record_alerts(db, ra, user_id=user.id, transaction_id=txn.id)
        audit(db, "wallet.transfer", actor_id=user.id, target_type="transaction", target_id=txn.reference,
              details={"amount": amount, "to": dst.account_number})
        notify(db, user.id, "transfer", "Transfer sent",
               f"You sent {src.currency} {amount:,.2f} to {recipient_name}. Ref {txn.reference}",
               {"reference": txn.reference})
        if dst.user_id:
            notify(db, dst.user_id, "transfer", "Money received",
                   f"You received {src.currency} {amount:,.2f} from {user.full_name}. Ref {txn.reference}",
                   {"reference": txn.reference})
        db.commit()
        return txn

    # ================================================================ staff operations
    def reverse(self, txn_id: uuid.UUID, staff: User, reason: str) -> Transaction:
        db = self.db
        txn = db.get(Transaction, txn_id)
        if not txn:
            raise NotFound("Transaction not found")
        if txn.status != TxnStatus.SUCCESSFUL:
            raise Conflict("Only successful transactions can be reversed")
        if txn.type not in (TxnType.TRANSFER, TxnType.PAYMENT, TxnType.DEPOSIT, TxnType.ADJUSTMENT):
            raise Conflict(f"{txn.type} transactions cannot be reversed; use a refund or adjustment")
        rev = Transaction(
            reference=generate_reference("REV"), type=TxnType.REVERSAL, status=TxnStatus.PENDING,
            channel=txn.channel, amount=txn.amount, fee=ZERO, currency=txn.currency,
            source_wallet_id=txn.destination_wallet_id, destination_wallet_id=txn.source_wallet_id,
            initiated_by_id=staff.id, provider="internal", provider_mode=txn.provider_mode,
            related_transaction_id=txn.id, description=f"Reversal of {txn.reference}: {reason}",
            business_id=txn.business_id)
        db.add(rev)
        db.flush()
        lj = self.ledger.reverse(txn.ledger_transaction_id, reason=reason)
        rev.ledger_transaction_id = lj.id
        rev.status = TxnStatus.SUCCESSFUL
        rev.completed_at = utcnow()
        txn.status = TxnStatus.REVERSED
        audit(db, "transaction.reversed", actor_id=staff.id, actor_type="staff", target_type="transaction",
              target_id=txn.reference, details={"reason": reason, "reversal": rev.reference})
        db.commit()
        return rev

    def adjust(self, wallet: Wallet, staff: User, amount: object, direction: str, reason: str) -> Transaction:
        """Manual credit/debit against the ADJUSTMENTS account (e.g. goodwill credit, error correction)."""
        db = self.db
        amount = validate_amount(amount, wallet.currency)
        if direction not in ("credit", "debit"):
            raise ValidationFailed("direction must be credit or debit")
        adj = self.ledger.system_account(SystemAccount.ADJUSTMENTS, wallet.currency)
        txn = Transaction(
            reference=generate_reference("ADJ"), type=TxnType.ADJUSTMENT, status=TxnStatus.PENDING,
            channel=Channel.WALLET, amount=amount, fee=ZERO, currency=wallet.currency,
            source_wallet_id=wallet.id if direction == "debit" else None,
            destination_wallet_id=wallet.id if direction == "credit" else None,
            initiated_by_id=staff.id, provider="internal", provider_mode="internal",
            description=f"Adjustment: {reason}", business_id=wallet.business_id)
        db.add(txn)
        db.flush()
        if direction == "credit":
            lines = [Line(adj.id, DR, amount), Line(wallet.ledger_account_id, CR, amount)]
        else:
            lines = [Line(wallet.ledger_account_id, DR, amount), Line(adj.id, CR, amount)]
        lj = self.ledger.post(kind="adjustment", lines=lines, reference=f"{txn.reference}:POST",
                              description=txn.description, enforce_restrictions=False)
        txn.ledger_transaction_id = lj.id
        txn.status = TxnStatus.SUCCESSFUL
        txn.completed_at = utcnow()
        audit(db, "wallet.adjusted", actor_id=staff.id, actor_type="staff", target_type="wallet",
              target_id=wallet.account_number, details={"amount": amount, "direction": direction, "reason": reason})
        db.commit()
        return txn


def find_by_provider_reference(db: Session, provider: str, provider_reference: str,
                               internal_reference: str | None) -> Transaction | None:
    txn = db.scalar(select(Transaction).where(Transaction.provider == provider,
                                              Transaction.provider_reference == provider_reference))
    if not txn and internal_reference:
        txn = db.scalar(select(Transaction).where(Transaction.reference == internal_reference))
    return txn

