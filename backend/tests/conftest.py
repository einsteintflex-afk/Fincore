import os

os.environ.setdefault("FINCORE_ENVIRONMENT", "test")
os.environ.setdefault("FINCORE_DATABASE_URL", "postgresql+psycopg://fincore:fincore@localhost:5432/fincore_test")
os.environ.setdefault("FINCORE_LIVE_PAYMENTS_ENABLED", "false")

import re  # noqa: E402
import uuid  # noqa: E402

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import select, text  # noqa: E402

from app.core.database import SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Base, OutboundMessage, User  # noqa: E402
from app.services.seed import seed_reference_data  # noqa: E402

PASSWORD = "Sup3rSecret!pw"


@pytest.fixture(scope="session", autouse=True)
def _schema():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    yield


@pytest.fixture(autouse=True)
def _clean():
    tables = ", ".join(t.name for t in reversed(Base.metadata.sorted_tables))
    with engine.begin() as conn:
        conn.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))
    with SessionLocal() as db:
        seed_reference_data(db)
    yield


@pytest.fixture
def db():
    s = SessionLocal()
    yield s
    s.close()


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


class Actor:
    def __init__(self, client: TestClient, email: str, user_id: str, token: str):
        self.client, self.email, self.id, self.token = client, email, user_id, token

    @property
    def h(self) -> dict:
        return {"Authorization": f"Bearer {self.token}"}

    def get(self, url, **kw):
        return self.client.get(f"/api/v1{url}", headers={**self.h, **kw.pop("headers", {})}, **kw)

    def post(self, url, json=None, **kw):
        return self.client.post(f"/api/v1{url}", json=json, headers={**self.h, **kw.pop("headers", {})}, **kw)

    def put(self, url, json=None, **kw):
        return self.client.put(f"/api/v1{url}", json=json, headers=self.h, **kw)

    def patch(self, url, json=None, **kw):
        return self.client.patch(f"/api/v1{url}", json=json, headers=self.h, **kw)

    def delete(self, url, **kw):
        return self.client.delete(f"/api/v1{url}", headers=self.h, **kw)

    def wallet(self) -> dict:
        return self.get("/wallets").json()[0]

    def balance(self) -> str:
        return self.wallet()["balance"]


@pytest.fixture
def make_user(client, db):
    counter = {"n": 0}

    def _make(role: str = "customer", kyc_tier: int = 1, email: str | None = None, phone: str | None = None) -> Actor:
        counter["n"] += 1
        email = email or f"user{counter['n']}-{uuid.uuid4().hex[:6]}@example.com"
        r = client.post("/api/v1/auth/register", json={"email": email, "password": PASSWORD,
                                                       "full_name": f"Test User {counter['n']}", "phone": phone})
        assert r.status_code == 201, r.text
        with SessionLocal() as s:
            u = s.scalar(select(User).where(User.email == email))
            u.role, u.kyc_tier = role, kyc_tier
            s.commit()
        r = client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
        assert r.status_code == 200, r.text
        return Actor(client, email, str(u.id), r.json()["access_token"])

    return _make


def fund(actor: Actor, amount: str = "1000.00", phone: str = "0241234567") -> dict:
    w = actor.wallet()
    r = actor.post("/deposits", {"wallet_id": w["id"], "amount": amount, "phone": phone})
    assert r.status_code == 201, r.text
    assert r.json()["status"] == "successful", r.json()
    return r.json()


def last_email(to: str) -> str:
    with SessionLocal() as s:
        m = s.scalar(select(OutboundMessage).where(OutboundMessage.recipient == to)
                     .order_by(OutboundMessage.created_at.desc()))
        return m.body


def token_from(body: str) -> str:
    return re.search(r"token=([\w\-\.]+)", body).group(1)


@pytest.fixture
def admin(make_user):
    return make_user(role="super_admin")


@pytest.fixture
def active_business(make_user, admin):
    """A merchant owner with an approved business."""
    owner = make_user(kyc_tier=2)
    r = owner.post("/businesses", {"name": "Kofi's Kitchen Ltd", "business_type": "limited_company",
                                   "email": "pay@kofis.example", "phone": "0201234567"})
    assert r.status_code == 201, r.text
    biz = r.json()
    r = admin.post(f"/admin/businesses/{biz['id']}/review", {"decision": "approve"})
    assert r.status_code == 200, r.text
    return owner, r.json()
