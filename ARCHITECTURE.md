# FinCore architecture

## 1. System overview

```
             ┌──────────────────────────── Browser / mobile web ───────────────────────────┐
             │  React SPA: /app (customer) · /merchant · /developer · /admin · /checkout   │
             └──────────────┬──────────────────────────────────────────────────────────────┘
                            │ HTTPS (same origin via nginx; /api → API)
  Merchant servers ── sk_test_/sk_live_ ──┐
                                          ▼
┌───────────────────────────────── FastAPI (stateless, N replicas) ─────────────────────────┐
│ middleware: request-id · security headers · rate limit · CORS · API-usage logging        │
│ routers: auth · me · wallets · businesses · developer · gateway · checkout · callbacks ·  │
│          admin · system                                                                   │
│ services: LedgerService · TransactionService · PaymentService · business · developer ·    │
│           webhooks · kyc · risk · limits · fees · reconciliation · analytics · audit      │
│ providers: Sandbox · MtnMomo · Paystack · TelecelCash* · AtMoney* · Ghipss*  (*stubs)     │
└───────────────┬───────────────────────────────────────────────┬──────────────────────────┘
                │ SQLAlchemy 2 / psycopg 3                       │ httpx
                ▼                                                ▼
        PostgreSQL 16 (single source of truth)          External rails (MoMo, banks, gateways)
                ▲
┌───────────────┴──────────────── Worker (python -m app.cli worker, N replicas) ────────────┐
│ webhook delivery w/ backoff · provider status polling · checkout expiry · email/SMS outbox │
└────────────────────────────────────────────────────────────────────────────────────────────┘
```

* **Modular monolith.** One deployable API with clear service boundaries (each service owns its
  tables). This keeps financial operations in single ACID transactions; modules can be split out
  later behind the same service interfaces if scale demands.
* **PostgreSQL is the only state store.** Queues (webhook deliveries, outbox, in-flight payouts) are
  tables claimed with `FOR UPDATE SKIP LOCKED`, so no extra broker is needed at this stage.

## 2. The ledger

Tables: `ledger_accounts`, `ledger_transactions` (journals), `ledger_entries`.

| Rule | Enforcement |
|---|---|
| Every journal balances per currency | `LedgerService.post` validation; `verify_integrity()` re-checks |
| Amounts > 0, direction ∈ {debit, credit} | DB `CHECK` constraints |
| No money from floats | `Decimal` everywhere; `round_money()` rejects `float`; `NUMERIC(20,4)` columns |
| Wallets never negative | `CHECK (allow_negative OR balance >= 0)` + service check |
| Concurrency safety | `SELECT … FOR UPDATE` on all touched accounts, locked in sorted-id order (deadlock-free) |
| Immutability | PL/pgSQL trigger rejects `UPDATE`/`DELETE` on `ledger_entries`, `ledger_transactions`, `audit_logs` |
| Corrections | Compensating journals (`reverse()`), at most once (`reversal_of_id` is `UNIQUE`) |
| Traceability | `balance_after` on every entry; journal `reference` links to business `Transaction` |

Account types follow standard normal balances: asset/expense are debit-normal; liability/equity/revenue
are credit-normal. Customer and merchant wallets are **liabilities** (money FinCore owes them).

### System accounts (per currency)

| Code | Type | Purpose |
|---|---|---|
| `SYS:GHS:PROVIDER_CLEARING:<PROVIDER>` | asset | Net position with each provider (collections in, payouts out) |
| `SYS:GHS:PENDING_PAYOUTS` | liability | Funds held for in-flight withdrawals/settlements/refunds |
| `SYS:GHS:FEE_REVENUE` | revenue | Fees earned |
| `SYS:GHS:ADJUSTMENTS` | expense | Manual credits/debits by finance staff |
| `SYS:GHS:SUSPENSE`, `SYS:GHS:OWNER_EQUITY` | liability / equity | Unallocated funds, capital |

## 3. Money flows

| Flow | Journal(s) |
|---|---|
| Deposit (MoMo → wallet) | on provider success: DR clearing `amount` / CR wallet `amount − fee` / CR fee revenue `fee` |
| Transfer (wallet → wallet) | DR sender `amount + fee` / CR recipient `amount` / CR fee revenue `fee` — one atomic journal |
| Withdrawal / settlement / MoMo refund | **hold**: DR wallet `amount + fee` / CR pending payouts → commit → call provider → **success**: DR pending / CR clearing `amount` / CR fee revenue `fee`; **failure**: reversal of the hold |
| Wallet payment to merchant | DR customer `amount` / CR merchant `amount − MDR` / CR fee revenue `MDR` |
| MoMo payment to merchant | on success: DR clearing `amount` / CR merchant `amount − MDR` / CR fee revenue `MDR` |
| Wallet refund | DR merchant / CR customer (merchant bears the original MDR) |
| Staff reversal | exact mirror of the original journal |
| Adjustment | DR adjustments / CR wallet (credit) or the reverse (debit) |

Two-phase outflows commit the hold **before** the external call, so a crash at any point leaves the
books balanced and the payout resolvable from the provider (callback, worker polling, or admin re-query).

## 4. Transactions vs journals

`transactions` is the customer-facing record (reference, status, fee, counterparty, provider refs);
`ledger_transactions` are the accounting truth. A `Transaction` links to its main journal and, for
two-phase flows, its completion journal. Status machine: `pending → processing → successful | failed`,
and `successful → reversed` (via a separate `reversal` transaction).

## 5. Provider abstraction

`PaymentProvider` (`collect`, `disburse`, `check_status`, `lookup_account`, `verify_webhook`,
`parse_webhook`). `providers.route(channel, network)` picks the adapter; while
`FINCORE_LIVE_PAYMENTS_ENABLED=false` (or for sandbox API keys) it always returns the sandbox simulator.
Every transaction records `provider` and `provider_mode` (`sandbox`/`live`/`internal`) and the UI marks
simulated transactions, so simulated payments are never presented as real.

## 6. Sandbox vs live for merchants

Sandbox API keys create `payment_requests` with `environment='sandbox'` that are resolved by the
simulator **without** `transactions` rows or ledger postings. Live keys require an approved business
and the platform live switch.

## 7. Security architecture

See [docs/SECURITY.md](docs/SECURITY.md). Summary: Argon2id passwords, short-lived JWT access tokens
bound to revocable server-side sessions, rotating refresh tokens, TOTP 2FA, Fernet encryption at rest
for TOTP seeds and webhook secrets, hashed API keys, HMAC-signed webhooks, RBAC for staff and per-business
roles, rate limiting, append-only audit log, risk scoring and restrictions.

## 8. Frontend

React 18 + TypeScript + Vite + Tailwind + TanStack Query. One SPA, four portals (code-split chunks),
plus public checkout/payment-link pages. Access token kept in memory, refresh token in localStorage
(see TECHNICAL_DECISIONS TD-011). All money is handled as decimal strings; display formatting only.

## 9. Future modules

* **Investments** – separate bounded context with its own ledger accounts (custody/omnibus liability),
  disabled by feature flag. Design: [docs/INVESTMENT_MODULE.md](docs/INVESTMENT_MODULE.md).
* **Multi-currency** – ledger, wallets, fees and limits are already currency-scoped; FX needs a quote
  service and FX P&L accounts.
* **Cards** – `Channel.CARD` reserved; requires a card-acquiring partner and PCI-DSS scope design.
