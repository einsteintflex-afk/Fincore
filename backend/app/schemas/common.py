from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Any, Generic, TypeVar

from pydantic import AliasChoices, BaseModel, ConfigDict, EmailStr, Field, PlainSerializer

T = TypeVar("T")

from app.core.money import to_api_str  # noqa: E402

# Output type for money: always a string such as "125.50".
Dec = Annotated[Decimal, PlainSerializer(to_api_str, return_type=str, when_used="json")]

# Money crosses the API as a string-encoded decimal ("125.50"). Floats are accepted on input but
# converted via their string repr, and precision is validated per currency in the service layer.
Money = Annotated[Decimal, Field(max_digits=18, decimal_places=4)]


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int
    page: int
    page_size: int


class Message(BaseModel):
    message: str


# ---------------------------------------------------------------- users & auth
class RegisterIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=10, max_length=128)
    full_name: str = Field(min_length=2, max_length=200)
    phone: str | None = None


class LoginIn(BaseModel):
    email: EmailStr
    password: str


class TwoFactorLoginIn(BaseModel):
    challenge_token: str
    code: str = Field(min_length=6, max_length=8)


class RefreshIn(BaseModel):
    refresh_token: str


class TokenOut(BaseModel):
    requires_2fa: bool = False
    challenge_token: str | None = None
    access_token: str | None = None
    refresh_token: str | None = None
    token_type: str | None = None
    expires_in: int | None = None
    session_id: str | None = None


class UserOut(ORM):
    id: uuid.UUID
    email: str
    phone: str | None
    full_name: str
    role: str
    status: str
    kyc_tier: int
    email_verified: bool
    totp_enabled: bool
    created_at: datetime
    last_login_at: datetime | None


class ProfileUpdateIn(BaseModel):
    full_name: str | None = Field(default=None, min_length=2, max_length=200)
    phone: str | None = None


class PasswordForgotIn(BaseModel):
    email: EmailStr


class PasswordResetIn(BaseModel):
    token: str
    new_password: str = Field(min_length=10, max_length=128)


class PasswordChangeIn(BaseModel):
    current_password: str
    new_password: str = Field(min_length=10, max_length=128)


class CodeIn(BaseModel):
    code: str = Field(min_length=6, max_length=8)


class Disable2faIn(BaseModel):
    password: str
    code: str


class SessionOut(ORM):
    id: uuid.UUID
    user_agent: str | None
    ip_address: str | None
    created_at: datetime
    last_used_at: datetime | None
    expires_at: datetime
    revoked_at: datetime | None


class NotificationOut(ORM):
    id: uuid.UUID
    type: str
    title: str
    body: str
    data: dict
    read_at: datetime | None
    created_at: datetime


class KycIn(BaseModel):
    tier_requested: int = Field(ge=1, le=3)
    id_type: str
    id_number: str
    first_name: str
    last_name: str
    date_of_birth: date
    address: str | None = None
    digital_address: str | None = None
    documents: dict[str, Any] | None = None


class KycOut(ORM):
    id: uuid.UUID
    user_id: uuid.UUID
    tier_requested: int
    id_type: str
    id_number: str
    first_name: str
    last_name: str
    date_of_birth: date
    address: str | None
    digital_address: str | None
    status: str
    review_note: str | None
    verification_result: dict
    created_at: datetime
    reviewed_at: datetime | None


# ---------------------------------------------------------------- wallets & transactions
class WalletOut(BaseModel):
    id: uuid.UUID
    account_number: str
    currency: str
    label: str
    is_default: bool
    status: str
    balance: Dec
    created_at: datetime


class WalletCreateIn(BaseModel):
    label: str = Field(min_length=1, max_length=100)
    currency: str = "GHS"


class DepositIn(BaseModel):
    wallet_id: uuid.UUID
    amount: Money
    phone: str
    description: str | None = None


class WithdrawIn(BaseModel):
    wallet_id: uuid.UUID
    amount: Money
    channel: str = Field(pattern="^(mobile_money|bank)$")
    phone: str | None = None
    bank_code: str | None = None
    account_number: str | None = None
    account_name: str | None = None
    description: str | None = None


