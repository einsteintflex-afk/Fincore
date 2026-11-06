from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import select

from app.core.database import SessionLocal
from app.models import Business, Settlement
from app.workers.runner import expire_checkouts, run_scheduled_settlements, settlement_period
from tests.test_payments import biz_balance
from tests.test_wallets import integrity_ok

MONDAY = datetime(2026, 11, 9, 2, 0, tzinfo=timezone.utc)
TUESDAY = datetime(2026, 11, 10, 2, 0, tzinfo=timezone.utc)


def _collect(owner, biz, amount="500"):
    pr = owner.post(f"/businesses/{biz['id']}/payment-requests", {"amount": amount}).json()
    owner.client.post(f"/api/v1/checkout/{pr['reference']}/mobile-money", json={"phone": "0241234567"})


def _schedule(owner, biz, schedule, destination=True):
    owner.patch(f"/businesses/{biz['id']}", {"settlement_schedule": schedule})
    if destination:
        owner.put(f"/businesses/{biz['id']}/settlement-destination",
                  {"channel": "mobile_money", "phone": "0201234567", "account_name": "Kofi"})


def test_period_keys():
    assert settlement_period("daily", TUESDAY) == "2026-11-10"
    assert settlement_period("weekly", MONDAY) == "2026-W46"
    assert settlement_period("weekly", TUESDAY) is None
    assert settlement_period("manual", MONDAY) is None


def test_daily_settlement_runs_once_per_day(active_business):
    owner, biz = active_business
    _collect(owner, biz)
    _schedule(owner, biz, "daily")
    assert run_scheduled_settlements(TUESDAY)["settled"] == 1
    assert biz_balance(owner, biz["id"]) == 0
    _collect(owner, biz, "100")
    assert run_scheduled_settlements(TUESDAY)["settled"] == 0  # same day: no second payout
    assert run_scheduled_settlements(datetime(2026, 11, 11, tzinfo=timezone.utc))["settled"] == 1
    with SessionLocal() as s:
        settlements = s.scalars(select(Settlement)).all()
        assert len(settlements) == 2 and all(x.status == "paid" for x in settlements)
        assert settlements[0].initiated_by_id is None and "Scheduled daily" in settlements[0].note
    integrity_ok()


def test_weekly_only_on_monday(active_business):
    owner, biz = active_business
    _collect(owner, biz)
    _schedule(owner, biz, "weekly")
    assert run_scheduled_settlements(TUESDAY)["settled"] == 0
    assert run_scheduled_settlements(MONDAY)["settled"] == 1


def test_skips_without_destination_or_funds(active_business):
    owner, biz = active_business
    _schedule(owner, biz, "daily", destination=False)
    _collect(owner, biz)
    assert run_scheduled_settlements(TUESDAY)["settled"] == 0
    assert biz_balance(owner, biz["id"]) == Decimal("492.50")
    owner.put(f"/businesses/{biz['id']}/settlement-destination",
              {"channel": "bank", "bank_code": "GCB", "account_number": "0011223344"})
    with SessionLocal() as s:
        b = s.get(Business, biz["id"])
        b.settlement_schedule = "daily"
        s.commit()
    assert run_scheduled_settlements(TUESDAY)["settled"] == 1
    # nothing left: next day is a no-op, not a failure
    assert run_scheduled_settlements(datetime(2026, 11, 11, tzinfo=timezone.utc)) == {"settled": 0, "skipped": 1, "failed": 0}


def test_expire_checkouts(active_business, db):
    owner, biz = active_business
    pr = owner.post(f"/businesses/{biz['id']}/payment-requests", {"amount": "5"}).json()
    from app.models import PaymentRequest

    row = db.scalar(select(PaymentRequest).where(PaymentRequest.reference == pr["reference"]))
    row.expires_at = datetime(2020, 1, 1, tzinfo=timezone.utc)
    db.commit()
    assert expire_checkouts() == 1
    assert owner.get(f"/businesses/{biz['id']}/payment-requests/{pr['reference']}").json()["status"] == "expired"
