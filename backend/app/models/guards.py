"""Database-level guards that make financial and audit records append-only.

These triggers are installed both by ``Base.metadata.create_all`` (tests, via the
``after_create`` event below) and by the Alembic migration, so the rule holds even if
application code is bypassed.
"""

from sqlalchemy import event

from app.core.database import Base

GUARD_FUNCTION = """
CREATE OR REPLACE FUNCTION fincore_forbid_mutation() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION USING
        MESSAGE = 'Table ' || TG_TABLE_NAME || ' is append-only: ' || TG_OP || ' is not permitted',
        ERRCODE = 'restrict_violation';
END;
$$ LANGUAGE plpgsql;
"""

APPEND_ONLY_TABLES = ("ledger_entries", "ledger_transactions", "audit_logs")


def trigger_sql(table: str) -> str:
    return (
        f"DROP TRIGGER IF EXISTS trg_{table}_append_only ON {table}; "
        f"CREATE TRIGGER trg_{table}_append_only BEFORE UPDATE OR DELETE ON {table} "
        f"FOR EACH ROW EXECUTE FUNCTION fincore_forbid_mutation();"
    )


def install_guards_sql() -> list[str]:
    return [GUARD_FUNCTION] + [trigger_sql(t) for t in APPEND_ONLY_TABLES]


@event.listens_for(Base.metadata, "after_create")
def _install_guards(target, connection, **kw):  # pragma: no cover - exercised in tests implicitly
    if connection.dialect.name != "postgresql":
        return
    for stmt in install_guards_sql():
        connection.exec_driver_sql(stmt)
