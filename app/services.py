"""Business logic for money movement.

Safety rules:
* Amounts are Decimal, validated positive with at most 2 decimal places.
* Accounts are locked with SELECT ... FOR UPDATE, always in ascending id order,
  so concurrent transfers cannot deadlock or double-spend.
* Balance can never go negative (checked in code and by a DB CHECK constraint).
* Optional idempotency keys make client retries safe.
* Each operation commits atomically or rolls back entirely.
"""

from __future__ import annotations

import secrets
import uuid
from decimal import Decimal

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import Account, AccountStatus, Customer, Transaction, TransactionType
from app.schemas import AccountCreate, CustomerCreate, MoneyMovement, TransferCreate

CENT = Decimal("0.01")


def _not_found(what: str, ident: int) -> HTTPException:
    return HTTPException(status.HTTP_404_NOT_FOUND, f"{what} {ident} not found")


# ---- customers ------------------------------------------------------------
def create_customer(db: Session, data: CustomerCreate) -> Customer:
    customer = Customer(full_name=data.full_name, email=data.email)
    db.add(customer)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "email already registered") from None
    return customer


def get_customer(db: Session, customer_id: int) -> Customer:
    customer = db.get(Customer, customer_id)
    if customer is None:
        raise _not_found("customer", customer_id)
    return customer


# ---- accounts -------------------------------------------------------------
def _new_account_number(db: Session) -> str:
    while True:
        number = "".join(secrets.choice("0123456789") for _ in range(12))
        if db.scalar(select(Account.id).where(Account.account_number == number)) is None:
            return number


def create_account(db: Session, data: AccountCreate) -> Account:
    get_customer(db, data.customer_id)
    account = Account(
        account_number=_new_account_number(db),
        customer_id=data.customer_id,
        account_type=data.account_type,
        currency=data.currency,
        balance=Decimal("0.00"),
    )
    db.add(account)
    db.commit()
    return account


def get_account(db: Session, account_id: int) -> Account:
    account = db.get(Account, account_id)
    if account is None:
        raise _not_found("account", account_id)
    return account


def _lock_accounts(db: Session, ids: list[int]) -> dict[int, Account]:
    stmt = select(Account).where(Account.id.in_(ids)).order_by(Account.id).with_for_update()
    found = {a.id: a for a in db.scalars(stmt)}
    for ident in ids:
        if ident not in found:
            db.rollback()
            raise _not_found("account", ident)
        if found[ident].status != AccountStatus.ACTIVE:
            db.rollback()
            raise HTTPException(status.HTTP_409_CONFLICT, f"account {ident} is not active")
    return found


# ---- idempotency ----------------------------------------------------------
def _existing(db: Session, account_id: int, key: str | None) -> Transaction | None:
    if key is None:
        return None
    return db.scalar(
        select(Transaction).where(
            Transaction.account_id == account_id, Transaction.idempotency_key == key
        )
    )


def _commit_or_replay(db: Session, account_id: int, key: str | None) -> Transaction | None:
    """Commit; if a concurrent request with the same key won the race, return its row."""
    try:
        db.commit()
        return None
    except IntegrityError:
        db.rollback()
        replay = _existing(db, account_id, key)
        if replay is None:
            raise
        return replay


# ---- money movement -------------------------------------------------------
def deposit(db: Session, data: MoneyMovement) -> Transaction:
    if replay := _existing(db, data.account_id, data.idempotency_key):
        return replay
    account = _lock_accounts(db, [data.account_id])[data.account_id]
    account.balance = (account.balance + data.amount).quantize(CENT)
    tx = Transaction(
        account_id=account.id,
        type=TransactionType.DEPOSIT,
        amount=data.amount,
        balance_after=account.balance,
        description=data.description,
        idempotency_key=data.idempotency_key,
    )
    db.add(tx)
    return _commit_or_replay(db, account.id, data.idempotency_key) or tx


def withdraw(db: Session, data: MoneyMovement) -> Transaction:
    if replay := _existing(db, data.account_id, data.idempotency_key):
        return replay
    account = _lock_accounts(db, [data.account_id])[data.account_id]
    if account.balance < data.amount:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "insufficient funds")
    account.balance = (account.balance - data.amount).quantize(CENT)
    tx = Transaction(
        account_id=account.id,
        type=TransactionType.WITHDRAWAL,
        amount=data.amount,
        balance_after=account.balance,
        description=data.description,
        idempotency_key=data.idempotency_key,
    )
    db.add(tx)
    return _commit_or_replay(db, account.id, data.idempotency_key) or tx


def _transfer_pair(db: Session, debit: Transaction) -> tuple[Transaction, Transaction]:
    credit = db.scalar(
        select(Transaction).where(
            Transaction.transfer_id == debit.transfer_id,
            Transaction.type == TransactionType.TRANSFER_IN,
        )
    )
    assert credit is not None
    return debit, credit


def transfer(db: Session, data: TransferCreate) -> tuple[Transaction, Transaction]:
    if replay := _existing(db, data.from_account_id, data.idempotency_key):
        return _transfer_pair(db, replay)

    accounts = _lock_accounts(db, [data.from_account_id, data.to_account_id])
    source, target = accounts[data.from_account_id], accounts[data.to_account_id]

    if source.currency != target.currency:
        db.rollback()
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "cross-currency transfers not supported")
    if source.balance < data.amount:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "insufficient funds")

    transfer_id = str(uuid.uuid4())
    source.balance = (source.balance - data.amount).quantize(CENT)
    target.balance = (target.balance + data.amount).quantize(CENT)
    debit = Transaction(
        account_id=source.id,
        type=TransactionType.TRANSFER_OUT,
        amount=data.amount,
        balance_after=source.balance,
        description=data.description,
        transfer_id=transfer_id,
        counterparty_account_id=target.id,
        idempotency_key=data.idempotency_key,
    )
    credit = Transaction(
        account_id=target.id,
        type=TransactionType.TRANSFER_IN,
        amount=data.amount,
        balance_after=target.balance,
        description=data.description,
        transfer_id=transfer_id,
        counterparty_account_id=source.id,
    )
    db.add_all([debit, credit])
    if replay := _commit_or_replay(db, source.id, data.idempotency_key):
        return _transfer_pair(db, replay)
    return debit, credit


def list_transactions(db: Session, account_id: int, limit: int, offset: int) -> list[Transaction]:
    get_account(db, account_id)
    stmt = (
        select(Transaction)
        .where(Transaction.account_id == account_id)
        .order_by(Transaction.id.desc())
        .limit(limit)
        .offset(offset)
    )
    return list(db.scalars(stmt))
