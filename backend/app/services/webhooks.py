"""Outgoing merchant webhooks: event fan-out, HMAC signing and retrying delivery."""

from __future__ import annotations

import json
import logging
import secrets
import time
import uuid
from datetime import timedelta

import httpx
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import utcnow
from app.core.security import build_signature_header, decrypt
from app.models.developer import DeveloperApp, WebhookDelivery, WebhookEndpoint

log = logging.getLogger("fincore.webhooks")

EVENT_TYPES = [
    "charge.success", "charge.failed", "refund.processed", "refund.failed",
    "settlement.paid", "settlement.failed", "payment_link.paid",
]


def emit(db: Session, business_id: uuid.UUID, event_type: str, data: dict, *, environment: str) -> int:
    """Queue an event for every matching endpoint of the business's apps. Committed with the caller."""
    endpoints = db.scalars(
        select(WebhookEndpoint).join(DeveloperApp, DeveloperApp.id == WebhookEndpoint.app_id).where(
            DeveloperApp.business_id == business_id, DeveloperApp.status == "active",
            WebhookEndpoint.active.is_(True), WebhookEndpoint.environment == environment)
    ).all()
    event_id = "evt_" + secrets.token_hex(12)
    payload = {"id": event_id, "type": event_type, "created_at": utcnow().isoformat(),
               "livemode": environment == "live", "data": _jsonable(data)}
    count = 0
    for ep in endpoints:
        if ep.events and event_type not in ep.events:
            continue
        db.add(WebhookDelivery(endpoint_id=ep.id, event_id=event_id, event_type=event_type, payload=payload,
                               status="pending", next_attempt_at=utcnow()))
        count += 1
    return count


def _jsonable(v):
    if isinstance(v, dict):
        return {k: _jsonable(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_jsonable(x) for x in v]
    if v is None or isinstance(v, (str, int, bool)):
        return v
    return str(v)


def backoff(attempts: int) -> timedelta:
    # 1m, 2m, 4m, 8m ... capped at 6h
    return timedelta(minutes=min(2 ** max(attempts - 1, 0), 360))


def deliver(db: Session, delivery: WebhookDelivery, client: httpx.Client) -> bool:
    ep = db.get(WebhookEndpoint, delivery.endpoint_id)
    body = json.dumps(delivery.payload, separators=(",", ":"), sort_keys=True).encode()
    ts = int(time.time())
    headers = {"Content-Type": "application/json", "User-Agent": "FinCore-Webhooks/1.0",
               "X-FinCore-Event": delivery.event_type, "X-FinCore-Delivery": str(delivery.id),
               "X-FinCore-Signature": build_signature_header(decrypt(ep.secret_enc), ts, body)}
    delivery.attempts += 1
    try:
        r = client.post(ep.url, content=body, headers=headers, timeout=settings.webhook_timeout_seconds)
        delivery.last_response_code = r.status_code
        ok = 200 <= r.status_code < 300
        delivery.last_error = None if ok else f"HTTP {r.status_code}"
    except httpx.HTTPError as exc:
        ok = False
        delivery.last_error = f"{type(exc).__name__}: {exc}"[:500]
    if ok:
        delivery.status = "succeeded"
        delivery.delivered_at = utcnow()
        delivery.next_attempt_at = None
    elif delivery.attempts >= settings.webhook_max_attempts:
        delivery.status = "failed"
        delivery.next_attempt_at = None
    else:
        delivery.status = "pending"
        delivery.next_attempt_at = utcnow() + backoff(delivery.attempts)
    return ok


def deliver_due(db: Session, client: httpx.Client | None = None, limit: int = 100) -> dict:
    owns = client is None
    client = client or httpx.Client()
    stats = {"attempted": 0, "succeeded": 0}
    try:
        due = db.scalars(select(WebhookDelivery).where(
            WebhookDelivery.status == "pending",
            or_(WebhookDelivery.next_attempt_at.is_(None), WebhookDelivery.next_attempt_at <= utcnow()))
            .order_by(WebhookDelivery.created_at).limit(limit).with_for_update(skip_locked=True)).all()
        for d in due:
            stats["attempted"] += 1
            if deliver(db, d, client):
                stats["succeeded"] += 1
        db.commit()
    finally:
        if owns:
            client.close()
    return stats
