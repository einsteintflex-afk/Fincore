"""Inbound provider notifications (MTN MoMo callbacks, Paystack webhooks, sandbox events).

Callbacks are never trusted blindly: signed providers are verified, and unsigned ones (MTN) are
confirmed by re-querying the provider's status API before any money moves.
"""

from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.errors import Forbidden, NotFound, Unauthorized
from app.models.business import PaymentRequest
from app.providers import PROVIDER_CLASSES, get_provider
from app.providers.base import ProviderResult
from app.services.audit import audit
from app.services.payments import PaymentService
from app.services.transactions import TransactionService, find_by_provider_reference

router = APIRouter(prefix="/callbacks", tags=["Provider callbacks"])
log = logging.getLogger("fincore.callbacks")


@router.post("/{provider_code}")
async def provider_callback(provider_code: str, request: Request, db: Session = Depends(get_db)):
    if provider_code not in PROVIDER_CLASSES:
        raise NotFound("Unknown provider")
    provider = get_provider(provider_code)
    raw = await request.body()
    headers = {k.lower(): v for k, v in request.headers.items()}
    if not provider.verify_webhook(headers, raw):
        log.warning("rejected provider callback with bad signature", extra={"provider": provider_code})
        raise Unauthorized("Invalid signature")
    event = provider.parse_webhook(json.loads(raw or b"{}"))
    audit(db, "provider.callback", actor_type="system", target_type="provider", target_id=provider_code,
          details={"provider_reference": event.provider_reference, "status": event.status})

    txn = find_by_provider_reference(db, provider_code, event.provider_reference, event.internal_reference)
    if txn:
        svc = TransactionService(db)
        if provider_code == "mtn_momo":
            # Unsigned callback: confirm with MTN before acting.
            direction = "collection" if txn.type in ("deposit", "payment") else "disbursement"
            result = provider.check_status(event.provider_reference, direction)
        else:
            result = ProviderResult(status=event.status, provider_reference=event.provider_reference,
                                    message="Provider notification", raw=event.raw)
        svc.apply_provider_result(txn, result)
        db.commit()
        return {"received": True, "reference": txn.reference, "status": txn.status}

    if provider_code == "sandbox":
        pr = db.scalar(select(PaymentRequest).where(PaymentRequest.provider_reference == event.provider_reference))
        if pr:
            if pr.environment == "live":
                raise Forbidden("Live charges cannot be resolved through sandbox events")
            PaymentService(db).resolve_sandbox_pending(pr, event.status)
            return {"received": True, "reference": pr.reference, "status": pr.status}
    db.commit()
    return {"received": True, "matched": False}
