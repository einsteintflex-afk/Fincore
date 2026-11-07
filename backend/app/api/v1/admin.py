"""Back-office API for FinCore staff. Every mutating action is audit-logged.

Role guide:
  support     – customers, tickets, read-only transactions
  compliance  – + KYC review, business review, restrictions, fraud alerts
  finance     – + reversals, adjustments, fees, limits, reconciliation, reports
  admin       – everything except changing staff roles
  super_admin – everything
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, time, timedelta, timezone

from fastapi import APIRouter, Depends, Query
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.api.deps import require_roles, staff_user
from app.api.v1.businesses import biz_out
from app.api.v1.wallets import txn_out, wallet_out
from app.core.config import settings
from app.core.database import get_db, utcnow
from app.core.errors import Conflict, NotFound, ValidationFailed
from app.core.money import validate_amount
from app.models.business import Business, PaymentRequest
from app.models.enums import RestrictionType, UserRole, UserStatus
from app.models.ledger import LedgerAccount, LedgerTransaction
from app.models.ops import (
    ApprovalRequest,
    AuditLog,
    FraudAlert,
    ReconciliationRun,
    SupportTicket,
    SystemSetting,
    TicketMessage,
)
from app.models.transaction import FeeRule, LimitRule, Transaction
from app.models.user import AccountRestriction, KycSubmission, User
from app.providers import provider_status
from app.schemas.common import (
    AdjustIn,
    ApprovalOut,
    AuditOut,
    BusinessOut,
    FeeRuleIn,
    FeeRuleOut,
    FraudAlertOut,
    FraudAlertUpdateIn,
    KycOut,
    LimitRuleIn,
    LimitRuleOut,
    Page,
    ReconciliationOut,
    RestrictionIn,
    ReverseIn,
    ReviewIn,
    RoleIn,
    SettingIn,
    StatusIn,
    TicketMessageIn,
    TicketMessageOut,
    TicketOut,
    TicketUpdateIn,
    TransactionOut,
    UserOut,
)
from app.services import aml, analytics, approvals, kyc, reconciliation
from app.services import business as bsvc
from app.services.audit import audit
from app.services.auth import revoke_all_sessions
from app.services.ledger import LedgerService
from app.services.notifications import notify
from app.services.restrictions import active_restrictions
from app.services.transactions import TransactionService
from app.services.wallets import user_wallets, wallet_by_number

router = APIRouter(prefix="/admin", tags=["Administration"])

R = UserRole
compliance = require_roles(R.COMPLIANCE, R.ADMIN)
finance = require_roles(R.FINANCE, R.ADMIN)
admin_only = require_roles(R.ADMIN)
super_admin = require_roles(R.SUPER_ADMIN)


def _page(db: Session, q, page: int, page_size: int, order, mapper=lambda x: x) -> Page:
    total = db.scalar(select(func.count()).select_from(q.subquery()))
    rows = db.scalars(q.order_by(order).offset((page - 1) * page_size).limit(page_size)).all()
    return Page(items=[mapper(r) for r in rows], total=total, page=page, page_size=page_size)


# ================================================================ dashboard & analytics
@router.get("/overview")
def overview(days: int = Query(30, ge=1, le=365), staff: User = Depends(staff_user), db: Session = Depends(get_db)):
    return analytics.platform_overview(db, days)


@router.get("/analytics/failures")
def failures(days: int = Query(30, ge=1, le=365), staff: User = Depends(staff_user), db: Session = Depends(get_db)):
    return analytics.failure_analysis(db, days)


@router.get("/analytics/merchants")
def merchants_perf(days: int = Query(30, ge=1, le=365), staff: User = Depends(staff_user),
                   db: Session = Depends(get_db)):
    return analytics.merchant_performance(db, days)


@router.get("/providers")
def providers(staff: User = Depends(staff_user)):
    return {"live_payments_enabled": settings.live_payments_enabled, "providers": provider_status()}


# ================================================================ customers
@router.get("/users", response_model=Page[UserOut])
def users(page: int = Query(1, ge=1), page_size: int = Query(20, le=100), search: str | None = None,
          status: str | None = None, role: str | None = None, kyc_tier: int | None = None,
          staff: User = Depends(staff_user), db: Session = Depends(get_db)):
    q = select(User)
    if search:
        like = f"%{search.strip()}%"
        q = q.where(or_(User.email.ilike(like), User.full_name.ilike(like), User.phone.ilike(like)))
    if status:
        q = q.where(User.status == status)
    if role:
        q = q.where(User.role == role)
    if kyc_tier is not None:
        q = q.where(User.kyc_tier == kyc_tier)
    return _page(db, q, page, page_size, User.created_at.desc())


@router.get("/users/{user_id}")
def user_detail(user_id: uuid.UUID, staff: User = Depends(staff_user), db: Session = Depends(get_db)):
    u = db.get(User, user_id)
    if not u:
        raise NotFound("User not found")
    wallets = user_wallets(db, u)
    ids = {w.id for w in wallets}
    txns = db.scalars(select(Transaction).where(or_(Transaction.source_wallet_id.in_(ids),
                                                    Transaction.destination_wallet_id.in_(ids)))
                      .order_by(Transaction.created_at.desc()).limit(20)).all() if ids else []
    restrictions = db.scalars(select(AccountRestriction).where(AccountRestriction.user_id == u.id)
                              .order_by(AccountRestriction.created_at.desc())).all()
    biz = bsvc.memberships(db, u)
    return {
        "user": UserOut.model_validate(u),
        "wallets": [wallet_out(db, w) for w in wallets],
        "recent_transactions": [txn_out(t, ids) for t in txns],
        "restrictions": [{"id": r.id, "type": r.type, "reason": r.reason, "created_at": r.created_at,
                          "lifted_at": r.lifted_at} for r in restrictions],
        "active_restrictions": sorted(active_restrictions(db, u.id)),
        "businesses": [{"id": b.id, "name": b.name, "role": m.role, "status": b.status} for b, m in biz],
        "kyc": [KycOut.model_validate(k) for k in db.scalars(
            select(KycSubmission).where(KycSubmission.user_id == u.id).order_by(KycSubmission.created_at.desc()))],
        "open_alerts": db.scalar(select(func.count()).select_from(FraudAlert).where(
            FraudAlert.user_id == u.id, FraudAlert.status.in_(["open", "investigating"]))),
    }


@router.post("/users/{user_id}/restrictions")
def add_restriction(user_id: uuid.UUID, body: RestrictionIn, staff: User = Depends(compliance),
                    db: Session = Depends(get_db)):
    u = db.get(User, user_id)
    if not u:
        raise NotFound("User not found")
    if body.type not in {r.value for r in RestrictionType}:
        raise ValidationFailed("Unknown restriction type")
    if body.type in active_restrictions(db, u.id):
        raise Conflict("Restriction already active")
    r = AccountRestriction(user_id=u.id, type=body.type, reason=body.reason, created_by_id=staff.id)
    db.add(r)
    if body.type in (RestrictionType.LOGIN_BLOCK, RestrictionType.FULL_FREEZE):
        revoke_all_sessions(db, u.id)
    if u.status == UserStatus.ACTIVE:
        u.status = UserStatus.RESTRICTED
    notify(db, u.id, "security", "Account restricted",
           "Some features on your account have been restricted. Please contact support.")
    audit(db, "user.restricted", actor_id=staff.id, actor_type="staff", target_type="user", target_id=u.id,
          details=body.model_dump())
    db.commit()
    return {"id": r.id, "type": r.type, "reason": r.reason}


@router.delete("/users/{user_id}/restrictions/{restriction_id}")
def lift_restriction(user_id: uuid.UUID, restriction_id: uuid.UUID, staff: User = Depends(compliance),
                     db: Session = Depends(get_db)):
    r = db.get(AccountRestriction, restriction_id)
    if not r or r.user_id != user_id or r.lifted_at:
        raise NotFound("Active restriction not found")
    r.lifted_at, r.lifted_by_id = utcnow(), staff.id
    db.flush()
    u = db.get(User, user_id)
    if u.status == UserStatus.RESTRICTED and not active_restrictions(db, u.id):
        u.status = UserStatus.ACTIVE
    audit(db, "user.restriction_lifted", actor_id=staff.id, actor_type="staff", target_type="user", target_id=u.id,
          details={"type": r.type})
    db.commit()
    return {"message": "Restriction lifted"}


@router.post("/users/{user_id}/status", response_model=UserOut)
def set_status(user_id: uuid.UUID, body: StatusIn, staff: User = Depends(compliance), db: Session = Depends(get_db)):
    u = db.get(User, user_id)
    if not u:
        raise NotFound("User not found")
    if body.status not in {s.value for s in UserStatus}:
        raise ValidationFailed("Unknown status")
    u.status = body.status
    if body.status in (UserStatus.FROZEN, UserStatus.CLOSED):
        revoke_all_sessions(db, u.id)
    audit(db, "user.status_changed", actor_id=staff.id, actor_type="staff", target_type="user", target_id=u.id,
          details=body.model_dump())
    db.commit()
    return u


@router.post("/users/{user_id}/role", response_model=UserOut)
def set_role(user_id: uuid.UUID, body: RoleIn, staff: User = Depends(super_admin), db: Session = Depends(get_db)):
    u = db.get(User, user_id)
    if not u:
        raise NotFound("User not found")
    if body.role not in {r.value for r in UserRole}:
        raise ValidationFailed("Unknown role")
    old = u.role
    u.role = body.role
    revoke_all_sessions(db, u.id)
    audit(db, "user.role_changed", actor_id=staff.id, actor_type="staff", target_type="user", target_id=u.id,
          details={"from": old, "to": body.role})
    db.commit()
    return u


# ================================================================ KYC
@router.get("/kyc", response_model=Page[KycOut])
def kyc_queue(status: str = "pending", page: int = Query(1, ge=1), page_size: int = Query(20, le=100),
              staff: User = Depends(compliance), db: Session = Depends(get_db)):
    q = select(KycSubmission).where(KycSubmission.status == status)
    return _page(db, q, page, page_size, KycSubmission.created_at)


@router.get("/kyc/{submission_id}/documents")
def kyc_documents(submission_id: uuid.UUID, staff: User = Depends(compliance), db: Session = Depends(get_db)):
    """Short-lived signed links to the submission's documents. Every access is audit-logged."""
    sub = db.get(KycSubmission, submission_id)
    if not sub:
        raise NotFound("Submission not found")
    docs = kyc.signed_documents(db, sub)
    audit(db, "kyc.documents_viewed", actor_id=staff.id, actor_type="staff", target_type="kyc",
          target_id=sub.id, details={"documents": [d["id"] for d in docs]})
    db.commit()
    return docs


