from decimal import Decimal

from tests.conftest import fund
from tests.test_wallets import integrity_ok


def biz_balance(owner, biz_id) -> Decimal:
    return Decimal(owner.get(f"/businesses/{biz_id}/wallets").json()[0]["balance"])


def test_business_onboarding_requires_approval(make_user, admin):
    owner = make_user()
    r = owner.post("/businesses", {"name": "Ama Fabrics", "business_type": "sole_proprietorship",
                                   "email": "hi@ama.example"})
    assert r.status_code == 201
    biz = r.json()
    assert biz["status"] == "pending" and biz["my_role"] == "owner" and biz["merchant_code"].startswith("M")
    r = owner.post(f"/businesses/{biz['id']}/payment-requests", {"amount": "10"})
    assert r.status_code == 403 and r.json()["error"]["code"] == "business_not_active"
    assert admin.post(f"/admin/businesses/{biz['id']}/review", {"decision": "approve"}).json()["status"] == "active"
    assert owner.post(f"/businesses/{biz['id']}/payment-requests", {"amount": "10"}).status_code == 201


def test_pay_with_wallet_and_refund(make_user, active_business):
    owner, biz = active_business
    customer = make_user()
    fund(customer, "500")
    pr = owner.post(f"/businesses/{biz['id']}/payment-requests",
                    {"amount": "200.00", "description": "Jollof x10", "merchant_reference": "ORDER-1"}).json()
    assert Decimal(pr["fee"]) == Decimal("3.00")  # 1.5% MDR
    assert pr["checkout_url"].endswith(pr["reference"])
    page = customer.client.get(f"/api/v1/checkout/{pr['reference']}").json()
    assert page["merchant_name"] == "Kofi's Kitchen Ltd" and page["status"] == "pending"
    r = customer.post(f"/checkout/{pr['reference']}/wallet", {"wallet_id": customer.wallet()["id"]})
    assert r.status_code == 200 and r.json()["status"] == "successful", r.text
    assert Decimal(customer.balance()) == Decimal("300.00")
    assert biz_balance(owner, biz["id"]) == Decimal("197.00")
    # cannot pay twice
    assert customer.post(f"/checkout/{pr['reference']}/wallet", {"wallet_id": customer.wallet()["id"]}).status_code == 409
    # partial refund then full
    r = owner.post(f"/businesses/{biz['id']}/payment-requests/{pr['reference']}/refunds", {"amount": "50"})
    assert r.status_code == 201 and r.json()["status"] == "successful"
    assert Decimal(customer.balance()) == Decimal("350.00")
    r = owner.post(f"/businesses/{biz['id']}/payment-requests/{pr['reference']}/refunds", {"amount": "151"})
    assert r.status_code == 422
    # remaining 150 exceeds the merchant's 147 balance (merchant bears the 3.00 MDR)
    r = owner.post(f"/businesses/{biz['id']}/payment-requests/{pr['reference']}/refunds", {})
    assert r.status_code == 422 and r.json()["error"]["code"] == "insufficient_funds"
    r = owner.post(f"/businesses/{biz['id']}/payment-requests/{pr['reference']}/refunds", {"amount": "147"})
    assert r.status_code == 201
    got = owner.get(f"/businesses/{biz['id']}/payment-requests/{pr['reference']}").json()
    assert got["status"] == "partially_refunded" and Decimal(got["amount_refunded"]) == Decimal("197.00")
    assert biz_balance(owner, biz["id"]) == 0
    integrity_ok()


def test_refund_cannot_exceed_merchant_balance(make_user, active_business):
    owner, biz = active_business
    customer = make_user()
    fund(customer, "100")
    pr = owner.post(f"/businesses/{biz['id']}/payment-requests", {"amount": "100"}).json()
    customer.post(f"/checkout/{pr['reference']}/wallet", {"wallet_id": customer.wallet()["id"]})
    # merchant holds 98.50 (fee 1.50) — a full 100 refund must fail rather than overdraw
    r = owner.post(f"/businesses/{biz['id']}/payment-requests/{pr['reference']}/refunds", {})
    assert r.status_code == 422 and r.json()["error"]["code"] == "insufficient_funds"
    integrity_ok()


def test_pay_with_mobile_money_and_momo_refund(make_user, active_business):
    owner, biz = active_business
    pr = owner.post(f"/businesses/{biz['id']}/payment-requests", {"amount": "80.00"}).json()
    r = owner.client.post(f"/api/v1/checkout/{pr['reference']}/mobile-money", json={"phone": "0541234567"})
    assert r.status_code == 200 and r.json()["status"] == "successful", r.text
    assert biz_balance(owner, biz["id"]) == Decimal("78.80")
    r = owner.post(f"/businesses/{biz['id']}/payment-requests/{pr['reference']}/refunds", {"amount": "20"})
    assert r.status_code == 201 and r.json()["status"] == "successful", r.text
    assert biz_balance(owner, biz["id"]) == Decimal("58.80")
    integrity_ok()


