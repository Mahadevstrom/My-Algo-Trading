from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.services.data_quality_service import get_data_quality_service


router = APIRouter(prefix="/api/data-quality", tags=["data-quality"])


@router.get("/status")
async def data_quality_status() -> dict:
    return {"ok": True, **await get_data_quality_service().status()}


@router.get("/config")
def data_quality_config() -> dict:
    return {"ok": True, "config": get_data_quality_service().config()}


@router.get("/symbol/{symbol}")
async def data_quality_symbol(symbol: str, db: Session = Depends(get_db)) -> dict:
    summary = await get_data_quality_service().get_symbol(db, symbol)
    return {"ok": True, "summary": summary.model_dump(mode="json")}


@router.get("/security/{security_id}")
async def data_quality_security(security_id: str, db: Session = Depends(get_db)) -> dict:
    summary = await get_data_quality_service().get_security(db, security_id)
    return {"ok": True, "summary": summary.model_dump(mode="json")}


@router.post("/check/{symbol}")
async def run_data_quality_symbol_check(symbol: str, db: Session = Depends(get_db)) -> dict:
    summary = await get_data_quality_service().check_symbol(db, symbol)
    return {"ok": True, "summary": summary.model_dump(mode="json")}


@router.post("/check-security/{security_id}")
async def run_data_quality_security_check(security_id: str, db: Session = Depends(get_db)) -> dict:
    summary = await get_data_quality_service().check_security(db, security_id)
    return {"ok": True, "summary": summary.model_dump(mode="json")}


@router.post("/check-nifty")
async def run_data_quality_nifty_check(db: Session = Depends(get_db)) -> dict:
    return await get_data_quality_service().check_nifty(db)


@router.get("/stale")
async def data_quality_stale() -> dict:
    return await get_data_quality_service().stale()


@router.get("/mismatches")
async def data_quality_mismatches() -> dict:
    return await get_data_quality_service().mismatches()


@router.get("/history/{symbol}")
async def data_quality_history(symbol: str, limit: int = Query(default=50, ge=1, le=500)) -> dict:
    return await get_data_quality_service().history(symbol, limit)


@router.post("/run-all")
async def run_all_data_quality_checks(db: Session = Depends(get_db)) -> dict:
    return await get_data_quality_service().run_all(db)
