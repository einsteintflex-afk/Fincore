"""The five-section dashboard: Overview, Applications, Transactions, Payments, Settings.

Transactions reuse ``/admin/transactions`` (with ``app_id`` filter); Settings reuse ``/admin/team``,
``/admin/subscribers``, ``/admin/audit-logs`` and the endpoints below. This module adds what the console
needs on top: the overview, application management for the owner, payment-provider status and the
withdrawal fee.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import case, func, select, text
from sqlalchemy.orm import Session

from app.api.deps import require_roles, staff_user
from app.core.config import settings
from app.core.database import get_db
from app.core.errors import NotFound, ValidationFailed
from app.core.money import to_api_str
from app.models.business import Business, PaymentRequest
from app.models.developer import ApiKey, AppSubscriber, DeveloperApp, WebhookEndpoint
from app.models.enums import AccountType, AppPermission, BusinessStatus, TxnStatus, TxnType, UserRole
from app.models.ledger import LedgerAccount, Wallet
from app.models.transaction import Transaction
from app.models.user import User
from app.providers import provider_status
from app.schemas.common import ApiKeyOut, TransactionOut, WebhookIn, WebhookOut
from app.services import backups, team, withdrawal_fee
from app.services import developer as dsvc
from app.services.audit import audit
from app.services.business import create_business
from app.services.wallets import create_wallet

router = APIRouter(prefix="/console", tags=["Dashboard (five sections)"])
manager = require_roles(UserRole.ADMIN)
finance = require_roles(UserRole.FINANCE, UserRole.ADMIN)

COLLECTION_TYPES = (TxnType.DEPOSIT, TxnType.PAYMENT)
DISBURSEMENT_TYPES = (TxnType.WITHDRAWAL, TxnType.SETTLEMENT, TxnType.REFUND)


def _d(v) -> str:
    return to_api_str(Decimal(v or 0))


# ================================================================ A. Overview
@router.get("/overview")
def overview(staff: User = Depends(staff_user), db: Session = Depends(get_db)):
    ok = TxnStatus.SUCCESSFUL
    payout_value = func.coalesce(Transaction.net_amount, Transaction.amount)
    row = db.execute(select(
        func.count().label("total"),
        func.sum(case((Transaction.status == ok, 1), else_=0)).label("successful"),
        func.sum(case((Transaction.status.in_([TxnStatus.PENDING, TxnStatus.PROCESSING]), 1), else_=0)).label("pending"),
        func.sum(case((Transaction.status == TxnStatus.FAILED, 1), else_=0)).label("failed"),
        func.sum(case(((Transaction.status == ok) & Transaction.type.in_(COLLECTION_TYPES), Transaction.amount),
                      else_=0)).label("collections"),
        func.sum(case(((Transaction.status == ok) & Transaction.type.in_(DISBURSEMENT_TYPES), payout_value),
                      else_=0)).label("disbursements"),
        func.sum(case(((Transaction.status == ok) & (Transaction.type == TxnType.WITHDRAWAL)
                       & Transaction.net_amount.is_not(None), Transaction.fee), else_=0)).label("withdrawal_fees"),
    )).one()
    balances = db.execute(
        select(LedgerAccount.currency, func.sum(LedgerAccount.balance))
        .join(Wallet, Wallet.ledger_account_id == LedgerAccount.id).group_by(LedgerAccount.currency)).all()
    pending_payouts = db.scalar(select(func.coalesce(func.sum(LedgerAccount.balance), 0)).where(
        LedgerAccount.code.like("SYS:%:PENDING_PAYOUTS")))
    fee_revenue = db.execute(select(LedgerAccount.code, LedgerAccount.balance).where(
        LedgerAccount.type == AccountType.REVENUE, LedgerAccount.is_system.is_(True))).all()
    recent = db.scalars(select(Transaction).order_by(Transaction.created_at.desc()).limit(10)).all()
    try:
        db.execute(text("SELECT 1"))
        database_ok = True
    except Exception:  # noqa: BLE001
        database_ok = False
    mtn = {p["code"]: p for p in provider_status() if p["code"].startswith("mtn_momo")}
    active_mtn = {"sandbox": "mtn_momo_sandbox", "production": "mtn_momo"}.get(settings.mtn_momo_mode)
    return {
        "totals": {"collections": _d(row.collections), "disbursements": _d(row.disbursements),
                   "withdrawal_fees": _d(row.withdrawal_fees), "transactions": row.total or 0,
                   "successful": int(row.successful or 0), "pending": int(row.pending or 0),
                   "failed": int(row.failed or 0)},
        "balances": [{"currency": c, "available": _d(b)} for c, b in balances],
        "pending_payouts": _d(pending_payouts),
        "revenue": [{"account": code, "balance": _d(b)} for code, b in fee_revenue],
        "recent": [TransactionOut.model_validate(t).model_dump(mode="json") for t in recent],
        "system": {
            "database": "ok" if database_ok else "down",
            "environment": settings.environment,
            "live_payments_enabled": settings.live_payments_enabled,
            "mtn_mode": settings.mtn_momo_mode,
            "mtn_collections": (mtn.get(active_mtn, {}).get("products") or {}).get("collection", False)
            if active_mtn else False,
            "mtn_disbursements": (mtn.get(active_mtn, {}).get("products") or {}).get("disbursement", False)
            if active_mtn else False,
            "withdrawal_fee_percent": format(withdrawal_fee.current_percent(db).normalize(), "f"),
            "seats": team.seat_summary(db),
            "last_backup": backups.last_backup_info(),
        },
    }


# ================================================================ B. Applications
class AppCreateIn(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    description: str | None = Field(default=None, max_length=500)
    permissions: list[str] | None = None
    require_verified_subscribers: bool = False


class AppUpdateIn(BaseModel):
    status: str | None = Field(default=None, pattern="^(active|disabled)$")
    permissions: list[str] | None = None
    require_verified_subscribers: bool | None = None
    description: str | None = Field(default=None, max_length=500)


class KeyIn(BaseModel):
    environment: str = Field(pattern="^(sandbox|live)$")


def _house_business(db: Session, staff: User) -> Business:
    """The owner's own business that holds applications created from the console (created once)."""
    biz = db.scalar(select(Business).where(Business.is_house.is_(True)))
    if biz:
        return biz
    owner = db.scalar(select(User).where(User.is_primary_admin.is_(True))) or staff
    biz = create_business(db, owner, {"name": f"{settings.app_name} Applications", "business_type": "sole_proprietorship",
                                      "email": owner.email})
    biz.status = BusinessStatus.ACTIVE
    biz.is_house = True
    audit(db, "console.house_business_created", actor_id=staff.id, actor_type="staff", target_type="business",
          target_id=biz.id)
    db.commit()
    return biz


