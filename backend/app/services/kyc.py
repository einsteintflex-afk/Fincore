"""KYC (identity verification).

Tiers (limits configured in ``limit_rules``):
  0 – registered, unverified
  1 – basic: name, date of birth, phone, address
  2 – Ghana Card verified (NIA)
  3 – enhanced: tier 2 + proof of address / source of funds, reviewed by compliance

The ``IdentityVerifier`` interface is where an NIA Ghana Card verification provider plugs in.
Until such a contract exists, submissions go to manual compliance review.
"""

from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import utcnow
from app.core.errors import Conflict, NotFound, ValidationFailed
from app.models.enums import KycStatus
from app.models.user import KycSubmission, User
from app.services.audit import audit
from app.services.ghana import validate_ghana_card
from app.services.notifications import notify

ID_TYPES = {"ghana_card", "passport", "voter_id", "drivers_license"}


class IdentityVerifier:
    """Plug-in point for automated ID verification (e.g. NIA Ghana Card API via a licensed vendor)."""

    name = "manual"

    def verify(self, submission: KycSubmission) -> dict:
        return {"provider": self.name, "automated": False, "result": "requires_manual_review"}


verifier: IdentityVerifier = IdentityVerifier()


def submit(db: Session, user: User, data: dict) -> KycSubmission:
    tier = int(data.get("tier_requested", 0))
    if tier not in (1, 2, 3):
        raise ValidationFailed("tier_requested must be 1, 2 or 3")
    if tier <= user.kyc_tier:
        raise ValidationFailed(f"You are already at tier {user.kyc_tier}")
    id_type = data.get("id_type")
    if id_type not in ID_TYPES:
        raise ValidationFailed(f"id_type must be one of {sorted(ID_TYPES)}")
    id_number = data.get("id_number", "").strip()
    if tier >= 2 and id_type != "ghana_card":
        raise ValidationFailed("Tier 2 and above require a Ghana Card")
    if id_type == "ghana_card":
        id_number = validate_ghana_card(id_number)
    dob: date = data["date_of_birth"]
    today = date.today()
    age = today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))
    if age < 18:
        raise ValidationFailed("You must be at least 18 years old")
    if db.scalar(select(KycSubmission.id).where(KycSubmission.user_id == user.id,
                                                KycSubmission.status == KycStatus.PENDING)):
        raise Conflict("You already have a verification under review")
    sub = KycSubmission(user_id=user.id, tier_requested=tier, id_type=id_type, id_number=id_number,
                        first_name=data["first_name"].strip(), last_name=data["last_name"].strip(),
                        date_of_birth=dob, address=data.get("address"), digital_address=data.get("digital_address"),
                        documents=data.get("documents") or {})
    db.add(sub)
    db.flush()
    sub.verification_result = verifier.verify(sub)
    audit(db, "kyc.submitted", actor_id=user.id, target_type="kyc", target_id=sub.id, details={"tier": tier})
    notify(db, user.id, "kyc", "Verification submitted", "We're reviewing your documents. This usually takes 1 business day.")
    db.commit()
    return sub


def review(db: Session, staff: User, submission_id: uuid.UUID, decision: str, note: str | None) -> KycSubmission:
    sub = db.get(KycSubmission, submission_id)
    if not sub:
        raise NotFound("Submission not found")
    if sub.status != KycStatus.PENDING:
        raise Conflict("Submission has already been reviewed")
    if decision not in ("approve", "reject"):
        raise ValidationFailed("decision must be approve or reject")
    if decision == "reject" and not note:
        raise ValidationFailed("A note is required when rejecting")
    user = db.get(User, sub.user_id)
    sub.status = KycStatus.APPROVED if decision == "approve" else KycStatus.REJECTED
    sub.reviewer_id, sub.review_note, sub.reviewed_at = staff.id, note, utcnow()
    if decision == "approve":
        user.kyc_tier = max(user.kyc_tier, sub.tier_requested)
        notify(db, user.id, "kyc", "Verification approved", f"You're now verified at tier {user.kyc_tier}.")
    else:
        notify(db, user.id, "kyc", "Verification unsuccessful", f"Reason: {note}")
    audit(db, f"kyc.{decision}d", actor_id=staff.id, actor_type="staff", target_type="kyc", target_id=sub.id,
          details={"user": user.email, "tier": sub.tier_requested, "note": note})
    db.commit()
    return sub
