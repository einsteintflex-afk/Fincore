# FinCore

A Ghanaian fintech platform: GHS wallets, mobile money and bank rails, merchant payments
(checkout, payment links, refunds, settlements), a developer API with sandbox keys and signed
webhooks, and a back-office admin console — all on a double-entry, append-only ledger.

> **Status:** development build. All payment-provider traffic goes to a **sandbox simulator** until
> provider contracts, credentials and Bank of Ghana authorisation are in place. No real money moves.
> See [`PROJECT_STATUS.md`](PROJECT_STATUS.md) and [`BLOCKERS.md`](BLOCKERS.md).

## What's inside

| Area | Highlights |
|---|---|
| **Ledger** | Double-entry, `Decimal` money, row-locked postings, DB-enforced immutability, compensating reversals, integrity verification |
| **Customers** | Registration, login with lockout, TOTP 2FA, session management, password reset, email verification, tiered KYC (Ghana Card), limits, notifications, support tickets |
| **Wallets** | Multiple GHS wallets, Luhn-checked account numbers, deposits (MoMo), withdrawals (MoMo/bank), instant transfers, beneficiaries, statements (JSON/CSV), fees, idempotency |
| **Merchants** | Business onboarding & review, team roles/permissions, payment requests, hosted checkout, payment links, refunds, settlements, reports, analytics |
| **Developers** | Apps, sandbox/live API keys (hashed), payment gateway API, HMAC-signed webhooks with retries, delivery logs, usage analytics |
| **Admin** | Customer 360, restrictions/freezes, KYC & business review, transaction monitoring, reversals, adjustments, fraud alerts, fees & limits, system settings, audit log, reconciliation, trial balance, revenue & failure analytics |
| **Providers** | Sandbox simulator, MTN MoMo Open API adapter, Paystack adapter, Telecel Cash / AT Money / GhIPSS adapters awaiting partner specs |

## Quick start (Docker)

```bash
docker compose up --build                       # db, migrations, api, worker, web
docker compose run --rm api python -m app.cli demo-data
```
Open http://localhost:8080 and sign in with a demo account (password `Demo!Pass2026`):
`ama@fincore.demo` (customer), `kofi@fincore.demo` (merchant), `admin@fincore.demo` (super admin).
API reference: http://localhost:8000/docs

## Quick start (without Docker)

Requirements: Python 3.12+, Node 20+, PostgreSQL 16.

```bash
# database
createuser -P fincore            # password: fincore (dev only)
createdb -O fincore fincore && createdb -O fincore fincore_test

# backend
python3 -m venv .venv && .venv/bin/pip install -r backend/requirements-dev.txt
cd backend
cp .env.example .env                       # adjust as needed
../.venv/bin/alembic upgrade head
../.venv/bin/python -m app.cli demo-data   # or: app.cli seed && app.cli create-admin you@x.com "Your Name"
../.venv/bin/uvicorn app.main:app --reload --port 8000
../.venv/bin/python -m app.cli worker      # separate terminal: webhooks, status polling, outbox

# frontend
cd ../frontend && npm install && npm run dev   # http://localhost:5173 (proxies /api to :8000)
```

## Tests

```bash
cd backend && ../.venv/bin/python -m pytest        # 128 tests, needs the fincore_test database
cd frontend && npm test                            # 16 unit tests
node frontend/e2e/journey.cjs <shots-dir> <recipient-acct> <link-slug>   # browser journey (Playwright)
node frontend/e2e/smoke.cjs <shots-dir>                                   # every page, all portals
python backend/scripts/loadtest.py --users 20 --transfers 400            # load test
```

## Repository layout

```
backend/         FastAPI app (app/), Alembic migrations, tests, CLI, worker
  app/core/      config, database, security, money, errors, logging, middleware
  app/models/    SQLAlchemy models (+ DB guards for append-only tables)
  app/services/  ledger, wallets, transactions, payments, business, developer, webhooks, kyc, risk, ...
  app/providers/ payment-provider adapters (sandbox, MTN MoMo, Paystack, partner stubs)
  app/api/v1/    HTTP routers
frontend/        React + TypeScript + Vite + Tailwind SPA (customer, merchant, developer, admin portals)
docs/            architecture, security, API, deployment, operations, providers, OpenAPI spec
```

## Documentation

- [ARCHITECTURE.md](ARCHITECTURE.md) – system design, ledger model, money flows
- [TECHNICAL_DECISIONS.md](TECHNICAL_DECISIONS.md) – decision log
- [docs/SECURITY.md](docs/SECURITY.md) – security controls and threat model
- [docs/API.md](docs/API.md) – API guide (full spec: [docs/openapi.json](docs/openapi.json))
- [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) – environments, deployment, configuration
- [docs/OPERATIONS.md](docs/OPERATIONS.md) – monitoring, backups, disaster recovery, runbooks
- [docs/PAYMENT_PROVIDERS.md](docs/PAYMENT_PROVIDERS.md) – provider integrations and what's needed to go live
- [docs/DATABASE.md](docs/DATABASE.md) – schema overview
- [docs/INVESTMENT_MODULE.md](docs/INVESTMENT_MODULE.md) – future investment platform design
- [docs/PRODUCTION_READINESS.md](docs/PRODUCTION_READINESS.md) – outstanding production requirements
- Project tracking: [PROJECT_STATUS.md](PROJECT_STATUS.md), [DEVELOPMENT_ROADMAP.md](DEVELOPMENT_ROADMAP.md),
  [CURRENT_TASK.md](CURRENT_TASK.md), [CHANGELOG.md](CHANGELOG.md), [BLOCKERS.md](BLOCKERS.md),
  [NEXT_SESSION_INSTRUCTIONS.md](NEXT_SESSION_INSTRUCTIONS.md)