def _validate_permissions(perms: list[str]) -> list[str]:
    allowed = {p.value for p in AppPermission}
    bad = [p for p in perms if p not in allowed]
    if bad:
        raise ValidationFailed(f"Unknown permissions: {', '.join(bad)}", details={"allowed": sorted(allowed)})
    return sorted(set(perms))


def _app(db: Session, app_id: uuid.UUID) -> DeveloperApp:
    app = db.get(DeveloperApp, app_id)
    if not app or app.status == "deleted":
        raise NotFound("Application not found")
    return app


def _app_out(db: Session, app: DeveloperApp) -> dict:
    stats = db.execute(select(
        func.count(),
        func.coalesce(func.sum(case((Transaction.status == TxnStatus.SUCCESSFUL, Transaction.amount), else_=0)), 0),
    ).where(Transaction.app_id == app.id)).one()
    charges = db.execute(select(
        func.count(),
        func.coalesce(func.sum(case((PaymentRequest.status == "successful", PaymentRequest.amount), else_=0)), 0),
    ).where(PaymentRequest.app_id == app.id, PaymentRequest.environment == "live")).one()
    biz = db.get(Business, app.business_id)
    wallet = db.scalar(select(Wallet).where(Wallet.business_id == app.business_id, Wallet.is_default.is_(True)))
    bal = db.get(LedgerAccount, wallet.ledger_account_id).balance if wallet else Decimal(0)
    return {
        "id": str(app.id), "app_id": str(app.id), "name": app.name, "description": app.description,
        "status": app.status, "business_id": str(app.business_id), "business_name": biz.name if biz else None,
        "permissions": app.permissions or [], "require_verified_subscribers": app.require_verified_subscribers,
        "created_at": app.created_at, "balance": _d(bal),
        "keys": db.scalar(select(func.count()).select_from(ApiKey).where(ApiKey.app_id == app.id,
                                                                          ApiKey.status == "active")),
        "webhooks": db.scalar(select(func.count()).select_from(WebhookEndpoint).where(
            WebhookEndpoint.app_id == app.id, WebhookEndpoint.active.is_(True))),
        "subscribers": db.scalar(select(func.count()).select_from(AppSubscriber).where(AppSubscriber.app_id == app.id)),
        "payouts": {"count": stats[0], "volume": _d(stats[1])},
        "charges": {"count": charges[0], "volume": _d(charges[1])},
    }


