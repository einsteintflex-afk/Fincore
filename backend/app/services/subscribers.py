"""Verified subscribers: customers of a connected application (Send Me, Nurses & Midwives Hub, PharmaStock...).

Subscribers are NOT FinCore dashboard users and never count toward the 15 dashboard seats. The connected
application authenticates its own users; FinCore keeps a verification status per (application, subscriber):

1. The app registers the subscriber (``pending``).
2. FinCore verifies them — a 6-digit code sent by SMS to their phone, confirmed through the app — or an
   administrator verifies them manually. They become ``active``.
3. The app asks FinCore for a short-lived *subscriber token* for an active subscriber and sends it as
   ``X-Subscriber-Token`` on subscriber-restricted calls (collections/payouts when the app requires it).
4. Deactivating a subscriber (``inactive``) bumps ``token_version``: every token issued before stops working
   immediately, and new tokens are refused with a clear access-denied message.
"""

from __future__ import annotations

import secrets
import uuid
from datetime import datetime, timedelta, timezone

import jwt
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import utcnow
from app.core.errors import AppError, Forbidden, NotFound, Unauthorized, ValidationFailed
from app.core.security import constant_time_equals, sha256_hex
from app.models.developer import AppSubscriber, DeveloperApp, SubscriberVerification
from app.models.enums import SubscriberStatus
from app.services.audit import audit
from app.services.ghana import local_format, normalize_msisdn
from app.services.notifications import queue_sms

TOKEN_TTL = timedelta(hours=12)
CODE_TTL = timedelta(minutes=10)
MAX_CODE_ATTEMPTS = 5
JWT_ALG = "HS256"


class SubscriberAccessDenied(AppError):
    def __init__(self, message: str, code: str) -> None:
        super().__init__(message, code=code, status_code=403)


def get(db: Session, app: DeveloperApp, external_id: str) -> AppSubscriber:
    sub = db.scalar(select(AppSubscriber).where(AppSubscriber.app_id == app.id,
                                                AppSubscriber.external_id == external_id))
    if not sub:
        raise NotFound("Subscriber not found")
    return sub


def upsert(db: Session, app: DeveloperApp, *, external_id: str, display_name: str | None = None,
           phone: str | None = None, email: str | None = None) -> AppSubscriber:
    msisdn = normalize_msisdn(phone) if phone else None
    sub = db.scalar(select(AppSubscriber).where(AppSubscriber.app_id == app.id,
                                                AppSubscriber.external_id == external_id).with_for_update())
    if sub:
        if msisdn and sub.phone and msisdn != sub.phone and sub.status == SubscriberStatus.ACTIVE:
            # A changed phone number must be re-verified.
            sub.status = SubscriberStatus.PENDING
            sub.verified_at = None
            sub.token_version += 1
        sub.display_name = display_name or sub.display_name
        sub.phone = msisdn or sub.phone
        sub.email = email or sub.email
    else:
        sub = AppSubscriber(app_id=app.id, external_id=external_id, display_name=display_name, phone=msisdn,
                            email=email, status=SubscriberStatus.PENDING, token_version=1)
        db.add(sub)
        db.flush()
        audit(db, "subscriber.registered", actor_type="api_key", target_type="subscriber", target_id=sub.id,
              details={"app_id": str(app.id), "external_id": external_id})
    db.commit()
    return sub


def start_verification(db: Session, sub: AppSubscriber) -> dict:
    if sub.status == SubscriberStatus.INACTIVE:
        raise SubscriberAccessDenied("This subscriber's access has been deactivated", "subscriber_inactive")
    if not sub.phone:
        raise ValidationFailed("Add the subscriber's phone number before verifying")
    code = f"{secrets.randbelow(1_000_000):06d}"
    for old in db.scalars(select(SubscriberVerification).where(SubscriberVerification.subscriber_id == sub.id,
                                                              SubscriberVerification.used_at.is_(None))):
        old.used_at = utcnow()  # only the newest code works
    db.add(SubscriberVerification(subscriber_id=sub.id, code_hash=sha256_hex(f"{sub.id}:{code}"),
                                  expires_at=utcnow() + CODE_TTL))
    queue_sms(db, sub.phone, f"Your verification code is {code}. It expires in 10 minutes. Do not share it.")
    db.commit()
    out = {"sent_to": local_format(sub.phone)[:-4] + "****", "expires_in": int(CODE_TTL.total_seconds())}
    if settings.environment in ("development", "test"):
        out["dev_code"] = code  # no SMS provider in development: expose the code (never in staging/production)
    return out


def confirm_verification(db: Session, sub: AppSubscriber, code: str) -> AppSubscriber:
    v = db.scalar(select(SubscriberVerification).where(SubscriberVerification.subscriber_id == sub.id,
                                                       SubscriberVerification.used_at.is_(None))
                  .order_by(SubscriberVerification.created_at.desc()).with_for_update())
    if not v:
        raise ValidationFailed("Request a new verification code", code="no_pending_code")
    expires = v.expires_at if v.expires_at.tzinfo else v.expires_at.replace(tzinfo=timezone.utc)
    if expires < utcnow() or v.attempts >= MAX_CODE_ATTEMPTS:
        v.used_at = utcnow()
        db.commit()
        raise ValidationFailed("The code has expired. Request a new one.", code="code_expired")
    v.attempts += 1
    if not constant_time_equals(v.code_hash, sha256_hex(f"{sub.id}:{code.strip()}")):
        db.commit()
        raise ValidationFailed("Incorrect code", code="invalid_code")
    v.used_at = utcnow()
    if sub.status != SubscriberStatus.INACTIVE:
        sub.status = SubscriberStatus.ACTIVE
        sub.verified_at = utcnow()
        sub.verification_method = "sms_code"
    audit(db, "subscriber.verified", actor_type="api_key", target_type="subscriber", target_id=sub.id,
          details={"method": "sms_code"})
    db.commit()
    return sub


