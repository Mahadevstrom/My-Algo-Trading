from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.services.strategy_evaluation_service import get_strategy_evaluation_service


router = APIRouter(prefix="/api/strategy-evaluation", tags=["strategy-evaluation"])


@router.get("/status")
def strategy_evaluation_status() -> dict:
    return {"ok": True, **get_strategy_evaluation_service().status()}


@router.get("/summary")
async def strategy_evaluation_summary(db: Session = Depends(get_db)) -> dict:
    return await get_strategy_evaluation_service().summary(db)


@router.get("/backtest-vs-paper")
def backtest_vs_paper(db: Session = Depends(get_db)) -> dict:
    return get_strategy_evaluation_service().backtest_vs_paper(db)


@router.get("/signal-v1-vs-v2")
def signal_v1_vs_v2(db: Session = Depends(get_db)) -> dict:
    return get_strategy_evaluation_service().signal_v1_vs_v2(db)


@router.get("/health-score")
def strategy_health_score(db: Session = Depends(get_db)) -> dict:
    return {"ok": True, **get_strategy_evaluation_service().health_score(db)}


@router.get("/rejections")
def strategy_rejections(db: Session = Depends(get_db)) -> dict:
    return get_strategy_evaluation_service().rejections(db)


@router.get("/data-quality-impact")
def data_quality_impact(db: Session = Depends(get_db)) -> dict:
    return get_strategy_evaluation_service().data_quality_impact(db)


@router.get("/performance/by-signal-type")
def performance_by_signal_type(db: Session = Depends(get_db)) -> dict:
    return get_strategy_evaluation_service().performance_by(db, "signal_type")


@router.get("/performance/by-confidence")
def performance_by_confidence(db: Session = Depends(get_db)) -> dict:
    return get_strategy_evaluation_service().performance_by(db, "confidence")


@router.get("/performance/by-chain-bias")
def performance_by_chain_bias(db: Session = Depends(get_db)) -> dict:
    return get_strategy_evaluation_service().performance_by(db, "chain_bias")


@router.get("/daily-review")
async def daily_review(db: Session = Depends(get_db)) -> dict:
    return await get_strategy_evaluation_service().daily_review(db)


@router.get("/recommendation")
def strategy_recommendation(db: Session = Depends(get_db)) -> dict:
    return get_strategy_evaluation_service().recommendation(db)

