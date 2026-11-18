"""Private FinCore: 15 dashboard seats, the 15% withdrawal fee, MTN Disbursements, verified subscribers,
application isolation and permissions, the console API and backups.

MTN is replaced by an in-process stand-in implementing the documented sandbox Disbursement endpoints; these are
simulated provider tests, not calls to MTN.
"""

import json
import threading
import uuid
from decimal import Decimal

import httpx
import pytest
from sqlalchemy import select, text

from app.core.config import settings
from app.core.database import SessionLocal
from app.models import LedgerAccount, Transaction, User
from app.models.enums import MAX_DASHBOARD_USERS
from app.providers import override_provider
from app.providers.mtn_momo import MtnMomoSandboxProvider, sandbox_profile
from app.services import team, withdrawal_fee
from tests.conftest import PASSWORD, fund, last_email, token_from
from tests.test_wallets import integrity_ok

API = "/api/v1"


def ledger_balance(code_suffix: str) -> Decimal:
    with SessionLocal() as s:
        return s.scalar(select(LedgerAccount.balance).where(LedgerAccount.code == f"SYS:GHS:{code_suffix}")) or Decimal(0)


def withdraw(u, amount="100.00", phone="0551234567", key=None, **extra):
    headers = {"Idempotency-Key": key} if key else {}
    return u.post("/withdrawals", {"wallet_id": u.wallet()["id"], "amount": amount, "channel": "mobile_money",
                                   "phone": phone, **extra}, headers=headers)


# ================================================================ withdrawal fee (15%, deducted)
def test_fee_formula():
    assert withdrawal_fee.calculate(Decimal("100"), Decimal("0.15"), "GHS") == (Decimal("15.00"), Decimal("85.00"))
    assert withdrawal_fee.calculate(Decimal("33.33"), Decimal("0.15"), "GHS") == (Decimal("5.00"), Decimal("28.33"))


def test_successful_withdrawal_100_gives_15_fee_85_net_100_debit(make_user):
    """Financial test 1."""
    u = make_user()
    fund(u, "500.00")
    q = u.get("/withdrawals/quote", params={"amount": "100"}).json()
    assert q == {"currency": "GHS", "requested_amount": "100.00", "fee_percent": "15", "fee_amount": "15.00",
                 "net_amount": "85.00", "total_debit": "100.00"}
    fee_before = ledger_balance("WITHDRAWAL_FEE_REVENUE")
    t = withdraw(u, expected_fee_percent="15").json()
    assert t["status"] == "successful"
    assert (Decimal(t["amount"]), Decimal(t["fee"]), Decimal(t["net_amount"])) == (100, 15, 85)
    assert Decimal(u.balance()) == Decimal("400.00")                          # GHS 100 debited in total
    assert ledger_balance("WITHDRAWAL_FEE_REVENUE") - fee_before == Decimal("15")  # fee booked separately
    with SessionLocal() as s:
        txn = s.scalar(select(Transaction).where(Transaction.reference == t["reference"]))
        entries = s.execute(text(
            "SELECT a.code, e.direction, e.amount FROM ledger_entries e JOIN ledger_accounts a ON a.id = e.account_id "
            "WHERE e.transaction_id = :id ORDER BY e.line"), {"id": txn.completion_ledger_transaction_id}).all()
    assert [(c.split(":", 2)[2], d, Decimal(a)) for c, d, a in entries] == [
        ("PENDING_PAYOUTS", "debit", 100), ("PROVIDER_CLEARING:SANDBOX", "credit", 85),
        ("WITHDRAWAL_FEE_REVENUE", "credit", 15)]
    integrity_ok()


def test_insufficient_balance_rejected(make_user):
    """Financial test 2."""
    u = make_user()
    fund(u, "50.00")
    r = withdraw(u, "100.00")
    assert r.status_code == 422 and r.json()["error"]["code"] == "insufficient_funds"
    assert Decimal(u.balance()) == Decimal("50.00")
    integrity_ok()


