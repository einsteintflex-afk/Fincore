import pyotp
from sqlalchemy import select

from app.core.database import SessionLocal
from app.core.security import decrypt
from app.models import User
from tests.conftest import PASSWORD, last_email, token_from

API = "/api/v1"


def register(client, email="ama@example.com", password=PASSWORD, phone="0241112233"):
    return client.post(f"{API}/auth/register", json={"email": email, "password": password, "full_name": "Ama Owusu",
                                                     "phone": phone})


def login(client, email="ama@example.com", password=PASSWORD):
    return client.post(f"{API}/auth/login", json={"email": email, "password": password})


def test_register_creates_user_and_ghs_wallet(client):
    r = register(client)
    assert r.status_code == 201, r.text
    assert r.json()["phone"] == "233241112233"
    tok = login(client).json()["access_token"]
    wallets = client.get(f"{API}/wallets", headers={"Authorization": f"Bearer {tok}"}).json()
    assert len(wallets) == 1 and wallets[0]["currency"] == "GHS" and wallets[0]["balance"] == "0.00"
    assert len(wallets[0]["account_number"]) == 10


def test_register_rejects_duplicates_and_weak_passwords(client):
    assert register(client).status_code == 201
    r = register(client)
    assert r.status_code == 409 and r.json()["error"]["code"] == "email_taken"
    r = register(client, email="x@example.com", password="alllowercase1", phone=None)
    assert r.status_code == 422
    r = register(client, email="y@example.com", phone="0111111111")
    assert r.status_code == 422


def test_login_lockout_after_failed_attempts(client):
    register(client)
    for _ in range(5):
        assert login(client, password="WrongPass123").status_code == 401
    r = login(client)
    assert r.status_code == 401 and r.json()["error"]["code"] == "account_locked"


def test_unknown_email_gives_generic_error(client):
    r = login(client, email="nobody@example.com")
    assert r.status_code == 401 and r.json()["error"]["code"] == "invalid_credentials"


def test_refresh_rotates_and_logout_revokes(client):
    register(client)
    tokens = login(client).json()
    r = client.post(f"{API}/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert r.status_code == 200
    new = r.json()
    # old refresh token no longer valid after rotation
    assert client.post(f"{API}/auth/refresh", json={"refresh_token": tokens["refresh_token"]}).status_code == 401
    h = {"Authorization": f"Bearer {new['access_token']}"}
    assert client.post(f"{API}/auth/logout", headers=h).status_code == 200
    assert client.get(f"{API}/me", headers=h).status_code == 401


def test_password_reset_flow(client):
    register(client)
    assert client.post(f"{API}/auth/password/forgot", json={"email": "ama@example.com"}).status_code == 200
    token = token_from(last_email("ama@example.com"))
    r = client.post(f"{API}/auth/password/reset", json={"token": token, "new_password": "BrandNew!Pass9"})
    assert r.status_code == 200
    assert login(client).status_code == 401
    assert login(client, password="BrandNew!Pass9").status_code == 200
    # token is single-use
    r = client.post(f"{API}/auth/password/reset", json={"token": token, "new_password": "Another!Pass9"})
    assert r.status_code == 401


def test_email_verification(client):
    register(client)
    with SessionLocal() as s:
        body = s.scalar(select(User)).email
    token = token_from(last_email(body))
    assert client.post(f"{API}/auth/verify-email", params={"token": token}).status_code == 200
    tok = login(client).json()["access_token"]
    assert client.get(f"{API}/me", headers={"Authorization": f"Bearer {tok}"}).json()["email_verified"] is True


def test_two_factor_flow(client):
    register(client)
    h = {"Authorization": f"Bearer {login(client).json()['access_token']}"}
    setup = client.post(f"{API}/auth/2fa/setup", headers=h).json()
    totp = pyotp.TOTP(setup["secret"])
    assert client.post(f"{API}/auth/2fa/enable", json={"code": "000000"}, headers=h).status_code == 422
    assert client.post(f"{API}/auth/2fa/enable", json={"code": totp.now()}, headers=h).status_code == 200
    with SessionLocal() as s:
        u = s.scalar(select(User))
        assert decrypt(u.totp_secret_enc) == setup["secret"]  # stored encrypted, not plaintext
        assert u.totp_secret_enc != setup["secret"]
    r = login(client).json()
    assert r["requires_2fa"] is True and r["access_token"] is None
    bad = client.post(f"{API}/auth/login/2fa", json={"challenge_token": r["challenge_token"], "code": "123456"})
    assert bad.status_code == 401
    ok = client.post(f"{API}/auth/login/2fa", json={"challenge_token": r["challenge_token"], "code": totp.now()})
    assert ok.status_code == 200 and ok.json()["access_token"]


def test_sessions_list_and_revoke_others(client):
    register(client)
    t1 = login(client).json()
    login(client)
    h = {"Authorization": f"Bearer {t1['access_token']}"}
    assert len(client.get(f"{API}/auth/sessions", headers=h).json()) == 2
    client.post(f"{API}/auth/sessions/revoke-others", headers=h)
    assert len(client.get(f"{API}/auth/sessions", headers=h).json()) == 1


def test_protected_routes_require_auth(client):
    assert client.get(f"{API}/me").status_code == 401
    assert client.get(f"{API}/me", headers={"Authorization": "Bearer garbage"}).status_code == 401


def test_customer_cannot_access_admin(make_user):
    u = make_user()
    assert u.get("/admin/overview").status_code == 403
