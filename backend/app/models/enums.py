"""String enums persisted as VARCHAR (keeps migrations simple when values are added)."""

from enum import StrEnum


class UserRole(StrEnum):
    CUSTOMER = "customer"
    SUPPORT = "support"
    COMPLIANCE = "compliance"
    FINANCE = "finance"
    ADMIN = "admin"
    SUPER_ADMIN = "super_admin"


STAFF_ROLES = {UserRole.SUPPORT, UserRole.COMPLIANCE, UserRole.FINANCE, UserRole.ADMIN, UserRole.SUPER_ADMIN}


class UserStatus(StrEnum):
    ACTIVE = "active"
    RESTRICTED = "restricted"
    FROZEN = "frozen"
    CLOSED = "closed"


class RestrictionType(StrEnum):
    NO_DEBIT = "no_debit"
    NO_CREDIT = "no_credit"
    FULL_FREEZE = "full_freeze"
    LOGIN_BLOCK = "login_block"


class KycStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class AccountType(StrEnum):
    ASSET = "asset"
    LIABILITY = "liability"
    EQUITY = "equity"
    REVENUE = "revenue"
    EXPENSE = "expense"


DEBIT_NORMAL = {AccountType.ASSET, AccountType.EXPENSE}


class EntryDirection(StrEnum):
    DEBIT = "debit"
    CREDIT = "credit"


class TxnType(StrEnum):
    DEPOSIT = "deposit"
    WITHDRAWAL = "withdrawal"
    TRANSFER = "transfer"
    PAYMENT = "payment"
    REFUND = "refund"
    SETTLEMENT = "settlement"
    REVERSAL = "reversal"
    ADJUSTMENT = "adjustment"


class TxnStatus(StrEnum):
    PENDING = "pending"
    PROCESSING = "processing"
    SUCCESSFUL = "successful"
    FAILED = "failed"
    REVERSED = "reversed"


class Channel(StrEnum):
    WALLET = "wallet"
    MOBILE_MONEY = "mobile_money"
    BANK = "bank"
    CARD = "card"


class MobileNetwork(StrEnum):
    MTN = "mtn"
    TELECEL = "telecel"
    AT = "at"


class BusinessStatus(StrEnum):
    PENDING = "pending"
    ACTIVE = "active"
    SUSPENDED = "suspended"
    REJECTED = "rejected"


class BusinessRole(StrEnum):
    OWNER = "owner"
    ADMIN = "admin"
    FINANCE = "finance"
    DEVELOPER = "developer"
    SUPPORT = "support"
    VIEWER = "viewer"


class PaymentStatus(StrEnum):
    PENDING = "pending"
    PROCESSING = "processing"
    SUCCESSFUL = "successful"
    FAILED = "failed"
    EXPIRED = "expired"
    CANCELLED = "cancelled"
    REFUNDED = "refunded"
    PARTIALLY_REFUNDED = "partially_refunded"


class ApiEnvironment(StrEnum):
    SANDBOX = "sandbox"
    LIVE = "live"