@router.post("/kyc/{submission_id}/review", response_model=KycOut)
def kyc_review(submission_id: uuid.UUID, body: ReviewIn, staff: User = Depends(compliance),
               db: Session = Depends(get_db)):
    return kyc.review(db, staff, submission_id, body.decision, body.note)


# ================================================================ businesses
@router.get("/businesses", response_model=Page[BusinessOut])
def businesses(status: str | None = None, search: str | None = None, page: int = Query(1, ge=1),
               page_size: int = Query(20, le=100), staff: User = Depends(staff_user), db: Session = Depends(get_db)):
    q = select(Business)
    if status:
        q = q.where(Business.status == status)
    if search:
        like = f"%{search}%"
        q = q.where(or_(Business.name.ilike(like), Business.merchant_code.ilike(like), Business.email.ilike(like)))
    return _page(db, q, page, page_size, Business.created_at.desc(), biz_out)


@router.post("/businesses/{business_id}/review", response_model=BusinessOut)
def business_review(business_id: uuid.UUID, body: ReviewIn, staff: User = Depends(compliance),
                    db: Session = Depends(get_db)):
    b = db.get(Business, business_id)
    if not b:
        raise NotFound("Business not found")
    return biz_out(bsvc.review_business(db, b, staff, body.decision, body.note))


