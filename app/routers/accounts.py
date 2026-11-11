from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import services
from app.deps import get_db
from app.models import Account
from app.schemas import AccountCreate, AccountOut, TransactionOut

router = APIRouter(prefix="/accounts", tags=["accounts"])


@router.post("", response_model=AccountOut, status_code=status.HTTP_201_CREATED)
def create_account(data: AccountCreate, db: Session = Depends(get_db)):
    return services.create_account(db, data)


@router.get("", response_model=list[AccountOut])
def list_accounts(
    customer_id: int | None = Query(None, gt=0),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    stmt = select(Account).order_by(Account.id).limit(limit).offset(offset)
    if customer_id is not None:
        stmt = stmt.where(Account.customer_id == customer_id)
    return db.scalars(stmt).all()


@router.get("/{account_id}", response_model=AccountOut)
def get_account(account_id: int, db: Session = Depends(get_db)):
    return services.get_account(db, account_id)


@router.get("/{account_id}/transactions", response_model=list[TransactionOut])
def account_transactions(
    account_id: int,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    return services.list_transactions(db, account_id, limit, offset)
