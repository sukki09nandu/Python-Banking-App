"""ORM models. Money is stored as NUMERIC(18,2) and handled as Decimal - never float."""

from __future__ import annotations

import enum
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base

MONEY = Numeric(18, 2)


def utcnow() -> datetime:
    return datetime.now(UTC)


class AccountType(enum.StrEnum):
    CHECKING = "checking"
    SAVINGS = "savings"


class AccountStatus(enum.StrEnum):
    ACTIVE = "active"
    FROZEN = "frozen"


class TransactionType(enum.StrEnum):
    DEPOSIT = "deposit"
    WITHDRAWAL = "withdrawal"
    TRANSFER_IN = "transfer_in"
    TRANSFER_OUT = "transfer_out"


class Customer(Base):
    __tablename__ = "customers"

    id: Mapped[int] = mapped_column(primary_key=True)
    full_name: Mapped[str] = mapped_column(String(100))
    email: Mapped[str] = mapped_column(String(254), unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    accounts: Mapped[list[Account]] = relationship(back_populates="customer")


class Account(Base):
    __tablename__ = "accounts"
    __table_args__ = (CheckConstraint("balance >= 0", name="ck_accounts_balance_non_negative"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    account_number: Mapped[str] = mapped_column(String(12), unique=True, index=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"), index=True)
    account_type: Mapped[AccountType] = mapped_column(Enum(AccountType, native_enum=False))
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    balance: Mapped[Decimal] = mapped_column(MONEY, default=Decimal("0.00"))
    status: Mapped[AccountStatus] = mapped_column(
        Enum(AccountStatus, native_enum=False), default=AccountStatus.ACTIVE
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    customer: Mapped[Customer] = relationship(back_populates="accounts")


class Transaction(Base):
    __tablename__ = "transactions"
    __table_args__ = (
        CheckConstraint("amount > 0", name="ck_transactions_amount_positive"),
        # The same idempotency key replayed against the same account returns the
        # original transaction instead of moving money twice.
        UniqueConstraint("account_id", "idempotency_key", name="uq_transactions_idempotency"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"), index=True)
    type: Mapped[TransactionType] = mapped_column(Enum(TransactionType, native_enum=False))
    amount: Mapped[Decimal] = mapped_column(MONEY)
    balance_after: Mapped[Decimal] = mapped_column(MONEY)
    description: Mapped[str | None] = mapped_column(String(140))
    transfer_id: Mapped[str | None] = mapped_column(String(36), index=True)
    counterparty_account_id: Mapped[int | None] = mapped_column(ForeignKey("accounts.id"))
    idempotency_key: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
