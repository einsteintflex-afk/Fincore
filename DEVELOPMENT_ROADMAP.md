# Development roadmap

Legend: ✅ done · 🔜 next · ⏳ blocked on owner/external · 📐 designed

## Phase 1 — Foundation ✅
- ✅ Architecture, repo layout, config, logging, error model
- ✅ PostgreSQL schema + Alembic migrations + append-only DB triggers
- ✅ Double-entry ledger service with locking, reversals, integrity verification
- ✅ Auth (Argon2, JWT + server sessions, refresh rotation, 2FA, lockout, reset, email verify)
- ✅ Test harness (pytest on real Postgres), CI workflow, Docker files

## Phase 2 — Core product ✅
- ✅ Wallets, deposits, withdrawals, transfers, beneficiaries, statements, fees, tiered limits, idempotency
- ✅ KYC submissions/review, restrictions, risk scoring & fraud alerts
- ✅ Businesses, team RBAC, payment requests, hosted checkout, payment links, refunds, settlements
- ✅ Developer apps, API keys, gateway API, sandbox, webhooks (signed, retried), usage analytics
- ✅ Admin console API + UI; finance reports; reconciliation
- ✅ Provider adapters: sandbox, MTN MoMo, Paystack; skeletons for Telecel Cash, AT Money, GhIPSS
- ✅ React frontend: customer, merchant, developer, admin portals, checkout, payment links
- ✅ Documentation set

## Phase 3 — Hardening (engineering, no external dependency) 🔜
1. ✅ Scheduled automatic settlements (daily/weekly) in the worker
2. ✅ Maker-checker approvals for adjustments/reversals above thresholds (fee/limit changes: 🔜)
3. ✅ Refresh token → HttpOnly cookie; CSRF header for cookie flow
4. ✅ AML monitoring scenarios (structuring, rapid in/out, fan-in, dormant reactivation) + CSV case export (goAML XML: 🔜)
5. ✅ KYC document upload (private storage: local disk or S3-compatible; signed, expiring, audit-logged staff links)
6. ✅ PDF statements and receipts (customer, merchant, public checkout; sandbox watermark)
7. 🔜 Provider settlement-file upload for reconciliation (CSV) in admin UI
8. 🔜 Redis-backed rate limiter option; covering indexes from load-test findings
9. 🔜 Frontend e2e suite in CI (Playwright) and visual regression snapshots
10. 🔜 Customer notification preferences; in-app receipt sharing

## Phase 4 — Go-live enablement ⏳ (needs business owner)
- ⏳ Direct provider agreements (MTN MoMo, Telecel Cash, AT Money, GhIPSS sponsor bank) → implement/enable adapters, test in each provider sandbox (no third-party gateway, TD-019)
- ⏳ Email + SMS providers → wire outbox
- ⏳ NIA/Ghana Card verification vendor → implement `IdentityVerifier`
- ⏳ Hosting account, domains, secrets manager, monitoring (Sentry/Grafana)
- ⏳ BoG licensing, fee & limit approval, legal terms, DPC registration, pen-test

## Phase 5 — Expansion 📐
- 📐 Investment module (docs/INVESTMENT_MODULE.md) after SEC Ghana route is decided
- 📐 Multi-currency wallets & FX
- 📐 Card acquiring/issuing (PCI-DSS)
- 📐 Native mobile apps; USSD channel
- 📐 Additional markets (Nigeria, Côte d'Ivoire, Kenya) via currency/provider abstraction
