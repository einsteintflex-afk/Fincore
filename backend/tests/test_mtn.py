"""MTN MoMo Collections integration: credential separation, RequestToPay deposits and payments, verified status
before crediting, callbacks, outcomes, expiry, idempotency, reconciliation and secret hygiene.

MTN is replaced by an in-process fake that implements the documented sandbox endpoints."""

import json
import logging
import uuid
from datetime import timedelta
from decimal import Decimal

import httpx
import pytest
from sqlalchemy import text, update

from app.core.config import Settings, settings
from app.core.database import SessionLocal, utcnow
from app.core.errors import ProviderNotConfigured
from app.models import Transaction
from app.providers import override_provider, route
from app.providers.mtn_momo import MtnMomoProvider, MtnMomoSandboxProvider, classify
from tests.conftest import fund
from tests.test_wallets import integrity_ok

SUB_KEY = "sandbox-sub-key-" + "x" * 16
API_USER = str(uuid.uuid4())
API_KEY = "sandbox-api-key-" + "y" * 16


class FakeMtn:
    """Minimal MTN sandbox: token, requesttopay (POST/GET), callback-free. Records requests."""

    def __init__(self):
        self.requests: dict[str, dict] = {}
        self.calls: list[httpx.Request] = []
        self.timeout_next_post = False

    def set(self, ref_or_external: str, status: str, reason: str | None = None):
        for ref, r in self.requests.items():
            if ref == ref_or_external or r["externalId"] == ref_or_external:
                r["status"], r["reason"] = status, reason
                return
        raise KeyError(ref_or_external)

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request)
        assert request.headers.get("Ocp-Apim-Subscription-Key") == SUB_KEY
        path = request.url.path
        if path.endswith("/collection/token/"):
            return httpx.Response(200, json={"access_token": "tok-123", "token_type": "access_token", "expires_in": 3600})
        assert request.headers.get("Authorization") == "Bearer tok-123"
        assert request.headers.get("X-Target-Environment") == "sandbox"
        if path.endswith("/collection/v1_0/requesttopay") and request.method == "POST":
            if self.timeout_next_post:
                self.timeout_next_post = False
                raise httpx.ReadTimeout("simulated timeout", request=request)
            ref = request.headers["X-Reference-Id"]
            if ref in self.requests:
                return httpx.Response(409, json={"code": "RESOURCE_ALREADY_EXIST"})
            body = json.loads(request.content)
            self.requests[ref] = {**body, "status": "PENDING", "reason": None}
            return httpx.Response(202)
        if "/collection/v1_0/requesttopay/" in path and request.method == "GET":
            ref = path.rsplit("/", 1)[-1]
            r = self.requests.get(ref)
            if not r:
                return httpx.Response(404, json={"code": "RESOURCE_NOT_FOUND"})
            out = {"externalId": r["externalId"], "amount": r["amount"], "currency": r["currency"], "status": r["status"]}
            if r["reason"]:
                out["reason"] = r["reason"]
            if r["status"] == "SUCCESSFUL":
                out["financialTransactionId"] = "8743920135"
            return httpx.Response(200, json=out)
        return httpx.Response(404)


@pytest.fixture
def mtn(monkeypatch):
    monkeypatch.setattr(settings, "mtn_momo_mode", "sandbox")
    monkeypatch.setattr(settings, "mtn_sandbox_collection_subscription_key", SUB_KEY)
    monkeypatch.setattr(settings, "mtn_sandbox_collection_api_user", API_USER)
    monkeypatch.setattr(settings, "mtn_sandbox_collection_api_key", API_KEY)
    fake = FakeMtn()
    override_provider("mtn_momo_sandbox", MtnMomoSandboxProvider(client=httpx.Client(transport=httpx.MockTransport(fake))))
    yield fake
    override_provider("mtn_momo_sandbox", None)


def deposit(user, amount="100.00", phone="0241234567", key=None):
    headers = {"Idempotency-Key": key} if key else {}
    return user.post("/deposits", {"wallet_id": user.wallet()["id"], "amount": amount, "phone": phone}, headers=headers)


