"""Payment provider abstraction.

Every external rail (MTN MoMo, Telecel Cash, AT Money, GhIPSS bank transfers, licensed gateways)
implements :class:`PaymentProvider`. Business logic never talks to a provider API directly.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Literal

ResultStatus = Literal["successful", "pending", "failed"]


@dataclass
class CollectionRequest:
    reference: str  # our internal reference (idempotency key at the provider)
    amount: Decimal
    currency: str
    msisdn: str | None = None
    network: str | None = None
    email: str | None = None
    description: str = ""
    callback_url: str | None = None


@dataclass
class DisbursementRequest:
    reference: str
    amount: Decimal
    currency: str
    channel: str  # mobile_money | bank
    msisdn: str | None = None
    network: str | None = None
    bank_code: str | None = None
    account_number: str | None = None
    account_name: str | None = None
    description: str = ""
    original_reference: str | None = None  # card refunds: the acquirer's reference of the original payment


@dataclass
class ProviderResult:
    status: ResultStatus
    provider_reference: str
    message: str = ""
    raw: dict = field(default_factory=dict)


@dataclass
class ProviderEvent:
    """Normalised inbound notification (webhook/callback) from a provider."""

    provider_reference: str
    internal_reference: str | None
    status: ResultStatus
    raw: dict = field(default_factory=dict)


@dataclass
class AccountLookup:
    valid: bool
    account_name: str | None = None
    message: str = ""


class PaymentProvider(ABC):
    code: str = "base"
    display_name: str = "Base provider"
    mode: Literal["sandbox", "live"] = "sandbox"
    supports_collection: bool = True
    supports_disbursement: bool = True

    @abstractmethod
    def collect(self, req: CollectionRequest) -> ProviderResult: ...

    @abstractmethod
    def disburse(self, req: DisbursementRequest) -> ProviderResult: ...

    @abstractmethod
    def check_status(self, provider_reference: str, direction: str) -> ProviderResult: ...

    def lookup_account(self, *, msisdn: str | None = None, bank_code: str | None = None,
                       account_number: str | None = None) -> AccountLookup:
        return AccountLookup(valid=True, message="Name lookup not supported by this provider")

    def verify_webhook(self, headers: dict[str, str], body: bytes) -> bool:
        return False

    def parse_webhook(self, body: dict) -> ProviderEvent:  # pragma: no cover - provider specific
        raise NotImplementedError

    def is_configured(self) -> bool:
        return True
