import io
from decimal import Decimal

from pypdf import PdfReader

from tests.test_payments import biz_balance
from tests.test_wallets import integrity_ok

API = "/api/v1"
OWNER_NUMBER = "0551234567"  # dummy; real numbers live only in the business settings


def enable(owner, biz):
    r = owner.put(f"/businesses/{biz['id']}/direct-momo", {"enabled": True, "phone": OWNER_NUMBER,
                                                          "account_name": "Kofi K. Mensah"})
    assert r.status_code == 200, r.text
    return r.json()


def new_payment(owner, biz, amount="150.00"):
    return owner.post(f"/businesses/{biz['id']}/payment-requests", {"amount": amount, "description": "Admission form"}).json()


def claim(c, ref, txid="MP261118.1234.A56789", phone="0241234567"):
    return c.post(f"{API}/checkout/{ref}/direct-momo", json={"transaction_id": txid, "sender_phone": phone,
                                                             "sender_name": "Abena Mensah"})


def test_disabled_by_default(active_business):
    owner, biz = active_business
    pr = new_payment(owner, biz)
    assert owner.client.get(f"{API}/checkout/{pr['reference']}").json()["direct_momo"] is None
    assert claim(owner.client, pr["reference"]).status_code == 403


def test_full_flow_confirm(active_business):
    owner, biz = active_business
    b = enable(owner, biz)
    assert b["direct_momo"]["msisdn"] == "233551234567"
    c = owner.client
    pr = new_payment(owner, biz)
    view = c.get(f"{API}/checkout/{pr['reference']}").json()
    assert view["direct_momo"]["number"] == OWNER_NUMBER and view["direct_momo"]["account_name"] == "Kofi K. Mensah"
    assert len(view["direct_momo"]["short_code"]) == 6
    r = claim(c, pr["reference"], txid="mp261118.1234.a56789")
    assert r.status_code == 200 and r.json()["status"] == "awaiting_confirmation"
    assert claim(c, pr["reference"]).status_code == 409  # can't claim twice
    todo = owner.get(f"/businesses/{biz['id']}/payment-requests", params={"status": "awaiting_confirmation"}).json()
    assert todo["total"] == 1 and todo["items"][0]["metadata"]["direct_momo"]["transaction_id"] == "MP261118.1234.A56789"
    n = owner.get("/me/notifications").json()["items"]
    assert any(x["type"] == "payment_to_confirm" for x in n)
    r = owner.post(f"/businesses/{biz['id']}/payment-requests/{pr['reference']}/direct-momo/review", {"decision": "confirm"})
    assert r.status_code == 200 and r.json()["status"] == "successful" and r.json()["fee"] == "0.00"
    # money went straight to the owner's MoMo: FinCore's books don't pretend to hold it
    assert biz_balance(owner, biz["id"]) == Decimal("0")
    receipt = "\n".join(p.extract_text() for p in PdfReader(io.BytesIO(
        c.get(f"{API}/checkout/{pr['reference']}/receipt.pdf").content)).pages)
    assert "MP261118.1234.A56789" in receipt and "Verification code" in receipt
    from app.services.forms import receipt_code

    v = c.get(f"{API}/verify-receipt", params={"reference": pr["reference"], "code": receipt_code(pr["reference"])}).json()
    assert v["valid"] is True
    integrity_ok()


def test_duplicate_transaction_id_rejected(active_business):
    owner, biz = active_business
    enable(owner, biz)
    a, b = new_payment(owner, biz), new_payment(owner, biz)
    assert claim(owner.client, a["reference"], txid="ABC12345").status_code == 200
    r = claim(owner.client, b["reference"], txid="abc 12345")
    assert r.status_code == 409 and r.json()["error"]["code"] == "duplicate_txid"


def test_reject_lets_payer_retry_and_frees_the_id(active_business):
    owner, biz = active_business
    enable(owner, biz)
    pr = new_payment(owner, biz)
    claim(owner.client, pr["reference"], txid="WRONG1234")
    r = owner.post(f"/businesses/{biz['id']}/payment-requests/{pr['reference']}/direct-momo/review",
                   {"decision": "reject", "note": "No such transaction on my statement"})
    assert r.json()["status"] == "failed"
    view = owner.client.get(f"{API}/checkout/{pr['reference']}").json()
    assert view["failure_reason"] == "No such transaction on my statement"
    assert claim(owner.client, pr["reference"], txid="RIGHT5678").json()["status"] == "awaiting_confirmation"


def test_only_permitted_staff_confirm(make_user, active_business):
    owner, biz = active_business
    enable(owner, biz)
    pr = new_payment(owner, biz)
    claim(owner.client, pr["reference"])
    viewer = make_user()
    owner.post(f"/businesses/{biz['id']}/members", {"email": viewer.email, "role": "viewer"})
    r = viewer.post(f"/businesses/{biz['id']}/payment-requests/{pr['reference']}/direct-momo/review", {"decision": "confirm"})
    assert r.status_code == 403


def test_refund_is_recorded_not_paid_out(active_business):
    owner, biz = active_business
    enable(owner, biz)
    pr = new_payment(owner, biz, "100")
    claim(owner.client, pr["reference"])
    owner.post(f"/businesses/{biz['id']}/payment-requests/{pr['reference']}/direct-momo/review", {"decision": "confirm"})
    r = owner.post(f"/businesses/{biz['id']}/payment-requests/{pr['reference']}/refunds", {"amount": "30", "reason": "Overpaid"})
    assert r.status_code == 201 and r.json()["status"] == "successful" and "directly from the merchant" in r.json()["reason"]
    assert biz_balance(owner, biz["id"]) == Decimal("0")
    integrity_ok()


def test_settings_validation(active_business):
    owner, biz = active_business
    assert owner.put(f"/businesses/{biz['id']}/direct-momo", {"enabled": True, "phone": "123"}).status_code == 422
    assert owner.put(f"/businesses/{biz['id']}/direct-momo", {"enabled": True, "phone": OWNER_NUMBER}).status_code == 422
    enable(owner, biz)
    r = owner.put(f"/businesses/{biz['id']}/direct-momo", {"enabled": False})
    assert r.json()["direct_momo"]["enabled"] is False


def test_test_mode_offers_only_the_real_method(active_business, make_user):
    owner, biz = active_business
    enable(owner, biz)
    c = owner.client
    pr = new_payment(owner, biz)
    assert c.get(f"{API}/checkout/{pr['reference']}").json()["direct_only"] is True
    r = c.post(f"{API}/checkout/{pr['reference']}/mobile-money", json={"phone": "0241234567"})
    assert r.status_code == 403 and r.json()["error"]["code"] == "direct_momo_only"
    assert c.post(f"{API}/checkout/{pr['reference']}/card").status_code == 403
    payer = make_user()
    assert payer.post(f"/checkout/{pr['reference']}/wallet", {"wallet_id": payer.wallet()["id"]}).status_code == 403


def test_sandbox_api_charges_never_offer_direct_momo(active_business):
    owner, biz = active_business
    enable(owner, biz)
    app = owner.post("/developer/apps", {"business_id": biz["id"], "name": "Site"}).json()
    key = owner.post(f"/developer/apps/{app['id']}/keys", {"environment": "sandbox"}).json()["secret_key"]
    ch = owner.client.post(f"{API}/gateway/charges", json={"amount": "10"}, headers={"Authorization": f"Bearer {key}"}).json()
    view = owner.client.get(f"{API}/checkout/{ch['reference']}").json()
    assert view["direct_momo"] is None and view["direct_only"] is False
    assert claim(owner.client, ch["reference"]).status_code == 403
