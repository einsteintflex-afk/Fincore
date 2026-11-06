from __future__ import annotations

import secrets
import uuid
from datetime import timedelta
from urllib.parse import urlparse

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import utcnow
from app.core.errors import Forbidden, NotFound, Unauthorized, ValidationFailed
from app.core.security import constant_time_equals, decrypt, encrypt, sha256_hex
from app.models.business import Business
from app.models.developer import ApiKey, ApiRequestLog, DeveloperApp, WebhookDelivery, WebhookEndpoint
from app.models.enums import BusinessStatus
from app.models.user import User
from app.services.audit import audit
from app.services.webhooks import EVENT_TYPES


def create_app(db: Session, user: User, business: Business, name: str, description: str | None) -> DeveloperApp:
    app = DeveloperApp(owner_user_id=user.id, business_id=business.id, name=name.strip(), description=description)
    db.add(app)
    db.flush()
    audit(db, "developer.app_created", actor_id=user.id, target_type="app", target_id=app.id, details={"name": name})
    db.commit()
    return app


def get_app(db: Session, app_id: uuid.UUID) -> DeveloperApp:
    app = db.get(DeveloperApp, app_id)
    if not app or app.status == "deleted":
        raise NotFound("App not found")
    return app


def create_api_key(db: Session, user: User, app: DeveloperApp, environment: str) -> tuple[ApiKey, str]:
    if environment not in ("sandbox", "live"):
        raise ValidationFailed("environment must be sandbox or live")
    if environment == "live":
        biz = db.get(Business, app.business_id)
        if biz.status != BusinessStatus.ACTIVE:
            raise Forbidden("Live keys require an approved business", code="business_not_active")
        if not settings.live_payments_enabled:
            raise Forbidden("Live payments are not enabled on this FinCore deployment yet",
                            code="live_payments_disabled")
    tag = "test" if environment == "sandbox" else "live"
    secret = f"sk_{tag}_{secrets.token_urlsafe(32)}"
    key = ApiKey(app_id=app.id, environment=environment, public_key=f"pk_{tag}_{secrets.token_urlsafe(18)}",
                 secret_prefix=secret[:16], secret_hash=sha256_hex(secret), last4=secret[-4:], status="active")
    db.add(key)
    db.flush()
    audit(db, "developer.api_key_created", actor_id=user.id, target_type="app", target_id=app.id,
          details={"environment": environment, "prefix": key.secret_prefix})
    db.commit()
    return key, secret


def revoke_api_key(db: Session, user: User, app: DeveloperApp, key_id: uuid.UUID) -> ApiKey:
    key = db.get(ApiKey, key_id)
    if not key or key.app_id != app.id:
        raise NotFound("API key not found")
    key.status = "revoked"
    key.revoked_at = utcnow()
    audit(db, "developer.api_key_revoked", actor_id=user.id, target_type="app", target_id=app.id,
          details={"prefix": key.secret_prefix})
    db.commit()
    return key


def authenticate_secret(db: Session, secret: str) -> tuple[ApiKey, DeveloperApp, Business]:
    if not secret.startswith(("sk_test_", "sk_live_")) or len(secret) < 20:
        raise Unauthorized("Invalid API key", code="invalid_api_key")
    key = db.scalar(select(ApiKey).where(ApiKey.secret_prefix == secret[:16]))
    if not key or key.status != "active" or not constant_time_equals(key.secret_hash, sha256_hex(secret)):
        raise Unauthorized("Invalid API key", code="invalid_api_key")
    app = db.get(DeveloperApp, key.app_id)
    if app.status != "active":
        raise Unauthorized("This app is disabled", code="app_disabled")
    biz = db.get(Business, app.business_id)
    if biz.status in (BusinessStatus.SUSPENDED, BusinessStatus.REJECTED):
        raise Forbidden("Business account is not active", code="business_not_active")
    if key.environment == "live" and not settings.live_payments_enabled:
        raise Forbidden("Live payments are disabled on this deployment", code="live_payments_disabled")
    key.last_used_at = utcnow()
    return key, app, biz


