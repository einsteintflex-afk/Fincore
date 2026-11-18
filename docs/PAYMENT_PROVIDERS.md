# Payment provider integrations

**Strategy (TD-019): direct integrations only.** FinCore connects straight to each mobile-money network and
to the bank network. No aggregator/gateway is used. Order of work: MTN MoMo (adapter already built) →
Telecel Cash → AT Money → GhIPSS bank transfers, each as soon as its partner agreement and API spec arrive.

All adapters implement `app/providers/base.py::PaymentProvider`. MTN routing is set by
`FINCORE_MTN_MOMO_MODE` (off | sandbox | production, see below); other rails by `FINCORE_ROUTE_TELECEL`,
`FINCORE_ROUTE_AT`, `FINCORE_ROUTE_BANK`, which only take effect when `FINCORE_LIVE_PAYMENTS_ENABLED=true`. Adapter status is visible in Admin → Overview → Payment providers.

| Adapter | Rails | Status | Tested with |
|---|---|---|---|
| `sandbox` | all | **Working** – deterministic simulator, signed callbacks | full test suite |
| `mtn_momo_sandbox` | MTN developer sandbox — RequestToPay collections (test money) | **Implemented**; sandbox keys provisioned, MTN login currently failing (see BLOCKERS B-1) | fake MTN API (`tests/test_mtn.py`, 31 tests) |
| `mtn_momo` | MTN production — collections & disbursements, name lookup | **Implemented**, needs production keys from MTN Ghana | same suite |
| `paystack` | MoMo (MTN, Telecel, AT) charges, transfers to MoMo/GhIPSS banks, name resolve, signed webhooks | **Implemented**, needs secret key | mocked HTTP |
| `telecel_cash` | Telecel Cash | **Adapter skeleton** – partner API spec required | config tests |
| `at_money` | AT Money | **Adapter skeleton** – partner API spec required | config tests |
| `ghipss` | GhIPSS Instant Pay bank transfers (via sponsor bank) | **Adapter skeleton** – partner spec required | config tests |

## What is needed from the business owner

### MTN MoMo Collections — how it works (TD-022)
1. Customer enters their MTN number and amount (deposit) or chooses MoMo at checkout.
2. FinCore sends **RequestToPay** with the customer's MSISDN. `X-Reference-Id` is derived from FinCore's own
   reference, so a retry can never create a second charge at MTN (MTN answers 409 and FinCore reads the status).
3. MTN sends the official authorisation prompt to the customer's phone (production only — the sandbox never
   prompts real phones); the customer approves with their PIN.
4. FinCore learns the outcome from MTN's callback **and always re-queries MTN's status API** before crediting
   anything; the browser and the (unsigned) callback are only hints. Status checks are rate-limited per
   transaction; the worker polls in-flight requests every 30 s.
5. Outcomes recorded on the transaction (`provider_outcome`): successful, pending, **rejected** (payer declined),
   **expired** (payer didn't approve in time, or still pending after `FINCORE_MTN_REQUEST_EXPIRY_MINUTES`),
   **timeout** (FinCore's call to MTN timed out — resolved from MTN's status, never guessed), failed.
6. On success the ledger posts DR `PROVIDER_CLEARING:MTN_MOMO[_SANDBOX]` / CR customer wallet. Provider records
   feed the reconciliation runs.

**Credential separation:** `FINCORE_MTN_SANDBOX_*` and `FINCORE_MTN_PRODUCTION_*` are separate variable sets,
separate provider codes (`mtn_momo_sandbox` / `mtn_momo`), separate clearing accounts. FinCore refuses to start
with production mode without live payments, with live payments on the sandbox, or with the sandbox in a
production deployment, and refuses a profile whose URL points at the other environment. Keys are read from
settings only, never logged, never stored in transaction/provider records, never sent to the browser.

**Callback URL:** `https://<api-domain>/api/v1/callbacks/mtn_momo?token=<FINCORE_MTN_CALLBACK_TOKEN>`
(`mtn_momo_sandbox` for the sandbox). The token filters forged calls; MTN's status API is still the authority.

### MTN MoMo — what the business owner must obtain for production
1. Commercial agreement with MTN Ghana Mobile Money Ltd (MoMo partner onboarding).
2. Production subscription keys for **Collections** and **Disbursements** products.
3. API user + API key for each product (created via the provisioning API for sandbox; issued by MTN for production).
4. The production `X-Target-Environment` value (e.g. `mtnghana`).
5. A public HTTPS callback URL (above) registered with MTN, and FinCore's server IPs whitelisted by MTN.
6. Registered business documents for the partner application (Registrar-General registration, TIN, etc.).

Having sandbox access does **not** mean production approval: MTN reviews the partner application separately
and issues production keys only after approval.

Sandbox credentials can be self-provisioned at https://momodeveloper.mtn.com (free) to test the adapter
end-to-end; note the MTN sandbox only accepts `EUR`, which the adapter handles automatically.

### Paystack — NOT USED (kept dormant, see TD-019)
1. Paystack Ghana business account (requires registered business documents).
2. Secret key (`sk_live_…`), webhook URL `https://<api-domain>/api/v1/callbacks/paystack`.
3. Funded Paystack balance for transfers (payouts).

### Telecel Cash, AT Money
Direct partner agreement with each operator to obtain
their API specification, credentials and callback signing scheme. Implement the three methods in
`app/providers/pending.py`, add mocked tests, then switch the route.

### Banks (GhIPSS)
Direct GIP/GhIPSS Instant Pay access is via a sponsor bank. Needed: sponsor-bank agreement, institution
code, API credentials and specification.

## Cards (Visa / Mastercard)
Cards are accepted through an **acquiring bank's hosted payment page** (`app/providers/cards.py`): FinCore
creates a session, redirects the payer to the bank's page, and on return asks the bank for the result (never
trusting the browser). FinCore never receives card numbers, keeping PCI-DSS scope to SAQ-A.

