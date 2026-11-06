from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import PlainTextResponse
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.core.errors import FeatureDisabled
from app.core.middleware import metrics
from app.models.ops import SystemSetting

router = APIRouter(tags=["System"])


@router.get("/health")
def health():
    return {"status": "ok", "service": settings.app_name, "environment": settings.environment}


@router.get("/ready")
def ready(db: Session = Depends(get_db)):
    db.execute(text("SELECT 1"))
    return {"status": "ready", "database": "ok"}


@router.get("/metrics", response_class=PlainTextResponse)
def prometheus_metrics():
    return metrics.render()


public = APIRouter(tags=["System"])


@public.get("/platform")
def platform(db: Session = Depends(get_db)):
    """Public platform info used by the frontends (sandbox banner, maintenance message, support contacts)."""
    maint = db.get(SystemSetting, "maintenance_mode")
    support = db.get(SystemSetting, "support_contact")
    return {
        "name": settings.app_name,
        "environment": settings.environment,
        "live_payments_enabled": settings.live_payments_enabled,
        "default_currency": settings.default_currency,
        "currencies": settings.supported_currencies,
        "maintenance": maint.value if maint else {"enabled": False},
        "support": support.value if support else {},
        "investments_enabled": settings.investments_enabled,
    }


investments = APIRouter(prefix="/investments", tags=["Investments (not active)"])


@investments.get("/products")
def investment_products():
    """Reserved for the future investment module. See docs/INVESTMENT_MODULE.md.

    Regulated investment products require SEC Ghana licensing (and possibly NPRA/BoG approvals);
    this endpoint stays disabled until the business owner confirms authorisation.
    """
    if not settings.investments_enabled:
        raise FeatureDisabled("Investment products are not available. This module requires regulatory "
                              "authorisation before activation.")
    return {"products": []}