class TransferIn(BaseModel):
    wallet_id: uuid.UUID
    destination_account: str
    amount: Money
    narration: str | None = Field(default=None, max_length=200)


class TransactionOut(ORM):
    id: uuid.UUID
    reference: str
    type: str
    status: str
    channel: str
    amount: Dec
    fee: Dec
    currency: str
    source_wallet_id: uuid.UUID | None
    destination_wallet_id: uuid.UUID | None
    provider: str | None
    provider_mode: str
    provider_reference: str | None
    counterparty: dict
    description: str
    failure_reason: str | None
    risk_score: int
    business_id: uuid.UUID | None
    initiated_by_id: uuid.UUID | None
    related_transaction_id: uuid.UUID | None
    created_at: datetime
    completed_at: datetime | None
    direction: str | None = None  # "in"/"out" relative to the viewer


class BeneficiaryIn(BaseModel):
    type: str = Field(pattern="^(wallet|mobile_money|bank)$")
    name: str
    nickname: str | None = None
    identifier: str
    bank_code: str | None = None


class BeneficiaryOut(ORM):
    id: uuid.UUID
    type: str
    name: str
    nickname: str | None
    identifier: str
    network: str | None
    bank_code: str | None
    favourite: bool
    created_at: datetime


class LookupOut(BaseModel):
    valid: bool
    account_name: str | None = None
    network: str | None = None
    message: str = ""


