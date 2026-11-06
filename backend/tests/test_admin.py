from datetime import date
from decimal import Decimal

from tests.conftest import fund
from tests.test_wallets import integrity_ok


def test_kyc_submission_and_review(make_user, admin):
    u = make_user(kyc_tier=0)
    bad = u.post("/me/kyc", {"tier_requested": 2, "id_type": "passport", "id_number": "G123", "first_name": "A",
                             "last_name": "B", "date_of_birth": "1990-01-01"})
    assert bad.status_code == 422
    minor = u.post("/me/kyc", {"tier_requested": 2, "id_type": "ghana_card", "id_number": "GHA-123456789-0",
                               "first_name": "A", "last_name": "B", "date_of_birth": str(date.today())})
    assert minor.status_code == 422
    r = u.post("/me/kyc", {"tier_requested": 2, "id_type": "ghana_card", "id_number": "gha-123456789-0",
                           "first_name": "Ama", "last_name": "Owusu", "date_of_birth": "1992-03-06",
                           "digital_address": "GA-123-4567"})
    assert r.status_code == 201, r.text
    sub = r.json()
    assert sub["id_number"] == "GHA-123456789-0"
    assert u.post("/me/kyc", {**{k: sub[k] for k in ("id_type", "id_number", "first_name", "last_name",
                                                     "date_of_birth")}, "tier_requested": 2}).status_code == 409
    queue = admin.get("/admin/kyc").json()
    assert queue["total"] == 1
    assert admin.post(f"/admin/kyc/{sub['id']}/review", {"decision": "reject"}).status_code == 422  # note required
    r = admin.post(f"/admin/kyc/{sub['id']}/review", {"decision": "approve"})
    assert r.status_code == 200
    assert u.get("/me").json()["kyc_tier"] == 2


def test_role_based_admin_access(make_user):
    support = make_user(role="support")
    target = make_user()
    assert support.get("/admin/users").status_code == 200
    assert support.post(f"/admin/users/{target.id}/restrictions", {"type": "no_debit", "reason": "x" * 5}).status_code == 403
    assert support.get("/admin/fees").status_code == 200
    assert support.post("/admin/adjustments", {"wallet_account_number": "x", "amount": "1", "direction": "credit",
                                               "reason": "test"}).status_code == 403


def test_reversal_and_adjustment(make_user, admin):
    a, b = make_user(), make_user()
    fund(a, "100")
    t = a.post("/transfers", {"wallet_id": a.wallet()["id"], "destination_account": b.wallet()["account_number"],
                              "amount": "40"}).json()
    r = admin.post(f"/admin/transactions/{t['reference']}/reverse", {"reason": "Customer error"})
    assert r.status_code == 200, r.text
    assert Decimal(a.balance()) == Decimal("100.00") and Decimal(b.balance()) == 0
    assert admin.post(f"/admin/transactions/{t['reference']}/reverse", {"reason": "again"}).status_code == 409
    detail = admin.get(f"/admin/transactions/{t['reference']}").json()
    assert detail["transaction"]["status"] == "reversed" and detail["journals"]
    r = admin.post("/admin/adjustments", {"wallet_account_number": b.wallet()["account_number"], "amount": "5",
                                          "direction": "credit", "reason": "Goodwill credit"})
    assert r.status_code == 200
    assert Decimal(b.balance()) == Decimal("5.00")
    r = admin.post("/admin/adjustments", {"wallet_account_number": b.wallet()["account_number"], "amount": "6",
                                          "direction": "debit", "reason": "Correction"})
    assert r.status_code == 422  # cannot overdraw
    integrity_ok()


def test_fee_configuration_changes_fees(make_user, admin):
    rules = admin.get("/admin/fees").json()
    transfer = next(r for r in rules if r["transaction_type"] == "transfer")
    body = {**{k: transfer[k] for k in ("name", "transaction_type", "channel", "currency", "payer", "min_fee",
                                        "max_fee", "active")}, "flat_fee": "1.00", "percent_fee": "0"}
    assert admin.put(f"/admin/fees/{transfer['id']}", body).status_code == 200
    a, b = make_user(), make_user()
    fund(a, "10")
    t = a.post("/transfers", {"wallet_id": a.wallet()["id"], "destination_account": b.wallet()["account_number"],
                              "amount": "5"}).json()
    assert Decimal(t["fee"]) == Decimal("1.00")
    assert Decimal(a.balance()) == Decimal("4.00")
    logs = admin.get("/admin/audit-logs", params={"action": "config.fee"}).json()
    assert logs["total"] == 1


