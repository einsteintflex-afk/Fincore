import hashlib
import hmac
import json
from decimal import Decimal

import httpx
import pytest

from app.core.config import settings
from app.core.errors import ProviderNotConfigured, ValidationFailed
from app.core.money import round_money, validate_amount
from app.providers.base import CollectionRequest, DisbursementRequest
from app.providers.paystack import PaystackProvider, to_minor
from app.providers.pending import AtMoneyProvider, GhipssProvider, TelecelCashProvider
from app.services.ghana import detect_network, normalize_msisdn, validate_ghana_card
from app.services.wallets import is_valid_account_number, luhn_check_digit


# ---------------------------------------------------------------- Ghana helpers
@pytest.mark.parametrize("raw,expected,network", [
    ("0241234567", "233241234567", "mtn"), ("+233 54 123 4567", "233541234567", "mtn"),
    ("233201234567", "233201234567", "telecel"), ("0501234567", "233501234567", "telecel"),
    ("0271234567", "233271234567", "at"), ("0571234567", "233571234567", "at"),
])
def test_msisdn(raw, expected, network):
    assert normalize_msisdn(raw) == expected
    assert detect_network(raw).value == network


@pytest.mark.parametrize("bad", ["12345", "0111234567", "", "02412345678"])
def test_bad_msisdn(bad):
    with pytest.raises(ValidationFailed):
        normalize_msisdn(bad)


def test_ghana_card():
    assert validate_ghana_card("gha-000000001-2") == "GHA-000000001-2"
    with pytest.raises(ValidationFailed):
        validate_ghana_card("GHA-12-3")


def test_account_number_luhn():
    body = "123456789"
    n = body + luhn_check_digit(body)
    assert is_valid_account_number(n)
    assert not is_valid_account_number(body + str((int(n[-1]) + 1) % 10))


def test_money_helpers():
    assert round_money("1.005", "GHS") == Decimal("1.01")
    assert validate_amount("10.5", "GHS") == Decimal("10.50")
    with pytest.raises(TypeError):
        round_money(1.1, "GHS")
    with pytest.raises(ValidationFailed):
        validate_amount("1.234", "GHS")
    with pytest.raises(ValidationFailed):
        validate_amount("1", "ZZZ")


# MTN MoMo adapter tests live in tests/test_mtn.py


# ---------------------------------------------------------------- Paystack
def test_paystack_charge_and_signature(monkeypatch):
    monkeypatch.setattr(settings, "paystack_secret_key", "sk_test_abc")

    def handler(request):
        body = json.loads(request.content)
        assert request.headers["Authorization"] == "Bearer sk_test_abc"
        assert body["amount"] == 1050 and body["mobile_money"] == {"phone": "0201234567", "provider": "vod"}
        return httpx.Response(200, json={"status": True, "message": "Charge attempted",
                                         "data": {"reference": "PAY-1", "status": "send_otp"}})

    p = PaystackProvider(client=httpx.Client(transport=httpx.MockTransport(handler)))
    res = p.collect(CollectionRequest(reference="PAY-1", amount=Decimal("10.50"), currency="GHS",
                                      msisdn="233201234567", network="telecel", email="a@b.c"))
    assert res.status == "pending" and res.provider_reference == "PAY-1"
    raw = json.dumps({"event": "charge.success", "data": {"reference": "PAY-1", "status": "success"}}).encode()
    sig = hmac.new(b"sk_test_abc", raw, hashlib.sha512).hexdigest()
    assert p.verify_webhook({"x-paystack-signature": sig}, raw)
    assert not p.verify_webhook({"x-paystack-signature": "bad"}, raw)
    assert p.parse_webhook(json.loads(raw)).status == "successful"
    assert to_minor(Decimal("0.01"), "GHS") == 1


# ---------------------------------------------------------------- partner-spec providers
@pytest.mark.parametrize("cls", [TelecelCashProvider, AtMoneyProvider, GhipssProvider])
def test_partner_providers_report_missing_config(cls):
    p = cls()
    assert not p.is_configured()
    with pytest.raises(ProviderNotConfigured, match="FINCORE_"):
        p.disburse(DisbursementRequest(reference="X", amount=Decimal("1"), currency="GHS", channel="mobile_money"))


def test_routing_stays_in_sandbox_when_live_disabled():
    from app.providers import route

    assert route("mobile_money", "mtn").code == "sandbox"
    assert route("bank").code == "sandbox"


def test_signed_sandbox_callback(client, make_user):
    from app.providers.sandbox import SandboxProvider
    from tests.conftest import fund  # noqa: F401

    u = make_user()
    t = u.post("/deposits", {"wallet_id": u.wallet()["id"], "amount": "15", "phone": "0241111111"}).json()
    body = SandboxProvider.event_body(t["provider_reference"], "successful", t["reference"])
    r = client.post("/api/v1/callbacks/sandbox", content=body, headers={"x-sandbox-signature": "forged"})
    assert r.status_code == 401
    r = client.post("/api/v1/callbacks/sandbox", content=body,
                    headers={"x-sandbox-signature": SandboxProvider.sign(body)})
    assert r.status_code == 200 and r.json()["status"] == "successful"
    assert Decimal(u.balance()) == Decimal("15.00")