def test_failed_then_retried_momo_payment(make_user, active_business):
    owner, biz = active_business
    pr = owner.post(f"/businesses/{biz['id']}/payment-requests", {"amount": "30"}).json()
    r = owner.client.post(f"/api/v1/checkout/{pr['reference']}/mobile-money", json={"phone": "0240000000"})
    assert r.json()["status"] == "failed"
    r = owner.client.post(f"/api/v1/checkout/{pr['reference']}/mobile-money", json={"phone": "0241234567"})
    assert r.json()["status"] == "successful"
    assert biz_balance(owner, biz["id"]) == Decimal("29.55")
    integrity_ok()


def test_settlement_to_bank(make_user, active_business):
    owner, biz = active_business
    pr = owner.post(f"/businesses/{biz['id']}/payment-requests", {"amount": "1000"}).json()
    owner.client.post(f"/api/v1/checkout/{pr['reference']}/mobile-money", json={"phone": "0241234567"})
    r = owner.post(f"/businesses/{biz['id']}/settlements", {})
    assert r.status_code == 422  # no destination yet
    r = owner.put(f"/businesses/{biz['id']}/settlement-destination",
                  {"channel": "bank", "bank_code": "ECO", "account_number": "0012345678", "account_name": "Kofi K"})
    assert r.status_code == 200
    r = owner.post(f"/businesses/{biz['id']}/settlements", {})
    assert r.status_code == 201 and r.json()["status"] == "paid", r.text
    assert Decimal(r.json()["amount"]) == Decimal("985.00")
    assert biz_balance(owner, biz["id"]) == 0
    report = owner.get(f"/businesses/{biz['id']}/reports/settlement").json()
    assert Decimal(report["gross_volume"]) == Decimal("1000") and Decimal(report["settled"]) == Decimal("985.00")
    integrity_ok()


def test_payment_link_flow(make_user, active_business):
    owner, biz = active_business
    r = owner.post(f"/businesses/{biz['id']}/payment-links", {"title": "Donate to Kofi", "single_use": True})
    assert r.status_code == 201
    link = r.json()
    assert link["url"].endswith("/pay/donate-to-kofi")
    c = owner.client
    assert c.get(f"/api/v1/pay/{link['slug']}").json()["active"] is True
    assert c.post(f"/api/v1/pay/{link['slug']}", json={}).status_code == 422  # amount required
    pr = c.post(f"/api/v1/pay/{link['slug']}", json={"amount": "25.00", "customer_email": "d@example.com"}).json()
    r = c.post(f"/api/v1/checkout/{pr['reference']}/mobile-money", json={"phone": "0201234567"})
    assert r.json()["status"] == "successful"
    assert c.get(f"/api/v1/pay/{link['slug']}").json()["active"] is False  # single-use
    assert owner.get(f"/businesses/{biz['id']}/payment-links").json()[0]["payments_count"] == 1


def test_team_permissions(make_user, active_business):
    owner, biz = active_business
    staff = make_user()
    r = owner.post(f"/businesses/{biz['id']}/members", {"email": staff.email, "role": "viewer"})
    assert r.status_code == 201
    member_id = r.json()["id"]
    assert staff.get(f"/businesses/{biz['id']}").status_code == 200
    assert staff.post(f"/businesses/{biz['id']}/payment-requests", {"amount": "5"}).status_code == 403
    owner.patch(f"/businesses/{biz['id']}/members/{member_id}", {"role": "finance"})
    assert staff.post(f"/businesses/{biz['id']}/payment-requests", {"amount": "5"}).status_code == 201
    outsider = make_user()
    assert outsider.get(f"/businesses/{biz['id']}").status_code == 404


def test_merchant_analytics(make_user, active_business):
    owner, biz = active_business
    for amt in ("10", "20"):
        pr = owner.post(f"/businesses/{biz['id']}/payment-requests", {"amount": amt}).json()
        owner.client.post(f"/api/v1/checkout/{pr['reference']}/mobile-money", json={"phone": "0241234567"})
    owner.post(f"/businesses/{biz['id']}/payment-requests", {"amount": "99"})
    a = owner.get(f"/businesses/{biz['id']}/analytics").json()
    assert a["charges"] == 3 and a["successful"] == 2 and Decimal(a["volume"]) == Decimal("30")
