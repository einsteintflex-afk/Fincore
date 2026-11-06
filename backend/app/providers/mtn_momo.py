"""MTN Mobile Money Open API adapter (Collections: RequestToPay, Disbursements: Transfer).

Docs: https://momodeveloper.mtn.com  — production access for Ghana is granted by MTN MoMo after
commercial onboarding. Required credentials (per product):
  * Ocp-Apim-Subscription-Key
  * API user (UUID) and API key
  * Target environment (``sandbox`` or the production value MTN assigns, e.g. ``mtnghana``)
"""

from __future__ import annotations

import base64
import time
import uuid

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

STATUS_MAP = {"SUCCESSFUL": "successful", "PENDING": "pending", "FAILED": "failed", "REJECTED": "failed",
              "TIMEOUT": "failed", "ONGOING": "pending"}


class MtnMomoProvider(PaymentProvider):
    code = "mtn_momo"
    display_name = "MTN Mobile Money"

    def __init__(self, client: httpx.Client | None = None) -> None:
        self.base_url = settings.mtn_momo_base_url.rstrip("/")
        self.target_env = settings.mtn_momo_target_environment
        self.mode = "sandbox" if self.target_env == "sandbox" else "live"
        self.client = client or httpx.Client(timeout=30)
        self._tokens: dict[str, tuple[str, float]] = {}

    def _creds(self, product: str) -> tuple[str, str, str]:
        if product == "collection":
            c = (settings.mtn_momo_collection_subscription_key, settings.mtn_momo_collection_api_user,
                 settings.mtn_momo_collection_api_key)
        else:
            c = (settings.mtn_momo_disbursement_subscription_key, settings.mtn_momo_disbursement_api_user,
                 settings.mtn_momo_disbursement_api_key)
        if not all(c):
            raise ProviderNotConfigured(f"MTN MoMo {product} credentials are not configured")
        return c

    def is_configured(self) -> bool:
        try:
            self._creds("collection")
            self._creds("disbursement")
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
            raise ProviderError(f"MTN MoMo token request failed ({r.status_code})")
        data = r.json()
        self._tokens[product] = (data["access_token"], time.time() + int(data.get("expires_in", 3600)))
        return data["access_token"]

    def _headers(self, product: str, ref: str | None = None) -> dict[str, str]:
        sub_key, _, _ = self._creds(product)
        h = {"Authorization": f"Bearer {self._token(product)}", "X-Target-Environment": self.target_env,
             "Ocp-Apim-Subscription-Key": sub_key, "Content-Type": "application/json"}
        if ref:
            h["X-Reference-Id"] = ref
        if settings.mtn_momo_callback_url:
            h["X-Callback-Url"] = settings.mtn_momo_callback_url
        return h

    @staticmethod
    def _ref_uuid(reference: str) -> str:
        # MTN requires a UUIDv4-shaped X-Reference-Id; derive it deterministically from our reference so
        # a retried request is idempotent at MTN.
        return str(uuid.uuid5(uuid.NAMESPACE_URL, f"fincore:{reference}"))

    def collect(self, req: CollectionRequest) -> ProviderResult:
        ref = self._ref_uuid(req.reference)
        body = {"amount": str(req.amount), "currency": req.currency if self.mode == "live" else "EUR",
                "externalId": req.reference, "payer": {"partyIdType": "MSISDN", "partyId": req.msisdn},
                "payerMessage": req.description[:160] or "FinCore payment", "payeeNote": req.reference}
        r = self.client.post(f"{self.base_url}/collection/v1_0/requesttopay", json=body,
                             headers=self._headers("collection", ref))
        if r.status_code == 202:
            return ProviderResult(status="pending", provider_reference=ref, message="Request to pay sent")
        if r.status_code == 409:  # duplicate reference -> already submitted; fetch current status
            return self.check_status(ref, "collection")
        return ProviderResult(status="failed", provider_reference=ref,
                              message=f"MTN rejected request ({r.status_code})", raw=_safe_json(r))

    def disburse(self, req: DisbursementRequest) -> ProviderResult:
        if req.channel != "mobile_money":
            raise ProviderError("MTN MoMo only supports mobile money disbursements")
        ref = self._ref_uuid(req.reference)
        body = {"amount": str(req.amount), "currency": req.currency if self.mode == "live" else "EUR",
                "externalId": req.reference, "payee": {"partyIdType": "MSISDN", "partyId": req.msisdn},
                "payerMessage": req.description[:160] or "FinCore payout", "payeeNote": req.reference}
        r = self.client.post(f"{self.base_url}/disbursement/v1_0/transfer", json=body,
                             headers=self._headers("disbursement", ref))
        if r.status_code == 202:
            return ProviderResult(status="pending", provider_reference=ref, message="Transfer submitted")
        if r.status_code == 409:
            return self.check_status(ref, "disbursement")
        return ProviderResult(status="failed", provider_reference=ref,
                              message=f"MTN rejected transfer ({r.status_code})", raw=_safe_json(r))

    def check_status(self, provider_reference: str, direction: str) -> ProviderResult:
        product = "collection" if direction == "collection" else "disbursement"
        path = "requesttopay" if product == "collection" else "transfer"
        r = self.client.get(f"{self.base_url}/{product}/v1_0/{path}/{provider_reference}",
                            headers=self._headers(product))
        if r.status_code != 200:
            raise ProviderError(f"MTN status check failed ({r.status_code})")
        data = r.json()
        return ProviderResult(status=STATUS_MAP.get(data.get("status", ""), "pending"),
                              provider_reference=provider_reference,
                              message=str(data.get("reason") or data.get("status")), raw=data)

    def lookup_account(self, *, msisdn=None, bank_code=None, account_number=None) -> AccountLookup:
        r = self.client.get(
            f"{self.base_url}/collection/v1_0/accountholder/msisdn/{msisdn}/basicuserinfo",
            headers=self._headers("collection"))
        if r.status_code != 200:
            return AccountLookup(valid=False, message="MTN account not found")
        data = r.json()
        name = " ".join(filter(None, [data.get("given_name"), data.get("family_name")])) or data.get("name")
        return AccountLookup(valid=True, account_name=name)

    def verify_webhook(self, headers: dict[str, str], body: bytes) -> bool:
        # MTN callbacks are unsigned. They must only be trusted after re-querying the status
        # (done in services.payments.handle_provider_event) and should be IP-allow-listed at the edge.
        return True

    def parse_webhook(self, body: dict) -> ProviderEvent:
        # Callback bodies carry our externalId; the X-Reference-Id we sent is derived from it.
        external_id = body.get("externalId") or ""
        return ProviderEvent(provider_reference=self._ref_uuid(external_id), internal_reference=external_id,
                             status=STATUS_MAP.get(body.get("status", ""), "pending"), raw=body)


def _safe_json(r: httpx.Response) -> dict:
    try:
        return r.json()
    except ValueError:
        return {"text": r.text[:500]}
