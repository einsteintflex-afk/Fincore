# Next session instructions

The owner will say: **"CONTINUE FINCORE FROM THE LAST SAVED DEVELOPMENT STATE."** Do this:

## 1. Orient (5 minutes)
Read, in order: `PROJECT_STATUS.md`, `CURRENT_TASK.md`, `DEVELOPMENT_ROADMAP.md`, `BLOCKERS.md`,
`TECHNICAL_DECISIONS.md`, then skim `ARCHITECTURE.md`. Run `git log --oneline | head -20`.
Work on branch `claude/fincore-fintech-platform-aia7tk` (create from the default branch if missing;
if its PR was merged, restart the branch from the default branch).

## 2. Rebuild the environment and verify — don't trust the docs
```bash
cd <repo root>
service postgresql start            # cloud sandbox; or: docker compose up -d db
su postgres -c "psql -c \"CREATE USER fincore WITH PASSWORD 'fincore' CREATEDB;\"" || true
su postgres -c "psql -c 'CREATE DATABASE fincore OWNER fincore;'" || true
su postgres -c "psql -c 'CREATE DATABASE fincore_test OWNER fincore;'" || true
python3 -m venv .venv && .venv/bin/pip install -q -r backend/requirements-dev.txt
cd backend
../.venv/bin/ruff check app tests
../.venv/bin/python -m pytest                 # expect all green (128+)
../.venv/bin/alembic upgrade head && ../.venv/bin/alembic check
../.venv/bin/python -m app.cli demo-data      # demo users, password Demo!Pass2026
cd ../frontend && npm install && npm run build && npm test
```
If anything fails, fixing it is the first task.

To run the stack: `cd backend && ../.venv/bin/uvicorn app.main:app --port 8000` and
`cd frontend && npx vite --port 5173`. Browser checks use the preinstalled Playwright
(`require('playwright')`); block `fonts.googleapis.com` in scripts (no external network) and use fixed
waits instead of `networkidle`. `frontend/e2e/journey.cjs` is a working example.

## 3. Continue
Start with the **Next task** in `CURRENT_TASK.md`, then work down Phase 3 of `DEVELOPMENT_ROADMAP.md`.
Cycle: plan → build → test → debug → verify (tests + browser where UI changed) → document → commit & push.

## 4. Rules that must not be broken
- Money: `Decimal` only (backend), decimal strings (frontend). Never float.
- Every money movement goes through `LedgerService.post` in one DB transaction; never UPDATE/DELETE
  ledger or audit rows (triggers will block it anyway) — correct with compensating journals.
- Outflows are two-phase (hold → provider → complete/release). Commit the hold before calling a provider.
- Keep `FINCORE_LIVE_PAYMENTS_ENABLED=false`; never present simulated payments as real.
- New money endpoints accept `Idempotency-Key`; add tests for concurrency where relevant.
- Ask the owner only for credentials, paid services, legal/regulatory decisions, or business-model changes
  (record them in BLOCKERS.md and carry on).

## 5. Before stopping
Run tests, update `PROJECT_STATUS.md`, `CURRENT_TASK.md` (exact next task + acceptance criteria),
`DEVELOPMENT_ROADMAP.md`, `CHANGELOG.md`, `BLOCKERS.md`; commit and push.
