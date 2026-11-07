import io

from pypdf import PdfReader

from tests.conftest import fund


def text(content: bytes) -> str:
    return "\n".join(p.extract_text() for p in PdfReader(io.BytesIO(content)).pages)


def test_statement_pdf_matches_ledger(make_user):
    a, b = make_user(), make_user()
    fund(a, "1250.00")
    a.post("/transfers", {"wallet_id": a.wallet()["id"], "destination_account": b.wallet()["account_number"],
                          "amount": "200.50", "narration": "Rent share"})
    wid = a.wallet()["id"]
    js = a.get(f"/wallets/{wid}/statement").json()
    r = a.get(f"/wallets/{wid}/statement", params={"format": "pdf"})
    assert r.status_code == 200 and r.headers["content-type"] == "application/pdf"
    assert r.content.startswith(b"%PDF") and "attachment" in r.headers["content-disposition"]
    t = text(r.content)
    assert "Account statement" in t and a.wallet()["account_number"] in t and "Rent share" in t
    assert js["closing_balance"] == "1049.50" and "GHS 1,049.50" in t
    assert "GHS 1,250.00" in t and "GHS 200.50" in t
    assert "SANDBOX" in t  # watermark while live payments are disabled


def test_statement_pdf_ownership(make_user):
    a, b = make_user(), make_user()
    assert b.get(f"/wallets/{a.wallet()['id']}/statement", params={"format": "pdf"}).status_code == 404


def test_transaction_receipt(make_user):
    a, b = make_user(), make_user()
    fund(a, "100")
    t = a.post("/transfers", {"wallet_id": a.wallet()["id"], "destination_account": b.wallet()["account_number"],
                              "amount": "35"}).json()
    sent = text(a.get(f"/transactions/{t['reference']}/receipt.pdf").content)
    assert "Transaction receipt" in sent and t["reference"] in sent and "GHS 35.00" in sent and "Sent" in sent
    received = text(b.get(f"/transactions/{t['reference']}/receipt.pdf").content)
    assert "Received" in received
    assert make_user().get(f"/transactions/{t['reference']}/receipt.pdf").status_code == 404
    dep = text(a.get(f"/transactions/{a.get('/transactions', params={'type': 'deposit'}).json()['items'][0]['reference']}/receipt.pdf").content)
    assert "Simulated (sandbox)" in dep


def test_payment_receipts(make_user, active_business):
    owner, biz = active_business
    pr = owner.post(f"/businesses/{biz['id']}/payment-requests",
                    {"amount": "80", "customer_email": "kwame.mensah@example.com", "description": "Jollof"}).json()
    c = owner.client
    assert c.get(f"/api/v1/checkout/{pr['reference']}/receipt.pdf").status_code == 404  # not paid yet
    c.post(f"/api/v1/checkout/{pr['reference']}/mobile-money", json={"phone": "0241234567"})
    public = text(c.get(f"/api/v1/checkout/{pr['reference']}/receipt.pdf").content)
    assert "Payment receipt" in public and "Kofi's Kitchen Ltd" in public and "kw***@example.com" in public
    assert "kwame.mensah" not in public and "Fee" not in public
    merchant = text(owner.get(f"/businesses/{biz['id']}/payment-requests/{pr['reference']}/receipt.pdf").content)
    assert "kwame.mensah@example.com" in merchant and "GHS 1.20" in merchant  # fee shown to the merchant
    assert make_user().get(f"/businesses/{biz['id']}/payment-requests/{pr['reference']}/receipt.pdf").status_code == 404


def test_recipient_sees_transfer_from_sender(make_user):
    a, b = make_user(), make_user()
    fund(a, "50")
    a.post("/transfers", {"wallet_id": a.wallet()["id"], "destination_account": b.wallet()["account_number"],
                          "amount": "10", "narration": "Lunch"})
    sender_view = a.get("/transactions", params={"type": "transfer"}).json()["items"][0]
    recipient_view = b.get("/transactions").json()["items"][0]
    assert sender_view["description"] == "Lunch"
    assert recipient_view["description"].startswith("Transfer from Test User") and recipient_view["description"].endswith(": Lunch")
    st = b.get(f"/wallets/{b.wallet()['id']}/statement").json()
    assert st["lines"][0]["description"] == recipient_view["description"]


def test_customer_does_not_see_merchant_fee(make_user, active_business):
    owner, biz = active_business
    c = make_user()
    fund(c, "100")
    pr = owner.post(f"/businesses/{biz['id']}/payment-requests", {"amount": "60"}).json()
    c.post(f"/checkout/{pr['reference']}/wallet", {"wallet_id": c.wallet()["id"]})
    mine = c.get("/transactions", params={"type": "payment"}).json()["items"][0]
    assert mine["fee"] == "0.00"
    receipt = text(c.get(f"/transactions/{mine['reference']}/receipt.pdf").content)
    assert "GHS 0.00" in receipt and "GHS 0.90" not in receipt
    merchant_view = owner.get(f"/businesses/{biz['id']}/transactions", params={"type": "payment"}).json()["items"][0]
    assert merchant_view["fee"] == "0.90"
