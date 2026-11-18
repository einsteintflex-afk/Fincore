"""MTN Mobile Money Open API adapter — Collections (RequestToPay) and Disbursements (Transfer).

Docs: https://momodeveloper.mtn.com

Two completely separate credential profiles (never mixed):

* ``mtn_momo_sandbox`` – MTN's developer sandbox (test money, no real prompt is sent to real phones).
  Variables: ``FINCORE_MTN_SANDBOX_*``.
* ``mtn_momo``         – production, only after MTN Ghana partner onboarding issues production keys.
  Variables: ``FINCORE_MTN_PRODUCTION_*``.

``FINCORE_MTN_MOMO_MODE`` (off | sandbox | production) selects which one FinCore routes MTN payments to.

Flow for a deposit / payment: FinCore sends RequestToPay with the payer's MSISDN → MTN pushes the
authorisation prompt to the payer's phone (production) → the payer approves with their PIN → FinCore learns the
result from MTN's callback *and re-queries MTN's status API before crediting anything* (callbacks are unsigned).
Secrets are read from settings only, never logged, and never returned in provider responses.
"""

from __future__ import annotations

import base64
import time
import uuid
from dataclasses import dataclass

import httpx

from app.core.config import settings
from app.core.errors import ProviderError, ProviderNotConfigured
from app.providers.base import (
    AccountLookup,
    CollectionRequest,
    DisbursementRequest,
    PaymentProvider,
    ProviderEvent,
    ProviderResult,
)

# MTN transaction status -> FinCore status.
STATUS_MAP = {"SUCCESSFUL": "successful", "PENDING": "pending", "ONGOING": "pending", "FAILED": "failed",
              "REJECTED": "failed", "TIMEOUT": "failed", "EXPIRED": "failed"}

# Finer-grained outcome kept on the transaction (shown to staff/customers). MTN puts the cause in ``reason``.
REJECTED_REASONS = {"APPROVAL_REJECTED", "PAYMENT_NOT_APPROVED", "TRANSACTION_CANCELED", "NOT_ALLOWED"}
EXPIRED_REASONS = {"EXPIRED", "TIMEOUT", "TRANSACTION_TIMED_OUT"}
OUTCOME_MESSAGES = {
    "successful": "Approved by the payer",
    "pending": "Waiting for the payer to approve on their phone",
    "rejected": "The payer declined the MoMo prompt",
    "expired": "The payer did not approve the MoMo prompt in time",
    "timeout": "MTN did not respond in time",
    "failed": "MTN could not complete the payment",
}
FRIENDLY_REASONS = {
    "NOT_ENOUGH_FUNDS": "Not enough money in the MoMo wallet",
    "PAYER_LIMIT_REACHED": "The payer's MoMo limit has been reached",
    "PAYER_NOT_FOUND": "This number is not registered for MTN MoMo",
    "PAYEE_NOT_ALLOWED_TO_RECEIVE": "The merchant account cannot receive this payment",
    "INTERNAL_PROCESSING_ERROR": "MTN had a processing error",
    "SERVICE_UNAVAILABLE": "MTN MoMo is temporarily unavailable",
}


def classify(status: str, reason: str | None) -> str:
    """MTN status + reason -> successful | pending | rejected | expired | failed."""
    status = (status or "").upper()
    reason = (reason or "").upper()
    if status == "SUCCESSFUL":
        return "successful"
    if status in ("PENDING", "ONGOING", ""):
        return "pending"
    if status == "REJECTED" or reason in REJECTED_REASONS:
        return "rejected"
    if status in ("TIMEOUT", "EXPIRED") or reason in EXPIRED_REASONS:
        return "expired"
    return "failed"


@dataclass(frozen=True)
class MtnProfile:
    name: str               # sandbox | production
    base_url: str
    target_environment: str
    collection: tuple[str, str, str]      # subscription key, api user, api key
    disbursement: tuple[str, str, str]
    callback_url: str


def sandbox_profile() -> MtnProfile:
    s = settings
    return MtnProfile("sandbox", s.mtn_sandbox_base_url, "sandbox",
                      (s.mtn_sandbox_collection_subscription_key, s.mtn_sandbox_collection_api_user,
                       s.mtn_sandbox_collection_api_key),
                      (s.mtn_sandbox_disbursement_subscription_key, s.mtn_sandbox_disbursement_api_user,
                       s.mtn_sandbox_disbursement_api_key),
                      s.mtn_sandbox_callback_url)