# ================================================================ transactions
@router.get("/transactions", response_model=Page[TransactionOut])
def transactions(page: int = Query(1, ge=1), page_size: int = Query(25, le=200), type: str | None = None,
                 status: str | None = None, search: str | None = None, provider: str | None = None,
                 min_amount: str | None = None, min_risk: int | None = None, start: date | None = None,
                 end: date | None = None, staff: User = Depends(staff_user), db: Session = Depends(get_db)):
    q = select(Transaction)
    if type:
        q = q.where(Transaction.type == type)
    if status:
        q = q.where(Transaction.status == status)
    if provider:
        q = q.where(Transaction.provider == provider)
    if search:
        like = f"%{search.strip()}%"
        q = q.where(or_(Transaction.reference.ilike(like), Transaction.provider_reference.ilike(like),
                        Transaction.description.ilike(like)))
    if min_amount:
        q = q.where(Transaction.amount >= min_amount)
    if min_risk is not None:
        q = q.where(Transaction.risk_score >= min_risk)
    if start:
        q = q.where(Transaction.created_at >= datetime.combine(start, time.min, tzinfo=timezone.utc))
    if end:
        q = q.where(Transaction.created_at < datetime.combine(end + timedelta(days=1), time.min, tzinfo=timezone.utc))
    return _page(db, q, page, page_size, Transaction.created_at.desc(), lambda t: txn_out(t))