@router.get("/applications")
def list_applications(staff: User = Depends(staff_user), db: Session = Depends(get_db)):
    apps = db.scalars(select(DeveloperApp).where(DeveloperApp.status != "deleted")
                      .order_by(DeveloperApp.created_at)).all()
    return {"items": [_app_out(db, a) for a in apps], "permissions": [p.value for p in AppPermission]}


@router.post("/applications", status_code=201)
def create_application(body: AppCreateIn, staff: User = Depends(manager), db: Session = Depends(get_db)):
    biz = _house_business(db, staff)
    if not db.scalar(select(Wallet.id).where(Wallet.business_id == biz.id)):
        create_wallet(db, business=biz, currency="GHS", label="Collections", is_default=True)
    app = dsvc.create_app(db, staff, biz, body.name, body.description)
    if body.permissions is not None:
        app.permissions = _validate_permissions(body.permissions)
    app.require_verified_subscribers = body.require_verified_subscribers
    db.commit()
    return _app_out(db, app)


@router.get("/applications/{app_id}")
def get_application(app_id: uuid.UUID, staff: User = Depends(staff_user), db: Session = Depends(get_db)):
    return _app_out(db, _app(db, app_id))


@router.patch("/applications/{app_id}")
def update_application(app_id: uuid.UUID, body: AppUpdateIn, staff: User = Depends(manager),
                       db: Session = Depends(get_db)):
    app = _app(db, app_id)
    changes = body.model_dump(exclude_none=True)
    if body.permissions is not None:
        app.permissions = _validate_permissions(body.permissions)
    if body.status:
        app.status = body.status
    if body.require_verified_subscribers is not None:
        app.require_verified_subscribers = body.require_verified_subscribers
    if body.description is not None:
        app.description = body.description
    audit(db, "console.application_updated", actor_id=staff.id, actor_type="staff", target_type="app",
          target_id=app.id, details=changes)
    db.commit()
    return _app_out(db, app)


@router.get("/applications/{app_id}/transactions")
def application_transactions(app_id: uuid.UUID, limit: int = Query(50, le=200), staff: User = Depends(staff_user),
                             db: Session = Depends(get_db)):
    app = _app(db, app_id)
    txns = db.scalars(select(Transaction).where(Transaction.app_id == app.id)
                      .order_by(Transaction.created_at.desc()).limit(limit)).all()
    charges = db.scalars(select(PaymentRequest).where(PaymentRequest.app_id == app.id)
                         .order_by(PaymentRequest.created_at.desc()).limit(limit)).all()
    return {
        "payouts": [TransactionOut.model_validate(t).model_dump(mode="json") for t in txns],
        "charges": [{"reference": p.reference, "merchant_reference": p.merchant_reference, "amount": _d(p.amount),
                     "currency": p.currency, "status": p.status, "environment": p.environment,
                     "created_at": p.created_at} for p in charges],
    }


@router.get("/applications/{app_id}/keys", response_model=list[ApiKeyOut])
def list_keys(app_id: uuid.UUID, staff: User = Depends(manager), db: Session = Depends(get_db)):
    return db.scalars(select(ApiKey).where(ApiKey.app_id == _app(db, app_id).id).order_by(ApiKey.created_at)).all()


@router.post("/applications/{app_id}/keys", response_model=ApiKeyOut, status_code=201,
             summary="Generate an API key. The secret is shown once.")
def create_key(app_id: uuid.UUID, body: KeyIn, staff: User = Depends(manager), db: Session = Depends(get_db)):
    key, secret = dsvc.create_api_key(db, staff, _app(db, app_id), body.environment)
    out = ApiKeyOut.model_validate(key)
    out.secret_key = secret
    return out


@router.post("/applications/{app_id}/keys/{key_id}/rotate", response_model=ApiKeyOut, status_code=201,
             summary="Rotate: revoke this key and issue a replacement in the same environment")
def rotate_key(app_id: uuid.UUID, key_id: uuid.UUID, staff: User = Depends(manager), db: Session = Depends(get_db)):
    app = _app(db, app_id)
    old = dsvc.revoke_api_key(db, staff, app, key_id)
    key, secret = dsvc.create_api_key(db, staff, app, old.environment)
    out = ApiKeyOut.model_validate(key)
    out.secret_key = secret
    return out


@router.post("/applications/{app_id}/keys/{key_id}/revoke", response_model=ApiKeyOut)
def revoke_key(app_id: uuid.UUID, key_id: uuid.UUID, staff: User = Depends(manager), db: Session = Depends(get_db)):
    return dsvc.revoke_api_key(db, staff, _app(db, app_id), key_id)


