"""Password hashing, JWT tokens, opaque tokens, encryption at rest and signatures."""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from cryptography.fernet import Fernet, InvalidToken

from app.core.config import settings
from app.core.errors import Unauthorized

_hasher = PasswordHasher()
JWT_ALG = "HS256"


# ---------------------------------------------------------------- passwords
def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def password_policy_errors(password: str) -> list[str]:
    errors = []
    if len(password) < 10:
        errors.append("at least 10 characters")
    if not any(c.islower() for c in password):
        errors.append("a lowercase letter")
    if not any(c.isupper() for c in password):
        errors.append("an uppercase letter")
    if not any(c.isdigit() for c in password):
        errors.append("a digit")
    return errors


# ---------------------------------------------------------------- JWT
def create_access_token(user_id: uuid.UUID, session_id: uuid.UUID, role: str) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "sid": str(session_id),
        "role": role,
        "typ": "access",
        "iat": now,
        "exp": now + timedelta(minutes=settings.access_token_ttl_minutes),
        "jti": secrets.token_hex(8),
    }
    return jwt.encode(payload, settings.secret_key, algorithm=JWT_ALG)


def create_challenge_token(user_id: uuid.UUID) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "typ": "2fa_challenge",
        "iat": now,
        "exp": now + timedelta(minutes=settings.two_factor_challenge_ttl_minutes),
    }
    return jwt.encode(payload, settings.secret_key, algorithm=JWT_ALG)


def decode_token(token: str, expected_type: str) -> dict[str, Any]:
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[JWT_ALG])
    except jwt.ExpiredSignatureError as exc:
        raise Unauthorized("Token expired", code="token_expired") from exc
    except jwt.PyJWTError as exc:
        raise Unauthorized("Invalid token", code="invalid_token") from exc
    if payload.get("typ") != expected_type:
        raise Unauthorized("Invalid token type", code="invalid_token")
    return payload


# ---------------------------------------------------------------- opaque tokens
def new_opaque_token(nbytes: int = 32) -> str:
    return secrets.token_urlsafe(nbytes)


def sha256_hex(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def constant_time_equals(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode(), b.encode())


# ---------------------------------------------------------------- encryption at rest
def _fernet() -> Fernet:
    material = settings.encryption_key or settings.secret_key
    key = base64.urlsafe_b64encode(hashlib.sha256(material.encode()).digest())
    return Fernet(key)


def encrypt(value: str) -> str:
    return _fernet().encrypt(value.encode()).decode()


def decrypt(token: str) -> str:
    try:
        return _fernet().decrypt(token.encode()).decode()
    except InvalidToken as exc:  # pragma: no cover - indicates key rotation problem
        raise RuntimeError("Unable to decrypt secret; check FINCORE_ENCRYPTION_KEY") from exc


# ---------------------------------------------------------------- webhook signatures
def sign_payload(secret: str, timestamp: int, body: bytes) -> str:
    mac = hmac.new(secret.encode(), f"{timestamp}.".encode() + body, hashlib.sha256)
    return mac.hexdigest()


def build_signature_header(secret: str, timestamp: int, body: bytes) -> str:
    return f"t={timestamp},v1={sign_payload(secret, timestamp, body)}"


def verify_signature_header(secret: str, header: str, body: bytes, tolerance_seconds: int = 300) -> bool:
    try:
        parts = dict(p.split("=", 1) for p in header.split(","))
        ts = int(parts["t"])
        sig = parts["v1"]
    except (KeyError, ValueError):
        return False
    now = int(datetime.now(timezone.utc).timestamp())
    if abs(now - ts) > tolerance_seconds:
        return False
    return hmac.compare_digest(sign_payload(secret, ts, body), sig)


# ---------------------------------------------------------------- references
def generate_reference(prefix: str = "FC") -> str:
    """Human-friendly, globally unique transaction reference, e.g. ``FC-20261106-7KQ2M9X4TZ``."""
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d")
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    rand = "".join(secrets.choice(alphabet) for _ in range(12))
    return f"{prefix}-{stamp}-{rand}"
