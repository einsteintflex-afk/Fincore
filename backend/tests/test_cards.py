import io
from decimal import Decimal

import pytest
from pypdf import PdfReader
from sqlalchemy import text

from app.core.config import settings
from app.core.database import SessionLocal
from app.core.errors import ProviderNotConfigured
from app.providers import card_acquirer
from app.providers.cards import BankCardAcquirer, luhn_ok
from tests.test_payments import biz_balance
from tests.test_wallets import integrity_ok

API = "/api/v1"


def start(owner, biz, amount="200.00"):
    pr = owner.post(f"/businesses/{biz['id']}/payment-requests", {"amount": amount, "description": "Nursing form"}).json()
    r = owner.client.post(f"{API}/checkout/{pr['reference']}/card")
    assert r.status_code == 200, r.text
    url = r.json()["redirect_url"]
    assert "/sandbox-card/" in url
    return pr, url.split("/sandbox-card/")[1]


def submit(client, token, number, expiry="12/30", cvc="123"):
    return client.post(f"{API}/sandbox/card/{token}", json={"number": number, "expiry": expiry, "cvc": cvc})


def test_test_cards_pass_luhn():
    from app.providers.cards import TEST_CARDS

    assert all(luhn_ok(n) for n in TEST_CARDS)


def test_successful_card_payment_posts_ledger_and_keeps_only_last4(active_business):
    owner, biz = active_business
    c = owner.client
    pr, token = start(owner, biz)
    page = c.get(f"{API}/sandbox/card/{token}").json()
    assert page["amount"] == "200.00" and page["merchant_name"] == "Kofi's Kitchen Ltd"
    r = submit(c, token, "4111 1111 1111 1111")
    assert r.json()["status"] == "successful" and r.json()["return_url"].endswith("?card_return=1")
    view = c.post(f"{API}/checkout/{pr['reference']}/card/complete").json()
    assert view["status"] == "successful" and view["card"] == "VISA •••• 1111"
    assert biz_balance(owner, biz["id"]) == Decimal("195.00")  # 2.5% card MDR
    # paying again or replaying the page can't double-post
    assert submit(c, token, "4111111111111111").json()["status"] == "successful"
    assert biz_balance(owner, biz["id"]) == Decimal("195.00")
    with SessionLocal() as s:
        dump = " ".join(str(r) for r in s.execute(text(
            "select metadata::text from payment_requests union all select counterparty::text from transactions "
            "union all select raw::text from provider_transactions")).scalars())
    assert "4111111111111111" not in dump and "1111" in dump
    receipt = "\n".join(p.extract_text() for p in PdfReader(io.BytesIO(
        c.get(f"{API}/checkout/{pr['reference']}/receipt.pdf").content)).pages)
    assert "VISA **** 1111" in receipt  # PDFs use * (standard fonts lack the bullet glyph)
    integrity_ok()


def test_declined_then_momo_retry(active_business):
    owner, biz = active_business
    c = owner.client
    pr, token = start(owner, biz, "50")
    assert submit(c, token, "4000000000000002").json()["status"] == "failed"
    assert c.get(f"{API}/checkout/{pr['reference']}").json()["failure_reason"] == "Card declined by issuer"
    r = c.post(f"{API}/checkout/{pr['reference']}/mobile-money", json={"phone": "0241234567"})
    assert r.json()["status"] == "successful"
    assert biz_balance(owner, biz["id"]) == Decimal("49.25")  # momo MDR 1.5%, not the card rate
    integrity_ok()


@pytest.mark.parametrize("approve,expected", [(True, "successful"), (False, "failed")])
def test_3ds(active_business, approve, expected):
    owner, biz = active_business
    c = owner.client
    pr, token = start(owner, biz, "80")
    assert submit(c, token, "4000000000003220").json()["status"] == "requires_3ds"
    assert c.get(f"{API}/sandbox/card/{token}").json()["awaiting_3ds"] is True
    assert c.post(f"{API}/sandbox/card/{token}/3ds", json={"approve": approve}).json()["status"] == expected
    assert c.get(f"{API}/checkout/{pr['reference']}").json()["status"] == expected


