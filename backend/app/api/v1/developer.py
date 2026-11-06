from __future__ import annotations

import uuid

import httpx
from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import current_user
from app.core.database import get_db
from app.core.errors import NotFound, ValidationFailed
from app.models.developer import ApiKey, DeveloperApp, WebhookDelivery, WebhookEndpoint
from app.models.user import User
from app.schemas.common import (
    ApiKeyIn,
    ApiKeyOut,
    AppIn,
    AppOut,
    DeliveryOut,
    Message,
    WebhookIn,
    WebhookOut,
    WebhookUpdateIn,
)
from app.services import business as bsvc
from app.services import developer as dsvc
from app.services import webhooks
from app.services.audit import audit

router = APIRouter(prefix="/developer", tags=["Developer platform"])


def _app(db: Session, user: User, app_id: uuid.UUID) -> DeveloperApp:
    app = dsvc.get_app(db, app_id)
    bsvc.require_permission(db, user, app.business_id, "developers:manage")
    return app


def _endpoint(db: Session, app: DeveloperApp, endpoint_id: uuid.UUID) -> WebhookEndpoint:
    ep = db.get(WebhookEndpoint, endpoint_id)
    if not ep or ep.app_id != app.id:
        raise NotFound("Webhook endpoint not found")
    return ep


@router.get("/events")
def event_types():
    return {"events": webhooks.EVENT_TYPES}


