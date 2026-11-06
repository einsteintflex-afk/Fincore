# Current task

## Done (session 1)
- [x] Backend foundation (ledger, wallets, payments, providers, developer, admin)
- [x] Frontend (customer, merchant, developer, admin portals + checkout), browser-verified
- [x] Documentation set, docker-compose, CI, load test
- [x] Phase 3.1 Scheduled daily/weekly settlements (worker, idempotent per period)
- [x] Phase 3.2 Maker-checker approvals for large adjustments/reversals (+ admin Approvals page)
- [x] Phase 3.4 AML monitoring scenarios + CSV case export (+ admin buttons)

## Next task (start here)
**Phase 3.3 — move the refresh token to an HttpOnly cookie** (see TECHNICAL_DECISIONS TD-011).

Acceptance criteria:
- `/auth/login`, `/auth/login/2fa` and `/auth/refresh` set the refresh token in an `HttpOnly; Secure`
  (Secure off in development) `SameSite=Strict` cookie scoped to `/api/v1/auth`, and stop returning it in
  the JSON body for browser clients (keep body support behind a flag for non-browser clients if needed).
- `/auth/refresh` reads the cookie; `/auth/logout` clears it.
- CSRF: because the cookie is SameSite=Strict and only sent to `/api/v1/auth/*`, require a custom header
  (e.g. `X-FinCore-CSRF: 1`) on `/auth/refresh` and reject requests without it.
- Frontend `lib/api.ts` stops using localStorage for the refresh token; `credentials: "include"` on auth calls.
- Update tests in `tests/test_auth.py` and `src/__tests__/api.test.ts`; re-run `frontend/e2e/journey.cjs`.

Then continue with the remaining 🔜 items in DEVELOPMENT_ROADMAP.md Phase 3 (5, 6, 7, 8, 9, 10, plus
maker-checker for fee/limit changes and goAML XML export).
