from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from app.config import settings
from app.db.database import get_db
from app.engine.historical_data_service import HistoricalDataService


router = APIRouter(prefix="/api/historical", tags=["historical-data"])


class IntradayDownloadRequest(BaseModel):
    symbol: str = Field(..., min_length=1, max_length=80)
    interval: str = Field(..., min_length=1, max_length=10)
    from_date: str = Field(..., min_length=1)
    to_date: str = Field(..., min_length=1)

    @field_validator("symbol", mode="before")
    @classmethod
    def normalize_symbol(cls, value: str) -> str:
        return str(value).strip().upper()


class DailyDownloadRequest(BaseModel):
    symbol: str = Field(..., min_length=1, max_length=80)
    from_date: str = Field(..., min_length=1)
    to_date: str = Field(..., min_length=1)

    @field_validator("symbol", mode="before")
    @classmethod
    def normalize_symbol(cls, value: str) -> str:
        return str(value).strip().upper()


class GapPatchRequest(BaseModel):
    symbol: str = Field(..., min_length=1, max_length=80)
    interval: str = Field(..., min_length=1, max_length=10)
    gaps: list[str] = Field(default_factory=list)

    @field_validator("symbol", mode="before")
    @classmethod
    def normalize_symbol(cls, value: str) -> str:
        return str(value).strip().upper()



@router.get("/status")
def historical_status() -> dict[str, Any]:
    database_type = "POSTGRESQL" if settings.database_url.startswith("postgresql") else "SQLITE"
    return {
        "ok": True,
        "status": "READY",
        "database_type": database_type,
        "storage": "LOCAL_DATABASE",
        "source": "DHAN",
        "dhan_data_enabled": settings.dhan_data_enabled,
        "paper_only": True,
        "live_orders_enabled": settings.allow_live_orders and settings.enable_dhan_order_placement,
        "message": "Historical candle storage is ready. This is market-data storage only, not trading execution.",
    }


@router.post("/download-intraday")
async def download_intraday(
    payload: IntradayDownloadRequest,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    return await HistoricalDataService().download_intraday(
        db=db,
        symbol=payload.symbol,
        interval=payload.interval,
        from_date=payload.from_date,
        to_date=payload.to_date,
    )


@router.post("/download-daily")
async def download_daily(
    payload: DailyDownloadRequest,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    return await HistoricalDataService().download_daily(
        db=db,
        symbol=payload.symbol,
        from_date=payload.from_date,
        to_date=payload.to_date,
    )


@router.get("/candles")
def get_candles(
    symbol: str = Query(..., min_length=1),
    interval: str = Query(..., min_length=1),
    from_date: str = Query(..., min_length=1),
    to_date: str = Query(..., min_length=1),
    limit: int = Query(default=5000, ge=1, le=20000),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    return HistoricalDataService().get_candles(
        db=db,
        symbol=symbol,
        interval=interval,
        from_date=from_date,
        to_date=to_date,
        limit=limit,
    )


@router.get("/summary")
def historical_summary(
    symbol: str = Query(..., min_length=1),
    interval: str = Query(..., min_length=1),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    return HistoricalDataService().get_summary(db=db, symbol=symbol, interval=interval)


@router.get("/gap-scan")
def gap_scan(
    symbol: str = Query(..., min_length=1),
    interval: str = Query(..., min_length=1),
    from_date: str = Query(..., min_length=1),
    to_date: str = Query(..., min_length=1),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    return HistoricalDataService().scan_gaps(
        db=db,
        symbol=symbol,
        interval=interval,
        from_date=from_date,
        to_date=to_date,
    )


@router.post("/gap-patch")
async def gap_patch(
    payload: GapPatchRequest,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    return await HistoricalDataService().patch_gaps(
        db=db,
        symbol=payload.symbol,
        interval=payload.interval,
        gaps_list=payload.gaps,
    )

