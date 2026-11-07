# Payment provider integrations

**Strategy (TD-019): direct integrations only.** FinCore connects straight to each mobile-money network and
to the bank network. No aggregator/gateway is used. Order of work: MTN MoMo (adapter already built) →
Telecel Cash → AT Money → GhIPSS bank transfers, each as soon as its partner agreement and API spec arrive.

All adapters implement `app/providers/base.py::PaymentProvider`. Routing is configured per rail with
`FINCORE_ROUTE_MTN`, `FINCORE_ROUTE_TELECEL`, `FINCORE_ROUTE_AT`, `FINCORE_ROUTE_BANK` and only takes
effect when `FINCORE_LIVE_PAYMENTS_ENABLED=true`. Adapter status is visible in Admin → Overview → Payment providers.

| Adapter | Rails | Status | Tested with |
|---|---|---|---|
| `sandbox` | all | **Working** – deterministic simulator, signed callbacks | full test suite |
| `mtn_momo` | MTN MoMo collections (RequestToPay) & disbursements (Transfer), name lookup | **Implemented**, needs credentials | mocked HTTP (`tests/test_providers.py`) |
| `paystack` | MoMo (MTN, Telecel, AT) charges, transfers to MoMo/GhIPSS banks, name resolve, signed webhooks | **Implemented**, needs secret key | mocked HTTP |
| `telecel_cash` | Telecel Cash | **Adapter skeleton** – partner API spec required | config tests |
| `at_money` | AT Money | **Adapter skeleton** – partner API spec required | config tests |
| `ghipss` | GhIPSS Instant Pay bank transfers (via sponsor bank) | **Adapter skeleton** – partner spec required | config tests |

## What is needed from the business owner

### MTN MoMo (direct)
1. Commercial agreement with MTN Ghana Mobile Money Ltd (MoMo partner onboarding).
2. Production subscription keys for **Collections** and **Disbursements** products.
3. API user + API key for each product (created via the provisioning API for sandbox; issued by MTN for production).
4. The production `X-Target-Environment` value (e.g. `mtnghana`).
5. A public HTTPS callback URL (`https://<api-domain>/api/v1/callbacks/mtn_momo`) and our egress IPs whitelisted.

Sandbox credentials can be self-provisioned at https://momodeveloper.mtn.com (free) to test the adapter
end-to-end; note the MTN sandbox only accepts `EUR`, which the adapter handles automatically.

### Paystack — NOT USED (kept dormant, see TD-019)
1. Paystack Ghana business account (requires registered business documents).
2. Secret key (`sk_live_…`), webhook URL `https://<api-domain>/api/v1/callbacks/paystack`.
3. Funded Paystack balance for transfers (payouts).

### Telecel Cash, AT Money
Partner agreement with each operator (or with an aggregator such as Hubtel/ExpressPay/Paystack) to obtain
their API specification, credentials and callback signing scheme. Implement the three methods in
`app/providers/pending.py`, add mocked tests, then switch the route.

### Banks (GhIPSS)
Direct GIP/GhIPSS Instant Pay access is via a sponsor bank. Needed: sponsor-bank agreement, institution
code, API credentials and specification.

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
