from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import AccountRestricted
from app.models.business import Business
from app.models.enums import BusinessStatus, RestrictionType, UserStatus
from app.models.ledger import Wallet
from app.models.user import AccountRestriction, User


def active_restrictions(db: Session, user_id: uuid.UUID) -> set[str]:
    return set(db.scalars(select(AccountRestriction.type).where(
        AccountRestriction.user_id == user_id, AccountRestriction.lifted_at.is_(None))))


def ensure_user_can_debit(db: Session, user: User) -> None:
    if user.status in (UserStatus.FROZEN, UserStatus.CLOSED):
        raise AccountRestricted("Your account is frozen. Please contact support.")
    r = active_restrictions(db, user.id)
    if RestrictionType.NO_DEBIT in r or RestrictionType.FULL_FREEZE in r:
        raise AccountRestricted("Outgoing transactions are restricted on your account. Please contact support.")


def ensure_user_can_credit(db: Session, user: User) -> None:
    if user.status in (UserStatus.FROZEN, UserStatus.CLOSED):
        raise AccountRestricted("The receiving account cannot accept funds")
    r = active_restrictions(db, user.id)
    if RestrictionType.NO_CREDIT in r or RestrictionType.FULL_FREEZE in r:
        raise AccountRestricted("The receiving account cannot accept funds")


def ensure_wallet_can_receive(db: Session, wallet: Wallet) -> None:
    if wallet.status != "active":
        raise AccountRestricted("The receiving wallet is not active")
    if wallet.user_id:
        ensure_user_can_credit(db, db.get(User, wallet.user_id))
    elif wallet.business_id:
        b = db.get(Business, wallet.business_id)
        if b.status in (BusinessStatus.SUSPENDED, BusinessStatus.REJECTED):
            raise AccountRestricted("The receiving business cannot accept funds")


def ensure_business_can_debit(business: Business) -> None:
    if business.status != BusinessStatus.ACTIVE:
        raise AccountRestricted("This business account is not active for payouts")
