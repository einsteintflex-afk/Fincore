# Project status

_Last updated: 2026-11-07 (session 2)_

**Overall:** Phase 1 (foundation) and Phase 2 (core product) are built and verified in sandbox mode.
No real money can move: `FINCORE_LIVE_PAYMENTS_ENABLED=false` and no production provider credentials exist.

## Verified state (re-run these to confirm)
| Check | Command | Last result |
|---|---|---|
| Backend tests | `cd backend && ../.venv/bin/python -m pytest` | 128 passed |
| Backend lint | `../.venv/bin/ruff check app tests` | clean |
| Migrations match models | `../.venv/bin/alembic upgrade head && ../.venv/bin/alembic check` | no drift |
| Frontend typecheck/build | `cd frontend && npm run build` | ok (initial JS ≈ 85 KB gz) |
| Frontend tests | `npm test` | 16 passed |
| Browser smoke (32 pages, 4 portals) | `node frontend/e2e/smoke.cjs <dir>` | 0 console/page errors |
| Browser maker-checker flow | admin raises GHS 2,500 adjustment → second finance user approves | executed, ledger balanced |
| Browser journey (register → deposit → send → limit → link checkout) | `node frontend/e2e/journey.cjs …` | all steps pass |
| Browser KYC documents flow | `node frontend/e2e/kyc.cjs <dir>` | upload → submit → reviewer previews → approve |
| Browser PDF downloads | statement + receipt buttons | both return valid PDFs |
| Browser settlement-file reconciliation | upload CSV with a wrong amount | discrepancy shown, links to the transaction |
| Load test | `python backend/scripts/loadtest.py` | 400/400 ok, ~71–76 req/s (4-core box), ledger balanced |

## Module status
| Module | Status | Notes |
|---|---|---|
| A. Customer management | ✅ Done | registration, login/lockout, 2FA, sessions, reset, email verify, profile, KYC tiers, restrictions, notifications, support |
| B. Digital wallet | ✅ Done | multi-wallet, ledger, deposits, withdrawals, transfers, beneficiaries, history, statements (JSON/CSV/PDF), receipts, reversals, fees, limits |
| C. Payment infrastructure | ✅ Done (sandbox) | payment requests, checkout, links, webhooks, settlements, refunds, reconciliation; provider adapters (MTN, Paystack implemented; Telecel/AT/GhIPSS skeletons) |
| D. Business accounts | ✅ Done | onboarding/review, profiles, merchant codes, team roles, business wallets, monitoring, reports |
| E. Developer platform | ✅ Done | apps, keys, gateway API, sandbox, webhooks + logs, usage analytics, quick-start docs, OpenAPI |
| F. Admin platform | ✅ Done | customers, businesses, KYC, transactions, fraud & AML, restrictions, fees, limits, audit, settings, finance reports, support, maker-checker approvals |
| G. Financial analytics | ✅ Done (v1) | platform overview, revenue, failure analysis, merchant performance, trial balance, reconciliation |
| H. Investments | 📐 Designed, disabled | docs/INVESTMENT_MODULE.md; endpoint returns 503 by design |
| Production readiness | 🟡 Partial | see docs/PRODUCTION_READINESS.md |

## Known limitations
- Email/SMS are queued and logged, not delivered (no provider configured).
- Uploaded documents are not malware-scanned yet.
- Rate limiting is per process.
- Docker images were written but not built in this sandbox (no Docker daemon); the stack was verified with local PostgreSQL + uvicorn + Vite.