@router.get("/transactions/{reference}")
def transaction_detail(reference: str, staff: User = Depends(staff_user), db: Session = Depends(get_db)):
    t = db.scalar(select(Transaction).where(Transaction.reference == reference))
    if not t:
        raise NotFound("Transaction not found")
    journals = []
    for jid in filter(None, [t.ledger_transaction_id, t.completion_ledger_transaction_id]):
        lj = db.get(LedgerTransaction, jid)
        journals.append({"reference": lj.reference, "kind": lj.kind, "created_at": lj.created_at,
                         "entries": [{"account": db.get(LedgerAccount, e.account_id).code, "direction": e.direction,
                                      "amount": e.amount, "balance_after": e.balance_after} for e in lj.entries]})
    alerts = db.scalars(select(FraudAlert).where(FraudAlert.transaction_id == t.id)).all()
    return {"transaction": txn_out(t), "journals": journals,
            "fraud_alerts": [FraudAlertOut.model_validate(a) for a in alerts]}


@router.post("/transactions/{reference}/reverse", response_model=None,
             responses={200: {"model": TransactionOut}, 202: {"description": "Queued for second approval"}})
def reverse(reference: str, body: ReverseIn, staff: User = Depends(finance), db: Session = Depends(get_db)):
    t = db.scalar(select(Transaction).where(Transaction.reference == reference))
    if not t:
        raise NotFound("Transaction not found")
    if approvals.requires_approval(db, "reversal", t.amount):
        req = approvals.request(db, staff, "reversal", {"transaction_id": str(t.id), "reference": t.reference,
                                                         "reason": body.reason}, t.amount, body.reason)
        return JSONResponse(status_code=202, content=jsonable_encoder(
            {"approval_required": True, "approval": ApprovalOut.model_validate(req)}))
    return txn_out(TransactionService(db).reverse(t.id, staff, body.reason))


@router.post("/transactions/{reference}/requery", response_model=TransactionOut)
def requery(reference: str, staff: User = Depends(finance), db: Session = Depends(get_db)):
    t = db.scalar(select(Transaction).where(Transaction.reference == reference))
    if not t:
        raise NotFound("Transaction not found")
    return txn_out(TransactionService(db).refresh_from_provider(t))


@router.post("/adjustments", response_model=None,
             responses={200: {"model": TransactionOut}, 202: {"description": "Queued for second approval"}})
def adjust(body: AdjustIn, staff: User = Depends(finance), db: Session = Depends(get_db)):
    w = wallet_by_number(db, body.wallet_account_number)
    amount = validate_amount(body.amount, w.currency)
    if approvals.requires_approval(db, "adjustment", amount):
        payload = {**body.model_dump(mode="json"), "amount": str(amount)}
        req = approvals.request(db, staff, "adjustment", payload, amount, body.reason)
        return JSONResponse(status_code=202, content=jsonable_encoder(
            {"approval_required": True, "approval": ApprovalOut.model_validate(req)}))
    return txn_out(TransactionService(db).adjust(w, staff, amount, body.direction, body.reason))


# ================================================================ maker-checker approvals
@router.get("/approvals", response_model=list[ApprovalOut])
def list_approvals(status: str = "pending", staff: User = Depends(finance), db: Session = Depends(get_db)):
    return db.scalars(select(ApprovalRequest).where(ApprovalRequest.status == status)
                      .order_by(ApprovalRequest.created_at.desc()).limit(200)).all()


@router.post("/approvals/{approval_id}/review", response_model=ApprovalOut)
def review_approval(approval_id: uuid.UUID, body: ReviewIn, staff: User = Depends(finance),
                    db: Session = Depends(get_db)):
    return approvals.review(db, staff, approval_id, body.decision, body.note)


