from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.core.errors import Conflict, InsufficientFunds, LedgerError
from app.models.enums import AccountType
from app.services.ledger import CR, DR, LedgerService, Line, SystemAccount


@pytest.fixture
def ledger(db):
    return LedgerService(db)


def _accounts(ledger):
    a = ledger.create_account(code="T:A", name="A", type=AccountType.LIABILITY, currency="GHS")
    b = ledger.create_account(code="T:B", name="B", type=AccountType.LIABILITY, currency="GHS")
    src = ledger.system_account(SystemAccount.clearing("test"), "GHS")
    return a, b, src


def test_balanced_posting_updates_balances(ledger, db):
    a, b, src = _accounts(ledger)
    ledger.post(kind="t", lines=[Line(src.id, DR, Decimal("100.00")), Line(a.id, CR, Decimal("100.00"))])
    ledger.post(kind="t", lines=[Line(a.id, DR, Decimal("40.00")), Line(b.id, CR, Decimal("40.00"))])
    db.commit()
    assert a.balance == Decimal("60.00")
    assert b.balance == Decimal("40.00")
    assert src.balance == Decimal("100.00")  # asset: debit-normal
    assert ledger.verify_integrity()["balanced"]


def test_unbalanced_journal_rejected(ledger):
    a, b, _ = _accounts(ledger)
    with pytest.raises(LedgerError, match="Unbalanced"):
        ledger.post(kind="t", lines=[Line(a.id, DR, Decimal("10")), Line(b.id, CR, Decimal("9.99"))])


def test_single_line_rejected(ledger):
    a, _, _ = _accounts(ledger)
    with pytest.raises(LedgerError):
        ledger.post(kind="t", lines=[Line(a.id, DR, Decimal("10"))])


def test_non_positive_and_excess_precision_rejected(ledger):
    a, b, _ = _accounts(ledger)
    with pytest.raises(LedgerError):
        ledger.post(kind="t", lines=[Line(a.id, DR, Decimal("0")), Line(b.id, CR, Decimal("0"))])
    with pytest.raises(LedgerError, match="precision"):
        ledger.post(kind="t", lines=[Line(a.id, DR, Decimal("1.005")), Line(b.id, CR, Decimal("1.005"))])


def test_wallet_cannot_go_negative(ledger, db):
    a, b, src = _accounts(ledger)
    ledger.post(kind="t", lines=[Line(src.id, DR, Decimal("5.00")), Line(a.id, CR, Decimal("5.00"))])
    db.commit()
    with pytest.raises(InsufficientFunds):
        ledger.post(kind="t", lines=[Line(a.id, DR, Decimal("5.01")), Line(b.id, CR, Decimal("5.01"))])
    db.rollback()


def test_reversal_mirrors_and_only_once(ledger, db):
    a, b, src = _accounts(ledger)
    lj = ledger.post(kind="t", lines=[Line(src.id, DR, Decimal("50.00")), Line(a.id, CR, Decimal("50.00"))])
    db.commit()
    ledger.reverse(lj.id, reason="test")
    db.commit()
    db.refresh(a)
    assert a.balance == Decimal("0.00")
    with pytest.raises(Conflict):
        ledger.reverse(lj.id, reason="again")
    assert ledger.verify_integrity()["balanced"]


def test_entries_are_immutable_at_db_level(ledger, db):
    a, _, src = _accounts(ledger)
    ledger.post(kind="t", lines=[Line(src.id, DR, Decimal("1.00")), Line(a.id, CR, Decimal("1.00"))])
    db.commit()
    with pytest.raises(DBAPIError, match="append-only"):
        db.execute(text("UPDATE ledger_entries SET amount = 999"))
    db.rollback()
    with pytest.raises(DBAPIError, match="append-only"):
        db.execute(text("DELETE FROM ledger_transactions"))
    db.rollback()
    from app.services.audit import audit

    audit(db, "test.event")
    db.commit()
    with pytest.raises(DBAPIError, match="append-only"):
        db.execute(text("DELETE FROM audit_logs"))
    db.rollback()


def test_db_check_constraint_blocks_negative_balance(db):
    with pytest.raises(DBAPIError):
        db.execute(text("INSERT INTO ledger_accounts (id, code, name, type, currency, balance, allow_negative, "
                        "is_system, debits_blocked, credits_blocked, version, created_at, updated_at) VALUES "
                        "(gen_random_uuid(), 'X', 'X', 'liability', 'GHS', -1, false, false, false, false, 0, now(), now())"))
    db.rollback()


def test_integrity_detects_tampered_cached_balance(ledger, db):
    a, _, src = _accounts(ledger)
    ledger.post(kind="t", lines=[Line(src.id, DR, Decimal("10.00")), Line(a.id, CR, Decimal("10.00"))])
    db.commit()
    db.execute(text("UPDATE ledger_accounts SET balance = 11 WHERE code = 'T:A'"))
    db.commit()
    report = ledger.verify_integrity()
    assert not report["balanced"]
    assert any(p["type"] == "balance_mismatch" for p in report["problems"])


def test_blocked_debits(ledger, db):
    from app.core.errors import AccountRestricted

    a, b, src = _accounts(ledger)
    ledger.post(kind="t", lines=[Line(src.id, DR, Decimal("10.00")), Line(a.id, CR, Decimal("10.00"))])
    a.debits_blocked = True
    db.commit()
    with pytest.raises(AccountRestricted):
        ledger.post(kind="t", lines=[Line(a.id, DR, Decimal("1.00")), Line(b.id, CR, Decimal("1.00"))])
