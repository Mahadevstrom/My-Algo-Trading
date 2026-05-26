from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.schemas.live_candle import TestTickIngestRequest
from app.schemas.live_feed import NormalizedTick
from app.services.live_market_monitor_service import get_live_market_monitor_service


router = APIRouter(prefix="/api/live-monitor", tags=["live-monitor"])


@router.get("/status")
async def live_monitor_status() -> dict:
    return {"ok": True, **await get_live_market_monitor_service().status()}


@router.post("/start")
async def start_live_monitor(db: Session = Depends(get_db)) -> dict:
    return await get_live_market_monitor_service().start(db)


@router.post("/stop")
async def stop_live_monitor(db: Session = Depends(get_db)) -> dict:
    return await get_live_market_monitor_service().stop(db)


@router.get("/snapshot/{symbol}")
async def live_snapshot(symbol: str) -> dict:
    return await get_live_market_monitor_service().snapshot(symbol)


@router.get("/candles/{symbol}")
async def live_candles(
    symbol: str,
    timeframe: str = Query(default="5m"),
    limit: int = Query(default=100),
) -> dict:
    return await get_live_market_monitor_service().candles(symbol, timeframe, limit)


@router.get("/latest-candle/{symbol}")
async def latest_live_candle(symbol: str, timeframe: str = Query(default="5m")) -> dict:
    return await get_live_market_monitor_service().latest_candle(symbol, timeframe)


@router.get("/market-state/{symbol}")
async def live_market_state(symbol: str) -> dict:
    return await get_live_market_monitor_service().market_state(symbol)


@router.get("/stale-symbols")
async def stale_symbols(db: Session = Depends(get_db)) -> dict:
    return await get_live_market_monitor_service().stale_symbols(db)


@router.get("/symbols")
async def live_symbols() -> dict:
    return await get_live_market_monitor_service().symbols()


@router.get("/option-snapshot/{symbol}")
async def option_snapshot(symbol: str) -> dict:
    return await get_live_market_monitor_service().option_snapshot(symbol)


@router.get("/nifty/overview")
async def nifty_overview() -> dict:
    return await get_live_market_monitor_service().nifty_overview()


@router.post("/rebuild-from-ticks")
async def rebuild_from_ticks(db: Session = Depends(get_db)) -> dict:
    return await get_live_market_monitor_service().rebuild_from_ticks(db)


@router.post("/test/ingest-tick")
async def ingest_test_tick(payload: TestTickIngestRequest, db: Session = Depends(get_db)) -> dict:
    tick_time = payload.timestamp or datetime.now(timezone.utc)
    tick = NormalizedTick(
        exchange_segment=payload.exchange_segment,
        security_id=payload.security_id,
        symbol=payload.symbol,
        ltp=payload.ltp,
        volume=payload.volume,
        open_interest=payload.open_interest,
        timestamp=tick_time,
        received_at=datetime.now(timezone.utc),
        raw_payload={"test_ingest": True},
    )
    return await get_live_market_monitor_service().ingest_test_tick(db, tick)