@router.post("/apps", response_model=AppOut, status_code=201)
def create_app(body: AppIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    biz = bsvc.require_permission(db, user, body.business_id, "developers:manage")
    return dsvc.create_app(db, user, biz, body.name, body.description)


@router.get("/apps", response_model=list[AppOut])
def list_apps(business_id: uuid.UUID, user: User = Depends(current_user), db: Session = Depends(get_db)):
    bsvc.require_permission(db, user, business_id, "developers:manage")
    return db.scalars(select(DeveloperApp).where(DeveloperApp.business_id == business_id,
                                                 DeveloperApp.status != "deleted")
                      .order_by(DeveloperApp.created_at)).all()


@router.get("/apps/{app_id}", response_model=AppOut)
def get_app(app_id: uuid.UUID, user: User = Depends(current_user), db: Session = Depends(get_db)):
    return _app(db, user, app_id)


@router.delete("/apps/{app_id}", response_model=Message)
def delete_app(app_id: uuid.UUID, user: User = Depends(current_user), db: Session = Depends(get_db)):
    app = _app(db, user, app_id)
    app.status = "deleted"
    for k in db.scalars(select(ApiKey).where(ApiKey.app_id == app.id, ApiKey.status == "active")):
        k.status = "revoked"
    audit(db, "developer.app_deleted", actor_id=user.id, target_type="app", target_id=app.id)
    db.commit()
    return {"message": "App deleted and its keys revoked"}


# ---------------------------------------------------------------- keys
@router.get("/apps/{app_id}/keys", response_model=list[ApiKeyOut])
def list_keys(app_id: uuid.UUID, user: User = Depends(current_user), db: Session = Depends(get_db)):
    app = _app(db, user, app_id)
    return db.scalars(select(ApiKey).where(ApiKey.app_id == app.id).order_by(ApiKey.created_at.desc())).all()


@router.post("/apps/{app_id}/keys", response_model=ApiKeyOut, status_code=201)
def create_key(app_id: uuid.UUID, body: ApiKeyIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    app = _app(db, user, app_id)
    key, secret = dsvc.create_api_key(db, user, app, body.environment)
    out = ApiKeyOut.model_validate(key)
    out.secret_key = secret
    return out


@router.post("/apps/{app_id}/keys/{key_id}/revoke", response_model=ApiKeyOut)
def revoke_key(app_id: uuid.UUID, key_id: uuid.UUID, user: User = Depends(current_user),
               db: Session = Depends(get_db)):
    return dsvc.revoke_api_key(db, user, _app(db, user, app_id), key_id)


@router.post("/apps/{app_id}/keys/{key_id}/roll", response_model=ApiKeyOut, status_code=201)
def roll_key(app_id: uuid.UUID, key_id: uuid.UUID, user: User = Depends(current_user), db: Session = Depends(get_db)):
    app = _app(db, user, app_id)
    old = dsvc.revoke_api_key(db, user, app, key_id)
    key, secret = dsvc.create_api_key(db, user, app, old.environment)
    out = ApiKeyOut.model_validate(key)
    out.secret_key = secret
    return out


# ---------------------------------------------------------------- webhooks
@router.get("/apps/{app_id}/webhooks", response_model=list[WebhookOut])
def list_webhooks(app_id: uuid.UUID, user: User = Depends(current_user), db: Session = Depends(get_db)):
    app = _app(db, user, app_id)
    return db.scalars(select(WebhookEndpoint).where(WebhookEndpoint.app_id == app.id)
                      .order_by(WebhookEndpoint.created_at)).all()


@router.post("/apps/{app_id}/webhooks", response_model=WebhookOut, status_code=201)
def create_webhook(app_id: uuid.UUID, body: WebhookIn, user: User = Depends(current_user),
                   db: Session = Depends(get_db)):
    app = _app(db, user, app_id)
    ep, secret = dsvc.create_endpoint(db, user, app, body.url, body.environment, body.events, body.description)
    out = WebhookOut.model_validate(ep)
    out.secret = secret
    return out


@router.patch("/apps/{app_id}/webhooks/{endpoint_id}", response_model=WebhookOut)
def update_webhook(app_id: uuid.UUID, endpoint_id: uuid.UUID, body: WebhookUpdateIn,
                   user: User = Depends(current_user), db: Session = Depends(get_db)):
    app = _app(db, user, app_id)
    ep = _endpoint(db, app, endpoint_id)
    if body.url:
        ep.url = dsvc._validate_url(body.url)
    if body.events is not None:
        bad = [e for e in body.events if e not in webhooks.EVENT_TYPES]
        if bad:
            raise ValidationFailed(f"Unknown events: {bad}")
        ep.events = body.events
    if body.active is not None:
        ep.active = body.active
    db.commit()
    return ep


@router.get("/apps/{app_id}/webhooks/{endpoint_id}/secret")
def reveal_secret(app_id: uuid.UUID, endpoint_id: uuid.UUID, user: User = Depends(current_user),
                  db: Session = Depends(get_db)):
    app = _app(db, user, app_id)
    ep = _endpoint(db, app, endpoint_id)
    audit(db, "developer.webhook_secret_revealed", actor_id=user.id, target_type="webhook", target_id=ep.id)
    db.commit()
    return {"secret": dsvc.endpoint_secret(ep)}


@router.delete("/apps/{app_id}/webhooks/{endpoint_id}", response_model=Message)
def delete_webhook(app_id: uuid.UUID, endpoint_id: uuid.UUID, user: User = Depends(current_user),
                   db: Session = Depends(get_db)):
    app = _app(db, user, app_id)
    db.delete(_endpoint(db, app, endpoint_id))
    db.commit()
    return {"message": "Webhook endpoint deleted"}


@router.post("/apps/{app_id}/webhooks/{endpoint_id}/test", response_model=DeliveryOut)
def test_webhook(app_id: uuid.UUID, endpoint_id: uuid.UUID, user: User = Depends(current_user),
                 db: Session = Depends(get_db)):
    app = _app(db, user, app_id)
    d = dsvc.send_test_event(db, _endpoint(db, app, endpoint_id))
    with httpx.Client() as client:
        webhooks.deliver(db, d, client)
    db.commit()
    return d


@router.get("/apps/{app_id}/deliveries", response_model=list[DeliveryOut])
def deliveries(app_id: uuid.UUID, status: str | None = None, limit: int = Query(50, le=200),
               user: User = Depends(current_user), db: Session = Depends(get_db)):
    app = _app(db, user, app_id)
    q = select(WebhookDelivery).join(WebhookEndpoint, WebhookEndpoint.id == WebhookDelivery.endpoint_id) \
        .where(WebhookEndpoint.app_id == app.id)
    if status:
        q = q.where(WebhookDelivery.status == status)
    return db.scalars(q.order_by(WebhookDelivery.created_at.desc()).limit(limit)).all()


@router.post("/apps/{app_id}/deliveries/{delivery_id}/retry", response_model=DeliveryOut)
def retry_delivery(app_id: uuid.UUID, delivery_id: uuid.UUID, user: User = Depends(current_user),
                   db: Session = Depends(get_db)):
    app = _app(db, user, app_id)
    d = db.get(WebhookDelivery, delivery_id)
    if not d or db.get(WebhookEndpoint, d.endpoint_id).app_id != app.id:
        raise NotFound("Delivery not found")
    with httpx.Client() as client:
        webhooks.deliver(db, d, client)
    db.commit()
    return d


# ---------------------------------------------------------------- analytics
@router.get("/apps/{app_id}/usage")
def usage(app_id: uuid.UUID, days: int = Query(30, ge=1, le=90), user: User = Depends(current_user),
          db: Session = Depends(get_db)):
    app = _app(db, user, app_id)
    return dsvc.usage(db, app.id, days)
