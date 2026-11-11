"""Seed SYNTHETIC demo data (fake names, example.com emails). Idempotent."""

import logging
from decimal import Decimal

from sqlalchemy import select

from app import services
from app.db import Database
from app.models import AccountType, Customer
from app.schemas import AccountCreate, CustomerCreate, MoneyMovement

log = logging.getLogger(__name__)

DEMO_CUSTOMERS = [
    ("Test Customer Alpha", "alpha@example.com", Decimal("2500.00")),
    ("Test Customer Bravo", "bravo@example.com", Decimal("1200.50")),
    ("Test Customer Charlie", "charlie@example.com", Decimal("75.25")),
]


def seed(db: Database) -> None:
    with db.session() as session:
        if session.scalar(select(Customer.id).limit(1)) is not None:
            return
        for name, email, opening in DEMO_CUSTOMERS:
            customer = services.create_customer(
                session, CustomerCreate(full_name=name, email=email)
            )
            account = services.create_account(
                session, AccountCreate(customer_id=customer.id, account_type=AccountType.CHECKING)
            )
            services.deposit(
                session,
                MoneyMovement(account_id=account.id, amount=opening, description="opening deposit"),
            )
        log.info("seeded %d synthetic customers", len(DEMO_CUSTOMERS))
