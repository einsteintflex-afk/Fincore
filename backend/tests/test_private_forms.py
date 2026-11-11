import io

from pypdf import PdfReader

from tests.conftest import PASSWORD

FIELDS = [
    {"label": "Full name", "type": "text"},
    {"label": "Programme", "type": "select", "options": ["Registered Nursing", "Midwifery"]},
    {"label": "Index number", "type": "text"},
    {"label": "Phone", "type": "phone"},
    {"label": "Notes", "type": "text", "required": False},
]


def make_link(owner, biz, **kw):
    body = {"title": "Nursing admission form", "amount": "150.00", "fields": FIELDS, **kw}
    r = owner.post(f"/businesses/{biz['id']}/payment-links", body)
    assert r.status_code == 201, r.text
    return r.json()


def test_link_questions_are_validated_and_printed_on_receipt(active_business):
    owner, biz = active_business
    link = make_link(owner, biz)
    c = owner.client
    page = c.get(f"/api/v1/pay/{link['slug']}").json()
    assert [f["key"] for f in page["fields"]] == ["full_name", "programme", "index_number", "phone", "notes"]
    bad = c.post(f"/api/v1/pay/{link['slug']}", json={"answers": {"full_name": "Abena Mensah"}})
    assert bad.status_code == 422 and bad.json()["error"]["message"] == "Please fill in: Programme"
    bad = c.post(f"/api/v1/pay/{link['slug']}", json={"answers": {"full_name": "A", "programme": "Pharmacy",
                                                                  "index_number": "1", "phone": "0241234567"}})
    assert bad.status_code == 422 and "Programme" in bad.json()["error"]["message"]
    answers = {"full_name": "Abena Mensah", "programme": "Midwifery", "index_number": "NMC/2026/0147",
               "phone": "233241234567"}
    pr = c.post(f"/api/v1/pay/{link['slug']}", json={"customer_name": "Abena Mensah", "answers": answers}).json()
    r = c.post(f"/api/v1/checkout/{pr['reference']}/mobile-money", json={"phone": "0241234567"})
    assert r.json()["status"] == "successful"
    text = "\n".join(p.extract_text() for p in PdfReader(io.BytesIO(
        c.get(f"/api/v1/checkout/{pr['reference']}/receipt.pdf").content)).pages)
    assert "NMC/2026/0147" in text and "Midwifery" in text and "Verification code" in text
    stored = owner.get(f"/businesses/{biz['id']}/payment-requests/{pr['reference']}").json()
    assert {"label": "Phone", "value": "0241234567", "type": "phone"} in stored["metadata"]["form"]


def test_receipt_verification(active_business):
    from app.services.forms import receipt_code

    owner, biz = active_business
    link = make_link(owner, biz, fields=[])
    c = owner.client
    pr = c.post(f"/api/v1/pay/{link['slug']}", json={"customer_name": "Kojo"}).json()
    code = receipt_code(pr["reference"])
    unpaid = c.get("/api/v1/verify-receipt", params={"reference": pr["reference"], "code": code}).json()
    assert unpaid["valid"] is False and "pending" in unpaid["message"]
    c.post(f"/api/v1/checkout/{pr['reference']}/mobile-money", json={"phone": "0241234567"})
    ok = c.get("/api/v1/verify-receipt", params={"reference": pr["reference"].lower(), "code": code.replace("-", "").lower()}).json()
    assert ok["valid"] is True and ok["amount"] == "150.00" and ok["payer_name"] == "Kojo"
    forged = c.get("/api/v1/verify-receipt", params={"reference": pr["reference"], "code": "AAAAA-BBBBB"}).json()
    assert forged["valid"] is False and "reference" not in forged


def test_edit_link_price_and_questions(active_business):
    owner, biz = active_business
    link = make_link(owner, biz)
    r = owner.patch(f"/businesses/{biz['id']}/payment-links/{link['id']}",
                    {"amount": "175.00", "fields": [{"label": "Student ID", "type": "text"}]})
    assert r.status_code == 200 and r.json()["amount"] == "175.00"
    assert [f["key"] for f in r.json()["fields"]] == ["student_id"]
    bad = owner.patch(f"/businesses/{biz['id']}/payment-links/{link['id']}",
                      {"fields": [{"label": "Programme", "type": "select", "options": ["Only one"]}]})
    assert bad.status_code == 422


def test_private_mode_and_staff_accounts(client, admin):
    from tests.conftest import last_email, token_from

    admin.put("/admin/settings/signup_enabled", {"value": {"enabled": False}})
    assert client.get("/api/v1/platform").json()["signup_enabled"] is False
    r = client.post("/api/v1/auth/register", json={"email": "x@example.com", "password": PASSWORD, "full_name": "X Y"})
    assert r.status_code == 403
    r = admin.post("/admin/users", {"email": "efua@example.com", "full_name": "Efua Staff", "role": "finance"})
    assert r.status_code == 201 and r.json()["role"] == "finance"
    token = token_from(last_email("efua@example.com"))
    assert client.post("/api/v1/auth/password/reset", json={"token": token, "new_password": "Efua!Pass2026x"}).status_code == 200
    assert client.post("/api/v1/auth/login", json={"email": "efua@example.com", "password": "Efua!Pass2026x"}).status_code == 200


def test_only_admins_create_accounts(make_user):
    finance = make_user(role="finance")
    assert finance.post("/admin/users", {"email": "z@example.com", "full_name": "Zed Z"}).status_code == 403
