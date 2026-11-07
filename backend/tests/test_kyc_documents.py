from sqlalchemy import select

from app.core.config import settings
from app.core.database import SessionLocal
from app.models import AuditLog
from tests.conftest import JPEG, PDF, PNG, kyc_docs, upload_doc

BASE = {"id_type": "ghana_card", "id_number": "GHA-123456789-0", "first_name": "Ama", "last_name": "Owusu",
        "date_of_birth": "1992-03-06"}


def test_upload_validates_by_content_not_name(make_user):
    u = make_user(kyc_tier=0)
    assert upload_doc(u, "id_front", JPEG).json()["content_type"] == "image/jpeg"
    assert upload_doc(u, "selfie", PNG, "selfie.exe").json()["content_type"] == "image/png"
    assert upload_doc(u, "proof_of_address", PDF, "bill.pdf").json()["content_type"] == "application/pdf"
    r = upload_doc(u, "id_front", b"MZ\x90\x00 not an image", "passport.jpg")  # executable renamed to .jpg
    assert r.status_code == 422 and "JPEG, PNG or PDF" in r.json()["error"]["message"]
    assert upload_doc(u, "passport_scan", JPEG).status_code == 422
    assert upload_doc(u, "selfie", b"").status_code == 422
    too_big = JPEG + b"0" * settings.kyc_max_upload_bytes
    assert upload_doc(u, "selfie", too_big).status_code == 422
    assert len(u.get("/me/kyc/documents").json()) == 3


def test_tier_two_requires_id_and_selfie(make_user):
    u = make_user(kyc_tier=0)
    only_id = kyc_docs(u, ["id_front"])
    r = u.post("/me/kyc", {**BASE, "tier_requested": 2, "document_ids": only_id})
    assert r.status_code == 422 and r.json()["error"]["details"]["missing_documents"] == ["selfie"]
    r = u.post("/me/kyc", {**BASE, "tier_requested": 2, "document_ids": only_id + kyc_docs(u, ["selfie"])})
    assert r.status_code == 201
    assert set(r.json()["documents"]) == {"id_front", "selfie"}


def test_tier_one_needs_no_documents(make_user):
    u = make_user(kyc_tier=0)
    r = u.post("/me/kyc", {**BASE, "id_type": "voter_id", "id_number": "1234567890", "tier_requested": 1})
    assert r.status_code == 201


def test_cannot_use_someone_elses_document_or_reuse_one(make_user):
    a, b = make_user(kyc_tier=0), make_user(kyc_tier=0)
    a_docs = kyc_docs(a)
    r = b.post("/me/kyc", {**BASE, "tier_requested": 2, "document_ids": a_docs})
    assert r.status_code == 422 and r.json()["error"]["message"] == "Unknown document"
    assert a.post("/me/kyc", {**BASE, "tier_requested": 2, "document_ids": a_docs}).status_code == 201
    assert b.get("/me/kyc/documents").json() == []


def test_staff_view_through_signed_links(make_user, admin):
    u = make_user(kyc_tier=0)
    sub = u.post("/me/kyc", {**BASE, "tier_requested": 2, "document_ids": kyc_docs(u)}).json()
    assert u.get(f"/admin/kyc/{sub['id']}/documents").status_code == 403  # customers can't use the staff route
    assert make_user(role="support").get(f"/admin/kyc/{sub['id']}/documents").status_code == 403
    docs = admin.get(f"/admin/kyc/{sub['id']}/documents").json()
    assert {d["kind"] for d in docs} == {"id_front", "selfie"}
    file = u.client.get(docs[0]["url"])  # signed link works without a login...
    assert file.status_code == 200 and file.content == JPEG and file.headers["content-type"] == "image/jpeg"
    assert "no-store" in file.headers["cache-control"]
    assert u.client.get(docs[0]["url"] + "x").status_code == 401  # ...but not if tampered with
    with SessionLocal() as s:
        assert s.scalar(select(AuditLog).where(AuditLog.action == "kyc.documents_viewed")) is not None


def test_signed_links_expire(make_user, admin, monkeypatch):
    u = make_user(kyc_tier=0)
    sub = u.post("/me/kyc", {**BASE, "tier_requested": 2, "document_ids": kyc_docs(u)}).json()
    monkeypatch.setattr(settings, "storage_signed_url_ttl_seconds", -1)
    url = admin.get(f"/admin/kyc/{sub['id']}/documents").json()[0]["url"]
    r = u.client.get(url)
    assert r.status_code == 401 and r.json()["error"]["code"] == "link_expired"
