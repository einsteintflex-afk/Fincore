"""Card acceptance through an acquiring bank's *hosted payment page*.

FinCore never receives card numbers in production: the payer is redirected to the acquirer's page, then
returns to FinCore, which asks the acquirer for the result (and also accepts its signed callback). This keeps
FinCore out of the heaviest PCI-DSS scope (SAQ-A). Refunds are sent to the acquirer against the original
payment.

* ``SandboxCardAcquirer`` – simulated hosted page served by FinCore itself, clearly marked TEST, with test cards.
* ``BankCardAcquirer``    – slot for the owner's acquiring bank (Ecobank, GCB, CalBank, Stanbic...). Its API
  spec and credentials arrive with the merchant (acquiring) agreement; until then it raises
  ``ProviderNotConfigured``.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import jwt

from app.core.config import settings
from app.core.errors import ProviderNotConfigured, Unauthorized, ValidationFailed
from app.core.security import JWT_ALG
from app.providers.base import CollectionRequest, DisbursementRequest, PaymentProvider, ProviderResult


@dataclass
class CardSession:
    session_id: str
    redirect_url: str


class CardAcquirer(PaymentProvider):
    supports_collection = True
    supports_disbursement = True  # refunds to the original card

    def create_session(self, *, reference: str, amount: Decimal, currency: str, description: str,
                       return_url: str, customer_email: str | None) -> CardSession:
        raise NotImplementedError

    def collect(self, req: CollectionRequest) -> ProviderResult:  # pragma: no cover - cards use sessions
        raise ValidationFailed("Card payments use a hosted payment session")


# ------------------------------------------------------------------ sandbox
# Test cards (all pass the Luhn check). Any expiry in the future and any 3-digit CVC.
TEST_CARDS = {
    "4111111111111111": ("successful", "Approved"),
    "5555555555554444": ("successful", "Approved"),
    "4000000000000002": ("failed", "Card declined by issuer"),
    "4000000000009995": ("failed", "Insufficient funds"),
    "4000000000003220": ("requires_3ds", "Cardholder authentication required"),
}


def luhn_ok(number: str) -> bool:
    digits = [int(d) for d in number]
    checksum = 0
    for i, d in enumerate(reversed(digits)):
        if i % 2:
            d *= 2
            if d > 9:
                d -= 9
        checksum += d
    return len(digits) >= 12 and checksum % 10 == 0


def card_brand(number: str) -> str:
    if number.startswith("4"):
        return "VISA"
    if number[:2] in {"51", "52", "53", "54", "55"} or 2221 <= int(number[:4] or 0) <= 2720:
        return "MASTERCARD"
    if number.startswith(("506", "507", "6500")):
        return "VERVE"
    return "CARD"


def sandbox_token(reference: str, session_id: str, return_url: str) -> str:
    now = datetime.now(timezone.utc)
    return jwt.encode({"typ": "sandbox_card", "ref": reference, "sid": session_id, "ret": return_url, "iat": now,
                       "exp": now + timedelta(minutes=30)}, settings.secret_key, algorithm=JWT_ALG)


def read_sandbox_token(token: str) -> dict:
    try:
        data = jwt.decode(token, settings.secret_key, algorithms=[JWT_ALG])
    except jwt.PyJWTError as exc:
        raise Unauthorized("This test card session has expired", code="session_expired") from exc
    if data.get("typ") != "sandbox_card":
        raise Unauthorized("Invalid session")
    return data


def sandbox_outcome(number: str, expiry: str, cvc: str) -> tuple[str, str]:
    number = "".join(ch for ch in number if ch.isdigit())
    if not luhn_ok(number):
        raise ValidationFailed("Card number is not valid")
    try:
        month, year = (int(x) for x in expiry.replace(" ", "").split("/"))
        year = year + 2000 if year < 100 else year
    except ValueError as exc:
        raise ValidationFailed("Expiry must be MM/YY") from exc
    now = datetime.now(timezone.utc)
    if not 1 <= month <= 12 or (year, month) < (now.year, now.month):
        raise ValidationFailed("Card has expired")
    if not (cvc.isdigit() and len(cvc) in (3, 4)):
        raise ValidationFailed("CVC must be 3 or 4 digits")
    return TEST_CARDS.get(number, ("failed", "Use one of the test cards in sandbox mode"))


class SandboxCardAcquirer(CardAcquirer):
    code = "sandbox_card"
    display_name = "Test card acquirer (simulated)"
    mode = "sandbox"

    def create_session(self, *, reference, amount, currency, description, return_url, customer_email) -> CardSession:
        sid = "SBXCARD-" + secrets.token_hex(8).upper()
        return CardSession(session_id=sid,
                           redirect_url=f"{settings.frontend_base_url}/sandbox-card/{sandbox_token(reference, sid, return_url)}")

    def check_status(self, provider_reference: str, direction: str) -> ProviderResult:
        # The simulated page reports its outcome directly (like an acquirer callback); nothing to poll.
        return ProviderResult(status="pending", provider_reference=provider_reference, message="Awaiting card entry")

    def disburse(self, req: DisbursementRequest) -> ProviderResult:
        return ProviderResult(status="successful", provider_reference=f"SBXREF-{secrets.token_hex(6).upper()}",
                              message="Refund to card approved (simulated)", raw={"simulated": True})


# ------------------------------------------------------------------ owner's acquiring bank (pending agreement)
class BankCardAcquirer(CardAcquirer):
    code = "bank_card"
    display_name = "Acquiring bank (cards)"
    mode = "live"
    required = ("card_acquirer_base_url", "card_acquirer_merchant_id", "card_acquirer_api_key",
                "card_acquirer_webhook_secret")

    def is_configured(self) -> bool:
        return all(getattr(settings, s) for s in self.required)

    def _blocked(self):
        missing = [f"FINCORE_{s.upper()}" for s in self.required if not getattr(settings, s)]
        if missing:
            raise ProviderNotConfigured("Card payments are not connected to an acquiring bank yet. Missing: "
                                        + ", ".join(missing))
        raise ProviderNotConfigured("Acquiring-bank credentials are set but the bank's API specification has not "
                                    "been implemented yet. See docs/PAYMENT_PROVIDERS.md.")

    def create_session(self, **kw) -> CardSession:
        self._blocked()

    def check_status(self, provider_reference: str, direction: str) -> ProviderResult:
        self._blocked()

    def disburse(self, req: DisbursementRequest) -> ProviderResult:
        self._blocked()
