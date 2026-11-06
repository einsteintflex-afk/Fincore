# Technical decisions

Each entry: context → decision → consequences. Newest last.

**TD-001 Modular monolith on PostgreSQL.** A single FastAPI service with strict service-layer boundaries
keeps every money movement inside one ACID transaction. Splitting into services now would require
distributed transactions/sagas for the ledger. Revisit when a module has independent scaling needs.

**TD-002 Ledger as the source of truth with cached balances.** Each account stores a running `balance`
updated under row lock in the same transaction as its entries, plus `balance_after` per entry. Reads are
O(1); `verify_integrity()` proves cache == Σ entries. Alternative (always summing entries) was rejected
for read cost.

**TD-003 `NUMERIC(20,4)` storage, currency-precision validation.** Stored with 4 dp to accommodate future
currencies and rates; API inputs are validated to the currency's minor unit (2 dp for GHS) and computed
values (fees) are rounded half-up. API outputs are strings (`"125.50"`), never JSON numbers.

**TD-004 Deterministic lock ordering.** Accounts in a journal are locked sorted by UUID, preventing deadlocks
between concurrent opposite-direction transfers. Verified by a 10-thread overdraft test.

**TD-005 Immutability at the database layer.** Triggers forbid UPDATE/DELETE on journals, entries and audit
logs, so even a buggy migration or manual SQL can't silently alter history. Corrections are compensating
journals; `reversal_of_id UNIQUE` prevents double reversal.

**TD-006 Two-phase payouts with a holding account.** Funds leave the wallet into `PENDING_PAYOUTS` and are
committed before the provider call. Provider success settles to the clearing account; failure reverses
the hold. Network timeouts leave the transaction `processing` for the poller instead of guessing.

**TD-007 Live-payments kill switch.** `FINCORE_LIVE_PAYMENTS_ENABLED` (default false) forces all routing to
the sandbox simulator, blocks creation/use of live API keys, and drives a UI banner. Real money can only
move after a deliberate configuration change by the business owner.

**TD-008 Sandbox merchant traffic never touches the ledger.** Sandbox-key charges live only in
`payment_requests` (environment = sandbox). This guarantees test traffic can't affect balances or reports.

**TD-009 Idempotency via stored responses.** `Idempotency-Key` on money-moving POSTs; `(scope, key)` is
unique, the record is row-locked while in progress, payload hash mismatches return 409, and both success
and deterministic 4xx outcomes are replayed.

**TD-010 Opaque API keys, hashed at rest.** `sk_{test|live}_<43 chars>`; lookup by 16-char prefix, verify
SHA-256 in constant time. Secret shown once. Webhook secrets and TOTP seeds are Fernet-encrypted with a
key derived from `FINCORE_ENCRYPTION_KEY` (use KMS in production).

**TD-011 Token storage in the SPA (revised).** Access JWT (15 min) lives in memory only. Browser clients
(`X-FinCore-Client: web`) receive the rotating refresh token as an `HttpOnly; SameSite=Strict` cookie scoped
to `/api/v1/auth` (`Secure` in staging/production), so JavaScript can never read it; cookie-based refreshes
also require the `X-FinCore-CSRF: 1` header. Non-browser clients still get the refresh token in the JSON body.
localStorage holds only a non-secret "has session" flag. Server-side sessions keep every token revocable.

**TD-012 Database-backed queues.** Webhook deliveries, email/SMS outbox and in-flight payouts are tables
processed by the worker with `SKIP LOCKED`. Avoids running Redis/RabbitMQ before it's needed.

**TD-013 Rules-based risk engine first.** Large-amount, velocity, new-account and unverified-withdrawal
rules produce scores; ≥90 blocks, ≥40 alerts for review. A duplicate verified Ghana Card raises a
high-severity alert. ML scoring needs labelled outcomes from production.

**TD-014 Placeholder limits and fees.** Seeded KYC-tier limits and the fee schedule are realistic
placeholders, editable in the admin console, and must be confirmed by compliance (Bank of Ghana e-money
guidelines) and the business owner before launch.

**TD-015 Adapters for partners without public specs.** Telecel Cash, AT Money and GhIPSS publish API specs
only to contracted partners, so their adapters define configuration and raise `ProviderNotConfigured`.
The Paystack adapter can reach all three MoMo networks and banks in the meantime.

**TD-016 MTN callbacks are not trusted.** MTN MoMo callbacks are unsigned; the callback handler re-queries
the status API before acting. Sandbox and Paystack callbacks are HMAC-verified.

**TD-017 In-process rate limiting.** Sliding-window per IP (strict bucket for login/registration/password
reset). Per-process only; production should enforce limits at the edge too (documented in DEPLOYMENT).

**TD-018 Code-split SPA by portal.** Customer users don't download admin code; charts load lazily.
Initial JS ≈ 85 KB gzipped.
