"""Deterministic sandbox provider. NO REAL MONEY MOVES.

Magic values let developers and tests exercise every path:

=========================  ==============================================
Phone number ends in       Outcome
=========================  ==============================================
``0000``                   failed  ("Payer has insufficient balance")
``1111``                   pending (complete later via the simulate endpoint
                           ``POST /api/v1/sandbox/provider-events``)
``2222``                   failed  ("Payer declined / timed out")
anything else              successful
=========================  ==============================================

Amount ``666.00`` always fails (simulated provider outage) regardless of number.
Bank account numbers follow the same suffix rules.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
from decimal import Decimal

from app.core.config import settings
from app.providers.base import (
    AccountLookup,
    CollectionRequest,
    DisbursementRequest,
    PaymentProvider,
    ProviderEvent,
    ProviderResult,
)

_SANDBOX_NAMES = ["Kwame Mensah", "Ama Owusu", "Kofi Boateng", "Akosua Asante", "Yaw Darko", "Efua Addo"]


def _outcome(identifier: str | None, amount: Decimal) -> tuple[str, str]:
    ident = identifier or ""
    if amount == Decimal("666.00"):
        return "failed", "Simulated provider outage"
    if ident.endswith("0000"):
        return "failed", "Payer has insufficient balance"
    if ident.endswith("2222"):
        return "failed", "Payer declined or approval timed out"
    if ident.endswith("1111"):
        return "pending", "Awaiting payer approval"
    return "successful", "Approved"


class SandboxProvider(PaymentProvider):
    code = "sandbox"
    display_name = "FinCore Sandbox (simulated)"
    mode = "sandbox"

    def collect(self, req: CollectionRequest) -> ProviderResult:
        status, msg = _outcome(req.msisdn or req.email, req.amount)
        return ProviderResult(status=status, provider_reference=f"SBX-C-{secrets.token_hex(8).upper()}",
                              message=msg, raw={"simulated": True, "network": req.network})

    def disburse(self, req: DisbursementRequest) -> ProviderResult:
        status, msg = _outcome(req.msisdn or req.account_number, req.amount)
        return ProviderResult(status=status, provider_reference=f"SBX-D-{secrets.token_hex(8).upper()}",
                              message=msg, raw={"simulated": True, "channel": req.channel})

    def check_status(self, provider_reference: str, direction: str) -> ProviderResult:
        return ProviderResult(status="pending", provider_reference=provider_reference, message="Use simulate endpoint")

    def lookup_account(self, *, msisdn=None, bank_code=None, account_number=None) -> AccountLookup:
        ident = msisdn or account_number or ""
        if ident.endswith("9999"):
            return AccountLookup(valid=False, message="Account not found")
        idx = int(hashlib.sha256(ident.encode()).hexdigest(), 16) % len(_SANDBOX_NAMES)
        return AccountLookup(valid=True, account_name=_SANDBOX_NAMES[idx], message="Sandbox name lookup")

    # Sandbox events are signed with the platform secret so the simulate endpoint can't be spoofed
    # by third parties in shared sandboxes.
    @staticmethod
    def sign(body: bytes) -> str:
        return hmac.new(settings.secret_key.encode(), body, hashlib.sha256).hexdigest()

    def verify_webhook(self, headers: dict[str, str], body: bytes) -> bool:
        sig = headers.get("x-sandbox-signature", "")
        return hmac.compare_digest(self.sign(body), sig)

    def parse_webhook(self, body: dict) -> ProviderEvent:
        return ProviderEvent(provider_reference=body["provider_reference"],
                             internal_reference=body.get("reference"), status=body["status"], raw=body)

    @staticmethod
    def event_body(provider_reference: str, status: str, reference: str | None = None) -> bytes:
        return json.dumps({"provider_reference": provider_reference, "status": status,
                           "reference": reference}).encode()
