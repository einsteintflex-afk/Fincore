"""Private dashboard accounts: at most 15 human users (including the primary administrator).

Rules (also enforced in the database — see ``models/guards.py``):

* No public registration. Accounts are created only by invitation from an administrator.
* An invited user holds a seat from the moment of invitation; deactivated and removed users hold none.
* The primary administrator (the owner) can never be deactivated, removed, demoted or deleted.
* Only super admins manage the team; only the primary administrator can create or change other super admins,
  so nobody can raise themselves (or anyone else) above their own level.

Customers of connected applications are *subscribers* (``services/subscribers.py``), never dashboard users.
"""

from __future__ import annotations

import secrets
import uuid
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import utcnow
from app.core.errors import AppError, Conflict, Forbidden, NotFound, Unauthorized, ValidationFailed
from app.core.security import hash_password, sha256_hex
from app.models.enums import MAX_DASHBOARD_USERS, SEATLESS_STATUSES, UserRole, UserStatus
from app.models.ledger import Wallet
from app.models.ops import AuditLog
from app.models.user import User, UserInvitation, UserSession
from app.services.audit import audit
from app.services.auth import check_password_policy, revoke_all_sessions
from app.services.ghana import normalize_msisdn
from app.services.notifications import queue_email
from app.services.wallets import create_wallet

INVITATION_TTL = timedelta(days=7)
ASSIGNABLE_ROLES = {r.value for r in UserRole}


class SeatLimitReached(AppError):
    def __init__(self) -> None:
        super().__init__(f"All {MAX_DASHBOARD_USERS} dashboard seats are in use. Deactivate or remove a user first.",
                         code="seat_limit_reached", status_code=409)


def seats_used(db: Session) -> int:
    return db.scalar(select(func.count()).select_from(User).where(User.status.not_in(SEATLESS_STATUSES))) or 0


def seat_summary(db: Session) -> dict:
    used = seats_used(db)
    return {"limit": MAX_DASHBOARD_USERS, "used": used, "available": max(MAX_DASHBOARD_USERS - used, 0)}


def _flush_seat_guarded(db: Session) -> None:
    """Flush, translating the database seat trigger / primary-admin trigger into API errors."""
    try:
        db.flush()
    except IntegrityError as exc:  # check_violation / restrict_violation raised by the triggers
        db.rollback()
        msg = str(exc.orig)
        if "dashboard_seat_limit" in msg:
            raise SeatLimitReached() from exc
        if "primary_admin_protected" in msg:
            raise Forbidden("The primary administrator cannot be deactivated, removed or demoted",
                            code="primary_admin_protected") from exc
        raise Conflict("An account with these details already exists") from exc


def _ensure_manager(actor: User) -> None:
    if actor.role != UserRole.SUPER_ADMIN or actor.status != UserStatus.ACTIVE:
        raise Forbidden("Only the administrator can manage dashboard users", code="not_team_admin")


def _ensure_can_touch(actor: User, target: User) -> None:
    _ensure_manager(actor)
    if target.is_primary_admin:
        raise Forbidden("The primary administrator cannot be changed by anyone", code="primary_admin_protected")
    if target.id == actor.id:
        raise Forbidden("You cannot change your own account here", code="self_change")
    if target.role == UserRole.SUPER_ADMIN and not actor.is_primary_admin:
        raise Forbidden("Only the primary administrator can change another super admin", code="not_primary_admin")


def _ensure_can_grant(actor: User, role: str) -> None:
    if role not in ASSIGNABLE_ROLES:
        raise ValidationFailed("Unknown role")
    if role == UserRole.SUPER_ADMIN and not actor.is_primary_admin:
        raise Forbidden("Only the primary administrator can grant super admin", code="not_primary_admin")


def create_user(db: Session, *, email: str, full_name: str, password: str, role: str = UserRole.CUSTOMER,
                phone: str | None = None, primary: bool = False, actor_id: uuid.UUID | None = None,
                kyc_tier: int = 0) -> User:
    """Create an active account directly (CLI bootstrap, demo data, tests). Still bound by the seat limit."""
    check_password_policy(password)
    email = email.strip().lower()
    if db.scalar(select(User.id).where(User.email == email)):
        raise Conflict("An account with this email already exists", code="email_taken")
    msisdn = normalize_msisdn(phone) if phone else None
    if msisdn and db.scalar(select(User.id).where(User.phone == msisdn)):
        raise Conflict("An account with this phone number already exists", code="phone_taken")
    user = User(email=email, full_name=full_name.strip(), phone=msisdn, password_hash=hash_password(password),
                role=str(role), status=UserStatus.ACTIVE, kyc_tier=kyc_tier, email_verified=True,
                password_changed_at=utcnow(), is_primary_admin=primary, invited_by_id=actor_id)
    db.add(user)
    _flush_seat_guarded(db)
    create_wallet(db, user=user, currency=settings.default_currency, label="Main", is_default=True)
    audit(db, "team.user_created", actor_id=actor_id, target_type="user", target_id=user.id,
          details={"role": str(role), "primary": primary})
    db.commit()
    return user