def _assert_access(sub: AppSubscriber) -> None:
    if sub.status == SubscriberStatus.INACTIVE:
        raise SubscriberAccessDenied("Access for this subscriber has been deactivated", "subscriber_inactive")
    if sub.status != SubscriberStatus.ACTIVE or not sub.verified_at:
        raise SubscriberAccessDenied("This subscriber has not been verified yet", "subscriber_not_verified")


def issue_token(db: Session, sub: AppSubscriber) -> dict:
    _assert_access(sub)
    now = datetime.now(timezone.utc)
    token = jwt.encode({"typ": "subscriber", "sub": str(sub.id), "app": str(sub.app_id), "ver": sub.token_version,
                        "iat": now, "exp": now + TOKEN_TTL, "jti": uuid.uuid4().hex},
                       settings.secret_key, algorithm=JWT_ALG)
    return {"subscriber_token": token, "expires_in": int(TOKEN_TTL.total_seconds())}


def check_token(db: Session, app: DeveloperApp, token: str | None) -> AppSubscriber:
    """Validate an X-Subscriber-Token for this application. Raises 401/403 with a clear reason."""
    if not token:
        raise SubscriberAccessDenied("This application only serves verified subscribers: send X-Subscriber-Token",
                                     "subscriber_token_required")
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[JWT_ALG])
    except jwt.ExpiredSignatureError as exc:
        raise Unauthorized("Subscriber session expired", code="subscriber_token_expired") from exc
    except jwt.PyJWTError as exc:
        raise Unauthorized("Invalid subscriber token", code="invalid_subscriber_token") from exc
    if payload.get("typ") != "subscriber" or payload.get("app") != str(app.id):
        raise Unauthorized("Invalid subscriber token", code="invalid_subscriber_token")  # other apps' tokens fail
    sub = db.get(AppSubscriber, uuid.UUID(payload["sub"]))
    if not sub or sub.app_id != app.id:
        raise Unauthorized("Invalid subscriber token", code="invalid_subscriber_token")
    if payload.get("ver") != sub.token_version:
        raise Unauthorized("This subscriber session was revoked", code="subscriber_session_revoked")
    _assert_access(sub)
    return sub


# ---------------------------------------------------------------- administrator actions
def admin_set_status(db: Session, staff_id: uuid.UUID, sub_id: uuid.UUID, action: str, reason: str = "") -> AppSubscriber:
    sub = db.get(AppSubscriber, sub_id)
    if not sub:
        raise NotFound("Subscriber not found")
    if action == "deactivate":
        sub.status = SubscriberStatus.INACTIVE
        sub.token_version += 1  # revoke every session immediately
        sub.deactivated_reason = reason or None
    elif action == "activate":
        sub.status = SubscriberStatus.ACTIVE if sub.verified_at else SubscriberStatus.PENDING
        sub.deactivated_reason = None
    elif action == "verify":
        if sub.status == SubscriberStatus.INACTIVE:
            raise Forbidden("Activate the subscriber before verifying them")
        sub.status = SubscriberStatus.ACTIVE
        sub.verified_at = utcnow()
        sub.verification_method = "admin"
    elif action == "revoke_sessions":
        sub.token_version += 1
    else:
        raise ValidationFailed("Unknown action")
    audit(db, f"subscriber.{action}", actor_id=staff_id, actor_type="staff", target_type="subscriber",
          target_id=sub.id, details={"reason": reason} if reason else None)
    db.commit()
    return sub


def list_for_admin(db: Session, *, app_id: uuid.UUID | None = None, status: str | None = None,
                   q: str | None = None, page: int = 1, page_size: int = 50) -> dict:
    query = select(AppSubscriber, DeveloperApp.name).join(DeveloperApp, DeveloperApp.id == AppSubscriber.app_id)
    if app_id:
        query = query.where(AppSubscriber.app_id == app_id)
    if status:
        query = query.where(AppSubscriber.status == status)
    if q:
        like = f"%{q.strip()}%"
        query = query.where(AppSubscriber.external_id.ilike(like) | AppSubscriber.display_name.ilike(like)
                            | AppSubscriber.phone.ilike(like) | AppSubscriber.email.ilike(like))
    total = db.scalar(select(func.count()).select_from(query.subquery()))
    rows = db.execute(query.order_by(AppSubscriber.created_at.desc()).offset((page - 1) * page_size).limit(page_size))
    return {"total": total, "items": [{**out(s), "app_name": name} for s, name in rows]}


def out(sub: AppSubscriber) -> dict:
    return {"id": str(sub.id), "app_id": str(sub.app_id), "external_id": sub.external_id,
            "display_name": sub.display_name, "phone": sub.phone, "email": sub.email, "status": sub.status,
            "verified": sub.verified_at is not None, "verified_at": sub.verified_at,
            "verification_method": sub.verification_method, "created_at": sub.created_at}
