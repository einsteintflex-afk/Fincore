"""Maker-checker approvals for high-value staff actions (manual adjustments and reversals).

Below the configured threshold the action executes immediately. At or above it, an ApprovalRequest is
created and a *different* finance/admin user must approve it; the action then executes with the
original requester recorded in the audit trail.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy.orm import Session

from app.core.database import utcnow
from app.core.errors import AppError, Conflict, Forbidden, NotFound, ValidationFailed
from app.models.ops import ApprovalRequest, SystemSetting
from app.models.transaction import Transaction
from app.models.user import User
from app.services.audit import audit
from app.services.transactions import TransactionService
from app.services.wallets import wallet_by_number

DEFAULTS = {"adjustment": Decimal("1000.00"), "reversal": Decimal("5000.00")}


def threshold(db: Session, action: str) -> Decimal:
    s = db.get(SystemSetting, "approval_thresholds")
    raw = (s.value if s else {}).get(action)
    return Decimal(str(raw)) if raw is not None else DEFAULTS[action]


def requires_approval(db: Session, action: str, amount: Decimal) -> bool:
    return amount >= threshold(db, action)


def request(db: Session, staff: User, action: str, payload: dict, amount: Decimal, reason: str) -> ApprovalRequest:
    req = ApprovalRequest(action=action, payload=payload, amount=str(amount), reason=reason,
                          requested_by_id=staff.id, status="pending")
    db.add(req)
    db.flush()
    audit(db, "approval.requested", actor_id=staff.id, actor_type="staff", target_type="approval",
          target_id=req.id, details={"action": action, "amount": amount, "payload": payload})
    db.commit()
    return req


def execute(db: Session, action: str, payload: dict, staff: User) -> Transaction:
    svc = TransactionService(db)
    if action == "adjustment":
        wallet = wallet_by_number(db, payload["wallet_account_number"])
        return svc.adjust(wallet, staff, payload["amount"], payload["direction"], payload["reason"])
    if action == "reversal":
        return svc.reverse(uuid.UUID(payload["transaction_id"]), staff, payload["reason"])
    raise ValidationFailed(f"Unknown action {action}")


def review(db: Session, reviewer: User, approval_id: uuid.UUID, decision: str, note: str | None) -> ApprovalRequest:
    req = db.get(ApprovalRequest, approval_id)
    if not req:
        raise NotFound("Approval request not found")
    if req.status != "pending":
        raise Conflict(f"Request is already {req.status}")
    if req.requested_by_id == reviewer.id:
        raise Forbidden("You cannot approve your own request", code="four_eyes")
    if decision not in ("approve", "reject"):
        raise ValidationFailed("decision must be approve or reject")
    req.reviewed_by_id, req.review_note, req.reviewed_at = reviewer.id, note, utcnow()
    if decision == "reject":
        req.status = "rejected"
        audit(db, "approval.rejected", actor_id=reviewer.id, actor_type="staff", target_type="approval",
              target_id=req.id, details={"note": note})
        db.commit()
        return req
    req.status = "approved"
    db.commit()
    requester = db.get(User, req.requested_by_id)
    try:
        txn = execute(db, req.action, req.payload, requester)
        req = db.get(ApprovalRequest, approval_id)
        req.status, req.result = "executed", {"transaction": txn.reference}
    except AppError as exc:
        db.rollback()
        req = db.get(ApprovalRequest, approval_id)
        req.status, req.result = "failed", {"code": exc.code, "message": exc.message}
    audit(db, f"approval.{req.status}", actor_id=reviewer.id, actor_type="staff", target_type="approval",
          target_id=req.id, details={"note": note, "result": req.result, "requested_by": str(req.requested_by_id)})
    db.commit()
    return req
