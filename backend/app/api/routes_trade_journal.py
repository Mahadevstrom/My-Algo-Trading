from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.services.trade_journal_service import get_trade_journal_service


router = APIRouter(prefix="/api/trade-journal", tags=["trade-journal"])


@router.get("/daily")
def trade_journal_daily(
    trading_date: date | None = Query(default=None),
    underlying: str = Query(default="NIFTY"),
    db: Session = Depends(get_db),
) -> dict:
    return get_trade_journal_service().daily_review(db, trading_date, underlying)


@router.get("/trades/{trade_id}")
def trade_journal_trade(trade_id: int, db: Session = Depends(get_db)) -> dict:
    return get_trade_journal_service().trade_review(db, trade_id)
