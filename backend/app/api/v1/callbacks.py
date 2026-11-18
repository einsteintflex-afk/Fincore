"""Inbound provider notifications (MTN MoMo callbacks, Paystack webhooks, sandbox events).

Callbacks are never trusted blindly: signed providers are verified, and unsigned ones (MTN) are
confirmed by re-querying the provider's status API before any money moves.
"""

from __future__ import annotations

import hmac
import json
import logging

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.core.errors import Forbidden, NotFound, Unauthorized, ValidationFailed
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
    if provider_code.startswith("mtn_momo") and settings.mtn_callback_token:
        # MTN does not sign callbacks; a secret token in the configured callback URL filters out forgeries
        # cheaply. Even with a valid token nothing is credited until MTN's status API confirms it (below).
        if not hmac.compare_digest(request.query_params.get("token", ""), settings.mtn_callback_token):
            log.warning("rejected MTN callback with bad token", extra={"provider": provider_code})
            raise Unauthorized("Invalid callback token")
    raw = await request.body()
    headers = {k.lower(): v for k, v in request.headers.items()}
    if not provider.verify_webhook(headers, raw):
        log.warning("rejected provider callback with bad signature", extra={"provider": provider_code})
        raise Unauthorized("Invalid signature")
    try:
        event = provider.parse_webhook(json.loads(raw or b"{}"))
    except (ValueError, KeyError, TypeError) as exc:
        raise ValidationFailed("Malformed callback body") from exc
    audit(db, "provider.callback", actor_type="system", target_type="provider", target_id=provider_code,
          details={"provider_reference": event.provider_reference, "status": event.status})

    txn = find_by_provider_reference(db, provider_code, event.provider_reference, event.internal_reference)
    if txn:
        svc = TransactionService(db)
        if provider_code.startswith("mtn_momo"):
            # Unsigned callback: it is only a hint. Ask MTN for the authoritative status before acting.
            svc.refresh_from_provider(txn, force=True)
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