# ---------------------------------------------------------------- routing & credential separation
def test_routing_by_mode(monkeypatch):
    monkeypatch.setattr(settings, "mtn_momo_mode", "off")
    assert route("mobile_money", "mtn").code == "sandbox"
    monkeypatch.setattr(settings, "mtn_momo_mode", "sandbox")
    with pytest.raises(ProviderNotConfigured):  # never falls back to the simulator when MTN is selected
        route("mobile_money", "mtn")
    monkeypatch.setattr(settings, "mtn_sandbox_collection_subscription_key", "sub")
    monkeypatch.setattr(settings, "mtn_sandbox_collection_api_user", "user")
    monkeypatch.setattr(settings, "mtn_sandbox_collection_api_key", "key")
    assert route("mobile_money", "mtn").code == "mtn_momo_sandbox"
    with pytest.raises(ProviderNotConfigured):  # Disbursements need their own credentials
        route("mobile_money", "mtn", direction="disbursement")
    assert route("mobile_money", "mtn", sandbox=True).code == "sandbox"  # developer test keys stay simulated
    assert route("mobile_money", "telecel").code == "sandbox"            # only MTN is integrated
    monkeypatch.setattr(settings, "mtn_momo_mode", "production")
    assert route("mobile_money", "mtn").code == "sandbox"  # production keys unused until live payments are on
    monkeypatch.setattr(settings, "live_payments_enabled", True)
    for k in ("subscription_key", "api_user", "api_key"):
        monkeypatch.setattr(settings, f"mtn_production_collection_{k}", "x")
    assert route("mobile_money", "mtn").code == "mtn_momo"


def test_production_deployment_never_uses_the_simulator_for_real_payments(monkeypatch):
    monkeypatch.setattr(settings, "environment", "production")
    monkeypatch.setattr(settings, "mtn_momo_mode", "off")
    with pytest.raises(ProviderNotConfigured):
        route("mobile_money", "mtn")
    assert route("mobile_money", "mtn", sandbox=True).code == "sandbox"


@pytest.mark.parametrize("overrides,message", [
    ({"mtn_momo_mode": "production"}, "requires FINCORE_LIVE_PAYMENTS_ENABLED"),
    ({"mtn_momo_mode": "sandbox", "live_payments_enabled": True}, "cannot run on the MTN sandbox"),
    ({"mtn_momo_mode": "sideways"}, "must be off, sandbox or production"),
])
def test_unsafe_configurations_refuse_to_start(overrides, message):
    with pytest.raises(RuntimeError, match=message):
        Settings(environment="test", **overrides).validate_for_runtime()


def test_sandbox_and_production_profiles_never_mix(monkeypatch):
    # Production keys alone don't configure the sandbox, and vice versa.
    monkeypatch.setattr(settings, "mtn_production_collection_subscription_key", "prod-sub")
    monkeypatch.setattr(settings, "mtn_production_collection_api_user", "prod-user")
    monkeypatch.setattr(settings, "mtn_production_collection_api_key", "prod-key")
    assert MtnMomoProvider().is_configured() and not MtnMomoSandboxProvider().is_configured()
    # A production profile pointed at the sandbox URL is refused.
    monkeypatch.setattr(settings, "mtn_production_base_url", "https://sandbox.momodeveloper.mtn.com")
    with pytest.raises(ProviderNotConfigured, match="refusing to mix"):
        MtnMomoProvider().profile
    monkeypatch.setattr(settings, "mtn_sandbox_base_url", "https://proxy.momoapi.mtn.com")
    with pytest.raises(ProviderNotConfigured, match="refusing to mix"):
        MtnMomoSandboxProvider().profile


@pytest.mark.parametrize("status,reason,outcome", [
    ("SUCCESSFUL", None, "successful"), ("PENDING", None, "pending"), ("CREATED", None, "pending"),
    ("FAILED", "APPROVAL_REJECTED", "rejected"), ("REJECTED", None, "rejected"),
    ("FAILED", "EXPIRED", "expired"), ("TIMEOUT", None, "expired"),
    ("FAILED", "NOT_ENOUGH_FUNDS", "failed"), ("FAILED", "INTERNAL_PROCESSING_ERROR", "failed"),
])
def test_status_classification(status, reason, outcome):
    assert classify(status, reason) == outcome


