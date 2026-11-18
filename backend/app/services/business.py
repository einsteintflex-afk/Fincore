from __future__ import annotations

import secrets
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import Conflict, Forbidden, NotFound, ValidationFailed
from app.models.business import Business, BusinessMember
from app.models.enums import STAFF_ROLES, BusinessRole, BusinessStatus
from app.models.user import User
from app.services.audit import audit
from app.services.ghana import normalize_msisdn, validate_bank
from app.services.notifications import notify, queue_email
from app.services.wallets import create_wallet

ALL = {"business:view", "business:manage", "members:manage", "payments:view", "payments:create",
       "refunds:create", "settlements:create", "developers:manage", "reports:view"}

ROLE_PERMISSIONS: dict[str, set[str]] = {
    BusinessRole.OWNER: ALL,
    BusinessRole.ADMIN: ALL,
    BusinessRole.FINANCE: {"business:view", "payments:view", "payments:create", "refunds:create",
                           "settlements:create", "reports:view"},
    BusinessRole.DEVELOPER: {"business:view", "payments:view", "developers:manage"},
    BusinessRole.SUPPORT: {"business:view", "payments:view", "refunds:create"},
    BusinessRole.VIEWER: {"business:view", "payments:view", "reports:view"},
}

BUSINESS_TYPES = {"sole_proprietorship", "partnership", "limited_company", "ngo", "public_company"}


def _merchant_code(db: Session) -> str:
    for _ in range(20):
        code = "M" + "".join(secrets.choice("0123456789") for _ in range(7))
        if not db.scalar(select(Business.id).where(Business.merchant_code == code)):
            return code
    raise RuntimeError("Could not allocate merchant code")


def create_business(db: Session, owner: User, data: dict) -> Business:
    if data.get("business_type") not in BUSINESS_TYPES:
        raise ValidationFailed(f"business_type must be one of {sorted(BUSINESS_TYPES)}")
    phone = normalize_msisdn(data["phone"]) if data.get("phone") else None
    biz = Business(name=data["name"].strip(), trading_name=data.get("trading_name"),
                   registration_number=data.get("registration_number"), tin=data.get("tin"),
                   business_type=data["business_type"], industry=data.get("industry"), email=data["email"].lower(),
                   phone=phone, address=data.get("address"), website=data.get("website"),
                   status=BusinessStatus.PENDING, owner_user_id=owner.id, merchant_code=_merchant_code(db))
    db.add(biz)
    db.flush()
    db.add(BusinessMember(business_id=biz.id, user_id=owner.id, role=BusinessRole.OWNER))
    create_wallet(db, business=biz, currency="GHS", label="Collections", is_default=True)
    audit(db, "business.created", actor_id=owner.id, target_type="business", target_id=biz.id,
          details={"name": biz.name})
    notify(db, owner.id, "business", "Business submitted",
           f"{biz.name} has been submitted for review. You can use sandbox keys while you wait.")
    db.commit()
    return biz


def memberships(db: Session, user: User) -> list[tuple[Business, BusinessMember]]:
    rows = db.execute(select(Business, BusinessMember).join(BusinessMember, BusinessMember.business_id == Business.id)
                      .where(BusinessMember.user_id == user.id, BusinessMember.status == "active")
                      .order_by(Business.created_at)).all()
    return [(b, m) for b, m in rows]


def require_permission(db: Session, user: User, business_id: uuid.UUID, permission: str) -> Business:
    biz = db.get(Business, business_id)
    if not biz:
        raise NotFound("Business not found")
    if user.role in STAFF_ROLES and permission.endswith(":view"):
        return biz
    member = db.scalar(select(BusinessMember).where(BusinessMember.business_id == business_id,
                                                    BusinessMember.user_id == user.id,
                                                    BusinessMember.status == "active"))
    if not member:
        raise NotFound("Business not found")
    if permission not in ROLE_PERMISSIONS.get(member.role, set()):
        raise Forbidden(f"Your role ({member.role}) does not allow {permission}")
    return biz


def member_role(db: Session, user: User, business_id: uuid.UUID) -> str | None:
    return db.scalar(select(BusinessMember.role).where(BusinessMember.business_id == business_id,
                                                       BusinessMember.user_id == user.id))


