"""Request/response models with strict validation."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

from app.models import AccountStatus, AccountType, TransactionType

Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
Email = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True, to_lower=True, max_length=254, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$"
    ),
]
Currency = Annotated[str, StringConstraints(pattern=r"^[A-Z]{3}$")]
Description = Annotated[str, StringConstraints(strip_whitespace=True, max_length=140)]
IdempotencyKey = Annotated[
    str, StringConstraints(min_length=8, max_length=64, pattern=r"^[A-Za-z0-9_\-]+$")
]
# Positive, max 2 decimal places, single-transaction cap of 1,000,000.00
Amount = Annotated[Decimal, Field(gt=0, le=Decimal("1000000.00"), max_digits=12, decimal_places=2)]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


# ---- customers ------------------------------------------------------------
class CustomerCreate(StrictModel):
    full_name: Name
    email: Email


class CustomerOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    full_name: str
    email: str
    created_at: datetime


# ---- accounts -------------------------------------------------------------
class AccountCreate(StrictModel):
    customer_id: int = Field(gt=0)
    account_type: AccountType = AccountType.CHECKING
    currency: Currency = "USD"


class AccountOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    account_number: str
    customer_id: int
    account_type: AccountType
    currency: str
    balance: Decimal
    status: AccountStatus
    created_at: datetime


# ---- transactions ---------------------------------------------------------
class MoneyMovement(StrictModel):
    account_id: int = Field(gt=0)
    amount: Amount
    description: Description | None = None
    idempotency_key: IdempotencyKey | None = None


class TransferCreate(StrictModel):
    from_account_id: int = Field(gt=0)
    to_account_id: int = Field(gt=0)
    amount: Amount
    description: Description | None = None
    idempotency_key: IdempotencyKey | None = None

    @field_validator("to_account_id")
    @classmethod
    def accounts_differ(cls, v: int, info) -> int:  # noqa: ANN001
        if v == info.data.get("from_account_id"):
            raise ValueError("from_account_id and to_account_id must differ")
        return v


class TransactionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    account_id: int
    type: TransactionType
    amount: Decimal
    balance_after: Decimal
    description: str | None
    transfer_id: str | None
    counterparty_account_id: int | None
    created_at: datetime


class TransferOut(BaseModel):
    transfer_id: str
    debit: TransactionOut
    credit: TransactionOut


class HealthOut(BaseModel):
    status: str
    version: str
    environment: str
    database: str | None = None
    detail: str | None = None