# ---------------------------------------------------------------- deposits
def test_deposit_requests_to_pay_and_credits_only_after_mtn_confirms(make_user, mtn):
    u = make_user()
    r = deposit(u, "100.00")
    assert r.status_code == 201, r.text
    t = r.json()
    assert t["status"] == "processing" and t["provider"] == "mtn_momo_sandbox" and t["provider_mode"] == "sandbox"
    assert Decimal(u.balance()) == 0  # nothing credited on MTN's 202
    sent = next(c for c in mtn.calls if c.method == "POST" and c.url.path.endswith("requesttopay"))
    body = json.loads(sent.content)
    assert body["payer"] == {"partyIdType": "MSISDN", "partyId": "233241234567"}
    assert body["externalId"] == t["reference"] and body["currency"] == "EUR"  # MTN sandbox currency
    assert sent.headers["X-Reference-Id"] == MtnMomoProvider.ref_uuid(t["reference"])
    # Still pending at MTN: refreshing changes nothing.
    assert u.post(f"/transactions/{t['reference']}/refresh").json()["status"] == "processing"
    mtn.set(t["reference"], "SUCCESSFUL")
    with SessionLocal() as s:  # skip the 3-second polite polling interval
        s.execute(update(Transaction).values(meta={}))
        s.commit()
    done = u.post(f"/transactions/{t['reference']}/refresh").json()
    assert done["status"] == "successful"
    assert Decimal(u.balance()) == Decimal("100.00")
    integrity_ok()
    with SessionLocal() as s:
        assert s.execute(text("select balance from ledger_accounts where code = 'SYS:GHS:PROVIDER_CLEARING:MTN_MOMO_SANDBOX'")).scalar() == Decimal("100.00")


@pytest.mark.parametrize("status,reason,outcome,message", [
    ("FAILED", "APPROVAL_REJECTED", "rejected", "The payer declined the MoMo prompt"),
    ("FAILED", "EXPIRED", "expired", "The payer did not approve the MoMo prompt in time"),
    ("TIMEOUT", None, "expired", "The payer did not approve the MoMo prompt in time"),
    ("FAILED", "NOT_ENOUGH_FUNDS", "failed", "Not enough money in the MoMo wallet"),
])
def test_unsuccessful_outcomes(make_user, mtn, status, reason, outcome, message):
    u = make_user()
    t = deposit(u).json()
    mtn.set(t["reference"], status, reason)
    with SessionLocal() as s:
        s.execute(update(Transaction).values(meta={}))
        s.commit()
    r = u.post(f"/transactions/{t['reference']}/refresh").json()
    assert r["status"] == "failed" and r["failure_reason"] == message
    with SessionLocal() as s:
        assert s.get(Transaction, uuid.UUID(t["id"])).meta["provider_outcome"] == outcome
    assert Decimal(u.balance()) == 0
    integrity_ok()


def test_pending_too_long_expires(make_user, mtn):
    u = make_user()
    t = deposit(u).json()
    with SessionLocal() as s:
        s.execute(update(Transaction).values(created_at=utcnow() - timedelta(minutes=settings.mtn_request_expiry_minutes + 1),
                                             meta={}))
        s.commit()
    r = u.post(f"/transactions/{t['reference']}/refresh").json()
    assert r["status"] == "failed" and "in time" in r["failure_reason"]


def test_network_timeout_is_resolved_from_mtn(make_user, mtn):
    u = make_user()
    mtn.timeout_next_post = True
    t = deposit(u).json()
    assert t["status"] == "processing"  # outcome unknown: never guessed
    with SessionLocal() as s:
        assert s.get(Transaction, uuid.UUID(t["id"])).meta["provider_outcome"] == "timeout"
    # MTN never received it -> status query 404 -> failed with timeout outcome
    with SessionLocal() as s:
        txn = s.get(Transaction, uuid.UUID(t["id"]))
        txn.provider_reference, txn.meta = MtnMomoProvider.ref_uuid(t["reference"]), {}
        s.commit()
    r = u.post(f"/transactions/{t['reference']}/refresh").json()
    assert r["status"] == "failed" and "timed out" in r["failure_reason"]
    with SessionLocal() as s:
        assert s.get(Transaction, uuid.UUID(t["id"])).meta["provider_outcome"] == "timeout"