@router.get("/applications/{app_id}/webhooks", response_model=list[WebhookOut])
def list_webhooks(app_id: uuid.UUID, staff: User = Depends(manager), db: Session = Depends(get_db)):
    return db.scalars(select(WebhookEndpoint).where(WebhookEndpoint.app_id == _app(db, app_id).id)
                      .order_by(WebhookEndpoint.created_at)).all()


@router.post("/applications/{app_id}/webhooks", response_model=WebhookOut, status_code=201)
def create_webhook(app_id: uuid.UUID, body: WebhookIn, staff: User = Depends(manager), db: Session = Depends(get_db)):
    ep, secret = dsvc.create_endpoint(db, staff, _app(db, app_id), body.url, body.environment, body.events,
                                      body.description)
    out = WebhookOut.model_validate(ep)
    out.secret = secret
    return out


@router.delete("/applications/{app_id}/webhooks/{endpoint_id}")
def delete_webhook(app_id: uuid.UUID, endpoint_id: uuid.UUID, staff: User = Depends(manager),
                   db: Session = Depends(get_db)):
    ep = db.get(WebhookEndpoint, endpoint_id)
    if not ep or ep.app_id != _app(db, app_id).id:
        raise NotFound("Webhook endpoint not found")
    ep.active = False
    audit(db, "console.webhook_disabled", actor_id=staff.id, actor_type="staff", target_type="webhook",
          target_id=ep.id)
    db.commit()
    return {"message": "Webhook endpoint disabled"}


# ================================================================ D. Payments
@router.get("/payments")
def payments_status(staff: User = Depends(staff_user), db: Session = Depends(get_db)):
    mode = settings.mtn_momo_mode
    rows = provider_status()
    mtn = next((r for r in rows if r["code"] == {"sandbox": "mtn_momo_sandbox"}.get(mode, "mtn_momo")), {})
    products = mtn.get("products") or {}
    return {
        "mtn": {
            "mode": mode,
            "environment": {"off": "simulator (development only)", "sandbox": "MTN sandbox — test money",
                            "production": "MTN production — real money"}.get(mode, mode),
            "collections": {"configured": bool(products.get("collection")),
                            "callback_url_set": bool(settings.mtn_sandbox_callback_url if mode == "sandbox"
                                                     else settings.mtn_production_callback_url)},
            "disbursements": {"configured": bool(products.get("disbursement")),
                              "primary_key_set": bool(settings.mtn_disbursement_primary_key)},
            "callback_token_set": bool(settings.mtn_callback_token),
            "request_expiry_minutes": settings.mtn_request_expiry_minutes,
        },
        "live_payments_enabled": settings.live_payments_enabled,
        "providers": rows,
        "withdrawal_fee_percent": format(withdrawal_fee.current_percent(db).normalize(), "f"),
        "pending_by_provider": [
            {"provider": p, "type": t, "count": n}
            for p, t, n in db.execute(select(Transaction.provider, Transaction.type, func.count()).where(
                Transaction.status.in_([TxnStatus.PENDING, TxnStatus.PROCESSING]))
                .group_by(Transaction.provider, Transaction.type)).all()],
    }


# ================================================================ E. Settings: withdrawal fee, backups
class FeeIn(BaseModel):
    percent: str = Field(max_length=8)


@router.get("/settings/withdrawal-fee")
def get_withdrawal_fee(amount: str = "100", staff: User = Depends(staff_user), db: Session = Depends(get_db)):
    return {"percent": format(withdrawal_fee.current_percent(db).normalize(), "f"),
            "example": withdrawal_fee.quote(db, amount, "GHS"),
            "applies_to": ["wallet withdrawals", "application payouts"],
            "never_applies_to": ["collections", "internal transfers", "merchant settlements", "refunds",
                                 "reversals", "reconciliation adjustments"]}


@router.put("/settings/withdrawal-fee")
def put_withdrawal_fee(body: FeeIn, staff: User = Depends(finance), db: Session = Depends(get_db)):
    pct = withdrawal_fee.set_percent(db, staff, body.percent)
    return {"percent": format(pct.normalize(), "f"), "example": withdrawal_fee.quote(db, "100", "GHS")}


@router.get("/settings/backups")
def list_backups(staff: User = Depends(manager)):
    return {"backups": backups.list_backups(), "directory_configured": bool(settings.backup_dir),
            "interval_hours": settings.backup_interval_hours, "keep": settings.backup_keep}


@router.post("/settings/backups", status_code=201)
def run_backup(staff: User = Depends(require_roles(UserRole.SUPER_ADMIN)), db: Session = Depends(get_db)):
    info = backups.create_backup()
    audit(db, "backup.created", actor_id=staff.id, actor_type="staff", target_type="backup",
          target_id=info["name"], details={"size": info["size_bytes"]})
    db.commit()
    return info
