from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.schemas.option_chain_snapshot import OptionChainSnapshotSummary, SnapshotCaptureRequest
from app.services.option_chain_snapshot_service import get_option_chain_snapshot_service


router = APIRouter(prefix="/api/option-chain-snapshots", tags=["option-chain-snapshots"])


@router.get("/status")
def option_chain_snapshot_status(db: Session = Depends(get_db)) -> dict:
    return {"ok": True, **get_option_chain_snapshot_service().status(db)}


@router.post("/capture")
async def capture_option_chain_snapshot(
    request: SnapshotCaptureRequest | None = None,
    symbol: str | None = Query(default=None),
    expiry: date | None = Query(default=None),
    max_strikes: int | None = Query(default=None, ge=1, le=200),
    db: Session = Depends(get_db),
) -> dict:
    body = request or SnapshotCaptureRequest()
    return await get_option_chain_snapshot_service().capture_snapshot(
        db,
        symbol=symbol or body.symbol,
        expiry=expiry or body.expiry,
        max_strikes=max_strikes or body.max_strikes,
    )


@router.get("/latest")
def latest_option_chain_snapshot(
    symbol: str = Query(default="NIFTY"),
    expiry: date | None = Query(default=None),
    db: Session = Depends(get_db),
) -> dict:
    snapshot = get_option_chain_snapshot_service().get_latest_snapshot(db, symbol, expiry)
    if snapshot is None:
        return {
            "ok": False,
            "status": "NO_LATEST_SNAPSHOT",
            "message": "No latest option-chain snapshot found.",
            "symbol": symbol.upper(),
            "expiry": expiry.isoformat() if expiry else None,
        }
    return {"ok": True, "snapshot": OptionChainSnapshotSummary.model_validate(snapshot).model_dump(mode="json")}


@router.get("/history")
def option_chain_snapshot_history(
    symbol: str = Query(default="NIFTY"),
    expiry: date | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=200),
    db: Session = Depends(get_db),
) -> dict:
    items = get_option_chain_snapshot_service().get_snapshot_history(db, symbol, expiry, limit)
    return {
        "ok": True,
        "symbol": symbol.upper(),
        "expiry": expiry.isoformat() if expiry else None,
        "count": len(items),
        "items": [OptionChainSnapshotSummary.model_validate(item).model_dump(mode="json") for item in items],
    }


@router.get("/changes/latest")
def option_chain_snapshot_changes(
    symbol: str = Query(default="NIFTY"),
    expiry: date | None = Query(default=None),
    db: Session = Depends(get_db),
) -> dict:
    return get_option_chain_snapshot_service().changes(db, symbol, expiry)


@router.get("/changes")
def option_chain_snapshot_changes_alias(
    symbol: str = Query(default="NIFTY"),
    expiry: date | None = Query(default=None),
    db: Session = Depends(get_db),
) -> dict:
    return get_option_chain_snapshot_service().changes(db, symbol, expiry)


@router.get("/strike-change")
def option_chain_strike_change(
    symbol: str = Query(default="NIFTY"),
    expiry: date | None = Query(default=None),
    strike: float = Query(...),
    option_type: str = Query(...),
    db: Session = Depends(get_db),
) -> dict:
    return get_option_chain_snapshot_service().strike_change(db, symbol, expiry, strike, option_type)


@router.post("/purge-old")
def purge_old_option_chain_snapshots(
    retention_days: int | None = Query(default=None, ge=1, le=365),
    db: Session = Depends(get_db),
) -> dict:
    return get_option_chain_snapshot_service().purge_old_snapshots(db, retention_days)


@router.get("/{snapshot_id}/strikes")
def option_chain_snapshot_strikes(snapshot_id: int, db: Session = Depends(get_db)) -> dict:
    return get_option_chain_snapshot_service().get_strike_snapshots(db, snapshot_id)
