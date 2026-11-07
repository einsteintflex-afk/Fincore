import threading
import uuid
from decimal import Decimal

from sqlalchemy import select

from app.core.database import SessionLocal
from app.models import AccountRestriction, FraudAlert
from app.services.ledger import LedgerService
from tests.conftest import fund


def integrity_ok():
    with SessionLocal() as s:
        report = LedgerService(s).verify_integrity()
        assert report["balanced"], report["problems"]


def test_mobile_money_deposit_success(make_user):
    u = make_user()
    t = fund(u, "250.00")
    assert t["provider"] == "sandbox" and t["provider_mode"] == "sandbox"
    assert Decimal(u.balance()) == Decimal("250.00")
    integrity_ok()


def test_deposit_failure_and_pending(make_user):
    u = make_user()
    w = u.wallet()
    r = u.post("/deposits", {"wallet_id": w["id"], "amount": "50", "phone": "0240000000"})
    assert r.status_code == 201 and r.json()["status"] == "failed"
    r = u.post("/deposits", {"wallet_id": w["id"], "amount": "50", "phone": "0241111111"})
    pending = r.json()
    assert pending["status"] == "processing"
    assert Decimal(u.balance()) == 0
    r = u.post(f"/transactions/{pending['reference']}/simulate", params={"outcome": "successful"})
    assert r.status_code == 200 and r.json()["status"] == "successful"
    assert Decimal(u.balance()) == Decimal("50.00")
    # applying again is a no-op (idempotent)
    u.post(f"/transactions/{pending['reference']}/simulate", params={"outcome": "successful"})
    assert Decimal(u.balance()) == Decimal("50.00")
    integrity_ok()


def test_amount_validation(make_user):
    u = make_user()
    w = u.wallet()
    for bad in ("0", "-5", "10.001"):
        r = u.post("/deposits", {"wallet_id": w["id"], "amount": bad, "phone": "0241234567"})
        assert r.status_code == 422, bad


def test_transfer_between_customers(make_user):
    a, b = make_user(), make_user()
    fund(a, "300.00")
    lookup = a.get("/wallets/lookup", params={"account_number": b.wallet()["account_number"]}).json()
    assert lookup["valid"] and lookup["account_name"].startswith("Test User")
    r = a.post("/transfers", {"wallet_id": a.wallet()["id"], "destination_account": b.wallet()["account_number"],
                              "amount": "120.50", "narration": "Lunch"})
    assert r.status_code == 201, r.text
    assert r.json()["direction"] == "out"
    assert Decimal(a.balance()) == Decimal("179.50")
    assert Decimal(b.balance()) == Decimal("120.50")
    hist = b.get("/transactions").json()
    assert hist["total"] == 1 and hist["items"][0]["direction"] == "in"
    integrity_ok()


