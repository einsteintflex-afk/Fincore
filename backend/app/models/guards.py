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


# ---- Private dashboard: at most 15 seat-holding human accounts, and an untouchable primary administrator.
# Seat-holding = any status except deactivated/closed (invited users hold the seat they were invited to).
# The advisory lock serialises concurrent invitations/activations so two can never both take the last seat.
SEAT_LIMIT = 15
SEAT_FUNCTION = f"""
CREATE OR REPLACE FUNCTION fincore_enforce_seat_limit() RETURNS trigger AS $$
DECLARE
    used integer;
BEGIN
    IF NEW.status IN ('deactivated', 'closed') THEN
        RETURN NEW;
    END IF;
    IF TG_OP = 'UPDATE' AND OLD.status NOT IN ('deactivated', 'closed') THEN
        RETURN NEW;
    END IF;
    PERFORM pg_advisory_xact_lock(7340015);
    SELECT count(*) INTO used FROM users WHERE status NOT IN ('deactivated', 'closed') AND id <> NEW.id;
    IF used >= {SEAT_LIMIT} THEN
        RAISE EXCEPTION USING
            MESSAGE = 'dashboard_seat_limit: at most {SEAT_LIMIT} active dashboard accounts are allowed',
            ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
"""
SEAT_TRIGGER = (
    "DROP TRIGGER IF EXISTS trg_users_seat_limit ON users; "
    "CREATE TRIGGER trg_users_seat_limit BEFORE INSERT OR UPDATE OF status ON users "
    "FOR EACH ROW EXECUTE FUNCTION fincore_enforce_seat_limit();"
)
PRIMARY_ADMIN_FUNCTION = """
CREATE OR REPLACE FUNCTION fincore_protect_primary_admin() RETURNS trigger AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        IF OLD.is_primary_admin THEN
            RAISE EXCEPTION USING MESSAGE = 'primary_admin_protected: the primary administrator cannot be deleted',
                ERRCODE = 'restrict_violation';
        END IF;
        RETURN OLD;
    END IF;
    IF OLD.is_primary_admin AND (NOT NEW.is_primary_admin OR NEW.status <> 'active'
                                 OR NEW.role <> 'super_admin') THEN
        RAISE EXCEPTION USING
            MESSAGE = 'primary_admin_protected: the primary administrator must stay an active super admin',
            ERRCODE = 'restrict_violation';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
"""
PRIMARY_ADMIN_TRIGGER = (
    "DROP TRIGGER IF EXISTS trg_users_primary_admin ON users; "
    "CREATE TRIGGER trg_users_primary_admin BEFORE UPDATE OR DELETE ON users "
    "FOR EACH ROW EXECUTE FUNCTION fincore_protect_primary_admin();"
)


def install_guards_sql() -> list[str]:
    return ([GUARD_FUNCTION] + [trigger_sql(t) for t in APPEND_ONLY_TABLES]
            + [SEAT_FUNCTION, SEAT_TRIGGER, PRIMARY_ADMIN_FUNCTION, PRIMARY_ADMIN_TRIGGER])


@event.listens_for(Base.metadata, "after_create")
def _install_guards(target, connection, **kw):  # pragma: no cover - exercised in tests implicitly
    if connection.dialect.name != "postgresql":
        return
    for stmt in install_guards_sql():
        connection.exec_driver_sql(stmt)