def test_duplicate_withdrawal_request_charges_once(make_user):
    """Financial test 3: same Idempotency-Key, sequential and concurrent -> one transaction, one fee."""
    u = make_user(kyc_tier=2)
    fund(u, "1000.00")
    key = str(uuid.uuid4())
    results = []

    def go():
        results.append(withdraw(u, "100.00", key=key))

    threads = [threading.Thread(target=go) for _ in range(4)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    withdraw(u, "100.00", key=key)
    refs = {r.json().get("reference") for r in results if r.status_code == 201}
    assert len(refs) == 1
    assert Decimal(u.balance()) == Decimal("900.00")
    assert ledger_balance("WITHDRAWAL_FEE_REVENUE") == Decimal("15")
    integrity_ok()


def test_failed_disbursement_returns_everything_and_keeps_no_fee(make_user):
    """Financial test 4."""
    u = make_user()
    fund(u, "200.00")
    t = withdraw(u, "100.00", phone="0240000000").json()  # simulator: always fails
    assert t["status"] == "failed"
    assert Decimal(u.balance()) == Decimal("200.00")
    assert ledger_balance("WITHDRAWAL_FEE_REVENUE") == 0
    integrity_ok()


def test_fee_change_by_admin_keeps_history_and_rejects_stale_confirmation(make_user, admin):
    u = make_user()
    fund(u, "500.00")
    first = withdraw(u, "100.00").json()
    assert admin.put("/console/settings/withdrawal-fee", {"percent": "10"}).status_code == 200
    r = withdraw(u, "100.00", expected_fee_percent="15")  # user saw 15%; it is now 10%
    assert r.status_code == 409 and r.json()["error"]["code"] == "fee_changed"
    second = withdraw(u, "100.00", expected_fee_percent="10").json()
    assert Decimal(second["fee"]) == 10 and Decimal(second["net_amount"]) == 90
    hist = u.get(f"/transactions/{first['reference']}").json()
    assert Decimal(hist["fee"]) == 15 and Decimal(hist["fee_rate"]) == Decimal("0.15")  # history unchanged
    assert admin.put("/console/settings/withdrawal-fee", {"percent": "75"}).status_code == 422
    assert admin.put("/console/settings/withdrawal-fee", {"percent": "abc"}).status_code == 422


def test_fee_setting_requires_finance_or_admin(make_user):
    support = make_user(role="support")
    assert support.put("/console/settings/withdrawal-fee", {"percent": "1"}).status_code == 403
    assert support.get("/console/settings/withdrawal-fee").json()["percent"] == "15"


def test_fee_never_applied_to_transfers_or_collections(make_user):
    a, b = make_user(kyc_tier=2), make_user(kyc_tier=2)
    dep = fund(a, "300.00")
    assert Decimal(dep["fee"]) == 0
    t = a.post("/transfers", {"wallet_id": a.wallet()["id"], "destination_account": b.wallet()["account_number"],
                              "amount": "100"}).json()
    assert Decimal(t["fee"]) == 0 and t["fee_rate"] is None
    assert Decimal(b.balance()) == Decimal("100.00")


# ================================================================ dashboard seats (max 15)
def _fill_seats(n: int):
    with SessionLocal() as s:
        for i in range(n):
            team.create_user(s, email=f"seat{i}-{uuid.uuid4().hex[:5]}@example.com", password=PASSWORD,
                             full_name=f"Seat {i}")


def test_sixteenth_active_user_is_rejected(admin):
    """Financial/security test 8."""
    _fill_seats(MAX_DASHBOARD_USERS - 1)  # admin + 14 = 15
    seats = admin.get("/admin/team").json()["seats"]
    assert seats == {"limit": 15, "used": 15, "available": 0}
    r = admin.post("/admin/team/invitations", {"email": "sixteen@example.com", "full_name": "Number Sixteen",
                                               "role": "support"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "seat_limit_reached"
    # The database refuses it too, even if application code is bypassed.
    with SessionLocal() as s, pytest.raises(Exception, match="dashboard_seat_limit"):
        s.execute(text("INSERT INTO users (id, email, full_name, password_hash, role, status, kyc_tier, "
                       "email_verified, totp_enabled, failed_login_count, is_primary_admin, created_at, updated_at) "
                       "VALUES (gen_random_uuid(), 'x@y.z', 'X', 'h', 'customer', 'active', 0, true, false, 0, "
                       "false, now(), now())"))
        s.commit()


def test_deactivation_frees_a_seat_and_reactivation_is_limited(admin):
    _fill_seats(MAX_DASHBOARD_USERS - 1)
    users = admin.get("/admin/team").json()["users"]
    victim = next(u for u in users if not u["is_primary_admin"])
    assert admin.post(f"/admin/team/{victim['id']}/deactivate", {"reason": "left"}).json()["seats"]["used"] == 14
    r = admin.post("/admin/team/invitations", {"email": "new@example.com", "full_name": "New Person", "role": "finance"})
    assert r.status_code == 201
    r = admin.post(f"/admin/team/{victim['id']}/activate")
    assert r.status_code == 409 and r.json()["error"]["code"] == "seat_limit_reached"


def test_concurrent_activations_cannot_exceed_limit(admin):
    _fill_seats(MAX_DASHBOARD_USERS - 1)
    users = [u for u in admin.get("/admin/team").json()["users"] if not u["is_primary_admin"]][:4]
    for u in users:
        admin.post(f"/admin/team/{u['id']}/deactivate", {"reason": "test"})
    codes = []
    barrier = threading.Barrier(4)

    def act(uid):
        with SessionLocal() as s:
            actor = s.get(User, uuid.UUID(admin.id))
            barrier.wait()
            try:
                team.activate(s, actor, uuid.UUID(uid))
                codes.append("ok")
            except team.SeatLimitReached:
                codes.append("full")

    # 11 seats used, 4 free. Take 1 more so 3 remain, then race 4 activations.
    _fill_seats(1)
    threads = [threading.Thread(target=act, args=(u["id"],)) for u in users]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert codes.count("ok") == 3 and codes.count("full") == 1
    assert admin.get("/admin/team").json()["seats"]["used"] == MAX_DASHBOARD_USERS


def test_invitation_flow_and_no_public_registration(client, admin):
    r = admin.post("/admin/team/invitations", {"email": "esi@example.com", "full_name": "Esi Mensah", "role": "finance"})
    assert r.status_code == 201
    link = r.json()["invitation_link"]
    token = link.split("token=")[1]
    assert token == token_from(last_email("esi@example.com"))
    assert client.post(f"{API}/auth/login", json={"email": "esi@example.com", "password": "Esi!Pass2026x"}).status_code == 401
    assert client.get(f"{API}/auth/invitation", params={"token": token}).json()["email"] == "esi@example.com"
    assert client.post(f"{API}/auth/invitation/accept", json={"token": token, "password": "Esi!Pass2026x"}).status_code == 200
    assert client.post(f"{API}/auth/invitation/accept", json={"token": token, "password": "Esi!Pass2026y"}).status_code == 401
    r = client.post(f"{API}/auth/login", json={"email": "esi@example.com", "password": "Esi!Pass2026x"})
    assert r.status_code == 200
    assert client.post(f"{API}/auth/register", json={"email": "z@example.com", "password": PASSWORD,
                                                     "full_name": "Zed"}).status_code == 403


def test_deactivation_revokes_sessions_immediately(make_user, admin):
    u = make_user(role="finance")
    assert u.get("/me").status_code == 200
    admin.post(f"/admin/team/{u.id}/deactivate", {"reason": "left the company"})
    r = u.get("/me")
    assert r.status_code == 401
    r = u.client.post(f"{API}/auth/login", json={"email": u.email, "password": PASSWORD})
    assert r.status_code == 403


def test_primary_admin_is_protected(make_user, admin):
    second = make_user(role="super_admin")  # not primary
    me = admin.get("/me").json()
    assert me["is_primary_admin"] is True
    for path in (f"/admin/team/{admin.id}/deactivate", f"/admin/team/{admin.id}/remove"):
        r = second.post(path, {"reason": "coup"})
        assert r.status_code == 403 and r.json()["error"]["code"] == "primary_admin_protected"
    r = admin.post(f"/admin/team/{admin.id}/deactivate", {"reason": "oops"})
    assert r.status_code == 403
    assert second.post(f"/admin/users/{admin.id}/status", {"status": "frozen", "reason": "takeover"}).status_code == 403
    with SessionLocal() as s, pytest.raises(Exception, match="primary_admin_protected"):
        s.execute(text("UPDATE users SET status = 'deactivated' WHERE is_primary_admin"))
        s.commit()


def test_no_privilege_escalation(make_user, admin):
    second = make_user(role="super_admin")
    finance = make_user(role="finance")
    r = second.post("/admin/team/invitations", {"email": "boss@example.com", "full_name": "Boss Two",
                                                "role": "super_admin"})
    assert r.status_code == 403 and r.json()["error"]["code"] == "not_primary_admin"
    assert second.post(f"/admin/team/{finance.id}/role", {"role": "super_admin"}).status_code == 403
    assert finance.post("/admin/team/invitations", {"email": "f@example.com", "full_name": "Eff",
                                                    "role": "admin"}).status_code == 403
    assert finance.get("/admin/team").status_code == 403
    assert admin.post(f"/admin/team/{finance.id}/role", {"role": "admin"}).status_code == 200
    assert finance.get("/me").status_code == 401  # role change signs the user out


def test_user_activity_and_session_revocation(make_user, admin):
    u = make_user()
    fund(u, "10")
    act = admin.get(f"/admin/team/{u.id}/activity").json()
    assert act["sessions"] and any(e["action"].startswith("wallet") or e["action"] for e in act["events"])
    assert admin.post(f"/admin/team/{u.id}/sessions/revoke").json()["revoked"] >= 1
    assert u.get("/me").status_code == 401


# ================================================================ applications, permissions, isolation
def _app(admin, name, **kw):
    r = admin.post("/console/applications", {"name": name, **kw})
    assert r.status_code == 201, r.text
    app = r.json()
    key = admin.post(f"/console/applications/{app['id']}/keys", {"environment": "sandbox"}).json()["secret_key"]
    return app, {"Authorization": f"Bearer {key}"}


def test_application_cannot_see_another_applications_charges(client, admin):
    a, ha = _app(admin, "Send Me")
    b, hb = _app(admin, "PharmaStock")
    assert a["business_id"] == b["business_id"]  # same owner business — still isolated
    r = client.post(f"{API}/gateway/charges", json={"amount": "20", "description": "Order 1", "reference": "SM-1"},
                    headers=ha)
    assert r.status_code == 201, r.text
    ref = r.json()["reference"]
    assert client.get(f"{API}/gateway/charges/{ref}", headers=ha).status_code == 200
    r = client.get(f"{API}/gateway/charges/{ref}", headers=hb)
    assert r.status_code == 404  # Financial/security test 9
    assert client.get(f"{API}/gateway/charges", headers=hb).json()["total"] == 0
    assert client.post(f"{API}/gateway/refunds", json={"charge_reference": ref, "amount": "1"},
                       headers=hb).status_code == 404


def test_webhooks_go_only_to_the_originating_app(client, admin):
    a, ha = _app(admin, "Send Me")
    b, hb = _app(admin, "Nurses Hub")
    for app in (a, b):
        admin.post(f"/console/applications/{app['id']}/webhooks", {"url": f"https://example.com/{app['name']}",
                                                                   "environment": "sandbox"})
    ref = client.post(f"{API}/gateway/charges", json={"amount": "5", "phone": "0241234567"}, headers=ha).json()
    assert ref["status"] in ("successful", "processing", "pending")
    from app.models import WebhookDelivery, WebhookEndpoint
    with SessionLocal() as s:
        rows = s.execute(select(WebhookEndpoint.app_id).join(
            WebhookDelivery, WebhookDelivery.endpoint_id == WebhookEndpoint.id)).all()
    assert rows and {str(r[0]) for r in rows} == {a["id"]}


def test_app_permissions_and_deactivation(client, admin):
    a, ha = _app(admin, "Send Me", permissions=["collections"])
    r = client.get(f"{API}/gateway/payouts/quote", params={"amount": "100"}, headers=ha)
    assert r.status_code == 403 and r.json()["error"]["code"] == "app_permission_denied"
    assert client.get(f"{API}/gateway/balance", headers=ha).status_code == 403
    admin.patch(f"/console/applications/{a['id']}", {"permissions": ["collections", "payouts"]})
    q = client.get(f"{API}/gateway/payouts/quote", params={"amount": "100"}, headers=ha).json()
    assert q["fee_amount"] == "15.00" and q["net_amount"] == "85.00"
    admin.patch(f"/console/applications/{a['id']}", {"status": "disabled"})
    assert client.get(f"{API}/gateway/charges", headers=ha).status_code in (401, 403)
    assert admin.patch(f"/console/applications/{a['id']}", {"permissions": ["everything"]}).status_code == 422


def test_key_rotation_and_revocation(client, admin):
    a, ha = _app(admin, "Send Me")
    keys = admin.get(f"/console/applications/{a['id']}/keys").json()
    new = admin.post(f"/console/applications/{a['id']}/keys/{keys[0]['id']}/rotate").json()
    assert client.get(f"{API}/gateway/charges", headers=ha).status_code == 401  # old key dead
    hn = {"Authorization": f"Bearer {new['secret_key']}"}
    assert client.get(f"{API}/gateway/charges", headers=hn).status_code == 200
    admin.post(f"/console/applications/{a['id']}/keys/{new['id']}/revoke")
    assert client.get(f"{API}/gateway/charges", headers=hn).status_code == 401


def test_sandbox_payout_is_a_labelled_simulation(client, admin):
    a, ha = _app(admin, "Send Me", permissions=["payouts"])
    r = client.post(f"{API}/gateway/payouts", json={"amount": "100", "phone": "0241234567", "reference": "P-1"},
                    headers=ha)
    assert r.status_code == 201
    assert r.json()["simulated"] is True and r.json()["livemode"] is False and r.json()["net_amount"] == "85.00"
    with SessionLocal() as s:
        assert s.scalar(select(Transaction).where(Transaction.type == "withdrawal")) is None  # nothing moved


# ================================================================ verified subscribers
def test_subscriber_verification_and_access(client, admin):
    a, ha = _app(admin, "Nurses Hub", require_verified_subscribers=True)
    b, hb = _app(admin, "PharmaStock")
    r = client.post(f"{API}/gateway/subscribers", json={"external_id": "nurse-42", "display_name": "Akua",
                                                        "phone": "0241234567"}, headers=ha)
    assert r.status_code == 201 and r.json()["status"] == "pending"
    r = client.post(f"{API}/gateway/subscribers/nurse-42/token", headers=ha)
    assert r.status_code == 403 and r.json()["error"]["code"] == "subscriber_not_verified"
    # Unverified/no token: subscriber-restricted functionality is refused with a clear message.
    r = client.post(f"{API}/gateway/charges", json={"amount": "10", "description": "Exam prep"}, headers=ha)
    assert r.status_code == 403 and r.json()["error"]["code"] == "subscriber_token_required"
    code = client.post(f"{API}/gateway/subscribers/nurse-42/verification", headers=ha).json()["dev_code"]
    assert client.post(f"{API}/gateway/subscribers/nurse-42/verification/confirm", json={"code": "000000"},
                       headers=ha).status_code == 422
    r = client.post(f"{API}/gateway/subscribers/nurse-42/verification/confirm", json={"code": code}, headers=ha)
    assert r.json()["status"] == "active" and r.json()["verified"] is True
    tok = client.post(f"{API}/gateway/subscribers/nurse-42/token", headers=ha).json()["subscriber_token"]
    hs = {**ha, "X-Subscriber-Token": tok}
    assert client.post(f"{API}/gateway/charges", json={"amount": "10", "description": "Exam prep"},
                       headers=hs).status_code == 201
    # Another application cannot use this subscriber's token.
    r = client.get(f"{API}/gateway/subscribers/access/check", headers={**hb, "X-Subscriber-Token": tok})
    assert r.status_code == 401
    # Administrator deactivates: existing sessions revoked immediately, new tokens refused.
    sub_id = admin.get("/admin/subscribers").json()["items"][0]["id"]
    admin.post(f"/admin/subscribers/{sub_id}", {"action": "deactivate", "reason": "subscription ended"})
    r = client.get(f"{API}/gateway/subscribers/access/check", headers=hs)
    assert r.status_code == 401 and r.json()["error"]["code"] == "subscriber_session_revoked"
    r = client.post(f"{API}/gateway/subscribers/nurse-42/token", headers=ha)
    assert r.status_code == 403 and r.json()["error"]["code"] == "subscriber_inactive"
    # Subscribers are not dashboard users.
    assert admin.get("/admin/team").json()["seats"]["used"] == 1


def test_many_subscribers_do_not_use_dashboard_seats(client, admin):
    a, ha = _app(admin, "Send Me")
    for i in range(30):
        assert client.post(f"{API}/gateway/subscribers", json={"external_id": f"cust-{i}"}, headers=ha).status_code == 201
    assert admin.get("/admin/team").json()["seats"]["used"] == 1


# ================================================================ MTN Disbursements (stand-in API)
DISB_KEY = "disb-primary-" + "k" * 19
DISB_USER = str(uuid.uuid4())
DISB_API_KEY = "disb-api-key-" + "z" * 19


class FakeMtnDisbursement:
    def __init__(self):
        self.transfers: dict[str, dict] = {}
        self.final_status = "SUCCESSFUL"
        self.reason = None

    def __call__(self, request: httpx.Request) -> httpx.Response:
        assert request.headers.get("Ocp-Apim-Subscription-Key") == DISB_KEY  # never the Collections key
        path = request.url.path
        if path.endswith("/disbursement/token/"):
            return httpx.Response(200, json={"access_token": "dtok", "expires_in": 3600})
        assert request.headers["Authorization"] == "Bearer dtok"
        if path.endswith("/disbursement/v1_0/transfer") and request.method == "POST":
            ref = request.headers["X-Reference-Id"]
            if ref in self.transfers:
                return httpx.Response(409)
            self.transfers[ref] = {**json.loads(request.content), "status": "PENDING"}
            return httpx.Response(202)
        if "/disbursement/v1_0/transfer/" in path:
            t = self.transfers.get(path.rsplit("/", 1)[-1])
            if not t:
                return httpx.Response(404)
            out = {"status": t["status"], "externalId": t["externalId"], "amount": t["amount"]}
            if self.reason:
                out["reason"] = self.reason
            return httpx.Response(200, json=out)
        return httpx.Response(404)

    def settle_all(self):
        for t in self.transfers.values():
            t["status"] = self.final_status


def fund_sim(u, amount, monkeypatch):
    """Fund through the labelled simulator (Collections are not under test here)."""
    monkeypatch.setattr(settings, "mtn_momo_mode", "off")
    fund(u, amount)
    monkeypatch.setattr(settings, "mtn_momo_mode", "sandbox")


@pytest.fixture
def mtn_disb(monkeypatch):
    monkeypatch.setattr(settings, "mtn_momo_mode", "sandbox")
    monkeypatch.setattr(settings, "mtn_disbursement_primary_key", DISB_KEY)
    monkeypatch.setattr(settings, "mtn_sandbox_disbursement_api_user", DISB_USER)
    monkeypatch.setattr(settings, "mtn_sandbox_disbursement_api_key", DISB_API_KEY)
    fake = FakeMtnDisbursement()
    override_provider("mtn_momo_sandbox", MtnMomoSandboxProvider(client=httpx.Client(transport=httpx.MockTransport(fake))))
    yield fake
    override_provider("mtn_momo_sandbox", None)


def test_primary_disbursement_key_belongs_to_the_active_mode_only(monkeypatch):
    monkeypatch.setattr(settings, "mtn_disbursement_primary_key", DISB_KEY)
    monkeypatch.setattr(settings, "mtn_momo_mode", "sandbox")
    assert sandbox_profile().disbursement[0] == DISB_KEY
    assert sandbox_profile().collection[0] == ""  # Collections never borrow the Disbursement key
    from app.providers.mtn_momo import production_profile
    assert production_profile().disbursement[0] == ""
    monkeypatch.setattr(settings, "mtn_sandbox_disbursement_subscription_key", "explicit")
    assert sandbox_profile().disbursement[0] == "explicit"


def test_mtn_withdrawal_is_processing_until_mtn_confirms(make_user, mtn_disb, monkeypatch):
    u = make_user()
    fund_sim(u, "300.00", monkeypatch)
    t = withdraw(u, "100.00", phone="0241234567").json()
    assert t["status"] == "processing" and t["provider"] == "mtn_momo_sandbox"  # submitted is not successful
    assert len(mtn_disb.transfers) == 1
    sent = next(iter(mtn_disb.transfers.values()))
    assert sent["amount"] == "85.00" and sent["payee"]["partyId"] == "233241234567"  # the net payout
    assert Decimal(u.balance()) == Decimal("200.00")
    assert ledger_balance("WITHDRAWAL_FEE_REVENUE") == 0
    mtn_disb.settle_all()
    r = u.post(f"/transactions/{t['reference']}/refresh").json()
    assert r["status"] == "successful"
    assert ledger_balance("WITHDRAWAL_FEE_REVENUE") == Decimal("15")
    assert ledger_balance("PROVIDER_CLEARING:MTN_MOMO_SANDBOX") == Decimal("-85")
    integrity_ok()


@pytest.mark.parametrize("status,reason,outcome", [("FAILED", "PAYEE_NOT_FOUND", "failed"),
                                                   ("REJECTED", None, "rejected")])
def test_mtn_failed_or_rejected_transfer_releases_funds(make_user, mtn_disb, status, reason, outcome, monkeypatch):
    u = make_user()
    fund_sim(u, "300.00", monkeypatch)
    t = withdraw(u, "100.00", phone="0241234567").json()
    mtn_disb.final_status, mtn_disb.reason = status, reason
    mtn_disb.settle_all()
    r = u.post(f"/transactions/{t['reference']}/refresh").json()
    assert r["status"] == "failed"
    assert Decimal(u.balance()) == Decimal("300.00")
    assert ledger_balance("WITHDRAWAL_FEE_REVENUE") == 0
    integrity_ok()


def test_mtn_transfer_unknown_to_mtn_is_resolved_as_failed(make_user, mtn_disb, monkeypatch):
    u = make_user()
    fund_sim(u, "300.00", monkeypatch)
    t = withdraw(u, "100.00", phone="0241234567").json()
    mtn_disb.transfers.clear()  # MTN never received it (e.g. our call timed out before reaching MTN)
    r = u.post(f"/transactions/{t['reference']}/refresh").json()
    assert r["status"] == "failed" and Decimal(u.balance()) == Decimal("300.00")
    integrity_ok()


def test_disbursements_refuse_to_run_without_their_own_credentials(make_user, monkeypatch):
    u = make_user()
    fund_sim(u, "300.00", monkeypatch)
    r = withdraw(u, "100.00", phone="0241234567")
    assert r.status_code == 503 and "disbursement is not configured" in r.json()["error"]["message"]
    assert Decimal(u.balance()) == Decimal("300.00")


def test_live_application_payout_end_to_end(client, admin, mtn_disb, monkeypatch):
    monkeypatch.setattr(settings, "live_payments_enabled", True)
    a = admin.post("/console/applications", {"name": "Send Me", "permissions": ["payouts", "balance"]}).json()
    live = admin.post(f"/console/applications/{a['id']}/keys", {"environment": "live"}).json()["secret_key"]
    h = {"Authorization": f"Bearer {live}"}
    acct = client.get(f"{API}/gateway/balance", headers=h).json()["balances"][0]["account_number"]
    assert admin.post("/admin/adjustments", {"wallet_account_number": acct, "amount": "500", "direction": "credit",
                                             "reason": "Opening float for tests"}).status_code == 200
    body = {"amount": "100", "phone": "0241234567", "reference": "SENDME-1", "expected_fee_percent": "15"}
    r = client.post(f"{API}/gateway/payouts", json=body, headers={**h, "Idempotency-Key": "k1"})
    assert r.status_code == 201, r.text
    p = r.json()
    assert (p["status"], p["fee"], p["net_amount"], p["fee_percent"]) == ("processing", "15.00", "85.00", "15")
    again = client.post(f"{API}/gateway/payouts", json=body, headers={**h, "Idempotency-Key": "k1"}).json()
    assert again["reference"] == p["reference"]
    dup = client.post(f"{API}/gateway/payouts", json=body, headers=h)
    assert dup.status_code == 409 and dup.json()["error"]["code"] == "duplicate_reference"
    assert len(mtn_disb.transfers) == 1
    mtn_disb.settle_all()
    done = client.get(f"{API}/gateway/payouts/SENDME-1", headers=h).json()
    assert done["status"] == "successful"
    assert client.get(f"{API}/gateway/balance", headers=h).json()["balances"][0]["available"] == "400.00"
    other = admin.post("/console/applications", {"name": "Other", "permissions": ["payouts"]}).json()
    ho = {"Authorization": "Bearer " + admin.post(f"/console/applications/{other['id']}/keys",
                                                  {"environment": "live"}).json()["secret_key"]}
    assert client.get(f"{API}/gateway/payouts/SENDME-1", headers=ho).status_code == 404
    ov = admin.get("/console/overview").json()
    assert Decimal(ov["totals"]["withdrawal_fees"]) == 15 and Decimal(ov["totals"]["disbursements"]) == 85
    integrity_ok()


# ================================================================ console
def test_console_sections(make_user, admin):
    u = make_user()
    fund(u, "100")
    withdraw(u, "20")
    ov = admin.get("/console/overview").json()
    assert ov["totals"]["successful"] == 2 and Decimal(ov["totals"]["collections"]) == 100
    assert Decimal(ov["totals"]["withdrawal_fees"]) == 3 and ov["system"]["database"] == "ok"
    assert ov["system"]["seats"]["limit"] == 15 and ov["recent"]
    pay = admin.get("/console/payments").json()
    assert pay["mtn"]["mode"] == "off" and pay["withdrawal_fee_percent"] == "15"
    assert admin.get("/admin/transactions", params={"type": "withdrawal"}).json()["total"] == 1
    assert u.get("/console/overview").status_code == 403


# ================================================================ backups
def test_backup_and_verified_restore(tmp_path, monkeypatch, make_user):
    from app.services import backups
    u = make_user()
    fund(u, "42")
    monkeypatch.setattr(settings, "backup_dir", str(tmp_path))
    info = backups.create_backup()
    assert info["size_bytes"] > 0 and backups.list_backups()[0]["name"] == info["name"]
    result = backups.verify_backup(info["name"])
    assert result["restored_ok"] and result["row_counts"]["users"] == 1 and result["guards_restored"] == 3
    with pytest.raises(backups.BackupError, match="existing database"):
        backups.restore_to(info["name"], "fincore_test")  # never overwrites a database