def invite(db: Session, actor: User, *, email: str, full_name: str, role: str, phone: str | None = None) -> tuple[User, str]:
    """Reserve a seat and return (user, invitation link). The link is also queued by email."""
    _ensure_manager(actor)
    _ensure_can_grant(actor, role)
    email = email.strip().lower()
    if db.scalar(select(User.id).where(User.email == email)):
        raise Conflict("An account with this email already exists", code="email_taken")
    msisdn = normalize_msisdn(phone) if phone else None
    user = User(email=email, full_name=full_name.strip(), phone=msisdn,
                password_hash=hash_password(secrets.token_urlsafe(32)),  # unusable until the invite is accepted
                role=role, status=UserStatus.INVITED, kyc_tier=0, invited_by_id=actor.id)
    db.add(user)
    _flush_seat_guarded(db)
    token = secrets.token_urlsafe(32)
    db.add(UserInvitation(user_id=user.id, token_hash=sha256_hex(token), invited_by_id=actor.id,
                          expires_at=utcnow() + INVITATION_TTL))
    link = f"{settings.frontend_base_url}/accept-invite?token={token}"
    queue_email(db, email, "You're invited to FinCore",
                f"Hello {user.full_name},\n\n{actor.full_name} invited you to FinCore.\n"
                f"Set your password within 7 days: {link}", user_id=user.id)
    audit(db, "team.user_invited", actor_id=actor.id, actor_type="staff", target_type="user", target_id=user.id,
          details={"email": email, "role": role})
    db.commit()
    return user, link


def _open_invitation(db: Session, token: str, *, lock: bool = False) -> UserInvitation:
    q = select(UserInvitation).where(UserInvitation.token_hash == sha256_hex(token))
    inv = db.scalar(q.with_for_update() if lock else q)
    if not inv or inv.accepted_at or inv.revoked_at:
        raise Unauthorized("This invitation link is invalid or has already been used", code="invalid_invitation")
    expires = inv.expires_at if inv.expires_at.tzinfo else inv.expires_at.replace(tzinfo=utcnow().tzinfo)
    if expires < utcnow():
        raise Unauthorized("This invitation has expired. Ask your administrator for a new one.",
                           code="invitation_expired")
    return inv


def invitation_info(db: Session, token: str) -> dict:
    inv = _open_invitation(db, token)
    user = db.get(User, inv.user_id)
    return {"email": user.email, "full_name": user.full_name, "role": user.role}


def accept_invitation(db: Session, token: str, password: str) -> User:
    check_password_policy(password)
    inv = _open_invitation(db, token, lock=True)
    user = db.get(User, inv.user_id)
    if user.status != UserStatus.INVITED:
        raise Unauthorized("This invitation is no longer valid", code="invalid_invitation")
    user.password_hash = hash_password(password)
    user.password_changed_at = utcnow()
    user.status = UserStatus.ACTIVE  # already holds its seat; no new seat is taken
    user.email_verified = True
    inv.accepted_at = utcnow()
    if not db.scalar(select(Wallet.id).where(Wallet.user_id == user.id)):
        create_wallet(db, user=user, currency=settings.default_currency, label="Main", is_default=True)
    audit(db, "team.invitation_accepted", actor_id=user.id, target_type="user", target_id=user.id)
    db.commit()
    return user


def _get(db: Session, user_id: uuid.UUID) -> User:
    u = db.get(User, user_id)
    if not u:
        raise NotFound("User not found")
    return u


def deactivate(db: Session, actor: User, user_id: uuid.UUID, reason: str = "") -> User:
    target = _get(db, user_id)
    _ensure_can_touch(actor, target)
    if target.status == UserStatus.CLOSED:
        raise ValidationFailed("This user has been removed")
    was_invited = target.status == UserStatus.INVITED
    target.status = UserStatus.DEACTIVATED
    target.deactivated_at = utcnow()
    _flush_seat_guarded(db)
    revoke_all_sessions(db, target.id)
    if was_invited:
        for inv in db.scalars(select(UserInvitation).where(UserInvitation.user_id == target.id,
                                                           UserInvitation.accepted_at.is_(None))):
            inv.revoked_at = utcnow()
    audit(db, "team.user_deactivated", actor_id=actor.id, actor_type="staff", target_type="user",
          target_id=target.id, details={"reason": reason})
    db.commit()
    return target


