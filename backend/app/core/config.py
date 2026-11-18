"""Application configuration.

All settings are read from environment variables prefixed with ``FINCORE_``
(or from a ``.env`` file). See ``backend/.env.example`` for the full list.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEV_SECRET = "dev-only-insecure-secret-key-change-me-0123456789abcdef"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="FINCORE_", extra="ignore")

    app_name: str = "FinCore"
    environment: str = Field(default="development", description="development|test|staging|production")
    debug: bool = False
    api_prefix: str = "/api/v1"
    public_base_url: str = "http://localhost:8000"
    frontend_base_url: str = "http://localhost:5173"

    database_url: str = "postgresql+psycopg://fincore:fincore@localhost:5432/fincore"
    db_pool_size: int = 10
    db_max_overflow: int = 20

    secret_key: str = DEV_SECRET
    # Separate key used to encrypt secrets at rest (webhook secrets, TOTP seeds).
    # In production this should come from a KMS / secrets manager.
    encryption_key: str = ""
    access_token_ttl_minutes: int = 15
    refresh_token_ttl_days: int = 14
    password_reset_ttl_minutes: int = 30
    two_factor_challenge_ttl_minutes: int = 5
    max_failed_logins: int = 5
    lockout_minutes: int = 15

    cors_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]

    default_currency: str = "GHS"
    supported_currencies: list[str] = ["GHS"]

    # Real-money switch. Must stay False until provider contracts, Bank of Ghana
    # authorisation and production credentials are in place.
    live_payments_enabled: bool = False

    rate_limit_per_minute: int = 300
    auth_rate_limit_per_minute: int = 20

    webhook_max_attempts: int = 8
    webhook_timeout_seconds: float = 10.0

    # --- Payment provider credentials (all optional; adapters stay in sandbox without them) ---
    # ---- MTN MoMo (Collections / Disbursements). Two completely separate credential profiles. ----
    # off        : MTN payments use the clearly-labelled simulator (development only)
    # sandbox    : MTN developer sandbox — real MTN API, test money only, no real phone prompts
    # production : real money — only after MTN Ghana partner onboarding AND FINCORE_LIVE_PAYMENTS_ENABLED=true
    mtn_momo_mode: str = "off"
    mtn_sandbox_base_url: str = "https://sandbox.momodeveloper.mtn.com"
    mtn_sandbox_collection_subscription_key: str = ""
    mtn_sandbox_collection_api_user: str = ""
    mtn_sandbox_collection_api_key: str = ""
    mtn_sandbox_disbursement_subscription_key: str = ""
    mtn_sandbox_disbursement_api_user: str = ""
    mtn_sandbox_disbursement_api_key: str = ""
    mtn_sandbox_callback_url: str = ""
    mtn_production_base_url: str = "https://proxy.momoapi.mtn.com"
    mtn_production_target_environment: str = "mtnghana"
    mtn_production_collection_subscription_key: str = ""
    mtn_production_collection_api_user: str = ""
    mtn_production_collection_api_key: str = ""
    mtn_production_disbursement_subscription_key: str = ""
    mtn_production_disbursement_api_user: str = ""
    mtn_production_disbursement_api_key: str = ""
    mtn_production_callback_url: str = ""
    # Shared secret that must appear as ?token=... on MTN callback URLs (callbacks are unsigned by MTN).
    mtn_callback_token: str = ""
    # A RequestToPay still pending after this long is treated as expired (payer never approved).
    mtn_request_expiry_minutes: int = 15

    telecel_cash_base_url: str = ""
    telecel_cash_client_id: str = ""
    telecel_cash_client_secret: str = ""

    at_money_base_url: str = ""
    at_money_client_id: str = ""
    at_money_client_secret: str = ""

    paystack_base_url: str = "https://api.paystack.co"
    paystack_secret_key: str = ""

    ghipss_base_url: str = ""
    ghipss_institution_code: str = ""
    ghipss_api_key: str = ""

    # Which adapter handles each channel when live payments are enabled.
    # Values: sandbox | telecel_cash | at_money | ghipss  (MTN is chosen by FINCORE_MTN_MOMO_MODE)
    route_telecel: str = "sandbox"
    route_at: str = "sandbox"
    route_bank: str = "sandbox"
    card_acquirer: str = "bank_card"  # used only when live payments are enabled

    # Acquiring bank for cards (from the merchant/acquiring agreement)
    card_acquirer_base_url: str = ""
    card_acquirer_merchant_id: str = ""
    card_acquirer_api_key: str = ""
    card_acquirer_webhook_secret: str = ""

    investments_enabled: bool = False

    # --- File storage (KYC documents) ---
    storage_backend: str = "local"  # local | s3
    storage_local_dir: str = "var/storage"
    storage_s3_bucket: str = ""
    storage_s3_region: str = ""
    storage_s3_endpoint_url: str = ""  # set for S3-compatible stores (MinIO, Wasabi, DigitalOcean Spaces...)
    storage_s3_access_key_id: str = ""
    storage_s3_secret_access_key: str = ""
    storage_signed_url_ttl_seconds: int = 300
    kyc_max_upload_bytes: int = 5 * 1024 * 1024

    @field_validator("environment")
    @classmethod
    def _env(cls, v: str) -> str:
        allowed = {"development", "test", "staging", "production"}
        if v not in allowed:
            raise ValueError(f"environment must be one of {sorted(allowed)}")
        return v

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    def validate_for_runtime(self) -> None:
        """Refuse to boot staging/production with insecure defaults."""
        if self.environment in {"staging", "production"}:
            if self.secret_key == DEV_SECRET or len(self.secret_key) < 32:
                raise RuntimeError("FINCORE_SECRET_KEY must be set to a strong value outside development")
            if not self.encryption_key:
                raise RuntimeError("FINCORE_ENCRYPTION_KEY must be set outside development")
        if self.mtn_momo_mode not in ("off", "sandbox", "production"):
            raise RuntimeError("FINCORE_MTN_MOMO_MODE must be off, sandbox or production")
        if self.mtn_momo_mode == "production" and not self.live_payments_enabled:
            raise RuntimeError("MTN production mode requires FINCORE_LIVE_PAYMENTS_ENABLED=true")
        if self.live_payments_enabled and self.mtn_momo_mode == "sandbox":
            raise RuntimeError("Live payments cannot run on the MTN sandbox; use FINCORE_MTN_MOMO_MODE=production")
        if self.environment == "production" and self.mtn_momo_mode == "sandbox":
            raise RuntimeError("The production deployment must not use MTN sandbox credentials")


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