def test_transfer_insufficient_funds_and_self(make_user):
    a, b = make_user(), make_user()
    fund(a, "10.00")
    r = a.post("/transfers", {"wallet_id": a.wallet()["id"], "destination_account": b.wallet()["account_number"],
                              "amount": "10.01"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "insufficient_funds"
    r = a.post("/transfers", {"wallet_id": a.wallet()["id"], "destination_account": a.wallet()["account_number"],
                              "amount": "1"})
    assert r.status_code == 422
    r = a.post("/transfers", {"wallet_id": a.wallet()["id"], "destination_account": "1234567890", "amount": "1"})
    assert r.status_code in (404, 422)
    assert Decimal(a.balance()) == Decimal("10.00")


def test_cannot_use_someone_elses_wallet(make_user):
    a, b = make_user(), make_user()
    fund(b, "100")
    r = a.post("/transfers", {"wallet_id": b.wallet()["id"], "destination_account": a.wallet()["account_number"],
                              "amount": "50"})
    assert r.status_code == 404
    assert Decimal(b.balance()) == Decimal("100.00")


def test_withdrawal_to_momo_with_fee(make_user):
    u = make_user()
    fund(u, "500.00")
    r = u.post("/withdrawals", {"wallet_id": u.wallet()["id"], "amount": "100.00", "channel": "mobile_money",
                                "phone": "0551234567"})
    assert r.status_code == 201, r.text
    t = r.json()
    assert t["status"] == "successful"
    assert Decimal(t["fee"]) == Decimal("0.75")  # 0.75% with GHS 0.50 minimum
    assert Decimal(u.balance()) == Decimal("399.25")
    integrity_ok()


def test_failed_withdrawal_releases_hold(make_user):
    u = make_user()
    fund(u, "200.00")
    r = u.post("/withdrawals", {"wallet_id": u.wallet()["id"], "amount": "100.00", "channel": "mobile_money",
                                "phone": "0240000000"})
    assert r.json()["status"] == "failed"
    assert Decimal(u.balance()) == Decimal("200.00")
    integrity_ok()


def test_pending_withdrawal_holds_then_fails(make_user):
    u = make_user()
    fund(u, "200.00")
    r = u.post("/withdrawals", {"wallet_id": u.wallet()["id"], "amount": "100.00", "channel": "bank",
                                "bank_code": "GCB", "account_number": "1234561111"})
    t = r.json()
    assert t["status"] == "processing"
    assert Decimal(u.balance()) == Decimal("98.00")  # 100 + GHS 2 bank fee held
    u.post(f"/transactions/{t['reference']}/simulate", params={"outcome": "failed"})
    assert Decimal(u.balance()) == Decimal("200.00")
    integrity_ok()


def test_limits_enforced_by_tier(make_user):
    u = make_user(kyc_tier=0)
    w = u.wallet()
    r = u.post("/deposits", {"wallet_id": w["id"], "amount": "250", "phone": "0241234567"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "limit_exceeded"
    for _ in range(2):
        assert u.post("/deposits", {"wallet_id": w["id"], "amount": "200", "phone": "0241234567"}).status_code == 201
    r = u.post("/deposits", {"wallet_id": w["id"], "amount": "150", "phone": "0241234567"})
    assert r.status_code == 422  # daily limit of 500
    limits = u.get("/me/limits").json()
    assert limits["kyc_tier"] == 0


def test_balance_cap(make_user):
    a = make_user(kyc_tier=2)
    b = make_user(kyc_tier=0)
    fund(a, "1000")
    # tier 0 max balance is 500; transfer limit for sender (tier 2) is fine
    r = a.post("/transfers", {"wallet_id": a.wallet()["id"], "destination_account": b.wallet()["account_number"],
                              "amount": "600"})
    assert r.status_code == 422 and r.json()["error"]["details"]["limit"] == "max_balance"


def test_idempotent_transfer(make_user):
    a, b = make_user(), make_user()
    fund(a, "100")
    body = {"wallet_id": a.wallet()["id"], "destination_account": b.wallet()["account_number"], "amount": "30"}
    key = str(uuid.uuid4())
    r1 = a.post("/transfers", body, headers={"Idempotency-Key": key})
    r2 = a.post("/transfers", body, headers={"Idempotency-Key": key})
    assert r1.status_code == 201 and r2.status_code == 201
    assert r1.json()["reference"] == r2.json()["reference"]
    assert Decimal(b.balance()) == Decimal("30.00")
    r3 = a.post("/transfers", {**body, "amount": "31"}, headers={"Idempotency-Key": key})
    assert r3.status_code == 409


def test_idempotent_failure_is_replayed(make_user):
    a, b = make_user(), make_user()
    body = {"wallet_id": a.wallet()["id"], "destination_account": b.wallet()["account_number"], "amount": "30"}
    key = str(uuid.uuid4())
    assert a.post("/transfers", body, headers={"Idempotency-Key": key}).status_code == 422
    fund(a, "100")
    r = a.post("/transfers", body, headers={"Idempotency-Key": key})
    assert r.status_code == 422  # same key returns the original outcome
    assert Decimal(a.balance()) == Decimal("100.00")


def test_restricted_user_cannot_send(make_user, admin):
    a, b = make_user(), make_user()
    fund(a, "100")
    r = admin.post(f"/admin/users/{a.id}/restrictions", {"type": "no_debit", "reason": "Investigation"})
    assert r.status_code == 200, r.text
    r = a.post("/transfers", {"wallet_id": a.wallet()["id"], "destination_account": b.wallet()["account_number"],
                              "amount": "10"})
    assert r.status_code == 403 and r.json()["error"]["code"] == "account_restricted"
    # receiving still works
    fund(a, "5")
    with SessionLocal() as s:
        rid = s.scalar(select(AccountRestriction.id))
    assert admin.delete(f"/admin/users/{a.id}/restrictions/{rid}").status_code == 200
    r = a.post("/transfers", {"wallet_id": a.wallet()["id"], "destination_account": b.wallet()["account_number"],
                              "amount": "10"})
    assert r.status_code == 201


def test_statement_balances(make_user):
    a, b = make_user(), make_user()
    fund(a, "100")
    a.post("/transfers", {"wallet_id": a.wallet()["id"], "destination_account": b.wallet()["account_number"],
                          "amount": "40"})
    st = a.get(f"/wallets/{a.wallet()['id']}/statement").json()
    assert Decimal(st["opening_balance"]) == 0
    assert Decimal(st["closing_balance"]) == Decimal("60.00")
    assert Decimal(st["total_credits"]) == Decimal("100.00") and Decimal(st["total_debits"]) == Decimal("40.00")
    csv = a.get(f"/wallets/{a.wallet()['id']}/statement", params={"format": "csv"})
    assert csv.status_code == 200 and "Closing balance" in csv.text


def test_beneficiaries(make_user):
    a, b = make_user(), make_user()
    r = a.post("/beneficiaries", {"type": "mobile_money", "name": "Mum", "identifier": "0201234567"})
    assert r.status_code == 201 and r.json()["network"] == "telecel"
    r = a.post("/beneficiaries", {"type": "wallet", "name": "B", "identifier": b.wallet()["account_number"]})
    assert r.status_code == 201
    assert a.post("/beneficiaries", {"type": "mobile_money", "name": "Mum", "identifier": "233201234567"}).status_code == 409
    bid = r.json()["id"]
    assert a.post(f"/beneficiaries/{bid}/favourite").json()["favourite"] is True
    assert len(a.get("/beneficiaries").json()) == 2
    assert a.delete(f"/beneficiaries/{bid}").status_code == 200


def test_large_transfer_creates_fraud_alert(make_user):
    a = make_user(kyc_tier=3)
    b = make_user(kyc_tier=3)
    fund(a, "15000", phone="0241234567")
    r = a.post("/transfers", {"wallet_id": a.wallet()["id"], "destination_account": b.wallet()["account_number"],
                              "amount": "12000"})
    assert r.status_code == 201
    with SessionLocal() as s:
        alerts = s.scalars(select(FraudAlert)).all()
        assert any(al.rule == "large_amount" for al in alerts)


def test_concurrent_transfers_never_overdraw(make_user):
    a, b = make_user(kyc_tier=3), make_user(kyc_tier=3)
    fund(a, "100.00")
    src, dst = a.wallet()["id"], b.wallet()["account_number"]
    results = []

    from fastapi.testclient import TestClient

    from app.main import app

    def worker():
        with TestClient(app) as c:
            r = c.post("/api/v1/transfers", json={"wallet_id": src, "destination_account": dst, "amount": "15.00"},
                       headers=a.h)
            results.append(r.status_code)

    threads = [threading.Thread(target=worker) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert results.count(201) == 6, results  # 6 * 15 = 90 <= 100; the 7th must fail
    assert Decimal(a.balance()) == Decimal("10.00")
    assert Decimal(b.balance()) == Decimal("90.00")
    integrity_ok()


def test_notifications(make_user):
    u = make_user()
    fund(u, "20")
    n = u.get("/me/notifications").json()
    assert n["unread"] >= 2
    u.post("/me/notifications/read-all")
    assert u.get("/me/notifications").json()["unread"] == 0




def test_concurrent_duplicate_idempotency_keys_move_money_once(make_user):
    a, b = make_user(kyc_tier=3), make_user(kyc_tier=3)
    fund(a, "100")
    body = {"wallet_id": a.wallet()["id"], "destination_account": b.wallet()["account_number"], "amount": "7"}
    key = str(uuid.uuid4())
    codes = []

    from fastapi.testclient import TestClient

    from app.main import app

    def worker():
        with TestClient(app) as c:
            codes.append(c.post("/api/v1/transfers", json=body, headers={**a.h, "Idempotency-Key": key}).status_code)

    threads = [threading.Thread(target=worker) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert set(codes) <= {201, 409} and 201 in codes, codes
    assert Decimal(b.balance()) == Decimal("7.00")
    integrity_ok()
