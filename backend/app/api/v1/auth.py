from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import Principal, client_ip, current_user, get_principal
from app.core.config import settings
from app.core.database import get_db
from app.core.errors import Forbidden, Unauthorized
from app.models.ops import SystemSetting
from app.models.user import User, UserSession
from app.schemas.common import (
    CodeIn,
    Disable2faIn,
    LoginIn,
    Message,
    PasswordChangeIn,
    PasswordForgotIn,
    PasswordResetIn,
    RefreshIn,
    RegisterIn,
    SessionOut,
    TokenOut,
    TwoFactorLoginIn,
    UserOut,
)
from app.services import auth as svc

router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.post("/register", response_model=UserOut, status_code=201)
def register(body: RegisterIn, db: Session = Depends(get_db)):
    s = db.get(SystemSetting, "signup_enabled")
    if s and not s.value.get("enabled", True):
        raise Forbidden("New registrations are temporarily paused", code="signup_disabled")
    return svc.register(db, email=body.email, password=body.password, full_name=body.full_name, phone=body.phone)


# ---------------------------------------------------------------- refresh-token transport
# Browser clients send ``X-FinCore-Client: web``: their refresh token is set as an HttpOnly cookie scoped to
# the auth endpoints and never exposed to JavaScript. Other clients (mobile apps, scripts) receive it in
# the JSON body as before. Cookie-based refreshes must carry ``X-FinCore-CSRF: 1`` — a custom header that a
# cross-site form or image request cannot add — on top of SameSite=Strict.
REFRESH_COOKIE = "fincore_rt"


def _is_web(request: Request) -> bool:
    return request.headers.get("x-fincore-client", "").lower() == "web"


def _set_refresh_cookie(response: Response, token: str) -> None:
    response.set_cookie(REFRESH_COOKIE, token, httponly=True, samesite="strict",
                        secure=settings.environment in ("staging", "production"),
                        max_age=settings.refresh_token_ttl_days * 86400, path=f"{settings.api_prefix}/auth")


def _clear_refresh_cookie(response: Response) -> None:
    response.delete_cookie(REFRESH_COOKIE, path=f"{settings.api_prefix}/auth")


def _deliver_tokens(request: Request, response: Response, tokens: dict, *, cookie: bool | None = None) -> dict:
    """Put the refresh token in the HttpOnly cookie (web clients) or leave it in the body (others)."""
    use_cookie = _is_web(request) if cookie is None else cookie
    if tokens.get("refresh_token") and use_cookie:
        _set_refresh_cookie(response, tokens["refresh_token"])
        tokens = {**tokens, "refresh_token": None}
    return tokens


@router.post("/login", response_model=TokenOut)
def login(body: LoginIn, request: Request, response: Response, db: Session = Depends(get_db)):
    tokens = svc.login(db, email=body.email, password=body.password,
                       user_agent=request.headers.get("user-agent"), ip=client_ip(request))
    return _deliver_tokens(request, response, tokens)


@router.post("/login/2fa", response_model=TokenOut)
def login_2fa(body: TwoFactorLoginIn, request: Request, response: Response, db: Session = Depends(get_db)):
    tokens = svc.complete_2fa_login(db, challenge_token=body.challenge_token, code=body.code,
                                    user_agent=request.headers.get("user-agent"), ip=client_ip(request))
    return _deliver_tokens(request, response, tokens)


@router.post("/refresh", response_model=TokenOut)
def refresh(request: Request, response: Response, body: RefreshIn | None = None, db: Session = Depends(get_db)):
    from_cookie = not (body and body.refresh_token)
    token = request.cookies.get(REFRESH_COOKIE) if from_cookie else body.refresh_token
    if from_cookie and token and request.headers.get("x-fincore-csrf") != "1":
        raise Forbidden("Missing CSRF header", code="csrf_required")
    if not token:
        raise Unauthorized("Session expired. Please sign in again.", code="session_expired")
    tokens = svc.refresh(db, token)
    return _deliver_tokens(request, response, tokens, cookie=from_cookie)


@router.post("/logout", response_model=Message)
def logout(response: Response, p: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    svc.revoke_session(db, p.user, p.session_id)
    _clear_refresh_cookie(response)
    return {"message": "Signed out"}


@router.post("/verify-email", response_model=Message)
def verify_email(token: str, db: Session = Depends(get_db)):
    svc.verify_email(db, token)
    return {"message": "Email verified"}


@router.post("/resend-verification", response_model=Message)
def resend_verification(user: User = Depends(current_user), db: Session = Depends(get_db)):
    from app.core.config import settings
    from app.services.notifications import queue_email

    if not user.email_verified:
        queue_email(db, user.email, "Verify your FinCore email",
                    f"Confirm your email: {settings.frontend_base_url}/verify-email?token="
                    f"{svc.email_verification_token(user)}", user_id=user.id)
        db.commit()
    return {"message": "If your email is unverified, a new link has been sent"}


@router.post("/password/forgot", response_model=Message)
def forgot(body: PasswordForgotIn, db: Session = Depends(get_db)):
    svc.request_password_reset(db, body.email)
    return {"message": "If an account exists for that email, a reset link has been sent"}


@router.post("/password/reset", response_model=Message)
def reset(body: PasswordResetIn, db: Session = Depends(get_db)):
    svc.reset_password(db, body.token, body.new_password)
    return {"message": "Password updated. Please sign in."}


@router.post("/password/change", response_model=Message)
def change(body: PasswordChangeIn, p: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    svc.change_password(db, p.user, body.current_password, body.new_password, p.session_id)
    return {"message": "Password changed"}


@router.post("/2fa/setup")
def setup_2fa(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return svc.setup_2fa(db, user)


@router.post("/2fa/enable", response_model=Message)
def enable_2fa(body: CodeIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    svc.enable_2fa(db, user, body.code)
    return {"message": "Two-factor authentication enabled"}


@router.post("/2fa/disable", response_model=Message)
def disable_2fa(body: Disable2faIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    svc.disable_2fa(db, user, body.password, body.code)
    return {"message": "Two-factor authentication disabled"}


@router.get("/sessions", response_model=list[SessionOut])
def sessions(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return db.scalars(select(UserSession).where(UserSession.user_id == user.id, UserSession.revoked_at.is_(None))
                      .order_by(UserSession.created_at.desc())).all()


@router.delete("/sessions/{session_id}", response_model=Message)
def revoke(session_id: uuid.UUID, user: User = Depends(current_user), db: Session = Depends(get_db)):
    svc.revoke_session(db, user, session_id)
    return {"message": "Session revoked"}


@router.post("/sessions/revoke-others", response_model=Message)
def revoke_others(p: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    n = svc.revoke_all_sessions(db, p.user.id, except_session=p.session_id)
    db.commit()
    return {"message": f"Signed out of {n} other session(s)"}