def test_status_checks_are_rate_limited(make_user, mtn):
    u = make_user()
    t = deposit(u).json()
    before = len(mtn.calls)
    for _ in range(5):
        u.post(f"/transactions/{t['reference']}/refresh")
    assert len(mtn.calls) - before <= 1  # one status query, not five


# ---------------------------------------------------------------- callbacks
def test_callback_is_verified_with_mtn_before_crediting(make_user, mtn, client):
    u = make_user()
    t = deposit(u).json()
    forged = {"externalId": t["reference"], "status": "SUCCESSFUL", "amount": "100.00"}
    r = client.post("/api/v1/callbacks/mtn_momo_sandbox", json=forged)
    assert r.status_code == 200 and r.json()["status"] == "processing"  # MTN still says PENDING
    assert Decimal(u.balance()) == 0
    mtn.set(t["reference"], "SUCCESSFUL")
    r = client.post("/api/v1/callbacks/mtn_momo_sandbox", json=forged)
    assert r.json()["status"] == "successful"
    assert Decimal(u.balance()) == Decimal("100.00")
    client.post("/api/v1/callbacks/mtn_momo_sandbox", json=forged)  # duplicate callback: no double credit
    assert Decimal(u.balance()) == Decimal("100.00")
    integrity_ok()


def test_callback_token_and_malformed_bodies(make_user, mtn, client, monkeypatch):
    monkeypatch.setattr(settings, "mtn_callback_token", "cb-secret-123")
    assert client.post("/api/v1/callbacks/mtn_momo_sandbox", json={"externalId": "X"}).status_code == 401
    assert client.post("/api/v1/callbacks/mtn_momo_sandbox?token=wrong", json={"externalId": "X"}).status_code == 401
    r = client.post("/api/v1/callbacks/mtn_momo_sandbox?token=cb-secret-123", json={"externalId": "UNKNOWN"})
    assert r.status_code == 200 and r.json()["matched"] is False
    r = client.post("/api/v1/callbacks/mtn_momo_sandbox?token=cb-secret-123", content=b"not json")
    assert r.status_code == 422


# ---------------------------------------------------------------- idempotency & reconciliation
def test_idempotent_deposit_sends_one_request_to_pay(make_user, mtn):
    u = make_user()
    a = deposit(u, key="dep-1").json()
    b = deposit(u, key="dep-1").json()
    assert a["reference"] == b["reference"]
    assert sum(1 for c in mtn.calls if c.method == "POST" and c.url.path.endswith("requesttopay")) == 1


def test_resubmitting_same_reference_is_idempotent_at_mtn(mtn):
    from app.providers import get_provider
    from app.providers.base import CollectionRequest

    p = get_provider("mtn_momo_sandbox")
    req = CollectionRequest(reference="DEP-SAME-1", amount=Decimal("5.00"), currency="GHS", msisdn="233241234567")
    first = p.collect(req)
    second = p.collect(req)  # MTN answers 409; adapter returns the existing request's status
    assert first.provider_reference == second.provider_reference and second.status == "pending"
    assert len(mtn.requests) == 1


def test_reconciliation_matches_mtn_records(make_user, mtn, admin):
    u = make_user()
    t = deposit(u, "40.00").json()
    mtn.set(t["reference"], "SUCCESSFUL")
    with SessionLocal() as s:
        s.execute(update(Transaction).values(meta={}))
        s.commit()
    u.post(f"/transactions/{t['reference']}/refresh")
    run = admin.post("/admin/reconciliation/providers", params={"provider": "mtn_momo_sandbox"}).json()
    assert run["status"] == "balanced", run["discrepancies"]
    assert admin.post("/admin/reconciliation/ledger").json()["status"] == "balanced"


