"""Verified subscribers: API for connected applications (API key) and Settings → Subscribers (administrators)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Header, Query
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.orm import Session

from app.api.deps import ApiContext, api_context, require_app_permission, require_roles
from app.core.database import get_db
from app.models.enums import AppPermission, UserRole
from app.models.user import User
from app.services import subscribers as svc

gateway = APIRouter(prefix="/gateway/subscribers", tags=["Payment gateway API: subscribers (API key)"])
router = APIRouter(prefix="/admin/subscribers", tags=["Settings: subscriber verification"])
manager = require_roles(UserRole.ADMIN, UserRole.SUPPORT, UserRole.COMPLIANCE)


class SubscriberIn(BaseModel):
    external_id: str = Field(min_length=1, max_length=128, description="Your application's own id for this user")
    display_name: str | None = Field(default=None, max_length=200)
    phone: str | None = None
    email: EmailStr | None = None


class CodeIn(BaseModel):
    code: str = Field(min_length=4, max_length=10)


class SubscriberActionIn(BaseModel):
    action: str = Field(pattern="^(activate|deactivate|verify|revoke_sessions)$")
    reason: str = Field(default="", max_length=500)


def _ctx(ctx: ApiContext = Depends(api_context)) -> ApiContext:
    require_app_permission(ctx, AppPermission.SUBSCRIBERS)
    return ctx


@gateway.post("", status_code=201, summary="Register (or update) a subscriber of your application")
def register(body: SubscriberIn, ctx: ApiContext = Depends(_ctx), db: Session = Depends(get_db)):
    return svc.out(svc.upsert(db, ctx.app, external_id=body.external_id, display_name=body.display_name,
                              phone=body.phone, email=body.email))


@gateway.get("/{external_id}")
def status(external_id: str, ctx: ApiContext = Depends(_ctx), db: Session = Depends(get_db)):
    return svc.out(svc.get(db, ctx.app, external_id))


@gateway.post("/{external_id}/verification", summary="Send a 6-digit verification code to the subscriber's phone")
def start(external_id: str, ctx: ApiContext = Depends(_ctx), db: Session = Depends(get_db)):
    return svc.start_verification(db, svc.get(db, ctx.app, external_id))


@gateway.post("/{external_id}/verification/confirm", summary="Confirm the code the subscriber received")
def confirm(external_id: str, body: CodeIn, ctx: ApiContext = Depends(_ctx), db: Session = Depends(get_db)):
    return svc.out(svc.confirm_verification(db, svc.get(db, ctx.app, external_id), body.code))


@gateway.post("/{external_id}/token", summary="Issue a subscriber token (verified, active subscribers only)")
def token(external_id: str, ctx: ApiContext = Depends(_ctx), db: Session = Depends(get_db)):
    return svc.issue_token(db, svc.get(db, ctx.app, external_id))


@gateway.get("/access/check", summary="Check a subscriber token: 200 with the subscriber, or 401/403 with the reason")
def check(x_subscriber_token: str | None = Header(default=None), ctx: ApiContext = Depends(_ctx),
          db: Session = Depends(get_db)):
    return {"access": "granted", "subscriber": svc.out(svc.check_token(db, ctx.app, x_subscriber_token))}


@router.get("")
def admin_list(app_id: uuid.UUID | None = None, status: str | None = None, q: str | None = None,
               page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=200),
               staff: User = Depends(manager), db: Session = Depends(get_db)):
    return svc.list_for_admin(db, app_id=app_id, status=status, q=q, page=page, page_size=page_size)


@router.post("/{subscriber_id}")
def admin_action(subscriber_id: uuid.UUID, body: SubscriberActionIn, staff: User = Depends(manager),
                 db: Session = Depends(get_db)):
    return svc.out(svc.admin_set_status(db, staff.id, subscriber_id, body.action, body.reason))