def update_business(db: Session, biz: Business, actor: User, data: dict) -> Business:
    for field in ("trading_name", "industry", "address", "website", "registration_number", "tin"):
        if field in data and data[field] is not None:
            setattr(biz, field, data[field])
    if data.get("phone"):
        biz.phone = normalize_msisdn(data["phone"])
    if data.get("settlement_schedule"):
        if data["settlement_schedule"] not in ("daily", "weekly", "manual"):
            raise ValidationFailed("settlement_schedule must be daily, weekly or manual")
        biz.settlement_schedule = data["settlement_schedule"]
    audit(db, "business.updated", actor_id=actor.id, target_type="business", target_id=biz.id,
          details={k: v for k, v in data.items() if v is not None})
    db.commit()
    return biz


def set_settlement_destination(db: Session, biz: Business, actor: User, data: dict) -> Business:
    channel = data.get("channel")
    if channel == "bank":
        code, acct = validate_bank(data.get("bank_code") or "", data.get("account_number") or "")
        dest = {"channel": "bank", "bank_code": code, "account_number": acct, "account_name": data.get("account_name")}
    elif channel == "mobile_money":
        dest = {"channel": "mobile_money", "msisdn": normalize_msisdn(data.get("phone") or ""),
                "account_name": data.get("account_name")}
    else:
        raise ValidationFailed("channel must be bank or mobile_money")
    biz.settlement_destination = dest
    audit(db, "business.settlement_destination_set", actor_id=actor.id, target_type="business", target_id=biz.id,
          details=dest)
    db.commit()
    return biz


def add_member(db: Session, biz: Business, actor: User, email: str, role: str) -> BusinessMember:
    if role not in ROLE_PERMISSIONS or role == BusinessRole.OWNER:
        raise ValidationFailed("Invalid role")
    user = db.scalar(select(User).where(User.email == email.strip().lower()))
    if not user:
        raise NotFound("No FinCore user with that email. Ask them to sign up first.")
    existing = db.scalar(select(BusinessMember).where(BusinessMember.business_id == biz.id,
                                                      BusinessMember.user_id == user.id))
    if existing:
        if existing.status == "active":
            raise Conflict("User is already a member")
        existing.status, existing.role = "active", role
        member = existing
    else:
        member = BusinessMember(business_id=biz.id, user_id=user.id, role=role)
        db.add(member)
    notify(db, user.id, "business", "Added to a business", f"You were added to {biz.name} as {role}.")
    queue_email(db, user.email, f"You've been added to {biz.name} on FinCore",
                f"{actor.full_name} added you to {biz.name} with the {role} role.", user_id=user.id)
    audit(db, "business.member_added", actor_id=actor.id, target_type="business", target_id=biz.id,
          details={"user": user.email, "role": role})
    db.commit()
    return member


def update_member(db: Session, biz: Business, actor: User, member_id: uuid.UUID, role: str | None,
                  remove: bool = False) -> BusinessMember:
    member = db.get(BusinessMember, member_id)
    if not member or member.business_id != biz.id:
        raise NotFound("Member not found")
    if member.role == BusinessRole.OWNER:
        raise Forbidden("The owner's membership cannot be changed")
    if remove:
        member.status = "removed"
    elif role:
        if role not in ROLE_PERMISSIONS or role == BusinessRole.OWNER:
            raise ValidationFailed("Invalid role")
        member.role = role
    audit(db, "business.member_updated", actor_id=actor.id, target_type="business", target_id=biz.id,
          details={"member": member_id, "role": role, "removed": remove})
    db.commit()
    return member


def review_business(db: Session, biz: Business, staff: User, decision: str, note: str | None) -> Business:
    mapping = {"approve": BusinessStatus.ACTIVE, "reject": BusinessStatus.REJECTED,
               "suspend": BusinessStatus.SUSPENDED, "reactivate": BusinessStatus.ACTIVE}
    if decision not in mapping:
        raise ValidationFailed("decision must be approve, reject, suspend or reactivate")
    biz.status = mapping[decision]
    biz.review_note = note
    notify(db, biz.owner_user_id, "business", f"Business {biz.status}",
           f"{biz.name} is now {biz.status}." + (f" Note: {note}" if note else ""))
    audit(db, f"business.{decision}", actor_id=staff.id, actor_type="staff", target_type="business",
          target_id=biz.id, details={"note": note})
    db.commit()
    return biz
