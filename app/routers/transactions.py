from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app import services
from app.deps import get_db
from app.schemas import MoneyMovement, TransactionOut, TransferCreate, TransferOut

router = APIRouter(prefix="/transactions", tags=["transactions"])


@router.post("/deposit", response_model=TransactionOut, status_code=status.HTTP_201_CREATED)
def deposit(data: MoneyMovement, db: Session = Depends(get_db)):
    return services.deposit(db, data)


@router.post("/withdrawal", response_model=TransactionOut, status_code=status.HTTP_201_CREATED)
def withdraw(data: MoneyMovement, db: Session = Depends(get_db)):
    return services.withdraw(db, data)


@router.post("/transfer", response_model=TransferOut, status_code=status.HTTP_201_CREATED)
def transfer(data: TransferCreate, db: Session = Depends(get_db)):
    debit, credit = services.transfer(db, data)
    return TransferOut(
        transfer_id=debit.transfer_id,
        debit=TransactionOut.model_validate(debit),
        credit=TransactionOut.model_validate(credit),
    )