def production_profile() -> MtnProfile:
    s = settings
    return MtnProfile("production", s.mtn_production_base_url, s.mtn_production_target_environment,
                      (s.mtn_production_collection_subscription_key, s.mtn_production_collection_api_user,
                       s.mtn_production_collection_api_key),
                      (s.mtn_production_disbursement_subscription_key, s.mtn_production_disbursement_api_user,
                       s.mtn_production_disbursement_api_key),
                      s.mtn_production_callback_url)


class MtnMomoProvider(PaymentProvider):
    """Production MTN MoMo (real money). Requires keys issued by MTN Ghana after partner onboarding."""

    code = "mtn_momo"
    display_name = "MTN Mobile Money"
    mode = "live"
    profile_loader = staticmethod(production_profile)

    def __init__(self, client: httpx.Client | None = None) -> None:
        self.client = client or httpx.Client(timeout=30)
        self._tokens: dict[str, tuple[str, float]] = {}

    # Read the profile on every call so credential rotation needs no restart (and tests can patch settings).
    @property
    def profile(self) -> MtnProfile:
        p = self.profile_loader()
        if self.mode == "live" and ("sandbox" in p.base_url or p.target_environment == "sandbox"):
            raise ProviderNotConfigured("Production MTN profile points at the sandbox — refusing to mix them")
        if self.mode == "sandbox" and "sandbox" not in p.base_url:
            raise ProviderNotConfigured("Sandbox MTN profile points at a non-sandbox URL — refusing to mix them")
        return p

    @property
    def base_url(self) -> str:
        return self.profile.base_url.rstrip("/")

    def _creds(self, product: str) -> tuple[str, str, str]:
        c = self.profile.collection if product == "collection" else self.profile.disbursement
        if not all(c):
            raise ProviderNotConfigured(f"MTN MoMo {self.profile.name} {product} credentials are not configured")
        return c

    def is_configured(self) -> bool:
        try:
            self._creds("collection")
            return True
        except ProviderNotConfigured:
            return False

    def _token(self, product: str) -> str:
        cached = self._tokens.get(product)
        if cached and cached[1] > time.time() + 30:
            return cached[0]
        sub_key, user, key = self._creds(product)
        basic = base64.b64encode(f"{user}:{key}".encode()).decode()
        r = self.client.post(f"{self.base_url}/{product}/token/",
                             headers={"Authorization": f"Basic {basic}", "Ocp-Apim-Subscription-Key": sub_key})
        if r.status_code != 200:
            # Only the status code is surfaced: MTN error bodies never contain our secrets, but keep it minimal.
            raise ProviderError(f"MTN MoMo {self.profile.name} login failed (HTTP {r.status_code})")
        data = r.json()
        self._tokens[product] = (data["access_token"], time.time() + int(data.get("expires_in", 3600)))
        return data["access_token"]

    def _headers(self, product: str, ref: str | None = None) -> dict[str, str]:
        sub_key, _, _ = self._creds(product)
        h = {"Authorization": f"Bearer {self._token(product)}", "X-Target-Environment": self.profile.target_environment,
             "Ocp-Apim-Subscription-Key": sub_key, "Content-Type": "application/json"}
        if ref:
            h["X-Reference-Id"] = ref
        if self.profile.callback_url:
            h["X-Callback-Url"] = self.profile.callback_url
        return h

    def _currency(self, currency: str) -> str:
        # MTN's sandbox only accepts EUR; production Ghana uses GHS.
        return "EUR" if self.profile.name == "sandbox" else currency

    @staticmethod
    def ref_uuid(reference: str) -> str:
        """MTN needs a UUIDv4-shaped X-Reference-Id. Deriving it from our reference makes retries idempotent:
        resubmitting the same FinCore reference returns 409 at MTN instead of charging twice."""
        return str(uuid.uuid5(uuid.NAMESPACE_URL, f"fincore:{reference}"))

    _ref_uuid = ref_uuid  # backwards-compatible name

    @staticmethod
    def _result(ref: str, status: str, reason: str | None, raw: dict) -> ProviderResult:
        outcome = classify(status, reason)
        message = FRIENDLY_REASONS.get((reason or "").upper()) or OUTCOME_MESSAGES[outcome]
        fincore_status = outcome if outcome in ("successful", "pending") else "failed"
        return ProviderResult(status=fincore_status, provider_reference=ref, message=message, outcome=outcome,
                              raw={k: raw.get(k) for k in ("status", "reason", "financialTransactionId", "externalId",
                                                          "amount", "currency") if k in raw})

    def collect(self, req: CollectionRequest) -> ProviderResult:
        ref = self.ref_uuid(req.reference)
        body = {"amount": str(req.amount), "currency": self._currency(req.currency), "externalId": req.reference,
                "payer": {"partyIdType": "MSISDN", "partyId": req.msisdn},
                "payerMessage": (req.description or "FinCore payment")[:160], "payeeNote": req.reference}
        r = self.client.post(f"{self.base_url}/collection/v1_0/requesttopay", json=body,
                             headers=self._headers("collection", ref))
        if r.status_code == 202:
            return ProviderResult(status="pending", provider_reference=ref, outcome="pending",
                                  message=OUTCOME_MESSAGES["pending"])
        if r.status_code == 409:  # same reference already submitted: ask MTN where it stands
            return self.check_status(ref, "collection")
        data = _safe_json(r)
        return ProviderResult(status="failed", provider_reference=ref, outcome="failed", raw=data,
                              message=FRIENDLY_REASONS.get(str(data.get("code", "")).upper())
                              or f"MTN rejected the request (HTTP {r.status_code})")

    def disburse(self, req: DisbursementRequest) -> ProviderResult:
        if req.channel != "mobile_money":
            raise ProviderError("MTN MoMo only supports mobile money disbursements")
        ref = self.ref_uuid(req.reference)
        body = {"amount": str(req.amount), "currency": self._currency(req.currency), "externalId": req.reference,
                "payee": {"partyIdType": "MSISDN", "partyId": req.msisdn},
                "payerMessage": (req.description or "FinCore payout")[:160], "payeeNote": req.reference}
        r = self.client.post(f"{self.base_url}/disbursement/v1_0/transfer", json=body,
                             headers=self._headers("disbursement", ref))
        if r.status_code == 202:
            return ProviderResult(status="pending", provider_reference=ref, outcome="pending", message="Transfer submitted")
        if r.status_code == 409:
            return self.check_status(ref, "disbursement")
        return ProviderResult(status="failed", provider_reference=ref, outcome="failed",
                              message=f"MTN rejected the transfer (HTTP {r.status_code})", raw=_safe_json(r))

    def check_status(self, provider_reference: str, direction: str) -> ProviderResult:
        product = "collection" if direction == "collection" else "disbursement"
        path = "requesttopay" if product == "collection" else "transfer"
        r = self.client.get(f"{self.base_url}/{product}/v1_0/{path}/{provider_reference}",
                            headers=self._headers(product))
        if r.status_code == 404:
            # MTN never received it (e.g. our original call timed out before reaching MTN).
            return ProviderResult(status="failed", provider_reference=provider_reference, outcome="timeout",
                                  message="MTN has no record of this request (the original call timed out)")
        if r.status_code != 200:
            raise ProviderError(f"MTN status check failed (HTTP {r.status_code})")
        data = r.json()
        return self._result(provider_reference, data.get("status", ""), data.get("reason"), data)

    def lookup_account(self, *, msisdn=None, bank_code=None, account_number=None) -> AccountLookup:
        r = self.client.get(f"{self.base_url}/collection/v1_0/accountholder/msisdn/{msisdn}/basicuserinfo",
                            headers=self._headers("collection"))
        if r.status_code != 200:
            return AccountLookup(valid=False, message="MTN account not found")
        data = r.json()
        name = " ".join(filter(None, [data.get("given_name"), data.get("family_name")])) or data.get("name")
        return AccountLookup(valid=True, account_name=name)

    def verify_webhook(self, headers: dict[str, str], body: bytes) -> bool:
        # MTN callbacks are unsigned. They are accepted only as a hint: the callback handler re-queries MTN's
        # status API before any money moves, and an optional URL token (FINCORE_MTN_CALLBACK_TOKEN) is checked
        # by the callback route. Restrict the route to MTN's published IPs at the edge in production.
        return True

    def parse_webhook(self, body: dict) -> ProviderEvent:
        external_id = body.get("externalId") or ""
        return ProviderEvent(provider_reference=self.ref_uuid(external_id), internal_reference=external_id,
                             status=STATUS_MAP.get(str(body.get("status", "")).upper(), "pending"), raw=body)


class MtnMomoSandboxProvider(MtnMomoProvider):
    """MTN's developer sandbox: real MTN API, **test money only**. No prompt reaches real phones."""

    code = "mtn_momo_sandbox"
    display_name = "MTN MoMo sandbox (test money)"
    mode = "sandbox"
    profile_loader = staticmethod(sandbox_profile)


def _safe_json(r: httpx.Response) -> dict:
    try:
        data = r.json()
        return data if isinstance(data, dict) else {"body": data}
    except ValueError:
        return {"text": r.text[:300]}
