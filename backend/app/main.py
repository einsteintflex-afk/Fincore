from __future__ import annotations

import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError

from app.api.v1 import admin, auth, businesses, callbacks, checkout, developer, gateway, me, system, wallets
from app.core.config import settings
from app.core.errors import AppError
from app.core.logging import configure_logging
from app.core.middleware import RateLimitMiddleware, RequestContextMiddleware

log = logging.getLogger("fincore")

DESCRIPTION = """
**FinCore** – Ghanaian fintech platform API (wallets, payments, merchant gateway).

* Money values are **strings** with up to 2 decimal places for GHS (e.g. `"125.50"`).
* Authenticate dashboard calls with `Authorization: Bearer <access token>` from `/auth/login`.
* Authenticate gateway calls (`/gateway/*`) with `Authorization: Bearer sk_test_...` / `sk_live_...`.
* Send an `Idempotency-Key` header on money-moving POSTs so retries are safe.
* While live payments are disabled every provider call goes to the **sandbox simulator** – no real money moves.
"""


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings.validate_for_runtime()
    log.info("FinCore API starting", extra={"environment": settings.environment,
                                            "live_payments_enabled": settings.live_payments_enabled})
    yield


def create_app() -> FastAPI:
    if settings.environment != "test":
        configure_logging("DEBUG" if settings.debug else "INFO")
    app = FastAPI(title="FinCore API", version="0.1.0", description=DESCRIPTION, lifespan=lifespan,
                  docs_url="/docs", redoc_url="/redoc", openapi_url=f"{settings.api_prefix}/openapi.json")

    app.add_middleware(RateLimitMiddleware)
    app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_credentials=True,
                       allow_methods=["*"], allow_headers=["*"], expose_headers=["X-Request-ID"])
    app.add_middleware(RequestContextMiddleware)

    @app.middleware("http")
    async def api_usage_logger(request: Request, call_next):
        start = time.perf_counter()
        response = await call_next(request)
        ctx = getattr(request.state, "api_ctx", None)
        if ctx:
            from app.core.database import SessionLocal
            from app.services.developer import log_request

            try:
                with SessionLocal() as db:
                    log_request(db, app_id=ctx["app_id"], api_key_id=ctx["key_id"], environment=ctx["environment"],
                                method=request.method, path=request.url.path, status_code=response.status_code,
                                latency_ms=int((time.perf_counter() - start) * 1000),
                                ip=request.client.host if request.client else None)
            except Exception:  # usage logging must never break the API call
                log.exception("failed to record API usage")
        return response

    @app.exception_handler(AppError)
    async def app_error(_: Request, exc: AppError):
        return JSONResponse(status_code=exc.status_code,
                            content={"error": {"code": exc.code, "message": exc.message, "details": exc.details}})

    @app.exception_handler(RequestValidationError)
    async def validation_error(_: Request, exc: RequestValidationError):
        errors = [{"field": ".".join(str(p) for p in e["loc"][1:]), "message": e["msg"]} for e in exc.errors()]
        msg = errors[0]["message"] if errors else "Invalid request"
        if errors and errors[0]["field"]:
            msg = f"{errors[0]['field']}: {msg}"
        return JSONResponse(status_code=422,
                            content={"error": {"code": "validation_failed", "message": msg, "details": errors}})

    @app.exception_handler(IntegrityError)
    async def integrity_error(_: Request, exc: IntegrityError):
        log.warning("integrity error", extra={"err": str(exc.orig)[:300]})
        return JSONResponse(status_code=409, content={"error": {"code": "conflict",
                                                                "message": "The request conflicts with existing data",
                                                                "details": None}})

    @app.exception_handler(Exception)
    async def unhandled(_: Request, exc: Exception):
        log.exception("unhandled error")
        return JSONResponse(status_code=500, content={"error": {"code": "internal_error",
                                                                "message": "Something went wrong. Please try again.",
                                                                "details": None}})

    app.include_router(system.router)
    p = settings.api_prefix
    for r in (system.public, system.investments, auth.router, me.router, wallets.router, businesses.router,
              developer.router, gateway.router, checkout.router, callbacks.router, admin.router):
        app.include_router(r, prefix=p)
    return app


app = create_app()
