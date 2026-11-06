from __future__ import annotations

import logging
import uuid

from sqlalchemy.orm import Session

from app.models.user import Notification, OutboundMessage

log = logging.getLogger("fincore.notify")


def notify(db: Session, user_id: uuid.UUID, type: str, title: str, body: str, data: dict | None = None) -> None:
    db.add(Notification(user_id=user_id, type=type, title=title, body=body, data=data or {}))


def queue_email(db: Session, to: str, subject: str, body: str, user_id: uuid.UUID | None = None) -> OutboundMessage:
    """Queue an email in the outbox. A delivery worker sends it via SMTP/ESP (see docs/OPERATIONS.md)."""
    msg = OutboundMessage(channel="email", recipient=to, subject=subject, body=body, user_id=user_id)
    db.add(msg)
    log.info("email queued", extra={"to": to, "subject": subject})
    return msg


def queue_sms(db: Session, to: str, body: str, user_id: uuid.UUID | None = None) -> OutboundMessage:
    msg = OutboundMessage(channel="sms", recipient=to, body=body, user_id=user_id)
    db.add(msg)
    return msg