# ================================================================ fraud
@router.get("/fraud-alerts", response_model=Page[FraudAlertOut])
def fraud_alerts(status: str | None = None, severity: str | None = None, page: int = Query(1, ge=1),
                 page_size: int = Query(25, le=100), staff: User = Depends(compliance), db: Session = Depends(get_db)):
    q = select(FraudAlert)
    if status:
        q = q.where(FraudAlert.status == status)
    if severity:
        q = q.where(FraudAlert.severity == severity)
    return _page(db, q, page, page_size, FraudAlert.created_at.desc())


@router.patch("/fraud-alerts/{alert_id}", response_model=FraudAlertOut)
def update_alert(alert_id: uuid.UUID, body: FraudAlertUpdateIn, staff: User = Depends(compliance),
                 db: Session = Depends(get_db)):
    a = db.get(FraudAlert, alert_id)
    if not a:
        raise NotFound("Alert not found")
    a.status = body.status
    a.notes = body.notes or a.notes
    a.assigned_to_id = a.assigned_to_id or staff.id
    if body.status in ("resolved", "false_positive"):
        a.resolved_at = utcnow()
    if body.restrict_user and a.user_id and RestrictionType.NO_DEBIT not in active_restrictions(db, a.user_id):
        db.add(AccountRestriction(user_id=a.user_id, type=RestrictionType.NO_DEBIT,
                                  reason=f"Fraud investigation ({a.rule})", created_by_id=staff.id))
        u = db.get(User, a.user_id)
        if u.status == UserStatus.ACTIVE:
            u.status = UserStatus.RESTRICTED
    audit(db, "fraud.alert_updated", actor_id=staff.id, actor_type="staff", target_type="fraud_alert",
          target_id=a.id, details=body.model_dump())
    db.commit()
    return a


@router.post("/aml/scan")
def aml_scan(staff: User = Depends(compliance), db: Session = Depends(get_db)):
    """Run the AML monitoring scenarios now (the worker also runs them every 15 minutes)."""
    result = aml.run_scan(db)
    audit(db, "aml.scan", actor_id=staff.id, actor_type="staff", details=result)
    db.commit()
    return {"alerts_raised": result}


@router.get("/fraud-alerts/export", response_class=StreamingResponse)
def export_alerts(start: date | None = None, end: date | None = None, status: str = "open,investigating",
                  staff: User = Depends(compliance), db: Session = Depends(get_db)):
    end = end or datetime.now(timezone.utc).date()
    start = start or end - timedelta(days=30)
    s = datetime.combine(start, time.min, tzinfo=timezone.utc)
    e = datetime.combine(end + timedelta(days=1), time.min, tzinfo=timezone.utc)
    content = aml.export_alerts_csv(db, s, e, [x.strip() for x in status.split(",") if x.strip()])
    audit(db, "aml.alerts_exported", actor_id=staff.id, actor_type="staff",
          details={"start": start, "end": end, "status": status})
    db.commit()
    return StreamingResponse(iter([content]), media_type="text/csv",
                             headers={"Content-Disposition": f'attachment; filename="fincore-alerts-{start}-{end}.csv"'})


# ================================================================ fees & limits
@router.get("/fees", response_model=list[FeeRuleOut])
def fees(staff: User = Depends(staff_user), db: Session = Depends(get_db)):
    return db.scalars(select(FeeRule).order_by(FeeRule.transaction_type, FeeRule.channel)).all()


@router.post("/fees", response_model=FeeRuleOut, status_code=201)
def create_fee(body: FeeRuleIn, staff: User = Depends(finance), db: Session = Depends(get_db)):
    rule = FeeRule(**body.model_dump())
    db.add(rule)
    audit(db, "config.fee_created", actor_id=staff.id, actor_type="staff", target_type="fee_rule",
          details=body.model_dump())
    db.commit()
    return rule


@router.put("/fees/{rule_id}", response_model=FeeRuleOut)
def update_fee(rule_id: uuid.UUID, body: FeeRuleIn, staff: User = Depends(finance), db: Session = Depends(get_db)):
    rule = db.get(FeeRule, rule_id)
    if not rule:
        raise NotFound("Fee rule not found")
    before = FeeRuleOut.model_validate(rule).model_dump()
    for k, v in body.model_dump().items():
        setattr(rule, k, v)
    audit(db, "config.fee_updated", actor_id=staff.id, actor_type="staff", target_type="fee_rule",
          target_id=rule.id, details={"before": before, "after": body.model_dump()})
    db.commit()
    return rule


