# Operations

## Monitoring
* **Health**: `GET /health` (liveness), `GET /ready` (checks DB) — wire to load balancer and uptime monitoring.
* **Metrics**: `GET /metrics` (Prometheus text): request counts by method/status, latency sum/count.
  Recommended alerts: 5xx rate > 1% for 5 min; p95 latency > 1 s; `/ready` failing.
* **Business alerts** (query-based, e.g. Grafana on a read replica):
  * transactions stuck in `processing` > 15 min (`SELECT count(*) FROM transactions WHERE status='processing' AND updated_at < now() - interval '15 minutes'`)
  * webhook deliveries `failed` in last hour
  * open `critical`/`high` fraud alerts
  * reconciliation run with `status = 'discrepancies'`
* **Logs**: JSON lines on stdout with `request_id`; ship to Loki/ELK/CloudWatch. Retain ≥ 5 years for
  financial audit trails where regulation requires (confirm with compliance).
* **Error tracking**: unhandled exceptions are logged with stack traces (`logger=fincore`, `level=ERROR`).
  To add Sentry: `pip install sentry-sdk` and call `sentry_sdk.init(dsn=..., traces_sample_rate=0.1)` in
  `app/main.py::create_app` (left out to avoid a paid dependency without approval).

## Scheduled jobs
| Job | How | Frequency |
|---|---|---|
| Worker loop (webhooks, polling, expiry, outbox, scheduled settlements, AML scan every 15 min) | `python -m app.cli worker` | continuous |
| Ledger + provider reconciliation | `python -m app.cli reconcile` (exit 2 on imbalance) | hourly + end of day |
| Database backup | managed snapshots + `docker compose --profile ops run --rm backup` for logical dumps | daily logical, continuous WAL/PITR |

## Email / SMS delivery
Messages are written to `outbound_messages` and drained by the worker (`drain_outbox`). The current
implementation logs them (no provider configured). To deliver: implement SMTP (e.g. AWS SES, Mailgun) and
an SMS gateway (e.g. Hubtel, mNotify, Arkesel) inside `app/workers/runner.py::drain_outbox`.

## Backups & disaster recovery

Built in (`app/services/backups.py`):

| Task | Command |
|---|---|
| Automatic backups | set `FINCORE_BACKUP_DIR` (and optionally `FINCORE_BACKUP_INTERVAL_HOURS`=24, `FINCORE_BACKUP_KEEP`=14); the worker writes `fincore-YYYYmmdd-HHMMSS.dump` (pg_dump custom format, mode 600) |
| Back up now | `python -m app.cli backup` or Settings → Backups → Back up now (super admin) |
| Prove a backup restores | `python -m app.cli verify-backup [name]` — restores into a scratch database, checks debits = credits, every journal balanced and the guard triggers present, then drops the scratch database |
| Restore | `python -m app.cli restore <name> <new_database>` — only into a NEW database (existing databases are never overwritten); then point `FINCORE_DATABASE_URL` at it and restart |

Copy the backup directory off the server every day (object storage with versioning, e.g. `rclone sync`),
encrypted at rest. Verified on 2026-11-18: a backup of the development database restored with 6,083 ledger entries,
debits = credits = 39,069.00, 0 unbalanced journals, all 3 guards present.

Recovery objectives with daily dumps: RPO ≤ 24 h. For a smaller RPO use PostgreSQL WAL archiving / point-in-time
recovery from the hosting provider in addition to the dumps.

## Runbooks
**Stuck payout** – Admin → Transactions → filter `processing` → open → *Re-query provider*. If the provider
confirms failure, the hold is released automatically; if success, it settles. Never adjust manually
without the provider's statement.

**Customer disputes a transfer** – verify in Admin → Transactions; if FinCore error, *Reverse* (finance role,
reason required). Reversal fails if the recipient has already spent the funds — escalate to compliance.

**Suspected fraud** – Admin → Fraud alerts → mark *investigating* + *Block outgoing transactions*; for
account takeover add `login_block` (revokes all sessions) from the customer page.

**Ledger imbalance reported** – page on-call immediately; enable maintenance mode; investigate the
problems listed in the reconciliation run. Corrections are only ever compensating journals.

## Performance
Baseline (`backend/scripts/loadtest.py`, 4 uvicorn workers on a small 2-vCPU sandbox, local Postgres):
400 concurrent wallet transfers at concurrency 20 → **~71 req/s, p50 263 ms, p95 450 ms, 0 errors**, ledger
balanced afterwards. Each transfer performs limit/risk aggregate queries.

Session 2 optimisation (same machine, same parameters, two runs each):

| | Throughput | p50 | p95 | DB statements per transfer |
|---|---|---|---|---|
| Before | 67.7–69.7 req/s | 271–280 ms | 415–424 ms | 30 |
| After | 70.7–75.7 req/s | 253–264 ms | 381–446 ms | 26 |

Changes: composite indexes (`transactions(initiated_by_id, type, created_at)`, `(source_wallet_id, created_at)`,
`(destination_wallet_id, created_at)`, `(provider, status, created_at)`, `ledger_entries(account_id, created_at)`),
one query for daily+monthly limit usage, 30-second per-process cache for fee/limit rules and 10-second cache for
the maintenance flag (cleared on admin edits), and one fewer commit per idempotent request.
Profiling shows the test box is CPU-bound (4 cores shared by the load generator, 4 API workers and PostgreSQL)
and about a third of request time is database round-trips/commits. Scale out by adding API replicas and a
dedicated database server; the indexes keep limit checks and statements fast as tables grow.
Never disable `synchronous_commit` for the ledger database.
