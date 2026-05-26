from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.services.market_flow_service import get_market_flow_service


router = APIRouter(prefix="/api/market-flow", tags=["market-flow"])


@router.get("/status")
async def market_flow_status(db: Session = Depends(get_db)) -> dict:
    return {"ok": True, **await get_market_flow_service().status(db)}


@router.get("/summary")
async def market_flow_summary(
    symbol: str = Query(default="NIFTY"),
    expiry: date | None = Query(default=None),
    db: Session = Depends(get_db),
) -> dict:
    return await get_market_flow_service().summary(db, symbol, expiry)


@router.get("/option-flow")
async def market_flow_option_flow(
    symbol: str = Query(default="NIFTY"),
    expiry: date | None = Query(default=None),
    db: Session = Depends(get_db),
) -> dict:
    return await get_market_flow_service().option_flow(db, symbol, expiry)


@router.get("/support-resistance")
async def market_flow_support_resistance(
    symbol: str = Query(default="NIFTY"),
    expiry: date | None = Query(default=None),
    db: Session = Depends(get_db),
) -> dict:
    return await get_market_flow_service().support_resistance(db, symbol, expiry)


@router.get("/trap-risk")
async def market_flow_trap_risk(
    symbol: str = Query(default="NIFTY"),
    expiry: date | None = Query(default=None),
    db: Session = Depends(get_db),
) -> dict:
    return await get_market_flow_service().trap_risk(db, symbol, expiry)


@router.get("/smart-money-bias")
async def market_flow_smart_money_bias(
    symbol: str = Query(default="NIFTY"),
    expiry: date | None = Query(default=None),
    db: Session = Depends(get_db),
) -> dict:
    return await get_market_flow_service().smart_money_bias(db, symbol, expiry)


@router.get("/explain")
async def market_flow_explain(
    symbol: str = Query(default="NIFTY"),
    expiry: date | None = Query(default=None),
    db: Session = Depends(get_db),
) -> dict:
    return await get_market_flow_service().explain(db, symbol, expiry)


@router.post("/refresh")
async def market_flow_refresh(
    symbol: str = Query(default="NIFTY"),
    expiry: date | None = Query(default=None),
    db: Session = Depends(get_db),
) -> dict:
    return await get_market_flow_service().summary(db, symbol, expiry, refresh=True)