@router.get("/limits", response_model=list[LimitRuleOut])
def limit_rules(staff: User = Depends(staff_user), db: Session = Depends(get_db)):
    return db.scalars(select(LimitRule).order_by(LimitRule.kyc_tier, LimitRule.transaction_type)).all()


@router.put("/limits", response_model=LimitRuleOut)
def upsert_limit(body: LimitRuleIn, staff: User = Depends(finance), db: Session = Depends(get_db)):
    rule = db.scalar(select(LimitRule).where(LimitRule.kyc_tier == body.kyc_tier,
                                             LimitRule.transaction_type == body.transaction_type,
                                             LimitRule.currency == body.currency))
    if not rule:
        rule = LimitRule(kyc_tier=body.kyc_tier, transaction_type=body.transaction_type, currency=body.currency)
        db.add(rule)
    for k, v in body.model_dump().items():
        setattr(rule, k, v)
    audit(db, "config.limit_updated", actor_id=staff.id, actor_type="staff", target_type="limit_rule",
          details=body.model_dump())
    db.commit()
    return rule


# ================================================================ audit & settings
@router.get("/audit-logs", response_model=Page[AuditOut])
def audit_logs(page: int = Query(1, ge=1), page_size: int = Query(50, le=200), action: str | None = None,
               actor_id: uuid.UUID | None = None, target_id: str | None = None,
               staff: User = Depends(require_roles(R.COMPLIANCE, R.FINANCE, R.ADMIN)), db: Session = Depends(get_db)):
    q = select(AuditLog)
    if action:
        q = q.where(AuditLog.action.ilike(f"{action}%"))
    if actor_id:
        q = q.where(AuditLog.actor_id == actor_id)
    if target_id:
        q = q.where(AuditLog.target_id == target_id)
    return _page(db, q, page, page_size, AuditLog.created_at.desc())


@router.get("/settings")
def get_settings(staff: User = Depends(staff_user), db: Session = Depends(get_db)):
    return [{"key": s.key, "value": s.value, "description": s.description, "updated_at": s.updated_at}
            for s in db.scalars(select(SystemSetting).order_by(SystemSetting.key))]


@router.put("/settings/{key}")
def put_setting(key: str, body: SettingIn, staff: User = Depends(admin_only), db: Session = Depends(get_db)):
    s = db.get(SystemSetting, key)
    if not s:
        s = SystemSetting(key=key, value=body.value)
        db.add(s)
    before = s.value
    s.value, s.updated_by_id = body.value, staff.id
    audit(db, "config.setting_updated", actor_id=staff.id, actor_type="staff", target_type="setting", target_id=key,
          details={"before": before, "after": body.value})
    db.commit()
    return {"key": s.key, "value": s.value}


# ================================================================ finance: reports & reconciliation
@router.get("/reports/trial-balance")
def trial_balance(staff: User = Depends(finance), db: Session = Depends(get_db)):
    accts = db.scalars(select(LedgerAccount).where(LedgerAccount.is_system.is_(True)).order_by(LedgerAccount.code)).all()
    wallets_total = db.execute(select(LedgerAccount.currency, func.sum(LedgerAccount.balance), func.count())
                               .where(LedgerAccount.is_system.is_(False)).group_by(LedgerAccount.currency)).all()
    return {
        "generated_at": utcnow(),
        "system_accounts": [{"code": a.code, "name": a.name, "type": a.type, "currency": a.currency,
                             "balance": a.balance} for a in accts],
        "customer_and_merchant_wallets": [{"currency": c, "total_balance": t, "accounts": n}
                                          for c, t, n in wallets_total],
        "integrity": LedgerService(db).verify_integrity(),
    }


