from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.services.replay_service import get_replay_service


router = APIRouter(prefix="/api/replay", tags=["replay"])


@router.get("/live-day")
def replay_live_day(
    trading_date: date | None = Query(default=None, description="Trading date in YYYY-MM-DD format. Defaults to today."),
    underlying: str = Query(default="NIFTY", min_length=1, max_length=30),
    max_signal_events: int = Query(default=80, ge=1, le=300),
    db: Session = Depends(get_db),
) -> dict:
    return get_replay_service().run_live_day_replay(db, trading_date, underlying, max_signal_events)
