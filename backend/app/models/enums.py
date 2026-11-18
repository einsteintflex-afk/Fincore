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
    INVITED = "invited"          # seat reserved, invitation not yet accepted
    ACTIVE = "active"
    RESTRICTED = "restricted"
    FROZEN = "frozen"
    DEACTIVATED = "deactivated"  # can be reactivated by an administrator; holds no seat
    CLOSED = "closed"            # removed; holds no seat


# Statuses that do not occupy one of the dashboard seats.
SEATLESS_STATUSES = {UserStatus.DEACTIVATED, UserStatus.CLOSED}
MAX_DASHBOARD_USERS = 15  # including the primary administrator; also enforced by a database trigger


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


class AppPermission(StrEnum):
    COLLECTIONS = "collections"
    PAYOUTS = "payouts"
    REFUNDS = "refunds"
    BALANCE = "balance"
    SUBSCRIBERS = "subscribers"


DEFAULT_APP_PERMISSIONS = [AppPermission.COLLECTIONS, AppPermission.REFUNDS, AppPermission.BALANCE,
                           AppPermission.SUBSCRIBERS]


class SubscriberStatus(StrEnum):
    PENDING = "pending"      # registered by the app, not yet verified
    ACTIVE = "active"        # verified and allowed
    INACTIVE = "inactive"    # access withdrawn (sessions revoked)


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
