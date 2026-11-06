from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import jwt
import pyotp
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import utcnow
from app.core.errors import AccountRestricted, Conflict, Unauthorized, ValidationFailed
from app.core.security import (
    JWT_ALG,
    create_access_token,
    create_challenge_token,
    decode_token,
    decrypt,
    encrypt,
    hash_password,
    new_opaque_token,
    password_policy_errors,
    sha256_hex,
    verify_password,
)
from app.models.enums import RestrictionType, UserRole, UserStatus
from app.models.user import PasswordResetToken, User, UserSession
from app.services.audit import audit
from app.services.ghana import normalize_msisdn
from app.services.notifications import notify, queue_email
from app.services.restrictions import active_restrictions
from app.services.wallets import create_wallet

# Pre-computed hash so login timing doesn't reveal whether an email exists.
_DUMMY_HASH = hash_password("timing-equaliser-Password1")


def _aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def check_password_policy(password: str) -> None:
    errors = password_policy_errors(password)
    if errors:
        raise ValidationFailed("Password must contain " + ", ".join(errors), details={"password": errors})


def register(db: Session, *, email: str, password: str, full_name: str, phone: str | None,
             role: UserRole = UserRole.CUSTOMER) -> User:
    email = email.strip().lower()
    check_password_policy(password)
    msisdn = normalize_msisdn(phone) if phone else None
    if db.scalar(select(User.id).where(User.email == email)):
        raise Conflict("An account with this email already exists", code="email_taken")
    if msisdn and db.scalar(select(User.id).where(User.phone == msisdn)):
        raise Conflict("An account with this phone number already exists", code="phone_taken")
    user = User(email=email, full_name=full_name.strip(), phone=msisdn, password_hash=hash_password(password),
                role=role.value, status=UserStatus.ACTIVE, kyc_tier=0, password_changed_at=utcnow())
    db.add(user)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise Conflict("An account with these details already exists") from exc
    create_wallet(db, user=user, currency=settings.default_currency, label="Main", is_default=True)
    token = email_verification_token(user)
    queue_email(db, user.email, "Verify your FinCore email",
                f"Welcome to FinCore, {user.full_name}!\n\nConfirm your email: "
                f"{settings.frontend_base_url}/verify-email?token={token}", user_id=user.id)
    notify(db, user.id, "welcome", "Welcome to FinCore",
           "Your GHS wallet is ready. Verify your identity to raise your limits.")
    audit(db, "user.registered", actor_id=user.id, target_type="user", target_id=user.id)
    db.commit()
    return user


def email_verification_token(user: User) -> str:
    now = datetime.now(timezone.utc)
    return jwt.encode({"sub": str(user.id), "typ": "email_verify", "email": user.email, "iat": now,
                       "exp": now + timedelta(hours=48)}, settings.secret_key, algorithm=JWT_ALG)


def verify_email(db: Session, token: str) -> User:
    payload = decode_token(token, "email_verify")
    user = db.get(User, uuid.UUID(payload["sub"]))
    if not user or user.email != payload.get("email"):
        raise Unauthorized("Invalid verification link")
    user.email_verified = True
    audit(db, "user.email_verified", actor_id=user.id, target_type="user", target_id=user.id)
    db.commit()
    return user


def _issue_session(db: Session, user: User, user_agent: str | None, ip: str | None) -> dict:
    refresh = "rt_" + new_opaque_token()
    session = UserSession(user_id=user.id, refresh_token_hash=sha256_hex(refresh), user_agent=(user_agent or "")[:400],
                          ip_address=ip, expires_at=utcnow() + timedelta(days=settings.refresh_token_ttl_days),
                          last_used_at=utcnow())
    db.add(session)
    db.flush()
    user.last_login_at = utcnow()
    return {
        "access_token": create_access_token(user.id, session.id, user.role),
        "refresh_token": refresh,
        "token_type": "bearer",
        "expires_in": settings.access_token_ttl_minutes * 60,
        "session_id": str(session.id),
    }


