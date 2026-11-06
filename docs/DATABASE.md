# Database

PostgreSQL 16, schema managed by Alembic (`backend/alembic/versions`). 34 tables. UUID primary keys;
timestamps are `timestamptz` (UTC). Money: `NUMERIC(20,4)`.

| Domain | Tables |
|---|---|
| Identity | `users`, `user_sessions`, `password_reset_tokens`, `account_restrictions`, `kyc_submissions`, `notifications`, `outbound_messages` |
| Ledger | `ledger_accounts`, `ledger_transactions`, `ledger_entries` (append-only), `wallets`, `idempotency_records` |
| Transactions | `transactions`, `beneficiaries`, `fee_rules`, `limit_rules`, `provider_transactions` |
| Merchants | `businesses`, `business_members`, `payment_requests`, `payment_links`, `refunds`, `settlements` |
| Developers | `developer_apps`, `api_keys`, `webhook_endpoints`, `webhook_deliveries`, `api_request_logs` |
| Operations | `audit_logs` (append-only), `fraud_alerts`, `support_tickets`, `ticket_messages`, `system_settings`, `reconciliation_runs` |

## Integrity mechanisms
* `ck_ledger_entry_positive` (`amount > 0`), `ck_ledger_entry_direction`
* `ck_ledger_account_non_negative` (`allow_negative OR balance >= 0`)
* `ledger_transactions.reversal_of_id UNIQUE` (no double reversal)
* `uq_idempotency_scope_key`, `uq_provider_ref (provider, provider_reference)`, `uq_limit_rule`, `uq_business_member`, `uq_beneficiary_identity`
* Trigger `fincore_forbid_mutation()` on `ledger_entries`, `ledger_transactions`, `audit_logs` blocks UPDATE/DELETE

## Migrations
```bash
cd backend
../.venv/bin/alembic revision --autogenerate -m "describe change"   # review the generated file!
../.venv/bin/alembic upgrade head
../.venv/bin/alembic check      # CI fails if models and migrations drift
```
Rules: never edit an applied migration; keep migrations backward compatible with the previous release;
data migrations that touch money must be compensating journals, never UPDATEs to ledger tables.

## Suggested production roles
* `fincore_migrator` – owns schema, used only by the migrate job.
* `fincore_app` – `SELECT/INSERT/UPDATE` on app tables, `SELECT/INSERT` only on ledger and audit tables, no DDL.
* `fincore_readonly` – analytics/BI on a read replica.
