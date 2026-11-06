"""Adapters whose public API specifications require a commercial agreement to obtain.

Telecel Cash, AT Money and GhIPSS (GIP / GhIPSS Instant Pay via a sponsor bank) issue their API
specifications and credentials only to contracted partners. These adapters define the configuration
surface and the integration points; each method raises ``ProviderNotConfigured`` until the partner
specification is implemented. See BLOCKERS.md and docs/PAYMENT_PROVIDERS.md.

Until then, the same networks can be reached in production through a licensed aggregator
(e.g. the Paystack adapter supports MTN, Telecel and AT mobile money).
"""

from __future__ import annotations

from app.core.config import settings
from app.core.errors import ProviderNotConfigured
from app.providers.base import CollectionRequest, DisbursementRequest, PaymentProvider, ProviderResult


class _PartnerSpecRequired(PaymentProvider):
    required_settings: tuple[str, ...] = ()

    def is_configured(self) -> bool:
        return all(getattr(settings, s) for s in self.required_settings)

    def _blocked(self):
        missing = [f"FINCORE_{s.upper()}" for s in self.required_settings if not getattr(settings, s)]
        if missing:
            raise ProviderNotConfigured(f"{self.display_name} is not configured. Missing: {', '.join(missing)}")
        raise ProviderNotConfigured(
            f"{self.display_name} credentials are present but the partner API specification has not been "
            "implemented yet. See docs/PAYMENT_PROVIDERS.md.")

    def collect(self, req: CollectionRequest) -> ProviderResult:
        self._blocked()

    def disburse(self, req: DisbursementRequest) -> ProviderResult:
        self._blocked()

    def check_status(self, provider_reference: str, direction: str) -> ProviderResult:
        self._blocked()


class TelecelCashProvider(_PartnerSpecRequired):
    code = "telecel_cash"
    display_name = "Telecel Cash"
    required_settings = ("telecel_cash_base_url", "telecel_cash_client_id", "telecel_cash_client_secret")


class AtMoneyProvider(_PartnerSpecRequired):
    code = "at_money"
    display_name = "AT Money"
    required_settings = ("at_money_base_url", "at_money_client_id", "at_money_client_secret")


class GhipssProvider(_PartnerSpecRequired):
    code = "ghipss"
    display_name = "GhIPSS Instant Pay (bank transfers)"
    supports_collection = False
    required_settings = ("ghipss_base_url", "ghipss_institution_code", "ghipss_api_key")
