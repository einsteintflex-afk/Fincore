"""PostgreSQL backups and verified restores.

* ``create_backup()`` writes ``fincore-YYYYmmdd-HHMMSS.dump`` (pg_dump custom format, compressed) into
  ``FINCORE_BACKUP_DIR`` and prunes to the newest ``FINCORE_BACKUP_KEEP`` files.
* ``verify_backup(path)`` restores a dump into a NEW scratch database, checks the restored ledger
  (debits = credits, every journal balanced, row counts) and drops the scratch database. It never touches
  the live database.
* ``restore_to(path, database)`` restores into a database that must not exist yet — so a restore can never
  overwrite live data by accident. Switching the application to it is a deliberate, separate step.

The worker runs ``create_backup()`` every ``FINCORE_BACKUP_INTERVAL_HOURS`` (default 24) when a backup
directory is configured. Copy the directory off the server (e.g. object storage) — see docs/OPERATIONS.md.
"""

from __future__ import annotations

import os
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from app.core.config import settings

NAME_RE = re.compile(r"^fincore-\d{8}-\d{6}\.dump$")


class BackupError(RuntimeError):
    pass


def _libpq(database: str | None = None) -> tuple[list[str], dict]:
    """Connection arguments for pg_dump/pg_restore/createdb. The password goes in the environment, never argv."""
    url = make_url(settings.database_url)
    args = ["-h", url.host or "localhost", "-p", str(url.port or 5432), "-U", url.username or "postgres"]
    env = {**os.environ, "PGPASSWORD": url.password or ""}
    return args, {"env": env, "dbname": database or url.database}


def _dir() -> Path:
    if not settings.backup_dir:
        raise BackupError("Set FINCORE_BACKUP_DIR to enable backups")
    d = Path(settings.backup_dir)
    d.mkdir(parents=True, exist_ok=True)
    os.chmod(d, 0o700)
    return d


def create_backup() -> dict:
    d = _dir()
    name = f"fincore-{datetime.now(timezone.utc):%Y%m%d-%H%M%S}.dump"
    path = d / name
    args, conn = _libpq()
    proc = subprocess.run(["pg_dump", *args, "-Fc", "-Z", "6", "-f", str(path), conn["dbname"]],
                          env=conn["env"], capture_output=True, text=True, timeout=3600)
    if proc.returncode != 0:
        path.unlink(missing_ok=True)
        raise BackupError(f"pg_dump failed: {proc.stderr.strip()[:300]}")
    os.chmod(path, 0o600)
    prune()
    return _info(path)


def _info(path: Path) -> dict:
    st = path.stat()
    return {"name": path.name, "size_bytes": st.st_size,
            "created_at": datetime.fromtimestamp(st.st_mtime, timezone.utc).isoformat()}


def list_backups() -> list[dict]:
    if not settings.backup_dir or not Path(settings.backup_dir).exists():
        return []
    files = sorted((p for p in Path(settings.backup_dir).iterdir() if NAME_RE.match(p.name)), reverse=True)
    return [_info(p) for p in files]


def last_backup_info() -> dict | None:
    items = list_backups()
    return items[0] if items else None


def prune() -> int:
    files = sorted((p for p in _dir().iterdir() if NAME_RE.match(p.name)), reverse=True)
    removed = 0
    for old in files[max(settings.backup_keep, 1):]:
        old.unlink()
        removed += 1
    return removed


def _resolve(path_or_name: str) -> Path:
    p = Path(path_or_name)
    if not p.is_absolute():
        p = _dir() / p
    if not p.exists():
        raise BackupError(f"Backup not found: {p}")
    return p


def _database_exists(name: str) -> bool:
    engine = create_engine(settings.database_url.rsplit("/", 1)[0] + "/postgres")
    with engine.connect() as c:
        found = c.execute(text("SELECT 1 FROM pg_database WHERE datname = :n"), {"n": name}).scalar()
    engine.dispose()
    return bool(found)


def restore_to(path_or_name: str, database: str) -> dict:
    if not re.match(r"^[a-z_][a-z0-9_]{2,62}$", database):
        raise BackupError("Database name must be lowercase letters, digits and underscores")
    if database == make_url(settings.database_url).database or _database_exists(database):
        raise BackupError(f"Refusing to restore into existing database '{database}'. Choose a new name.")
    path = _resolve(path_or_name)
    args, conn = _libpq()
    run = {"env": conn["env"], "capture_output": True, "text": True, "timeout": 3600}
    proc = subprocess.run(["createdb", *args, database], **run)
    if proc.returncode != 0:
        raise BackupError(f"createdb failed: {proc.stderr.strip()[:300]}")
    proc = subprocess.run(["pg_restore", *args, "--no-owner", "--exit-on-error", "-d", database, str(path)], **run)
    if proc.returncode != 0:
        raise BackupError(f"pg_restore failed: {proc.stderr.strip()[:300]}")
    return {"database": database, "backup": path.name}


def verify_backup(path_or_name: str) -> dict:
    """Restore into a scratch database, check it, drop it. Returns the checks performed."""
    scratch = f"fincore_restore_check_{datetime.now(timezone.utc):%Y%m%d%H%M%S}"
    restore_to(path_or_name, scratch)
    url = make_url(settings.database_url).set(database=scratch)
    engine = create_engine(url)
    try:
        with engine.connect() as c:
            counts = {t: c.execute(text(f"SELECT count(*) FROM {t}")).scalar()  # noqa: S608 — fixed names
                      for t in ("users", "wallets", "ledger_accounts", "ledger_transactions", "ledger_entries",
                                "transactions", "audit_logs")}
            dr, cr = c.execute(text(
                "SELECT coalesce(sum(amount) FILTER (WHERE direction='debit'),0), "
                "coalesce(sum(amount) FILTER (WHERE direction='credit'),0) FROM ledger_entries")).one()
            unbalanced = c.execute(text(
                "SELECT count(*) FROM (SELECT transaction_id FROM ledger_entries GROUP BY transaction_id "
                "HAVING sum(CASE WHEN direction='debit' THEN amount ELSE -amount END) <> 0) x")).scalar()
            guards = c.execute(text(
                "SELECT count(*) FROM pg_trigger WHERE tgname IN ('trg_ledger_entries_append_only', "
                "'trg_users_seat_limit', 'trg_users_primary_admin')")).scalar()
    finally:
        engine.dispose()
        args, conn = _libpq()
        subprocess.run(["dropdb", *args, "--if-exists", scratch], env=conn["env"], capture_output=True, timeout=600)
    ok = dr == cr and unbalanced == 0 and guards == 3
    return {"backup": Path(path_or_name).name, "restored_ok": ok, "row_counts": counts,
            "ledger_debits": str(dr), "ledger_credits": str(cr), "unbalanced_journals": unbalanced,
            "guards_restored": guards}