def _assert_can_login(db: Session, user: User) -> None:
    if user.status == UserStatus.CLOSED:
        raise AccountRestricted("This account has been closed")
    if RestrictionType.LOGIN_BLOCK in active_restrictions(db, user.id):
        raise AccountRestricted("Sign-in is blocked for this account. Please contact support.")


def login(db: Session, *, email: str, password: str, user_agent: str | None, ip: str | None) -> dict:
    user = db.scalar(select(User).where(User.email == email.strip().lower()))
    if not user:
        verify_password(password, _DUMMY_HASH)
        raise Unauthorized("Incorrect email or password", code="invalid_credentials")
    now = utcnow()
    if user.locked_until and _aware(user.locked_until) > now:
        raise Unauthorized("Too many failed attempts. Try again later.", code="account_locked")
    if not verify_password(password, user.password_hash):
        user.failed_login_count += 1
        if user.failed_login_count >= settings.max_failed_logins:
            user.locked_until = now + timedelta(minutes=settings.lockout_minutes)
            user.failed_login_count = 0
            audit(db, "user.locked_out", actor_id=user.id, target_type="user", target_id=user.id)
        audit(db, "user.login_failed", actor_id=user.id, target_type="user", target_id=user.id)
        db.commit()
        raise Unauthorized("Incorrect email or password", code="invalid_credentials")
    _assert_can_login(db, user)
    user.failed_login_count = 0
    user.locked_until = None
    if user.totp_enabled:
        db.commit()
        return {"requires_2fa": True, "challenge_token": create_challenge_token(user.id)}
    tokens = _issue_session(db, user, user_agent, ip)
    audit(db, "user.login", actor_id=user.id, target_type="user", target_id=user.id)
    db.commit()
    return {"requires_2fa": False, **tokens}


def complete_2fa_login(db: Session, *, challenge_token: str, code: str, user_agent: str | None,
                       ip: str | None) -> dict:
    payload = decode_token(challenge_token, "2fa_challenge")
    user = db.get(User, uuid.UUID(payload["sub"]))
    if not user or not user.totp_enabled:
        raise Unauthorized("Invalid challenge")
    _assert_can_login(db, user)
    if not _verify_totp(user, code):
        audit(db, "user.2fa_failed", actor_id=user.id, target_type="user", target_id=user.id)
        db.commit()
        raise Unauthorized("Invalid authentication code", code="invalid_otp")
    tokens = _issue_session(db, user, user_agent, ip)
    audit(db, "user.login", actor_id=user.id, target_type="user", target_id=user.id, details={"2fa": True})
    db.commit()
    return {"requires_2fa": False, **tokens}


def refresh(db: Session, refresh_token: str) -> dict:
    session = db.scalar(select(UserSession).where(UserSession.refresh_token_hash == sha256_hex(refresh_token)))
    if not session or session.revoked_at or _aware(session.expires_at) <= utcnow():
        raise Unauthorized("Session expired. Please sign in again.", code="session_expired")
    user = db.get(User, session.user_id)
    _assert_can_login(db, user)
    new_refresh = "rt_" + new_opaque_token()
    session.refresh_token_hash = sha256_hex(new_refresh)  # rotate on every use
    session.last_used_at = utcnow()
    db.commit()
    return {"access_token": create_access_token(user.id, session.id, user.role), "refresh_token": new_refresh,
            "token_type": "bearer", "expires_in": settings.access_token_ttl_minutes * 60,
            "session_id": str(session.id)}


def revoke_session(db: Session, user: User, session_id: uuid.UUID) -> None:
    session = db.get(UserSession, session_id)
    if not session or session.user_id != user.id:
        raise Unauthorized("Session not found")
    session.revoked_at = session.revoked_at or utcnow()
    audit(db, "user.session_revoked", actor_id=user.id, target_type="session", target_id=session_id)
    db.commit()


def revoke_all_sessions(db: Session, user_id: uuid.UUID, except_session: uuid.UUID | None = None) -> int:
    count = 0
    for s in db.scalars(select(UserSession).where(UserSession.user_id == user_id, UserSession.revoked_at.is_(None))):
        if s.id != except_session:
            s.revoked_at = utcnow()
            count += 1
    return count