def test_limit_configuration(make_user, admin):
    r = admin.put("/admin/limits", {"kyc_tier": 1, "transaction_type": "transfer", "per_transaction_max": "5",
                                    "daily_max": "100", "monthly_max": "1000"})
    assert r.status_code == 200
    a, b = make_user(), make_user()
    fund(a, "50")
    r = a.post("/transfers", {"wallet_id": a.wallet()["id"], "destination_account": b.wallet()["account_number"],
                              "amount": "6"})
    assert r.status_code == 422 and r.json()["error"]["details"]["limit"] == "per_transaction"


def test_fraud_alert_workflow(make_user, admin):
    a, b = make_user(kyc_tier=3), make_user(kyc_tier=3)
    fund(a, "20000")
    a.post("/transfers", {"wallet_id": a.wallet()["id"], "destination_account": b.wallet()["account_number"],
                          "amount": "15000"})
    alerts = admin.get("/admin/fraud-alerts", params={"status": "open"}).json()
    assert alerts["total"] >= 1
    aid = alerts["items"][0]["id"]
    r = admin.patch(f"/admin/fraud-alerts/{aid}", {"status": "investigating", "notes": "Calling customer",
                                                   "restrict_user": True})
    assert r.status_code == 200
    r = a.post("/transfers", {"wallet_id": a.wallet()["id"], "destination_account": b.wallet()["account_number"],
                              "amount": "1"})
    assert r.status_code == 403


def test_freeze_blocks_login(make_user, admin):
    u = make_user()
    admin.post(f"/admin/users/{u.id}/restrictions", {"type": "login_block", "reason": "Account takeover suspected"})
    assert u.get("/me").status_code == 401


def test_maintenance_mode_blocks_money_movement(make_user, admin):
    u = make_user()
    admin.put("/admin/settings/maintenance_mode", {"value": {"enabled": True, "message": "Upgrading"}})
    r = u.post("/deposits", {"wallet_id": u.wallet()["id"], "amount": "5", "phone": "0241234567"})
    assert r.status_code == 503 and r.json()["error"]["message"] == "Upgrading"
    assert u.client.get("/api/v1/platform").json()["maintenance"]["enabled"] is True


def test_reconciliation_and_reports(make_user, admin, active_business):
    a = make_user()
    fund(a, "100")
    a.post("/withdrawals", {"wallet_id": a.wallet()["id"], "amount": "10", "channel": "mobile_money",
                            "phone": "0241234567"})
    r = admin.post("/admin/reconciliation/ledger")
    assert r.status_code == 200 and r.json()["status"] == "balanced"
    r = admin.post("/admin/reconciliation/providers")
    assert r.status_code == 200 and r.json()["status"] == "balanced", r.json()
    tb = admin.get("/admin/reports/trial-balance").json()
    assert tb["integrity"]["balanced"]
    rev = admin.get("/admin/reports/revenue").json()
    assert Decimal(str(rev["total_fees"])) == Decimal("0.50")
    ov = admin.get("/admin/overview").json()
    assert ov["users"] >= 2 and Decimal(ov["customer_funds"]) == Decimal("89.50")
    assert admin.get("/admin/analytics/failures").status_code == 200
    assert admin.get("/admin/analytics/merchants").status_code == 200
    assert admin.get("/admin/providers").json()["live_payments_enabled"] is False


def test_provider_reconciliation_flags_mismatch(make_user, admin, db):
    from app.services.reconciliation import run_provider_reconciliation

    a = make_user()
    t = fund(a, "100")
    run = run_provider_reconciliation(db, statement=[
        {"provider": "sandbox", "provider_reference": t["provider_reference"], "amount": "99.00",
         "status": "successful"},
        {"provider": "sandbox", "provider_reference": "UNKNOWN", "amount": "1.00", "status": "successful"}])
    kinds = {d["type"] for d in run.discrepancies}
    assert kinds == {"amount_mismatch", "missing_internal"}


def test_support_tickets(make_user, admin):
    u = make_user()
    t = u.post("/me/tickets", {"subject": "Missing deposit", "message": "I sent 50 cedis but didn't receive it"}).json()
    assert admin.get("/admin/tickets").json()["total"] == 1
    admin.post(f"/admin/tickets/{t['id']}/messages", {"body": "Internal: check MTN", "internal": True})
    admin.post(f"/admin/tickets/{t['id']}/messages", {"body": "We're looking into it"})
    mine = u.get(f"/me/tickets/{t['id']}").json()
    assert len(mine["messages"]) == 2  # internal note hidden from customer
    assert admin.patch(f"/admin/tickets/{t['id']}", {"status": "resolved", "assign_to_me": True}).json()["status"] == "resolved"


def test_investments_disabled(client):
    r = client.get("/api/v1/investments/products")
    assert r.status_code == 503 and r.json()["error"]["code"] == "feature_disabled"