def activate(db: Session, actor: User, user_id: uuid.UUID) -> User:
    target = _get(db, user_id)
    _ensure_can_touch(actor, target)
    if target.status != UserStatus.DEACTIVATED:
        raise ValidationFailed("Only deactivated users can be activated")
    # A deactivated user who never accepted their invitation goes back to "invited" with a fresh link.
    has_password = target.password_changed_at is not None
    target.status = UserStatus.ACTIVE if has_password else UserStatus.INVITED
    target.deactivated_at = None
    target.failed_login_count = 0
    _flush_seat_guarded(db)  # the seat trigger rejects the 16th seat, serialised by an advisory lock
    audit(db, "team.user_activated", actor_id=actor.id, actor_type="staff", target_type="user", target_id=target.id)
    db.commit()
    return target


def remove(db: Session, actor: User, user_id: uuid.UUID, reason: str = "") -> User:
    """Remove an account permanently from the dashboard. The row stays (ledger/audit history references it)."""
    target = _get(db, user_id)
    _ensure_can_touch(actor, target)
    target.status = UserStatus.CLOSED
    target.deactivated_at = utcnow()
    _flush_seat_guarded(db)
    revoke_all_sessions(db, target.id)
    for inv in db.scalars(select(UserInvitation).where(UserInvitation.user_id == target.id,
                                                       UserInvitation.accepted_at.is_(None))):
        inv.revoked_at = utcnow()
    audit(db, "team.user_removed", actor_id=actor.id, actor_type="staff", target_type="user", target_id=target.id,
          details={"reason": reason})
    db.commit()
    return target


def change_role(db: Session, actor: User, user_id: uuid.UUID, role: str) -> User:
    target = _get(db, user_id)
    _ensure_can_touch(actor, target)
    _ensure_can_grant(actor, role)
    old = target.role
    target.role = role
    _flush_seat_guarded(db)
    revoke_all_sessions(db, target.id)  # new permissions take effect on next sign-in
    audit(db, "team.role_changed", actor_id=actor.id, actor_type="staff", target_type="user", target_id=target.id,
          details={"from": old, "to": role})
    db.commit()
    return target


def resend_invitation(db: Session, actor: User, user_id: uuid.UUID) -> str:
    target = _get(db, user_id)
    _ensure_can_touch(actor, target)
    if target.status != UserStatus.INVITED:
        raise ValidationFailed("This user has already accepted their invitation")
    for inv in db.scalars(select(UserInvitation).where(UserInvitation.user_id == target.id,
                                                       UserInvitation.accepted_at.is_(None),
                                                       UserInvitation.revoked_at.is_(None))):
        inv.revoked_at = utcnow()
    token = secrets.token_urlsafe(32)
    db.add(UserInvitation(user_id=target.id, token_hash=sha256_hex(token), invited_by_id=actor.id,
                          expires_at=utcnow() + INVITATION_TTL))
    link = f"{settings.frontend_base_url}/accept-invite?token={token}"
    queue_email(db, target.email, "Your FinCore invitation", f"Set your password within 7 days: {link}",
                user_id=target.id)
    audit(db, "team.invitation_resent", actor_id=actor.id, actor_type="staff", target_type="user",
          target_id=target.id)
    db.commit()
    return link


def revoke_sessions(db: Session, actor: User, user_id: uuid.UUID) -> int:
    target = _get(db, user_id)
    if target.id != actor.id:
        _ensure_can_touch(actor, target)
    n = revoke_all_sessions(db, target.id)
    audit(db, "team.sessions_revoked", actor_id=actor.id, actor_type="staff", target_type="user",
          target_id=target.id, details={"count": n})
    db.commit()
    return n


def activity(db: Session, actor: User, user_id: uuid.UUID, limit: int = 50) -> dict:
    _ensure_manager(actor)
    target = _get(db, user_id)
    events = db.scalars(select(AuditLog).where(AuditLog.actor_id == target.id)
                        .order_by(AuditLog.created_at.desc()).limit(limit))
    sessions = db.scalars(select(UserSession).where(UserSession.user_id == target.id)
                          .order_by(UserSession.created_at.desc()).limit(20))
    return {
        "user_id": str(target.id), "last_login_at": target.last_login_at,
        "events": [{"action": e.action, "at": e.created_at, "target_type": e.target_type,
                    "target_id": e.target_id, "ip_address": getattr(e, "ip_address", None)} for e in events],
        "sessions": [{"id": str(s.id), "created_at": s.created_at, "last_used_at": s.last_used_at,
                      "user_agent": s.user_agent, "ip_address": s.ip_address,
                      "active": s.revoked_at is None and (s.expires_at if s.expires_at.tzinfo else
                                                          s.expires_at.replace(tzinfo=utcnow().tzinfo)) > utcnow()}
                     for s in sessions],
    }


def list_team(db: Session) -> list[User]:
    order = (User.is_primary_admin.desc(), User.created_at)
    return list(db.scalars(select(User).order_by(*order)))
