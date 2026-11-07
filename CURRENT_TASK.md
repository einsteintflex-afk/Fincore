# Current task

## Done
- [x] Session 1: platform foundation, frontend, docs, settlements, maker-checker, HttpOnly refresh cookie, AML
- [x] Session 2: KYC document upload; PDF statements & receipts; settlement-file reconciliation;
      performance pass (indexes, caching, fewer commits — measured in docs/OPERATIONS.md)

## Next task (start here)
**Phase 3.8b — Redis-backed rate limiter (optional backend).**

Acceptance criteria:
- `FINCORE_RATE_LIMIT_BACKEND=memory|redis` (default memory) and `FINCORE_REDIS_URL`.
- Redis implementation uses a fixed-window or sliding-window counter with `INCR` + `EXPIRE` per
  (ip, bucket, window); fails *open* with a logged warning if Redis is unreachable (never blocks payments
  because the limiter is down).
- Tests with an in-memory fake Redis client; existing limiter tests unchanged.
- Add `redis` service to docker-compose (profile `scale`) and document in DEPLOYMENT.md.

Then: Phase 3.9 (Playwright e2e in CI), 3.10 (notification preferences, receipt sharing), malware scanning for
uploads, maker-checker for fee/limit changes, goAML XML export.
