from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.services.startup_market_backfill_service import get_startup_market_backfill_service


router = APIRouter(prefix="/api/market-backfill", tags=["market-backfill"])


class MarketBackfillRunRequest(BaseModel):
    symbols: list[str] = Field(default_factory=list)
    source_interval: str | None = None

    @field_validator("symbols", mode="before")
    @classmethod
    def normalize_symbols(cls, value):
        if not value:
            return []
        return [str(item).strip().upper() for item in value if str(item).strip()]


@router.get("/status")
def market_backfill_status() -> dict:
    return {"ok": True, **get_startup_market_backfill_service().status()}


@router.post("/run")
async def run_market_backfill(
    payload: MarketBackfillRunRequest | None = None,
    db: Session = Depends(get_db),
) -> dict:
    payload = payload or MarketBackfillRunRequest()
    return await get_startup_market_backfill_service().backfill_today(
        db=db,
        symbols=payload.symbols or None,
        source_interval=payload.source_interval,
    )
