from __future__ import annotations

from typing import Any


class AppError(Exception):
    """Base domain error. Rendered as ``{"error": {"code", "message", "details"}}``."""

    status_code = 400
    code = "bad_request"

    def __init__(self, message: str, *, code: str | None = None, status_code: int | None = None,
                 details: Any = None) -> None:
        super().__init__(message)
        self.message = message
        if code:
            self.code = code
        if status_code:
            self.status_code = status_code
        self.details = details


class NotFound(AppError):
    status_code = 404
    code = "not_found"


class Unauthorized(AppError):
    status_code = 401
    code = "unauthorized"


class Forbidden(AppError):
    status_code = 403
    code = "forbidden"


class Conflict(AppError):
    status_code = 409
    code = "conflict"


class ValidationFailed(AppError):
    status_code = 422
    code = "validation_failed"


class InsufficientFunds(AppError):
    status_code = 422
    code = "insufficient_funds"


class LimitExceeded(AppError):
    status_code = 422
    code = "limit_exceeded"


class AccountRestricted(AppError):
    status_code = 403
    code = "account_restricted"


class LedgerError(AppError):
    status_code = 500
    code = "ledger_error"


class ProviderError(AppError):
    status_code = 502
    code = "provider_error"


class ProviderNotConfigured(AppError):
    status_code = 503
    code = "provider_not_configured"


class RateLimited(AppError):
    status_code = 429
    code = "rate_limited"


class FeatureDisabled(AppError):
    status_code = 503
    code = "feature_disabled"
