from datetime import timedelta

from sqlalchemy import select, update

from app.core.database import SessionLocal, utcnow
from app.models import FraudAlert, Transaction
from app.services import aml
from tests.conftest import fund


def rules():
    with SessionLocal() as s:
        return sorted(a.rule for a in s.scalars(select(FraudAlert).where(FraudAlert.details["source"].as_string() == "aml_scan")))


def scan():
    with SessionLocal() as s:
        return aml.run_scan(s)


def test_structuring_just_below_limit(make_user, admin):
    admin.put("/admin/limits", {"kyc_tier": 1, "transaction_type": "deposit", "per_transaction_max": "1000",
                                "daily_max": "10000", "monthly_max": "50000"})
    u = make_user(kyc_tier=1)
    for _ in range(3):
        fund(u, "950.00")
    assert scan()["structuring"] == 1
    assert scan()["structuring"] == 0  # deduplicated for the day
    assert rules() == ["structuring"]


def test_rapid_movement(make_user):
    a, b = make_user(kyc_tier=3), make_user(kyc_tier=3)
    fund(a, "6000")
    a.post("/transfers", {"wallet_id": a.wallet()["id"], "destination_account": b.wallet()["account_number"],
                          "amount": "5600"})
    assert scan()["rapid_movement"] == 1


def test_fan_in(make_user):
    mule = make_user(kyc_tier=3)
    for i in range(10):
        s = make_user(kyc_tier=1)
        fund(s, "20")
        r = s.post("/transfers", {"wallet_id": s.wallet()["id"], "destination_account": mule.wallet()["account_number"],
                                  "amount": "10"})
        assert r.status_code == 201
    assert scan()["fan_in"] == 1


def test_dormant_reactivation(make_user):
    u = make_user(kyc_tier=3)
    fund(u, "50")
    with SessionLocal() as s:
        s.execute(update(Transaction).values(created_at=utcnow() - timedelta(days=120)))
        s.commit()
    fund(u, "3000")
    r = u.post("/withdrawals", {"wallet_id": u.wallet()["id"], "amount": "2500", "channel": "mobile_money",
                                "phone": "0241234567"})
    assert r.json()["status"] == "successful"
    assert scan()["dormant_reactivation"] == 1


def test_normal_activity_raises_nothing(make_user):
    a, b = make_user(), make_user()
    fund(a, "300")
    a.post("/transfers", {"wallet_id": a.wallet()["id"], "destination_account": b.wallet()["account_number"],
                          "amount": "50"})
    assert sum(scan().values()) == 0


def test_admin_scan_and_csv_export(make_user, admin):
    a, b = make_user(kyc_tier=3), make_user(kyc_tier=3)
    fund(a, "6000")
    a.post("/transfers", {"wallet_id": a.wallet()["id"], "destination_account": b.wallet()["account_number"],
                          "amount": "5600"})
    r = admin.post("/admin/aml/scan")
    assert r.status_code == 200 and r.json()["alerts_raised"]["rapid_movement"] == 1
    csv = admin.get("/admin/fraud-alerts/export")
    assert csv.status_code == 200 and "rapid_movement" in csv.text and a.email in csv.text
    assert make_user(role="support").get("/admin/fraud-alerts/export").status_code == 403
