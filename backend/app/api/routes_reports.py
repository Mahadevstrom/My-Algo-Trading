from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.services.reporting_service import get_reporting_service


router = APIRouter(prefix="/api/reports", tags=["reports"])


@router.get("/status")
def reports_status() -> dict:
    return {"ok": True, **get_reporting_service().status()}


@router.get("/system-health")
async def system_health_report(db: Session = Depends(get_db)) -> dict:
    return await get_reporting_service().system_health(db)


@router.get("/daily-review")
async def daily_review_report(
    report_date: date | None = Query(default=None, alias="date"),
    db: Session = Depends(get_db),
) -> dict:
    return await get_reporting_service().daily_review(db, report_date)


@router.get("/strategy-evaluation")
async def strategy_evaluation_report(db: Session = Depends(get_db)) -> dict:
    return await get_reporting_service().strategy_evaluation(db)


@router.get("/live-paper-summary")
async def live_paper_report(db: Session = Depends(get_db)) -> dict:
    return await get_reporting_service().live_paper_summary(db)


@router.get("/market-flow-summary")
async def market_flow_report(symbol: str = Query(default="NIFTY"), db: Session = Depends(get_db)) -> dict:
    return await get_reporting_service().market_flow_summary(db, symbol)


@router.get("/participant-flow-summary")
def participant_flow_report(symbol: str = Query(default="NIFTY"), db: Session = Depends(get_db)) -> dict:
    return get_reporting_service().participant_flow_summary(db, symbol)


@router.get("/sector-breadth-summary")
async def sector_breadth_report(index: str = Query(default="NIFTY"), db: Session = Depends(get_db)) -> dict:
    return await get_reporting_service().sector_breadth_summary(db, index)


@router.get("/data-quality-summary")
async def data_quality_report(db: Session = Depends(get_db)) -> dict:
    return await get_reporting_service().data_quality_summary(db)


@router.get("/audit-summary")
def audit_summary_report(
    lookback_days: int = Query(default=7, ge=1, le=365),
    db: Session = Depends(get_db),
) -> dict:
    return get_reporting_service().audit_summary(db, lookback_days)


@router.get("/export/daily-review")
async def export_daily_review(format: str = Query(default="json"), db: Session = Depends(get_db)) -> dict:
    return await get_reporting_service().export_report(db, "daily_review", format)


@router.get("/export/strategy-evaluation")
async def export_strategy_evaluation(format: str = Query(default="json"), db: Session = Depends(get_db)) -> dict:
    return await get_reporting_service().export_report(db, "strategy_evaluation", format)


@router.get("/export/system-health")
async def export_system_health(format: str = Query(default="json"), db: Session = Depends(get_db)) -> dict:
    return await get_reporting_service().export_report(db, "system_health", format)