def test_card_input_validation_and_tokens(active_business):
    owner, biz = active_business
    c = owner.client
    pr, token = start(owner, biz)
    assert submit(c, token, "4111111111111112").status_code == 422  # bad Luhn
    assert submit(c, token, "4111111111111111", expiry="01/20").status_code == 422
    assert submit(c, token, "4111111111111111", cvc="12").status_code == 422
    assert submit(c, token, "4242424242424242").json()["status"] == "failed"  # valid but not a test card
    assert c.get(f"{API}/sandbox/card/{token}x").status_code == 401
    pr2, token2 = start(owner, biz)
    c.post(f"{API}/checkout/{pr2['reference']}/card")  # new session replaces the old one
    assert c.get(f"{API}/sandbox/card/{token2}").status_code == 403


def test_pending_return_stays_processing(active_business):
    owner, biz = active_business
    pr, _ = start(owner, biz)
    assert owner.client.post(f"{API}/checkout/{pr['reference']}/card/complete").json()["status"] == "processing"


def test_card_refund_goes_back_to_card(active_business):
    owner, biz = active_business
    c = owner.client
    pr, token = start(owner, biz, "100")
    submit(c, token, "5555555555554444")
    r = owner.post(f"/businesses/{biz['id']}/payment-requests/{pr['reference']}/refunds", {"amount": "40"})
    assert r.status_code == 201 and r.json()["status"] == "successful", r.text
    assert biz_balance(owner, biz["id"]) == Decimal("57.50")  # 100 - 2.50 MDR - 40 refund
    txns = owner.get(f"/businesses/{biz['id']}/transactions", params={"type": "refund"}).json()["items"]
    assert txns[0]["counterparty"]["card"] == "MASTERCARD •••• 4444"
    integrity_ok()


def test_api_sandbox_charge_by_card_never_touches_ledger(active_business):
    owner, biz = active_business
    app = owner.post("/developer/apps", {"business_id": biz["id"], "name": "Site"}).json()
    key = owner.post(f"/developer/apps/{app['id']}/keys", {"environment": "sandbox"}).json()["secret_key"]
    ch = owner.client.post(f"{API}/gateway/charges", json={"amount": "30"}, headers={"Authorization": f"Bearer {key}"}).json()
    token = owner.client.post(f"{API}/checkout/{ch['reference']}/card").json()["redirect_url"].split("/sandbox-card/")[1]
    assert submit(owner.client, token, "4111111111111111").json()["status"] == "successful"
    assert biz_balance(owner, biz["id"]) == 0


def test_bank_acquirer_reports_missing_configuration(monkeypatch):
    monkeypatch.setattr(settings, "live_payments_enabled", True)
    acq = card_acquirer()
    assert isinstance(acq, BankCardAcquirer) and not acq.is_configured()
    with pytest.raises(ProviderNotConfigured, match="FINCORE_CARD_ACQUIRER_MERCHANT_ID"):
        acq.create_session(reference="X", amount=Decimal("1"), currency="GHS", description="", return_url="",
                           customer_email=None)
    assert card_acquirer(sandbox=True).code == "sandbox_card"


def test_abandoned_card_then_momo(active_business):
    owner, biz = active_business
    c = owner.client
    pr, _ = start(owner, biz, "60")
    r = c.post(f"{API}/checkout/{pr['reference']}/mobile-money", json={"phone": "0241234567"})
    assert r.status_code == 200 and r.json()["status"] == "successful", r.text
    assert biz_balance(owner, biz["id"]) == Decimal("59.10")
    integrity_ok()


def test_worker_expires_stale_card_sessions(active_business):
    from datetime import timedelta

    from sqlalchemy import update

    from app.core.database import utcnow
    from app.models import PaymentRequest, Transaction
    from app.workers.runner import expire_card_sessions

    owner, biz = active_business
    pr, _ = start(owner, biz)
    with SessionLocal() as s:
        s.execute(update(PaymentRequest).values(updated_at=utcnow() - timedelta(hours=1)))
        s.commit()
    assert expire_card_sessions() == 1
    got = owner.client.get(f"{API}/checkout/{pr['reference']}").json()
    assert got["status"] == "failed" and "not completed" in got["failure_reason"]
    with SessionLocal() as s:
        assert {t.status for t in s.query(Transaction).filter(Transaction.provider == "sandbox_card")} == {"failed"}
