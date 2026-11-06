from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from fastapi import Depends, Header, Request
from fastapi.encoders import jsonable_encoder
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.errors import AppError, Conflict, Forbidden, Unauthorized
from app.core.security import decode_token
from app.models.business import Business
from app.models.developer import ApiKey, DeveloperApp
from app.models.enums import STAFF_ROLES, RestrictionType, UserRole, UserStatus
from app.models.ledger import IdempotencyRecord
from app.models.ops import SystemSetting
from app.models.user import User, UserSession
from app.services import developer as dev_service
from app.services.restrictions import active_restrictions


@dataclass
class Principal:
    user: User
    session_id: uuid.UUID


def _bearer(request: Request) -> str:
    auth = request.headers.get("authorization", "")
    if not auth.lower().startswith("bearer "):
        raise Unauthorized("Missing bearer token")
    return auth[7:].strip()


def get_principal(request: Request, db: Session = Depends(get_db)) -> Principal:
    payload = decode_token(_bearer(request), "access")
    session = db.get(UserSession, uuid.UUID(payload["sid"]))
    if not session or session.revoked_at:
        raise Unauthorized("Session has been signed out", code="session_revoked")
    user = db.get(User, uuid.UUID(payload["sub"]))
    if not user or user.status == UserStatus.CLOSED:
        raise Unauthorized("Account unavailable")
    if RestrictionType.LOGIN_BLOCK in active_restrictions(db, user.id):
        raise Unauthorized("Sign-in is blocked for this account", code="login_blocked")
    return Principal(user=user, session_id=session.id)


def current_user(p: Principal = Depends(get_principal)) -> User:
    return p.user


def require_roles(*roles: UserRole) -> Callable[[User], User]:
    allowed = {r.value for r in roles}

    def dep(user: User = Depends(current_user)) -> User:
        if user.role not in allowed and user.role != UserRole.SUPER_ADMIN:
            raise Forbidden("You do not have permission for this action")
        return user

    return dep


def staff_user(user: User = Depends(current_user)) -> User:
    if user.role not in STAFF_ROLES:
        raise Forbidden("Staff access required")
    return user


def client_ip(request: Request) -> str | None:
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else None


def ensure_not_in_maintenance(db: Session) -> None:
    s = db.get(SystemSetting, "maintenance_mode")
    if s and s.value.get("enabled"):
        raise AppError(s.value.get("message") or "FinCore is under maintenance. Please try again shortly.",
                       code="maintenance", status_code=503)


def money_movement_allowed(db: Session = Depends(get_db)) -> None:
    ensure_not_in_maintenance(db)


# ---------------------------------------------------------------- API-key auth (gateway)
@dataclass
class ApiContext:
    key: ApiKey
    app: DeveloperApp
    business: Business

    @property
    def environment(self) -> str:
        return self.key.environment


def api_context(request: Request, db: Session = Depends(get_db)) -> ApiContext:
    key, app, biz = dev_service.authenticate_secret(db, _bearer(request))
    db.commit()
    ctx = ApiContext(key=key, app=app, business=biz)
    request.state.api_ctx = {"app_id": app.id, "key_id": key.id, "environment": key.environment}
    return ctx


# ---------------------------------------------------------------- idempotency
IdempotencyKey = Header(default=None, alias="Idempotency-Key", max_length=128,
                        description="Unique key so a retried request is executed at most once")


def run_idempotent(db: Session, scope: str, key: str | None, payload: Any, fn: Callable[[], Any]) -> Any:
    """Execute ``fn`` at most once per (scope, key). Replays return the stored response.

    Deterministic business errors (e.g. insufficient funds) are stored and replayed too, so a client
    retrying after a timeout always sees the original outcome.
    """
    if not key:
        return fn()
    digest = hashlib.sha256(json.dumps(jsonable_encoder(payload), sort_keys=True).encode()).hexdigest()

    def lookup(lock: bool = False) -> IdempotencyRecord | None:
        q = select(IdempotencyRecord).where(IdempotencyRecord.scope == scope, IdempotencyRecord.key == key)
        return db.scalar(q.with_for_update() if lock else q)

    if lookup() is None:
        try:
            db.add(IdempotencyRecord(scope=scope, key=key, request_hash=digest, completed=False))
            db.commit()
        except IntegrityError:
            db.rollback()
    # Row lock serialises concurrent duplicates: the loser sees note == "owned" (or the stored result).
    rec = lookup(lock=True)
    if rec.request_hash != digest:
        db.rollback()
        raise Conflict("Idempotency-Key was already used with a different request", code="idempotency_mismatch")
    if rec.completed:
        status, body = rec.status_code, rec.response_body or {}
        db.rollback()
        if status and status >= 400:
            raise AppError(body.get("message", "Request failed"), code=body.get("code", "error"),
                           status_code=status, details=body.get("details"))
        return body
    if rec.note == "owned":
        db.rollback()
        raise Conflict("A request with this Idempotency-Key is still being processed", code="idempotency_in_progress")
    rec.note = "owned"
    db.commit()
    rec_id = rec.id
    try:
        result = fn()
    except AppError as exc:
        db.rollback()
        rec = db.get(IdempotencyRecord, rec_id)
        if exc.status_code < 500:
            rec.completed, rec.status_code = True, exc.status_code
            rec.response_body = {"code": exc.code, "message": exc.message, "details": jsonable_encoder(exc.details)}
        else:
            db.delete(rec)
        db.commit()
        raise
    except Exception:
        db.rollback()
        rec = db.get(IdempotencyRecord, rec_id)
        if rec:
            db.delete(rec)
            db.commit()
        raise
    rec = db.get(IdempotencyRecord, rec_id)
    rec.completed, rec.status_code = True, 200
    rec.response_body = jsonable_encoder(result)
    db.commit()
    return rec.response_body
