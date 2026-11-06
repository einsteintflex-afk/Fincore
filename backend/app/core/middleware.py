from __future__ import annotations

import logging
import threading
import time
import uuid
from collections import defaultdict, deque

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.core.config import settings
from app.core.context import client_ip_var, request_id_var

log = logging.getLogger("fincore.http")


class Metrics:
    """Minimal in-process counters exposed at /metrics in Prometheus text format."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.requests: dict[tuple[str, int], int] = defaultdict(int)
        self.latency_sum = 0.0
        self.latency_count = 0

    def observe(self, method: str, status: int, seconds: float) -> None:
        with self.lock:
            self.requests[(method, status)] += 1
            self.latency_sum += seconds
            self.latency_count += 1

    def render(self) -> str:
        lines = ["# TYPE fincore_http_requests_total counter"]
        with self.lock:
            for (m, s), n in sorted(self.requests.items()):
                lines.append(f'fincore_http_requests_total{{method="{m}",status="{s}"}} {n}')
            lines += ["# TYPE fincore_http_request_seconds summary",
                      f"fincore_http_request_seconds_sum {self.latency_sum:.6f}",
                      f"fincore_http_request_seconds_count {self.latency_count}"]
        return "\n".join(lines) + "\n"


metrics = Metrics()


class RequestContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        rid = request.headers.get("x-request-id") or uuid.uuid4().hex
        ip = (request.headers.get("x-forwarded-for", "").split(",")[0].strip()
              or (request.client.host if request.client else None))
        t_rid, t_ip = request_id_var.set(rid), client_ip_var.set(ip)
        start = time.perf_counter()
        try:
            response = await call_next(request)
        finally:
            request_id_var.reset(t_rid)
            client_ip_var.reset(t_ip)
        elapsed = time.perf_counter() - start
        metrics.observe(request.method, response.status_code, elapsed)
        response.headers["X-Request-ID"] = rid
        # Security headers (the API serves JSON only; the SPA sets its own CSP at the edge).
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault("Cache-Control", "no-store")
        if settings.is_production:
            response.headers.setdefault("Strict-Transport-Security", "max-age=63072000; includeSubDomains")
        log.info("request", extra={"method": request.method, "path": request.url.path,
                                   "status": response.status_code, "ms": round(elapsed * 1000, 1), "ip": ip})
        return response


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Sliding-window limiter per client IP (and stricter for auth endpoints).

    In-memory, so per-process. For multi-instance deployments put the same limits at the
    edge (API gateway / nginx / Cloudflare) or swap this for a Redis-backed store.
    """

    def __init__(self, app, per_minute: int | None = None, auth_per_minute: int | None = None) -> None:
        super().__init__(app)
        self.per_minute = per_minute or settings.rate_limit_per_minute
        self.auth_per_minute = auth_per_minute or settings.auth_rate_limit_per_minute
        self.hits: dict[str, deque] = defaultdict(deque)
        self.lock = threading.Lock()

    def _allow(self, key: str, limit: int) -> tuple[bool, int]:
        now = time.monotonic()
        with self.lock:
            q = self.hits[key]
            while q and now - q[0] > 60:
                q.popleft()
            if len(q) >= limit:
                return False, int(60 - (now - q[0])) + 1
            q.append(now)
            return True, 0

    async def dispatch(self, request: Request, call_next) -> Response:
        if settings.environment == "test" or request.url.path in ("/health", "/ready", "/metrics"):
            return await call_next(request)
        ip = (request.headers.get("x-forwarded-for", "").split(",")[0].strip()
              or (request.client.host if request.client else "unknown"))
        path = request.url.path
        is_auth = "/auth/" in path and request.method == "POST"
        ok, retry = self._allow(f"{ip}:{'auth' if is_auth else 'all'}",
                                self.auth_per_minute if is_auth else self.per_minute)
        if not ok:
            return JSONResponse(status_code=429, headers={"Retry-After": str(retry)},
                                content={"error": {"code": "rate_limited",
                                                   "message": "Too many requests. Please slow down.",
                                                   "details": {"retry_after": retry}}})
        return await call_next(request)
