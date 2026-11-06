# Current task

## Done this session
- [x] Backend foundation (ledger, wallets, payments, providers, developer, admin) — 94 tests
- [x] Frontend (customer, merchant, developer, admin portals + checkout) — 15 tests, browser-verified
- [x] Documentation set (architecture, security, API, deployment, operations, providers, DB, investments, readiness)
- [x] docker-compose, CI workflow, load test

## Next task (start here)
**Phase 3, item 1 — scheduled automatic settlements.** If already done (check `app/workers/runner.py` for
`run_scheduled_settlements`), continue with the next unchecked item in DEVELOPMENT_ROADMAP.md Phase 3.

Acceptance criteria:
- Worker settles each active business whose `settlement_schedule` is `daily` (once per day) or `weekly`
  (Mondays) and that has a settlement destination and a positive balance.
- Uses `PaymentService.settle` (so holds/fees/webhooks are identical to manual settlements).
- Idempotent per business per period (no double settlement if the worker runs twice).
- Tests in `backend/tests/` covering daily, weekly, no-destination and double-run cases.
