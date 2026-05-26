from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.engine.paper_engine import (
    PaperEngine,
    PaperTradeAlreadyClosedError,
    PaperTradeBlockedError,
    PaperTradeNotFoundError,
)
from app.models.trade import PaperTradeCreate, PaperTradeExit, PaperTradeRead, PerformanceRead


router = APIRouter(prefix="/api/paper", tags=["paper"])


@router.post("/trades", response_model=PaperTradeRead, status_code=status.HTTP_201_CREATED)
def create_paper_trade(payload: PaperTradeCreate, db: Session = Depends(get_db)) -> PaperTradeRead:
    try:
        return PaperEngine().create_trade(db, payload)
    except PaperTradeBlockedError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"message": "Paper trade blocked by risk manager.", "reasons": exc.reasons},
        ) from exc


@router.get("/trades", response_model=list[PaperTradeRead])
def list_paper_trades(db: Session = Depends(get_db)) -> list[PaperTradeRead]:
    return PaperEngine().list_trades(db)


@router.post("/trades/{trade_id}/exit", response_model=PaperTradeRead)
def exit_paper_trade(
    trade_id: int, payload: PaperTradeExit, db: Session = Depends(get_db)
) -> PaperTradeRead:
    try:
        return PaperEngine().exit_trade(db, trade_id, payload)
    except PaperTradeNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except PaperTradeAlreadyClosedError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.get("/performance", response_model=PerformanceRead)
def paper_performance(db: Session = Depends(get_db)) -> PerformanceRead:
    return PaperEngine().performance(db)