def _validate_url(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme not in ("https", "http") or not parsed.netloc:
        raise ValidationFailed("Webhook URL must be an absolute http(s) URL")
    if settings.is_production and parsed.scheme != "https":
        raise ValidationFailed("Webhook URLs must use HTTPS")
    host = (parsed.hostname or "").lower()
    if settings.is_production and (host in ("localhost", "127.0.0.1", "0.0.0.0") or host.endswith(".internal")):  # noqa: S104 (blocklist, not a bind)
        raise ValidationFailed("Webhook URL must be publicly reachable")
    return url


def create_endpoint(db: Session, user: User, app: DeveloperApp, url: str, environment: str, events: list[str],
                    description: str | None) -> tuple[WebhookEndpoint, str]:
    bad = [e for e in events if e not in EVENT_TYPES]
    if bad:
        raise ValidationFailed(f"Unknown events: {bad}")
    if environment not in ("sandbox", "live"):
        raise ValidationFailed("environment must be sandbox or live")
    secret = "whsec_" + secrets.token_urlsafe(24)
    ep = WebhookEndpoint(app_id=app.id, url=_validate_url(url), environment=environment, secret_enc=encrypt(secret),
                         events=events, description=description)
    db.add(ep)
    db.flush()
    audit(db, "developer.webhook_created", actor_id=user.id, target_type="app", target_id=app.id, details={"url": url})
    db.commit()
    return ep, secret


def endpoint_secret(ep: WebhookEndpoint) -> str:
    return decrypt(ep.secret_enc)


def send_test_event(db: Session, ep: WebhookEndpoint) -> WebhookDelivery:
    payload = {"id": "evt_test_" + secrets.token_hex(8), "type": "test.ping", "created_at": utcnow().isoformat(),
               "livemode": ep.environment == "live", "data": {"message": "Hello from FinCore"}}
    d = WebhookDelivery(endpoint_id=ep.id, event_id=payload["id"], event_type="test.ping", payload=payload,
                        status="pending", next_attempt_at=utcnow())
    db.add(d)
    db.commit()
    return d


def log_request(db: Session, *, app_id, api_key_id, environment, method, path, status_code, latency_ms, ip) -> None:
    db.add(ApiRequestLog(app_id=app_id, api_key_id=api_key_id, environment=environment, method=method, path=path,
                         status_code=status_code, latency_ms=latency_ms, ip_address=ip))
    db.commit()


def usage(db: Session, app_id: uuid.UUID, days: int = 30) -> dict:
    since = utcnow() - timedelta(days=days)
    day = func.date_trunc("day", ApiRequestLog.created_at)
    rows = db.execute(
        select(day.label("day"), func.count().label("requests"),
               func.sum(case((ApiRequestLog.status_code >= 400, 1), else_=0)).label("errors"),
               func.avg(ApiRequestLog.latency_ms).label("avg_latency"))
        .where(ApiRequestLog.app_id == app_id, ApiRequestLog.created_at >= since)
        .group_by(day).order_by(day)).all()
    endpoints = db.execute(
        select(ApiRequestLog.method, ApiRequestLog.path, func.count().label("n"))
        .where(ApiRequestLog.app_id == app_id, ApiRequestLog.created_at >= since)
        .group_by(ApiRequestLog.method, ApiRequestLog.path).order_by(func.count().desc()).limit(10)).all()
    total = sum(r.requests for r in rows)
    errors = sum(int(r.errors or 0) for r in rows)
    return {
        "total_requests": total, "error_requests": errors,
        "error_rate": round(errors / total, 4) if total else 0.0,
        "daily": [{"day": r.day.date().isoformat(), "requests": r.requests, "errors": int(r.errors or 0),
                   "avg_latency_ms": round(float(r.avg_latency or 0), 1)} for r in rows],
        "top_endpoints": [{"method": r.method, "path": r.path, "requests": r.n} for r in endpoints],
    }
