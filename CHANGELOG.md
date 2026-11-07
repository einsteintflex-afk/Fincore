# Changelog

## 0.3.0 — 2026-11-07 (session 2)

### Added
- KYC document uploads: ID front/back, selfie, proof of address. Types detected from file bytes (JPEG/PNG/PDF),
  5 MB limit, random storage keys, private storage (local disk in development, S3-compatible with server-side
  encryption in production). Tier 2 requires ID front + selfie; tier 3 also proof of address.
- Compliance reviewers see document previews through 5-minute signed links; every view is audit-logged.
- Upload controls on the customer Verification page (camera capture for selfies on phones); previews in the
  admin KYC review dialog. `frontend/e2e/kyc.cjs` browser test.

- PDF statements (`/wallets/{id}/statement?format=pdf`), transaction receipts, merchant payment receipts
  and public checkout receipts (customer details masked). Sandbox watermark on every page while live
  payments are disabled. Download buttons in the app.

- Provider settlement-file reconciliation: finance uploads a provider CSV (flexible column names, status
  aliases, line-numbered validation errors); FinCore reports amount/status mismatches, rows unknown to FinCore
  and FinCore successes missing from the file. Readable discrepancy view in the admin console.

### Fixed
- Recipients saw the sender's wording on incoming transfers ("Transfer to <me>"); they now see
  "Transfer from <sender>: <narration>" in history, statements and receipts.
- Customers were shown the merchant's fee on wallet payments; customer views now show the fee they paid.

### Changed
- Business decision TD-019: direct provider integrations only; the Paystack adapter is dormant.

## 0.2.0 — 2026-11-06 (session 1, continued)

### Added
- Scheduled daily/weekly merchant settlements in the worker (once per period, system-attributed, retry-safe).
- Maker-checker approvals: adjustments ≥ GHS 1,000 and reversals ≥ GHS 5,000 (configurable
  `approval_thresholds` setting) require a different finance/admin user; admin Approvals page.
- AML monitoring scenarios (structuring, rapid movement, fan-in, dormant reactivation) run every 15 minutes
  by the worker or on demand; CSV case export for compliance; admin buttons.
- Duplicate verified Ghana Card detection raises a high-severity alert; customer email masked on public checkout.
- `frontend/e2e/smoke.cjs` (all-pages browser smoke test).

### Security
- Browser refresh tokens moved from localStorage to an HttpOnly, SameSite=Strict cookie scoped to the auth
  endpoints, with a CSRF header requirement on cookie-based refresh. API clients keep body-based refresh.

## 0.1.0 — 2026-11-06 (session 1)

### Added
- **Ledger:** double-entry engine (`LedgerService`) with row locking in deterministic order, balance
  checks, compensating reversals, integrity verification; DB triggers make journals, entries and audit
  logs append-only; CHECK constraints prevent negative wallet balances.
- **Auth & customers:** registration with automatic GHS wallet, Argon2 passwords, login lockout, JWT +
  revocable server sessions with rotating refresh tokens, TOTP 2FA, password reset, email verification,
  session management, profile, notifications, support tickets.
- **KYC:** tiered submissions (Ghana Card validation, age check), compliance review, duplicate-ID fraud alert.
- **Wallets & transactions:** deposits from MoMo, withdrawals to MoMo/bank (two-phase holds), instant
  transfers, beneficiaries, statements (JSON/CSV), fee engine, tier limits incl. max balance, idempotency keys,
  risk scoring, staff reversals and adjustments.
- **Merchants:** business onboarding & review, team roles/permissions, payment requests, hosted checkout
  (MoMo or wallet), payment links, refunds (wallet & MoMo), settlements, settlement reports, analytics.
- **Developers:** apps, sandbox/live API keys (hashed), gateway API (charges, verify, refunds, balance,
  sandbox resolve), signed webhooks with retry/backoff and delivery log, usage analytics.
- **Admin:** overview dashboard, customer 360, restrictions/status/roles, KYC & business queues,
  transaction monitoring with journals, fraud alerts, fees/limits/settings editors, audit log,
  reconciliation runs, trial balance, revenue, failure analysis, merchant performance, support desk.
- **Providers:** sandbox simulator with magic numbers and signed callbacks; MTN MoMo and Paystack adapters;
  Telecel Cash, AT Money, GhIPSS skeletons; provider routing with live-payments kill switch.
- **Frontend:** React/TS/Vite/Tailwind SPA with four code-split portals, checkout and payment-link pages,
  responsive layouts, loading/error/empty states, toasts, notifications.
- **Ops:** management CLI (seed, create-admin, demo-data, reconcile, worker), background worker, JSON logging,
  request IDs, security headers, rate limiting, `/health` `/ready` `/metrics`, Dockerfiles, docker-compose,
  CI workflow, load-test script, full documentation set.

### Fixed during verification
- Integrity check read stale ORM state (now forces a fresh read).
- Idempotent replays failed response validation for `metadata` alias.
- Money serialised as `"1118.5000"`/JSON floats → now exact strings like `"1118.50"` everywhere.
- Token refresh was rate-limited with the login bucket, causing 429s on page reloads.
- SPA made a guaranteed-401 call before refreshing on startup.