# ---------------------------------------------------------------- business & payments
class BusinessIn(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    trading_name: str | None = None
    registration_number: str | None = None
    tin: str | None = None
    business_type: str
    industry: str | None = None
    email: EmailStr
    phone: str | None = None
    address: str | None = None
    website: str | None = None


class BusinessUpdateIn(BaseModel):
    trading_name: str | None = None
    registration_number: str | None = None
    tin: str | None = None
    industry: str | None = None
    phone: str | None = None
    address: str | None = None
    website: str | None = None
    settlement_schedule: str | None = None


class BusinessOut(ORM):
    id: uuid.UUID
    name: str
    trading_name: str | None
    registration_number: str | None
    tin: str | None
    business_type: str
    industry: str | None
    email: str
    phone: str | None
    address: str | None
    website: str | None
    status: str
    review_note: str | None
    merchant_code: str
    settlement_schedule: str
    settlement_destination: dict
    owner_user_id: uuid.UUID
    created_at: datetime
    my_role: str | None = None


class SettlementDestinationIn(BaseModel):
    channel: str
    bank_code: str | None = None
    account_number: str | None = None
    phone: str | None = None
    account_name: str | None = None


class MemberIn(BaseModel):
    email: EmailStr
    role: str


class MemberUpdateIn(BaseModel):
    role: str | None = None
    remove: bool = False


class MemberOut(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    email: str
    full_name: str
    role: str
    status: str
    created_at: datetime


class PaymentRequestIn(BaseModel):
    amount: Money
    currency: str = "GHS"
    description: str | None = None
    customer_email: EmailStr | None = None
    customer_phone: str | None = None
    customer_name: str | None = None
    merchant_reference: str | None = Field(default=None, max_length=100)
    callback_url: str | None = None
    metadata: dict[str, Any] | None = None


class PaymentRequestOut(ORM):
    id: uuid.UUID
    reference: str
    merchant_reference: str | None
    business_id: uuid.UUID
    environment: str
    amount: Dec
    currency: str
    fee: Dec
    amount_refunded: Dec
    status: str
    description: str | None
    customer_name: str | None
    customer_email: str | None
    customer_phone: str | None
    channel: str | None
    network: str | None
    provider: str | None
    provider_reference: str | None
    failure_reason: str | None
    payment_link_id: uuid.UUID | None
    meta: dict = Field(validation_alias=AliasChoices("meta", "metadata"), serialization_alias="metadata")
    expires_at: datetime | None
    paid_at: datetime | None
    created_at: datetime
    checkout_url: str | None = None


class PaymentLinkIn(BaseModel):
    title: str = Field(min_length=2, max_length=200)
    description: str | None = None
    amount: Money | None = None
    currency: str = "GHS"
    single_use: bool = False
    redirect_url: str | None = None
    slug: str | None = Field(default=None, max_length=40)


class PaymentLinkUpdateIn(BaseModel):
    active: bool | None = None
    title: str | None = None
    description: str | None = None


class PaymentLinkOut(ORM):
    id: uuid.UUID
    slug: str
    title: str
    description: str | None
    amount: Dec | None
    currency: str
    active: bool
    single_use: bool
    redirect_url: str | None
    payments_count: int
    created_at: datetime
    url: str | None = None


class RefundIn(BaseModel):
    amount: Money | None = None
    reason: str | None = Field(default=None, max_length=300)


class RefundOut(ORM):
    id: uuid.UUID
    reference: str
    payment_request_id: uuid.UUID
    amount: Dec
    currency: str
    reason: str | None
    status: str
    created_at: datetime


class SettlementIn(BaseModel):
    amount: Money | None = None


class SettlementOut(ORM):
    id: uuid.UUID
    reference: str
    amount: Dec
    fee: Dec
    currency: str
    status: str
    destination: dict
    note: str | None
    created_at: datetime
    paid_at: datetime | None


class CheckoutPayMomoIn(BaseModel):
    phone: str


class CheckoutPayWalletIn(BaseModel):
    wallet_id: uuid.UUID


class LinkPayIn(BaseModel):
    amount: Money | None = None
    customer_email: EmailStr | None = None
    customer_name: str | None = None
    customer_phone: str | None = None


# ---------------------------------------------------------------- developer
class AppIn(BaseModel):
    business_id: uuid.UUID
    name: str = Field(min_length=2, max_length=120)
    description: str | None = None


class AppOut(ORM):
    id: uuid.UUID
    business_id: uuid.UUID
    name: str
    description: str | None
    status: str
    created_at: datetime


class ApiKeyIn(BaseModel):
    environment: str = Field(pattern="^(sandbox|live)$")


class ApiKeyOut(ORM):
    id: uuid.UUID
    environment: str
    public_key: str
    secret_prefix: str
    last4: str
    status: str
    created_at: datetime
    last_used_at: datetime | None
    secret_key: str | None = None  # only returned once, at creation


class WebhookIn(BaseModel):
    url: str
    environment: str = Field(default="sandbox", pattern="^(sandbox|live)$")
    events: list[str] = []
    description: str | None = None


class WebhookUpdateIn(BaseModel):
    active: bool | None = None
    events: list[str] | None = None
    url: str | None = None


class WebhookOut(ORM):
    id: uuid.UUID
    url: str
    environment: str
    events: list
    active: bool
    description: str | None
    created_at: datetime
    secret: str | None = None


class DeliveryOut(ORM):
    id: uuid.UUID
    endpoint_id: uuid.UUID
    event_id: str
    event_type: str
    status: str
    attempts: int
    last_response_code: int | None
    last_error: str | None
    next_attempt_at: datetime | None
    delivered_at: datetime | None
    created_at: datetime
    payload: dict


# ---------------------------------------------------------------- admin / ops
class RestrictionIn(BaseModel):
    type: str
    reason: str = Field(min_length=3)


class StatusIn(BaseModel):
    status: str
    reason: str = Field(min_length=3)


class RoleIn(BaseModel):
    role: str


class ReviewIn(BaseModel):
    decision: str
    note: str | None = None


class ReverseIn(BaseModel):
    reason: str = Field(min_length=3)


class AdjustIn(BaseModel):
    wallet_account_number: str
    amount: Money
    direction: str = Field(pattern="^(credit|debit)$")
    reason: str = Field(min_length=3)


class FeeRuleIn(BaseModel):
    name: str
    transaction_type: str
    channel: str | None = None
    currency: str = "GHS"
    payer: str = Field(default="customer", pattern="^(customer|merchant)$")
    flat_fee: Money = Decimal("0")
    percent_fee: Dec = Field(default=Decimal("0"), ge=0, le=Decimal("0.2"))
    min_fee: Money = Decimal("0")
    max_fee: Money | None = None
    active: bool = True


class FeeRuleOut(ORM):
    id: uuid.UUID
    name: str
    transaction_type: str
    channel: str | None
    currency: str
    payer: str
    flat_fee: Dec
    percent_fee: Dec
    min_fee: Dec
    max_fee: Dec | None
    active: bool
    updated_at: datetime


class LimitRuleIn(BaseModel):
    kyc_tier: int = Field(ge=0, le=3)
    transaction_type: str
    currency: str = "GHS"
    per_transaction_max: Money | None = None
    daily_max: Money | None = None
    monthly_max: Money | None = None
    max_balance: Money | None = None
    active: bool = True


class LimitRuleOut(ORM):
    id: uuid.UUID
    kyc_tier: int
    transaction_type: str
    currency: str
    per_transaction_max: Dec | None
    daily_max: Dec | None
    monthly_max: Dec | None
    max_balance: Dec | None
    active: bool


class AuditOut(ORM):
    id: uuid.UUID
    actor_id: uuid.UUID | None
    actor_type: str
    action: str
    target_type: str | None
    target_id: str | None
    ip_address: str | None
    request_id: str | None
    details: dict
    created_at: datetime


class FraudAlertOut(ORM):
    id: uuid.UUID
    user_id: uuid.UUID | None
    transaction_id: uuid.UUID | None
    rule: str
    severity: str
    score: int
    status: str
    details: dict
    notes: str | None
    assigned_to_id: uuid.UUID | None
    created_at: datetime
    resolved_at: datetime | None


class FraudAlertUpdateIn(BaseModel):
    status: str = Field(pattern="^(open|investigating|resolved|false_positive)$")
    notes: str | None = None
    restrict_user: bool = False


class SettingIn(BaseModel):
    value: dict[str, Any]


class TicketIn(BaseModel):
    subject: str = Field(min_length=3, max_length=200)
    category: str = "general"
    message: str = Field(min_length=3)
    transaction_reference: str | None = None


class TicketMessageIn(BaseModel):
    body: str = Field(min_length=1)
    internal: bool = False


class TicketUpdateIn(BaseModel):
    status: str | None = Field(default=None, pattern="^(open|pending|resolved|closed)$")
    priority: str | None = Field(default=None, pattern="^(low|normal|high|urgent)$")
    assign_to_me: bool = False


class TicketOut(ORM):
    id: uuid.UUID
    user_id: uuid.UUID
    subject: str
    category: str
    priority: str
    status: str
    transaction_reference: str | None
    assigned_to_id: uuid.UUID | None
    created_at: datetime
    updated_at: datetime


class TicketMessageOut(ORM):
    id: uuid.UUID
    author_id: uuid.UUID
    body: str
    internal: bool
    created_at: datetime


class ReconciliationOut(ORM):
    id: uuid.UUID
    kind: str
    provider: str | None
    status: str
    summary: dict
    discrepancies: list
    created_at: datetime


# ---------------------------------------------------------------- gateway (public API)
class ChargeIn(BaseModel):
    amount: Money
    currency: str = "GHS"
    email: EmailStr | None = None
    phone: str | None = None
    customer_name: str | None = None
    reference: str | None = Field(default=None, max_length=100, description="Your unique reference")
    description: str | None = None
    callback_url: str | None = None
    metadata: dict[str, Any] | None = None


class GatewayRefundIn(BaseModel):
    charge_reference: str
    amount: Money | None = None
    reason: str | None = None


class SandboxResolveIn(BaseModel):
    status: str = Field(pattern="^(successful|failed)$")


class ApprovalOut(ORM):
    id: uuid.UUID
    action: str
    payload: dict
    amount: str | None
    reason: str
    status: str
    requested_by_id: uuid.UUID
    reviewed_by_id: uuid.UUID | None
    review_note: str | None
    reviewed_at: datetime | None
    result: dict
    created_at: datetime
