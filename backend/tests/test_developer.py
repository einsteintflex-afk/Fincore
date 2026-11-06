import json
from decimal import Decimal

import httpx
from sqlalchemy import func, select

from app.core.database import SessionLocal
from app.core.security import verify_signature_header
from app.models import ApiRequestLog, LedgerEntry, Transaction
from app.services import webhooks


def setup_app(owner, biz):
    app = owner.post("/developer/apps", {"business_id": biz["id"], "name": "Kitchen POS"}).json()
    key = owner.post(f"/developer/apps/{app['id']}/keys", {"environment": "sandbox"}).json()
    assert key["secret_key"].startswith("sk_test_")
    return app, key


def gw(client, key, method, path, **kw):
    headers = {"Authorization": f"Bearer {key['secret_key']}", **kw.pop("headers", {})}
    return client.request(method, f"/api/v1/gateway{path}", headers=headers, **kw)


def test_sandbox_charges_never_touch_ledger(make_user, active_business):
    owner, biz = active_business
    _, key = setup_app(owner, biz)
    c = owner.client
    r = gw(c, key, "POST", "/charges", json={"amount": "45.00", "phone": "0241234567", "reference": "INV-1",
                                             "email": "c@example.com"})
    assert r.status_code == 201, r.text
    charge = r.json()
    assert charge["status"] == "successful" and charge["environment"] == "sandbox"
    with SessionLocal() as s:
        assert s.scalar(select(func.count()).select_from(LedgerEntry)) == 0
        assert s.scalar(select(func.count()).select_from(Transaction)) == 0
    # verify by our reference or merchant reference
    assert gw(c, key, "GET", "/charges/INV-1").json()["reference"] == charge["reference"]
    assert gw(c, key, "GET", "/charges").json()["total"] == 1
    # duplicate merchant reference rejected
    assert gw(c, key, "POST", "/charges", json={"amount": "1", "reference": "INV-1"}).status_code == 409
    assert gw(c, key, "GET", "/balance").json()["livemode"] is False
    # refunds in sandbox
    r = gw(c, key, "POST", "/refunds", json={"charge_reference": "INV-1", "amount": "5"})
    assert r.status_code == 201 and r.json()["status"] == "successful"


def test_pending_sandbox_charge_resolution(make_user, active_business):
    owner, biz = active_business
    _, key = setup_app(owner, biz)
    c = owner.client
    charge = gw(c, key, "POST", "/charges", json={"amount": "10", "phone": "0241111111"}).json()
    assert charge["status"] == "processing"
    r = gw(c, key, "POST", f"/sandbox/charges/{charge['reference']}/resolve", json={"status": "successful"})
    assert r.json()["status"] == "successful"


def test_charge_without_phone_returns_checkout(make_user, active_business):
    owner, biz = active_business
    _, key = setup_app(owner, biz)
    charge = gw(owner.client, key, "POST", "/charges", json={"amount": "10"}).json()
    assert charge["status"] == "pending" and "/checkout/" in charge["checkout_url"]


def test_invalid_and_revoked_keys(make_user, active_business):
    owner, biz = active_business
    app, key = setup_app(owner, biz)
    c = owner.client
    assert c.get("/api/v1/gateway/charges", headers={"Authorization": "Bearer sk_test_nope_nope_nope"}).status_code == 401
    owner.post(f"/developer/apps/{app['id']}/keys/{key['id']}/revoke")
    assert gw(c, key, "GET", "/charges").status_code == 401


def test_live_keys_blocked_until_enabled(make_user, active_business):
    owner, biz = active_business
    app, _ = setup_app(owner, biz)
    r = owner.post(f"/developer/apps/{app['id']}/keys", {"environment": "live"})
    assert r.status_code == 403 and r.json()["error"]["code"] == "live_payments_disabled"


def test_api_idempotency(make_user, active_business):
    owner, biz = active_business
    _, key = setup_app(owner, biz)
    body = {"amount": "12.00", "phone": "0241234567"}
    a = gw(owner.client, key, "POST", "/charges", json=body, headers={"Idempotency-Key": "abc-1"})
    b = gw(owner.client, key, "POST", "/charges", json=body, headers={"Idempotency-Key": "abc-1"})
    assert a.json()["reference"] == b.json()["reference"]
    assert gw(owner.client, key, "GET", "/charges").json()["total"] == 1


def test_usage_is_logged(make_user, active_business):
    owner, biz = active_business
    app, key = setup_app(owner, biz)
    gw(owner.client, key, "GET", "/charges")
    gw(owner.client, key, "GET", "/charges/missing")
    with SessionLocal() as s:
        assert s.scalar(select(func.count()).select_from(ApiRequestLog)) == 2
    u = owner.get(f"/developer/apps/{app['id']}/usage").json()
    assert u["total_requests"] == 2 and u["error_requests"] == 1


def test_webhooks_are_signed_and_retried(make_user, active_business):
    owner, biz = active_business
    app, key = setup_app(owner, biz)
    r = owner.post(f"/developer/apps/{app['id']}/webhooks",
                   {"url": "https://merchant.example/hooks", "environment": "sandbox",
                    "events": ["charge.success"]})
    assert r.status_code == 201
    secret = r.json()["secret"]
    assert secret.startswith("whsec_")
    gw(owner.client, key, "POST", "/charges", json={"amount": "9.99", "phone": "0241234567"})
    gw(owner.client, key, "POST", "/charges", json={"amount": "9.99", "phone": "0240000000"})  # failed: not subscribed

    received = []
    calls = {"n": 0}

    def handler(request: httpx.Request):
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(500)
        received.append(request)
        return httpx.Response(200)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    with SessionLocal() as s:
        assert webhooks.deliver_due(s, client) == {"attempted": 1, "succeeded": 0}
        from app.models import WebhookDelivery

        d = s.scalar(select(WebhookDelivery))
        assert d.status == "pending" and d.attempts == 1
        d.next_attempt_at = None
        s.commit()
        assert webhooks.deliver_due(s, client)["succeeded"] == 1
    req = received[0]
    assert verify_signature_header(secret, req.headers["X-FinCore-Signature"], req.content)
    payload = json.loads(req.content)
    assert payload["type"] == "charge.success" and payload["livemode"] is False
    assert Decimal(payload["data"]["amount"]) == Decimal("9.99")
    deliveries = owner.get(f"/developer/apps/{app['id']}/deliveries").json()
    assert deliveries[0]["status"] == "succeeded"


def test_developer_requires_business_permission(make_user, active_business):
    owner, biz = active_business
    other = make_user()
    assert other.post("/developer/apps", {"business_id": biz["id"], "name": "Intruder"}).status_code == 404
