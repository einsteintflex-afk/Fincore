"""Double-entry ledger engine.

Rules enforced here (and backed by DB constraints/triggers):

* Every journal has >= 2 lines, every line amount > 0, and per currency
  ``sum(debits) == sum(credits)``.
* Accounts are locked with ``SELECT ... FOR UPDATE`` in a deterministic order
  (sorted by id) so concurrent postings serialise without deadlocking.
* A non-``allow_negative`` account can never go below zero.
* Entries and journals are never updated or deleted. Corrections are made with
  compensating journals via :meth:`LedgerService.reverse` (at most once per journal).
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.core.errors import AccountRestricted, Conflict, InsufficientFunds, LedgerError, NotFound
from app.core.money import ZERO, round_money
from app.core.security import generate_reference
from app.models.enums import DEBIT_NORMAL, AccountType, EntryDirection
from app.models.ledger import LedgerAccount, LedgerEntry, LedgerTransaction

DR = EntryDirection.DEBIT
CR = EntryDirection.CREDIT


class SystemAccount:
    """Purposes of platform-owned ledger accounts (one per currency)."""

    FEE_REVENUE = ("FEE_REVENUE", AccountType.REVENUE, False, "Fee revenue")
    PENDING_PAYOUTS = ("PENDING_PAYOUTS", AccountType.LIABILITY, False, "Funds held for in-flight payouts")
    SUSPENSE = ("SUSPENSE", AccountType.LIABILITY, True, "Suspense / unallocated funds")
    ADJUSTMENTS = ("ADJUSTMENTS", AccountType.EXPENSE, True, "Manual adjustments & write-offs")
    EQUITY = ("OWNER_EQUITY", AccountType.EQUITY, True, "Owner equity")

    @staticmethod
    def clearing(provider: str) -> tuple[str, AccountType, bool, str]:
        # Asset: what the provider owes us (collections) minus what we've paid out through it.
        return (f"PROVIDER_CLEARING:{provider.upper()}", AccountType.ASSET, True, f"{provider} clearing")


@dataclass(frozen=True)
class Line:
    account_id: uuid.UUID
    direction: EntryDirection
    amount: Decimal


def balance_delta(account_type: str, direction: str, amount: Decimal) -> Decimal:
    debit_normal = AccountType(account_type) in DEBIT_NORMAL
    if direction == DR:
        return amount if debit_normal else -amount
    return -amount if debit_normal else amount


class LedgerService:
    def __init__(self, db: Session) -> None:
        self.db = db

    # ------------------------------------------------------------ accounts
    def create_account(self, *, code: str, name: str, type: AccountType, currency: str,
                       allow_negative: bool = False, is_system: bool = False) -> LedgerAccount:
        acct = LedgerAccount(code=code, name=name, type=type.value, currency=currency,
                             allow_negative=allow_negative, is_system=is_system, balance=ZERO)
        self.db.add(acct)
        self.db.flush()
        return acct

    def system_account(self, purpose: tuple[str, AccountType, bool, str], currency: str) -> LedgerAccount:
        key, acct_type, allow_negative, name = purpose
        code = f"SYS:{currency}:{key}"
        acct = self.db.scalar(select(LedgerAccount).where(LedgerAccount.code == code))
        if acct:
            return acct
        # Create in a savepoint so a concurrent creator doesn't abort the outer transaction.
        try:
            with self.db.begin_nested():
                return self.create_account(code=code, name=f"{name} ({currency})", type=acct_type,
                                           currency=currency, allow_negative=allow_negative, is_system=True)
        except Exception:  # unique violation from a concurrent insert
            acct = self.db.scalar(select(LedgerAccount).where(LedgerAccount.code == code))
            if not acct:
                raise
            return acct

    def get_account(self, account_id: uuid.UUID) -> LedgerAccount:
        acct = self.db.get(LedgerAccount, account_id)
        if not acct:
            raise NotFound("Ledger account not found")
        return acct

    # ------------------------------------------------------------ posting
    def post(self, *, kind: str, lines: list[Line], description: str = "", reference: str | None = None,
             meta: dict | None = None, reversal_of_id: uuid.UUID | None = None,
             enforce_restrictions: bool = True) -> LedgerTransaction:
        if len(lines) < 2:
            raise LedgerError("A journal needs at least two lines")

        accounts = self._lock_accounts({ln.account_id for ln in lines})

        totals: dict[str, dict[str, Decimal]] = defaultdict(lambda: {DR: ZERO, CR: ZERO})
        normalised: list[Line] = []
        for ln in lines:
            acct = accounts[ln.account_id]
            if ln.direction not in (DR, CR):
                raise LedgerError(f"Invalid direction {ln.direction}")
            amount = round_money(ln.amount, acct.currency)
            if amount != ln.amount:
                raise LedgerError(f"Amount {ln.amount} has more precision than {acct.currency} allows")
            if amount <= 0:
                raise LedgerError("Ledger line amounts must be positive")
            totals[acct.currency][ln.direction] += amount
            normalised.append(Line(ln.account_id, EntryDirection(ln.direction), amount))

        for currency, t in totals.items():
            if t[DR] != t[CR]:
                raise LedgerError(f"Unbalanced journal in {currency}: debits {t[DR]} != credits {t[CR]}")

        txn = LedgerTransaction(
            reference=reference or generate_reference("LJ"),
            kind=kind,
            description=description,
            meta=meta or {},
            reversal_of_id=reversal_of_id,
        )
        self.db.add(txn)
        self.db.flush()

        running: dict[uuid.UUID, Decimal] = {aid: a.balance for aid, a in accounts.items()}
        for i, ln in enumerate(normalised, start=1):
            acct = accounts[ln.account_id]
            if enforce_restrictions:
                if ln.direction == DR and acct.debits_blocked:
                    raise AccountRestricted(f"Account {acct.code} is blocked for debits")
                if ln.direction == CR and acct.credits_blocked:
                    raise AccountRestricted(f"Account {acct.code} is blocked for credits")
            running[acct.id] += balance_delta(acct.type, ln.direction, ln.amount)
            self.db.add(LedgerEntry(
                transaction_id=txn.id, account_id=acct.id, line=i, direction=ln.direction.value,
                amount=ln.amount, currency=acct.currency, balance_after=running[acct.id],
            ))

        for aid, new_balance in running.items():
            acct = accounts[aid]
            if new_balance < 0 and not acct.allow_negative:
                raise InsufficientFunds("Insufficient funds", details={"account": acct.code})
            if new_balance != acct.balance:
                acct.balance = new_balance
                acct.version += 1

        self.db.flush()
        return txn

    def transfer(self, *, kind: str, debit_account_id: uuid.UUID, credit_account_id: uuid.UUID,
                 amount: Decimal, **kw) -> LedgerTransaction:
        return self.post(kind=kind, lines=[Line(debit_account_id, DR, amount), Line(credit_account_id, CR, amount)], **kw)

    def reverse(self, ledger_txn_id: uuid.UUID, *, reason: str, kind: str = "reversal",
                enforce_restrictions: bool = False) -> LedgerTransaction:
        """Post a compensating journal that exactly mirrors ``ledger_txn_id``."""
        original = self.db.get(LedgerTransaction, ledger_txn_id)
        if not original:
            raise NotFound("Ledger transaction not found")
        already = self.db.scalar(select(LedgerTransaction.id).where(LedgerTransaction.reversal_of_id == original.id))
        if already:
            raise Conflict("Ledger transaction has already been reversed", code="already_reversed")
        lines = [
            Line(e.account_id, CR if e.direction == DR else DR, e.amount)
            for e in sorted(original.entries, key=lambda e: e.line)
        ]
        return self.post(kind=kind, lines=lines, description=f"Reversal of {original.reference}: {reason}",
                         reversal_of_id=original.id, meta={"reason": reason, "original": original.reference},
                         enforce_restrictions=enforce_restrictions)

    def _lock_accounts(self, ids: set[uuid.UUID]) -> dict[uuid.UUID, LedgerAccount]:
        stmt = (
            select(LedgerAccount)
            .where(LedgerAccount.id.in_(sorted(ids)))
            .order_by(LedgerAccount.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        rows = {a.id: a for a in self.db.scalars(stmt)}
        missing = ids - rows.keys()
        if missing:
            raise NotFound(f"Ledger account(s) not found: {sorted(map(str, missing))}")
        return rows

    # ------------------------------------------------------------ queries
    def computed_balance(self, account: LedgerAccount) -> Decimal:
        debits = self.db.scalar(select(func.coalesce(func.sum(LedgerEntry.amount), 0)).where(
            LedgerEntry.account_id == account.id, LedgerEntry.direction == DR))
        credits = self.db.scalar(select(func.coalesce(func.sum(LedgerEntry.amount), 0)).where(
            LedgerEntry.account_id == account.id, LedgerEntry.direction == CR))
        debits, credits = Decimal(debits), Decimal(credits)
        return debits - credits if AccountType(account.type) in DEBIT_NORMAL else credits - debits

    def verify_integrity(self) -> dict:
        """Check (1) every journal balances, (2) cached balances equal entry sums, (3) trial balance."""
        problems: list[dict] = []

        unbalanced = self.db.execute(
            select(LedgerEntry.transaction_id, LedgerEntry.currency,
                   func.sum(case((LedgerEntry.direction == DR, LedgerEntry.amount), else_=0)).label("dr"),
                   func.sum(case((LedgerEntry.direction == CR, LedgerEntry.amount), else_=0)).label("cr"))
            .group_by(LedgerEntry.transaction_id, LedgerEntry.currency)
        ).all()
        for row in unbalanced:
            if Decimal(row.dr) != Decimal(row.cr):
                problems.append({"type": "unbalanced_journal", "transaction_id": str(row.transaction_id),
                                 "currency": row.currency, "debits": str(row.dr), "credits": str(row.cr)})

        sums = {
            (r.account_id, r.direction): Decimal(r.total)
            for r in self.db.execute(
                select(LedgerEntry.account_id, LedgerEntry.direction, func.sum(LedgerEntry.amount).label("total"))
                .group_by(LedgerEntry.account_id, LedgerEntry.direction)
            )
        }
        accounts = self.db.scalars(select(LedgerAccount).execution_options(populate_existing=True)).all()
        trial: dict[str, dict[str, Decimal]] = defaultdict(lambda: {"debit": ZERO, "credit": ZERO})
        for acct in accounts:
            dr = sums.get((acct.id, "debit"), ZERO)
            cr = sums.get((acct.id, "credit"), ZERO)
            expected = dr - cr if AccountType(acct.type) in DEBIT_NORMAL else cr - dr
            if expected != acct.balance:
                problems.append({"type": "balance_mismatch", "account": acct.code,
                                 "cached": str(acct.balance), "computed": str(expected)})
            if acct.balance < 0 and not acct.allow_negative:
                problems.append({"type": "negative_balance", "account": acct.code, "balance": str(acct.balance)})
            trial[acct.currency]["debit"] += dr
            trial[acct.currency]["credit"] += cr

        for currency, t in trial.items():
            if t["debit"] != t["credit"]:
                problems.append({"type": "trial_balance", "currency": currency,
                                 "debits": str(t["debit"]), "credits": str(t["credit"])})

        return {
            "balanced": not problems,
            "accounts_checked": len(accounts),
            "journals_checked": len(unbalanced),
            "trial_balance": {c: {k: str(v) for k, v in t.items()} for c, t in trial.items()},
            "problems": problems,
        }
