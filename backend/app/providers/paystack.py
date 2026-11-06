"""Paystack (licensed gateway operating in Ghana) adapter – mobile money charges and transfers.

Docs: https://paystack.com/docs/api/  Required: ``FINCORE_PAYSTACK_SECRET_KEY`` (sk_test_... / sk_live_...).
Amounts are sent in pesewas (minor units) as integers.
"""

from __future__ import annotations

import hashlib
import hmac
from decimal import Decimal

import httpx

from app.core.config import settings
from app.core.errors import ProviderError, ProviderNotConfigured
from app.core.money import exponent
from app.providers.base import (
    AccountLookup,
    CollectionRequest,
    DisbursementRequest,
    PaymentProvider,
    ProviderEvent,
    ProviderResult,
)

NETWORK_CODES = {"mtn": "mtn", "telecel": "vod", "at": "atl"}
STATUS_MAP = {"success": "successful", "failed": "failed", "abandoned": "failed", "reversed": "failed",
              "pending": "pending", "ongoing": "pending", "send_otp": "pending", "pay_offline": "pending",
              "otp": "pending", "processing": "pending", "received": "pending"}


def to_minor(amount: Decimal, currency: str) -> int:
    return int((amount * (10 ** exponent(currency))).to_integral_exact())


class PaystackProvider(PaymentProvider):
    code = "paystack"
    display_name = "Paystack"

    def __init__(self, client: httpx.Client | None = None) -> None:
        self.base_url = settings.paystack_base_url.rstrip("/")
        self.secret = settings.paystack_secret_key
        self.mode = "live" if self.secret.startswith("sk_live_") else "sandbox"
        self.client = client or httpx.Client(timeout=30)

    def is_configured(self) -> bool:
        return bool(self.secret)

    def _headers(self) -> dict[str, str]:
        if not self.secret:
            raise ProviderNotConfigured("Paystack secret key is not configured")
        return {"Authorization": f"Bearer {self.secret}", "Content-Type": "application/json"}

    def _post(self, path: str, body: dict) -> dict:
        r = self.client.post(f"{self.base_url}{path}", json=body, headers=self._headers())
        data = r.json() if r.content else {}
        if r.status_code >= 500:
            raise ProviderError(f"Paystack error ({r.status_code})")
        return {"http_status": r.status_code, **data}

    def collect(self, req: CollectionRequest) -> ProviderResult:
        body = {
            "email": req.email or f"{req.msisdn}@customers.fincore.local",
            "amount": to_minor(req.amount, req.currency),
            "currency": req.currency,
            "reference": req.reference,
            "mobile_money": {"phone": "0" + (req.msisdn or "")[3:], "provider": NETWORK_CODES.get(req.network or "", "mtn")},
        }
        data = self._post("/charge", body)
        d = data.get("data") or {}
        status = STATUS_MAP.get(str(d.get("status", "")).lower(), "failed" if not data.get("status") else "pending")
        return ProviderResult(status=status, provider_reference=str(d.get("reference") or req.reference),
                              message=d.get("display_text") or data.get("message", ""), raw=data)

    def disburse(self, req: DisbursementRequest) -> ProviderResult:
        if req.channel == "mobile_money":
            recipient = {"type": "mobile_money", "name": req.account_name or "FinCore customer",
                         "account_number": "0" + (req.msisdn or "")[3:],
                         "bank_code": {"mtn": "MTN", "telecel": "VOD", "at": "ATL"}.get(req.network or "", "MTN"),
                         "currency": req.currency}
        else:
            recipient = {"type": "ghipss", "name": req.account_name or "FinCore customer",
                         "account_number": req.account_number, "bank_code": req.bank_code, "currency": req.currency}
        rec = self._post("/transferrecipient", recipient)
        if not rec.get("status"):
            return ProviderResult(status="failed", provider_reference=req.reference,
                                  message=rec.get("message", "Could not create recipient"), raw=rec)
        data = self._post("/transfer", {"source": "balance", "amount": to_minor(req.amount, req.currency),
                                        "recipient": rec["data"]["recipient_code"], "reference": req.reference,
                                        "reason": req.description[:100], "currency": req.currency})
        d = data.get("data") or {}
        status = STATUS_MAP.get(str(d.get("status", "")).lower(), "failed" if not data.get("status") else "pending")
        return ProviderResult(status=status, provider_reference=str(d.get("transfer_code") or req.reference),
                              message=data.get("message", ""), raw=data)

    def check_status(self, provider_reference: str, direction: str) -> ProviderResult:
        path = f"/transaction/verify/{provider_reference}" if direction == "collection" else f"/transfer/{provider_reference}"
        r = self.client.get(f"{self.base_url}{path}", headers=self._headers())
        data = r.json()
        d = data.get("data") or {}
        return ProviderResult(status=STATUS_MAP.get(str(d.get("status", "")).lower(), "pending"),
                              provider_reference=provider_reference, message=data.get("message", ""), raw=data)

    def lookup_account(self, *, msisdn=None, bank_code=None, account_number=None) -> AccountLookup:
        acct = account_number or ("0" + msisdn[3:] if msisdn else "")
        r = self.client.get(f"{self.base_url}/bank/resolve", params={"account_number": acct, "bank_code": bank_code},
                            headers=self._headers())
        data = r.json()
        if not data.get("status"):
            return AccountLookup(valid=False, message=data.get("message", "Account not found"))
        return AccountLookup(valid=True, account_name=data["data"].get("account_name"))

    def verify_webhook(self, headers: dict[str, str], body: bytes) -> bool:
        if not self.secret:
            return False
        expected = hmac.new(self.secret.encode(), body, hashlib.sha512).hexdigest()
        return hmac.compare_digest(expected, headers.get("x-paystack-signature", ""))

    def parse_webhook(self, body: dict) -> ProviderEvent:
        d = body.get("data") or {}
        event = body.get("event", "")
        if event in ("charge.success", "transfer.success"):
            status = "successful"
        elif event in ("transfer.failed", "transfer.reversed", "charge.failed"):
            status = "failed"
        else:
            status = STATUS_MAP.get(str(d.get("status", "")).lower(), "pending")
        ref = str(d.get("reference", ""))
        return ProviderEvent(provider_reference=str(d.get("transfer_code") or ref), internal_reference=ref,
                             status=status, raw=body)
