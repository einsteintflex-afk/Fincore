# Current task

## Done
- [x] Session 1: platform foundation, frontend, docs, settlements, maker-checker, HttpOnly refresh cookie, AML
- [x] Session 2: KYC document upload; PDF statements & receipts; settlement-file reconciliation (all browser-verified)

## Next task (start here)
**Phase 3.8 — performance & multi-instance readiness.**

Acceptance criteria:
- Add composite indexes found from the load test hot paths: `transactions(initiated_by_id, type, created_at)`,
  `transactions(source_wallet_id, created_at)`, `transactions(destination_wallet_id, created_at)`,
  `ledger_entries(account_id, created_at)`; Alembic migration; `alembic check` clean.
- Cache active fee and limit rules per process with a short TTL (e.g. 30 s) and invalidate on admin edits.
- Optional Redis-backed rate limiter (`FINCORE_RATE_LIMIT_BACKEND=memory|redis`, `FINCORE_REDIS_URL`), with the
  in-memory limiter remaining the default; test the Redis path with a fake/in-memory client.
- Re-run `backend/scripts/loadtest.py` (same parameters as PROJECT_STATUS) and record before/after numbers in
  docs/OPERATIONS.md.

Then continue with Phase 3 items 9–10, plus malware scanning for uploads, maker-checker for fee/limit changes
and goAML XML export.
