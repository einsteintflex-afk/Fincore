"""The signed-in user's profile, notifications, KYC, limits and support tickets."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.api.deps import current_user
from app.core.database import get_db, utcnow
from app.core.errors import Conflict, NotFound
from app.models.ops import SupportTicket, TicketMessage
from app.models.user import KycSubmission, Notification, User
from app.schemas.common import (
    KycIn,
    KycOut,
    Message,
    NotificationOut,
    ProfileUpdateIn,
    TicketIn,
    TicketMessageIn,
    TicketMessageOut,
    TicketOut,
    UserOut,
)
from app.services import analytics, kyc, limits
from app.services.audit import audit
from app.services.ghana import normalize_msisdn

router = APIRouter(prefix="/me", tags=["My account"])


@router.get("", response_model=UserOut)
def me(user: User = Depends(current_user)):
    return user


@router.patch("", response_model=UserOut)
def update_me(body: ProfileUpdateIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    if body.full_name:
        if user.kyc_tier >= 2 and body.full_name != user.full_name:
            raise Conflict("Verified accounts must contact support to change their legal name")
        user.full_name = body.full_name
    if body.phone:
        msisdn = normalize_msisdn(body.phone)
        if db.scalar(select(User.id).where(User.phone == msisdn, User.id != user.id)):
            raise Conflict("Phone number is used by another account")
        user.phone = msisdn
    audit(db, "user.profile_updated", actor_id=user.id, target_type="user", target_id=user.id,
          details=body.model_dump(exclude_none=True))
    db.commit()
    return user


@router.get("/limits")
def my_limits(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return {"kyc_tier": user.kyc_tier, "limits": limits.limits_summary(db, user)}


@router.get("/summary")
def my_summary(days: int = Query(30, ge=1, le=365), user: User = Depends(current_user),
               db: Session = Depends(get_db)):
    return analytics.customer_summary(db, user, days)


# ---------------------------------------------------------------- notifications
@router.get("/notifications")
def notifications(unread_only: bool = False, limit: int = Query(30, le=100), user: User = Depends(current_user),
                  db: Session = Depends(get_db)):
    q = select(Notification).where(Notification.user_id == user.id)
    if unread_only:
        q = q.where(Notification.read_at.is_(None))
    items = db.scalars(q.order_by(Notification.created_at.desc()).limit(limit)).all()
    unread = db.scalar(select(func.count()).select_from(Notification).where(
        Notification.user_id == user.id, Notification.read_at.is_(None)))
    return {"unread": unread, "items": [NotificationOut.model_validate(n) for n in items]}


@router.post("/notifications/read-all", response_model=Message)
def read_all(user: User = Depends(current_user), db: Session = Depends(get_db)):
    db.execute(update(Notification).where(Notification.user_id == user.id, Notification.read_at.is_(None))
               .values(read_at=utcnow()))
    db.commit()
    return {"message": "All notifications marked as read"}


@router.post("/notifications/{notification_id}/read", response_model=Message)
def read_one(notification_id: uuid.UUID, user: User = Depends(current_user), db: Session = Depends(get_db)):
    n = db.get(Notification, notification_id)
    if not n or n.user_id != user.id:
        raise NotFound("Notification not found")
    n.read_at = n.read_at or utcnow()
    db.commit()
    return {"message": "Marked as read"}


# ---------------------------------------------------------------- KYC
@router.post("/kyc", response_model=KycOut, status_code=201)
def submit_kyc(body: KycIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    return kyc.submit(db, user, body.model_dump())


@router.get("/kyc", response_model=list[KycOut])
def my_kyc(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return db.scalars(select(KycSubmission).where(KycSubmission.user_id == user.id)
                      .order_by(KycSubmission.created_at.desc())).all()


# ---------------------------------------------------------------- support
@router.post("/tickets", response_model=TicketOut, status_code=201)
def open_ticket(body: TicketIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    t = SupportTicket(user_id=user.id, subject=body.subject, category=body.category,
                      transaction_reference=body.transaction_reference)
    db.add(t)
    db.flush()
    db.add(TicketMessage(ticket_id=t.id, author_id=user.id, body=body.message))
    db.commit()
    return t


@router.get("/tickets", response_model=list[TicketOut])
def my_tickets(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return db.scalars(select(SupportTicket).where(SupportTicket.user_id == user.id)
                      .order_by(SupportTicket.updated_at.desc())).all()


@router.get("/tickets/{ticket_id}")
def my_ticket(ticket_id: uuid.UUID, user: User = Depends(current_user), db: Session = Depends(get_db)):
    t = db.get(SupportTicket, ticket_id)
    if not t or t.user_id != user.id:
        raise NotFound("Ticket not found")
    msgs = db.scalars(select(TicketMessage).where(TicketMessage.ticket_id == t.id, TicketMessage.internal.is_(False))
                      .order_by(TicketMessage.created_at)).all()
    return {"ticket": TicketOut.model_validate(t), "messages": [TicketMessageOut.model_validate(m) for m in msgs]}


@router.post("/tickets/{ticket_id}/messages", response_model=TicketMessageOut, status_code=201)
def reply(ticket_id: uuid.UUID, body: TicketMessageIn, user: User = Depends(current_user),
          db: Session = Depends(get_db)):
    t = db.get(SupportTicket, ticket_id)
    if not t or t.user_id != user.id:
        raise NotFound("Ticket not found")
    m = TicketMessage(ticket_id=t.id, author_id=user.id, body=body.body, internal=False)
    db.add(m)
    if t.status in ("resolved", "closed", "pending"):
        t.status = "open"
    t.updated_at = utcnow()
    db.commit()
    return m