# ---------------------------------------------------------------- merchant payments through MTN
def test_payment_link_checkout_uses_mtn_and_credits_merchant(active_business, mtn):
    owner, biz = active_business
    c = owner.client
    pr = owner.post(f"/businesses/{biz['id']}/payment-requests", {"amount": "150.00"}).json()
    r = c.post(f"/api/v1/checkout/{pr['reference']}/mobile-money", json={"phone": "0541234567"})
    assert r.json()["status"] == "processing" and r.json()["provider"] == "mtn_momo_sandbox"
    txn_ref = json.loads(next(x for x in mtn.calls if x.method == "POST" and x.url.path.endswith("requesttopay")).content)["externalId"]
    mtn.set(txn_ref, "SUCCESSFUL")
    view = c.post(f"/api/v1/checkout/{pr['reference']}/refresh").json()
    assert view["status"] == "successful"
    wallet = owner.get(f"/businesses/{biz['id']}/wallets").json()[0]
    assert Decimal(wallet["balance"]) == Decimal("147.75")  # 1.5% MDR
    integrity_ok()


def test_rejected_checkout_shows_outcome(active_business, mtn):
    owner, biz = active_business
    c = owner.client
    pr = owner.post(f"/businesses/{biz['id']}/payment-requests", {"amount": "20.00"}).json()
    c.post(f"/api/v1/checkout/{pr['reference']}/mobile-money", json={"phone": "0541234567"})
    ext = json.loads(next(x for x in mtn.calls if x.method == "POST" and x.url.path.endswith("requesttopay")).content)["externalId"]
    mtn.set(ext, "FAILED", "APPROVAL_REJECTED")
    view = c.post(f"/api/v1/checkout/{pr['reference']}/refresh").json()
    assert view["status"] == "failed" and view["outcome"] == "rejected"
    assert view["failure_reason"] == "The payer declined the MoMo prompt"


# ---------------------------------------------------------------- secret hygiene
def test_secrets_never_logged_or_stored(make_user, mtn, caplog):
    caplog.set_level(logging.DEBUG)
    u = make_user()
    t = deposit(u).json()
    mtn.set(t["reference"], "SUCCESSFUL")
    with SessionLocal() as s:
        s.execute(update(Transaction).values(meta={}))
        s.commit()
    u.post(f"/transactions/{t['reference']}/refresh")
    for secret in (SUB_KEY, API_KEY, "tok-123"):
        assert secret not in caplog.text
    with SessionLocal() as s:
        dump = " ".join(str(v) for v in s.execute(text(
            "select metadata::text from transactions union all select raw::text from provider_transactions "
            "union all select details::text from audit_logs")).scalars())
    for secret in (SUB_KEY, API_KEY, "tok-123", API_USER):
        assert secret not in dump


def test_simulated_payments_are_labelled(make_user):
    u = make_user()
    t = fund(u, "10.00")
    assert t["provider"] == "sandbox" and t["provider_mode"] == "sandbox"  # simulator (mode off): labelled test


def test_sandbox_creates_its_own_api_user_from_the_subscription_key(make_user, monkeypatch):
    """Only the subscription key is configured: FinCore provisions a sandbox API user once and uses it."""
    created = []

    class Provisioning(FakeMtn):
        def __call__(self, request):
            path = request.url.path
            if path.endswith("/v1_0/apiuser"):
                created.append(request.headers["X-Reference-Id"])
                return httpx.Response(201)
            if path.endswith("/apikey"):
                return httpx.Response(201, json={"apiKey": "generated-key"})
            if path.endswith("/collection/token/"):
                assert request.headers["Authorization"].startswith("Basic ")
            return super().__call__(request)

    MtnMomoProvider._sandbox_users.clear()
    monkeypatch.setattr(settings, "mtn_momo_mode", "sandbox")
    monkeypatch.setattr(settings, "mtn_sandbox_collection_subscription_key", SUB_KEY)
    fake = Provisioning()
    override_provider("mtn_momo_sandbox", MtnMomoSandboxProvider(client=httpx.Client(transport=httpx.MockTransport(fake))))
    try:
        assert route("mobile_money", "mtn").code == "mtn_momo_sandbox"  # configured without an API user
        u = make_user()
        assert deposit(u).json()["status"] == "processing"
        deposit(u, amount="5.00")
        assert len(created) == 1  # provisioned once, then reused
    finally:
        override_provider("mtn_momo_sandbox", None)
        MtnMomoProvider._sandbox_users.clear()


def test_production_never_auto_provisions(monkeypatch):
    monkeypatch.setattr(settings, "mtn_production_collection_subscription_key", "prod-sub")
    assert MtnMomoProvider().is_configured("collection") is False
