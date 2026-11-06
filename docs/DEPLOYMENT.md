# Deployment

## Environments

| Env | Purpose | `FINCORE_ENVIRONMENT` | Live payments | Data |
|---|---|---|---|---|
| development | local work | `development` | off | demo data |
| test | CI / pytest | `test` | off | truncated per test |
| staging | pre-production, provider sandboxes | `staging` | off (provider sandboxes via adapter config) | synthetic |
| production | real customers | `production` | **on only after approval** | real |

Staging and production refuse to start without a strong `FINCORE_SECRET_KEY` and a
`FINCORE_ENCRYPTION_KEY`. Use separate databases, keys, provider credentials and domains per environment.

## Components

| Component | Image | Scale | Notes |
|---|---|---|---|
| `api` | `backend/Dockerfile` | ≥2 replicas behind a load balancer | stateless; `uvicorn --workers 4` per container |
| `worker` | same image, `python -m app.cli worker` | ≥1 (safe to run several) | webhooks, provider polling, checkout expiry, outbox |
| `migrate` | same image, `alembic upgrade head && python -m app.cli seed` | one-off job per release | run before rolling the API |
| `web` | `frontend/Dockerfile` (nginx) | ≥2 | serves SPA, proxies `/api` |
| PostgreSQL 16 | managed (e.g. AWS RDS / Azure Flexible Server / GCP Cloud SQL) | primary + standby | PITR enabled |

Data residency: confirm with counsel/BoG whether customer data must be hosted in Ghana; local options
include Ghanaian data centres and in-country cloud regions where available.

## Release procedure
1. CI green (lint, backend tests, migration check, frontend build/tests).
2. Build and tag images with the git SHA.
3. Take an on-demand database snapshot.
4. Run the `migrate` job. Migrations must be backward compatible with the running version (expand → migrate → contract).
5. Roll `api` and `worker` (rolling update; `/ready` gates traffic).
6. Smoke test: `/health`, login, a sandbox charge, `python -m app.cli reconcile`.
7. Roll back by redeploying the previous image; never down-migrate production data without a restore plan.

## Configuration
All settings are environment variables prefixed `FINCORE_` — see `backend/.env.example`. Secrets
(`SECRET_KEY`, `ENCRYPTION_KEY`, DB password, provider keys) must come from a secrets manager.

Edge requirements:
* TLS termination with HSTS; HTTP→HTTPS redirect.
* Rate limiting at the edge (the in-app limiter is per process).
* Forward `X-Forwarded-For` and `X-Request-ID`; uvicorn runs with `--proxy-headers`.
* Allow-list provider callback source IPs for `/api/v1/callbacks/*` where providers publish them.

## Docker Compose (single host / demo)
```bash
export FINCORE_SECRET_KEY=$(python -c "import secrets;print(secrets.token_urlsafe(48))")
export FINCORE_ENCRYPTION_KEY=$(python -c "import secrets;print(secrets.token_urlsafe(48))")
docker compose up -d --build
docker compose exec api python -m app.cli create-admin ops@yourdomain.com "Ops Admin"
```

## Going live checklist (business owner sign-off required)
- [ ] Bank of Ghana licence/authorisation obtained for the intended activities (e.g. EMI / PSP licence category)
- [ ] Provider contracts signed and production credentials issued (see PAYMENT_PROVIDERS.md)
- [ ] Fee schedule and KYC tier limits approved by compliance and the business owner
- [ ] Security checklist in SECURITY.md complete; penetration test passed
- [ ] Backups and restore drill completed (OPERATIONS.md)
- [ ] Monitoring and on-call in place
- [ ] Set `FINCORE_LIVE_PAYMENTS_ENABLED=true` and the per-rail `FINCORE_ROUTE_*` values