def request_password_reset(db: Session, email: str) -> None:
    user = db.scalar(select(User).where(User.email == email.strip().lower()))
    if not user:
        return  # don't reveal whether the email exists
    token = new_opaque_token()
    db.add(PasswordResetToken(user_id=user.id, token_hash=sha256_hex(token),
                              expires_at=utcnow() + timedelta(minutes=settings.password_reset_ttl_minutes)))
    queue_email(db, user.email, "Reset your FinCore password",
                f"Use this link within {settings.password_reset_ttl_minutes} minutes: "
                f"{settings.frontend_base_url}/reset-password?token={token}\n\n"
                "If you didn't request this, you can ignore this email.", user_id=user.id)
    audit(db, "user.password_reset_requested", actor_id=user.id, target_type="user", target_id=user.id)
    db.commit()


def reset_password(db: Session, token: str, new_password: str) -> None:
    rec = db.scalar(select(PasswordResetToken).where(PasswordResetToken.token_hash == sha256_hex(token)))
    if not rec or rec.used_at or _aware(rec.expires_at) <= utcnow():
        raise Unauthorized("This reset link is invalid or has expired", code="invalid_reset_token")
    check_password_policy(new_password)
    user = db.get(User, rec.user_id)
    user.password_hash = hash_password(new_password)
    user.password_changed_at = utcnow()
    user.failed_login_count = 0
    user.locked_until = None
    rec.used_at = utcnow()
    revoke_all_sessions(db, user.id)
    notify(db, user.id, "security", "Password changed", "Your password was reset. All sessions were signed out.")
    audit(db, "user.password_reset", actor_id=user.id, target_type="user", target_id=user.id)
    db.commit()


def change_password(db: Session, user: User, current: str, new: str, session_id: uuid.UUID | None) -> None:
    if not verify_password(current, user.password_hash):
        raise Unauthorized("Current password is incorrect", code="invalid_credentials")
    check_password_policy(new)
    user.password_hash = hash_password(new)
    user.password_changed_at = utcnow()
    revoke_all_sessions(db, user.id, except_session=session_id)
    notify(db, user.id, "security", "Password changed", "Your password was changed. Other sessions were signed out.")
    audit(db, "user.password_changed", actor_id=user.id, target_type="user", target_id=user.id)
    db.commit()


# ---------------------------------------------------------------- TOTP 2FA
def _verify_totp(user: User, code: str) -> bool:
    if not user.totp_secret_enc:
        return False
    return pyotp.TOTP(decrypt(user.totp_secret_enc)).verify(code.strip(), valid_window=1)


def setup_2fa(db: Session, user: User) -> dict:
    if user.totp_enabled:
        raise Conflict("Two-factor authentication is already enabled")
    secret = pyotp.random_base32()
    user.totp_secret_enc = encrypt(secret)
    db.commit()
    uri = pyotp.TOTP(secret).provisioning_uri(name=user.email, issuer_name="FinCore")
    return {"secret": secret, "otpauth_uri": uri}


def enable_2fa(db: Session, user: User, code: str) -> None:
    if not _verify_totp(user, code):
        raise ValidationFailed("Invalid authentication code")
    user.totp_enabled = True
    notify(db, user.id, "security", "Two-factor authentication enabled", "Your account is now protected by 2FA.")
    audit(db, "user.2fa_enabled", actor_id=user.id, target_type="user", target_id=user.id)
    db.commit()


def disable_2fa(db: Session, user: User, password: str, code: str) -> None:
    if not verify_password(password, user.password_hash) or not _verify_totp(user, code):
        raise Unauthorized("Password or authentication code is incorrect")
    user.totp_enabled = False
    user.totp_secret_enc = None
    notify(db, user.id, "security", "Two-factor authentication disabled", "2FA was turned off for your account.")
    audit(db, "user.2fa_disabled", actor_id=user.id, target_type="user", target_id=user.id)
    db.commit()
