"""FinCore management commands.

    python -m app.cli seed                       # fee schedule, limits, system accounts, settings
    python -m app.cli create-admin EMAIL NAME    # prompts for password (or FINCORE_ADMIN_PASSWORD)
    python -m app.cli demo-data                  # sample customers + merchant (development only)
    python -m app.cli reconcile                  # ledger integrity + provider reconciliation
    python -m app.cli worker                     # webhook delivery + provider status polling loop
"""

from __future__ import annotations

import argparse
import getpass
import json
import os
import sys

from sqlalchemy import select

from app.core.config import settings
from app.core.database import SessionLocal
from app.models import User
from app.models.enums import UserRole
from app.services import auth, reconciliation
from app.services.seed import seed_reference_data


def cmd_seed(_: argparse.Namespace) -> None:
    with SessionLocal() as db:
        print(json.dumps(seed_reference_data(db)))


def cmd_create_admin(args: argparse.Namespace) -> None:
    password = os.environ.get("FINCORE_ADMIN_PASSWORD") or getpass.getpass("Password: ")
    with SessionLocal() as db:
        existing = db.scalar(select(User).where(User.email == args.email.lower()))
        if existing:
            existing.role = UserRole.SUPER_ADMIN
            db.commit()
            print(f"Promoted existing user {existing.email} to super_admin")
            return
        user = auth.register(db, email=args.email, password=password, full_name=args.name, phone=None,
                             role=UserRole.SUPER_ADMIN)
        user.email_verified = True
        db.commit()
        print(f"Created super_admin {user.email}")


def cmd_demo_data(_: argparse.Namespace) -> None:
    if settings.is_production:
        sys.exit("Refusing to create demo data in production")
    from app.services.business import create_business, review_business
    from app.services.payments import PaymentService
    from app.services.transactions import TransactionService
    from app.services.wallets import default_user_wallet

    pw = "Demo!Pass2026"
    with SessionLocal() as db:
        seed_reference_data(db)
        if db.scalar(select(User).where(User.email == "admin@fincore.demo")):
            print("Demo data already present")
            return
        admin = auth.register(db, email="admin@fincore.demo", password=pw, full_name="FinCore Admin", phone=None,
                              role=UserRole.SUPER_ADMIN)
        ama = auth.register(db, email="ama@fincore.demo", password=pw, full_name="Ama Owusu", phone="0241234567")
        kofi = auth.register(db, email="kofi@fincore.demo", password=pw, full_name="Kofi Mensah", phone="0201234567")
        for u in (admin, ama, kofi):
            u.email_verified, u.kyc_tier = True, 2
        db.commit()
        txs = TransactionService(db)
        txs.deposit_mobile_money(ama, default_user_wallet(db, ama).id, "1500.00", "0241234567")
        txs.deposit_mobile_money(kofi, default_user_wallet(db, kofi).id, "800.00", "0201234567")
        txs.transfer(ama, default_user_wallet(db, ama).id, default_user_wallet(db, kofi).account_number, "120.00",
                     "Chop money")
        txs.withdraw(ama, default_user_wallet(db, ama).id, "200.00", channel="mobile_money", phone="0241234567")
        biz = create_business(db, kofi, {"name": "Kofi's Kitchen", "business_type": "sole_proprietorship",
                                         "email": "kitchen@fincore.demo", "phone": "0201234567",
                                         "industry": "Food & beverage"})
        review_business(db, biz, admin, "approve", "Demo approval")
        ps = PaymentService(db)
        for amount, phone in (("85.00", "0551234567"), ("42.50", "0271234567"), ("300.00", "0501234567")):
            pr = ps.create_request(biz, amount=amount, description="Lunch order", customer_phone=phone)
            db.commit()
            ps.pay_with_mobile_money(pr, phone)
        pr = ps.create_request(biz, amount="60.00", description="Catering deposit")
        db.commit()
        ps.pay_with_wallet(pr, ama, default_user_wallet(db, ama).id)
        ps.create_link(biz, kofi, title="Kofi's Kitchen - order online", amount=None, description="Pay any amount")
        print("Demo data created. All demo accounts use password:", pw)
        print("  admin@fincore.demo (super admin), ama@fincore.demo (customer), kofi@fincore.demo (merchant owner)")


def cmd_reconcile(_: argparse.Namespace) -> None:
    with SessionLocal() as db:
        ledger = reconciliation.run_ledger_integrity(db)
        prov = reconciliation.run_provider_reconciliation(db)
        print(json.dumps({"ledger": ledger.status, "provider": prov.status, "provider_summary": prov.summary}))
        if ledger.status != "balanced":
            sys.exit(2)


def cmd_worker(args: argparse.Namespace) -> None:
    from app.workers.runner import run_forever

    run_forever(interval=args.interval, once=args.once)


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(prog="fincore")
    sub = p.add_subparsers(required=True)
    sub.add_parser("seed").set_defaults(fn=cmd_seed)
    a = sub.add_parser("create-admin")
    a.add_argument("email")
    a.add_argument("name")
    a.set_defaults(fn=cmd_create_admin)
    sub.add_parser("demo-data").set_defaults(fn=cmd_demo_data)
    sub.add_parser("reconcile").set_defaults(fn=cmd_reconcile)
    w = sub.add_parser("worker")
    w.add_argument("--interval", type=float, default=5.0)
    w.add_argument("--once", action="store_true")
    w.set_defaults(fn=cmd_worker)
    args = p.parse_args(argv)
    args.fn(args)


if __name__ == "__main__":
    main()
