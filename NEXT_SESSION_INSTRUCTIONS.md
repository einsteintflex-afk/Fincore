# Next session instructions

Paste-ready prompt for a new Claude session: **"CONTINUE FINCORE FROM THE LAST SAVED DEVELOPMENT STATE."**

1. Read `PROJECT_STATUS.md`, `CURRENT_TASK.md`, `DEVELOPMENT_ROADMAP.md`, `BLOCKERS.md`.
2. Verify against code, don't trust docs: run the backend tests (below) and `git log --oneline | head`.
3. Continue with the first unchecked item in `CURRENT_TASK.md`, then the roadmap.

## Environment setup (cloud sandbox or local)
```bash
service postgresql start          # or docker compose up -d db
su postgres -c "psql -c \"CREATE USER fincore WITH PASSWORD 'fincore' CREATEDB;\""
su postgres -c "psql -c 'CREATE DATABASE fincore OWNER fincore;'"
su postgres -c "psql -c 'CREATE DATABASE fincore_test OWNER fincore;'"
python3 -m venv .venv && .venv/bin/pip install -r backend/requirements-dev.txt
cd backend && ../.venv/bin/alembic upgrade head && ../.venv/bin/python -m app.cli demo-data
../.venv/bin/python -m pytest          # all tests must pass
cd ../frontend && npm install && npm run build && npm test
```
Branch: `claude/fincore-fintech-platform-aia7tk`. Commit and push after each verified milestone.
