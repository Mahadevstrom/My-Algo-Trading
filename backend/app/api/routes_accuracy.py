from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.engine.paper_accuracy_engine import PaperAccuracyEngine


router = APIRouter(prefix="/api/accuracy", tags=["accuracy"])


@router.get("/summary")
def accuracy_summary(db: Session = Depends(get_db)) -> dict:
    return PaperAccuracyEngine().summary(db)


@router.get("/by-underlying")
def accuracy_by_underlying(db: Session = Depends(get_db)) -> dict:
    return PaperAccuracyEngine().by_underlying(db)


@router.get("/by-signal-type")
def accuracy_by_signal_type(db: Session = Depends(get_db)) -> dict:
    return PaperAccuracyEngine().by_signal_type(db)


@router.get("/by-confidence")
def accuracy_by_confidence(db: Session = Depends(get_db)) -> dict:
    return PaperAccuracyEngine().by_confidence(db)


@router.get("/by-chain-bias")
def accuracy_by_chain_bias(db: Session = Depends(get_db)) -> dict:
    return PaperAccuracyEngine().by_chain_bias(db)


@router.get("/equity-curve")
def equity_curve(db: Session = Depends(get_db)) -> list[dict]:
    return PaperAccuracyEngine().equity_curve(db)


@router.get("/drawdown")
def drawdown(db: Session = Depends(get_db)) -> dict:
    return PaperAccuracyEngine().drawdown(db)


@router.get("/open-risk")
def open_risk(db: Session = Depends(get_db)) -> dict:
    return PaperAccuracyEngine().open_risk(db)


@router.post("/mark-to-market")
async def mark_to_market(
    target_1_exit: bool = Query(default=False),
    db: Session = Depends(get_db),
) -> dict:
    return await PaperAccuracyEngine().mark_to_market(db, target_1_exit=target_1_exit)