| Adapter | Status |
|---|---|
| `sandbox_card` | **Working** – FinCore-hosted simulated card page marked TEST, used while live payments are off |
| `bank_card` | **Slot** – implement the chosen bank's session/status/refund API once the acquiring agreement is signed |

Test cards (any future expiry, any CVC): `4111 1111 1111 1111` and `5555 5555 5555 4444` approve,
`4000 0000 0000 0002` declined, `4000 0000 0000 9995` insufficient funds, `4000 0000 0000 3220` asks for
3-D Secure (approve or decline on the next screen). Card MDR placeholder: 2.5% (min GH₵0.20, max GH₵500).

What the owner needs from the bank: merchant (acquiring) agreement, merchant ID, API credentials, the hosted
payment page / 3-D Secure integration guide, refund API, callback signing method, and settlement account.

## Adding a provider
1. Implement `PaymentProvider` (idempotent on our `reference`; map statuses to `successful|pending|failed`).
2. Register it in `app/providers/__init__.py::PROVIDER_CLASSES`.
3. Add settings to `app/core/config.py` and `.env.example`.
4. Add mocked-HTTP tests (see `tests/test_providers.py`).
5. Configure a callback URL → `POST /api/v1/callbacks/<code>`; verify signatures or re-query status.

## Reconciliation
Every provider call writes a `provider_transactions` row. `Admin → Finance → Run provider recon` (or
`python -m app.cli reconcile`) compares provider records — or an uploaded settlement file passed to
`run_provider_reconciliation(statement=[...])` — with internal transactions and flags
`missing_internal`, `amount_mismatch`, `status_mismatch` and `in_flight` items.

Finance can upload a provider's statement/settlement CSV in Admin → Finance → Reconciliation
(`POST /admin/reconciliation/providers/upload`). Accepted columns (case-insensitive aliases):
transaction reference (`provider_reference`/`Transaction ID`, or FinCore `reference`), `amount`, `status`
(success/completed/paid, failed/rejected/reversed, pending...) and optional ISO `date`. When every row has
a date, FinCore also lists its own successful transactions in that period that the provider file lacks
(`missing_in_provider_file`). Add provider-specific aliases in `services/reconciliation.py::COLUMN_ALIASES`
once each operator's real statement format is known.

## Sandbox verification log

- 2026-11-18: Real MTN sandbox verified 2026-11-18 after removing the environment's network secret (it was replacing the Authorization header): fresh sandbox API users for Collections and Disbursements log in (200); through FinCore's own services a GH₵100 RequestToPay deposit and a GH₵40 Transfer withdrawal (fee 6.00, net 34.00) both reached SUCCESSFUL with the ledger balanced. Fix found on the way: MTN's `CREATED` status is now treated as pending.
  Troubleshooting: if every token call returns `500 login_failed` (even without credentials), something between FinCore and MTN is rewriting the `Authorization` header — e.g. a proxy-injected secret for the MTN host. Remove it and create fresh API users.
