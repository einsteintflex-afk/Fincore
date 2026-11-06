"""Provider registry and routing."""

from __future__ import annotations

from app.core.config import settings
from app.core.errors import ValidationFailed
from app.providers.base import PaymentProvider
from app.providers.mtn_momo import MtnMomoProvider
from app.providers.paystack import PaystackProvider
from app.providers.pending import AtMoneyProvider, GhipssProvider, TelecelCashProvider
from app.providers.sandbox import SandboxProvider

PROVIDER_CLASSES: dict[str, type[PaymentProvider]] = {
    "sandbox": SandboxProvider,
    "mtn_momo": MtnMomoProvider,
    "paystack": PaystackProvider,
    "telecel_cash": TelecelCashProvider,
    "at_money": AtMoneyProvider,
    "ghipss": GhipssProvider,
}

_instances: dict[str, PaymentProvider] = {}
_overrides: dict[str, PaymentProvider] = {}


def get_provider(code: str) -> PaymentProvider:
    if code in _overrides:
        return _overrides[code]
    if code not in PROVIDER_CLASSES:
        raise ValidationFailed(f"Unknown provider {code}")
    if code not in _instances:
        _instances[code] = PROVIDER_CLASSES[code]()
    return _instances[code]


def override_provider(code: str, provider: PaymentProvider | None) -> None:
    """Testing hook."""
    if provider is None:
        _overrides.pop(code, None)
    else:
        _overrides[code] = provider


def route(channel: str, network: str | None = None, *, sandbox: bool = False) -> PaymentProvider:
    """Choose the provider for a channel/network.

    While ``FINCORE_LIVE_PAYMENTS_ENABLED`` is false, or for sandbox API traffic, everything goes to the
    simulated sandbox provider so no real money can move.
    """
    if sandbox or not settings.live_payments_enabled:
        return get_provider("sandbox")
    if channel == "mobile_money":
        code = {"mtn": settings.route_mtn, "telecel": settings.route_telecel, "at": settings.route_at}.get(network or "")
        if not code:
            raise ValidationFailed("Unsupported mobile money network")
    elif channel == "bank":
        code = settings.route_bank
    else:
        raise ValidationFailed(f"Unsupported channel {channel}")
    return get_provider(code)


def provider_status() -> list[dict]:
    out = []
    for code, cls in PROVIDER_CLASSES.items():
        p = get_provider(code)
        out.append({"code": code, "name": cls.display_name, "configured": p.is_configured(),
                    "mode": p.mode, "collection": cls.supports_collection, "disbursement": cls.supports_disbursement})
    return out