@router.get("/reports/revenue")
def revenue(start: date | None = None, end: date | None = None, staff: User = Depends(finance),
            db: Session = Depends(get_db)):
    end = end or datetime.now(timezone.utc).date()
    start = start or end - timedelta(days=30)
    s = datetime.combine(start, time.min, tzinfo=timezone.utc)
    e = datetime.combine(end + timedelta(days=1), time.min, tzinfo=timezone.utc)
    rows = db.execute(select(Transaction.type, Transaction.channel, func.count(), func.sum(Transaction.fee))
                      .where(Transaction.status == "successful", Transaction.fee > 0, Transaction.created_at >= s,
                             Transaction.created_at < e).group_by(Transaction.type, Transaction.channel)).all()
    merchant_fees = db.scalar(select(func.coalesce(func.sum(PaymentRequest.fee), 0)).where(
        PaymentRequest.environment == "live", PaymentRequest.paid_at >= s, PaymentRequest.paid_at < e))
    return {"period_start": start, "period_end": end,
            "by_type": [{"type": t, "channel": c, "count": n, "fees": f} for t, c, n, f in rows],
            "total_fees": sum((r[3] for r in rows), start=0), "merchant_discount_fees": merchant_fees}


@router.post("/reconciliation/ledger", response_model=ReconciliationOut)
def recon_ledger(staff: User = Depends(finance), db: Session = Depends(get_db)):
    return reconciliation.run_ledger_integrity(db, staff.id)


@router.post("/reconciliation/providers", response_model=ReconciliationOut)
def recon_providers(provider: str | None = None, staff: User = Depends(finance), db: Session = Depends(get_db)):
    return reconciliation.run_provider_reconciliation(db, provider, staff.id)


@router.get("/reconciliation/runs", response_model=list[ReconciliationOut])
def recon_runs(staff: User = Depends(finance), db: Session = Depends(get_db)):
    return db.scalars(select(ReconciliationRun).order_by(ReconciliationRun.created_at.desc()).limit(50)).all()


# ================================================================ support
@router.get("/tickets", response_model=Page[TicketOut])
def tickets(status: str | None = None, page: int = Query(1, ge=1), page_size: int = Query(25, le=100),
            mine: bool = False, staff: User = Depends(staff_user), db: Session = Depends(get_db)):
    q = select(SupportTicket)
    if status:
        q = q.where(SupportTicket.status == status)
    if mine:
        q = q.where(SupportTicket.assigned_to_id == staff.id)
    return _page(db, q, page, page_size, SupportTicket.updated_at.desc())


@router.get("/tickets/{ticket_id}")
def ticket(ticket_id: uuid.UUID, staff: User = Depends(staff_user), db: Session = Depends(get_db)):
    t = db.get(SupportTicket, ticket_id)
    if not t:
        raise NotFound("Ticket not found")
    msgs = db.scalars(select(TicketMessage).where(TicketMessage.ticket_id == t.id).order_by(TicketMessage.created_at))
    customer = db.get(User, t.user_id)
    return {"ticket": TicketOut.model_validate(t), "customer": UserOut.model_validate(customer),
            "messages": [TicketMessageOut.model_validate(m) for m in msgs]}


@router.patch("/tickets/{ticket_id}", response_model=TicketOut)
def update_ticket(ticket_id: uuid.UUID, body: TicketUpdateIn, staff: User = Depends(staff_user),
                  db: Session = Depends(get_db)):
    t = db.get(SupportTicket, ticket_id)
    if not t:
        raise NotFound("Ticket not found")
    if body.status:
        t.status = body.status
    if body.priority:
        t.priority = body.priority
    if body.assign_to_me:
        t.assigned_to_id = staff.id
    audit(db, "support.ticket_updated", actor_id=staff.id, actor_type="staff", target_type="ticket", target_id=t.id,
          details=body.model_dump(exclude_none=True))
    db.commit()
    return t


@router.post("/tickets/{ticket_id}/messages", response_model=TicketMessageOut, status_code=201)
def reply_ticket(ticket_id: uuid.UUID, body: TicketMessageIn, staff: User = Depends(staff_user),
                 db: Session = Depends(get_db)):
    t = db.get(SupportTicket, ticket_id)
    if not t:
        raise NotFound("Ticket not found")
    m = TicketMessage(ticket_id=t.id, author_id=staff.id, body=body.body, internal=body.internal)
    db.add(m)
    if not body.internal:
        t.status = "pending" if t.status == "open" else t.status
        notify(db, t.user_id, "support", f"Reply on: {t.subject}", body.body[:200], {"ticket_id": str(t.id)})
    t.assigned_to_id = t.assigned_to_id or staff.id
    t.updated_at = utcnow()
    db.commit()
    return m
