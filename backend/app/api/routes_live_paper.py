from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.schemas.live_paper import (
    LivePaperEvaluateRequest,
    LivePaperManualExitRequest,
    LivePaperStartRequest,
    LivePaperStopRequest,
)
from app.services.live_paper_simulator_service import get_live_paper_simulator_service


router = APIRouter(prefix="/api/live-paper", tags=["live-paper"])


@router.get("/status")
async def live_paper_status(db: Session = Depends(get_db)) -> dict:
    return {"ok": True, **await get_live_paper_simulator_service().status(db)}


@router.get("/settings")
def live_paper_settings() -> dict:
    return {"ok": True, "settings": get_live_paper_simulator_service().settings_response()}


@router.post("/start")
async def start_live_paper(
    payload: LivePaperStartRequest | None = None,
    db: Session = Depends(get_db),
) -> dict:
    payload = payload or LivePaperStartRequest()
    return await get_live_paper_simulator_service().start(db, payload)


@router.post("/stop")
async def stop_live_paper(
    payload: LivePaperStopRequest | None = None,
    db: Session = Depends(get_db),
) -> dict:
    return await get_live_paper_simulator_service().stop(db, payload)


@router.post("/evaluate-once")
async def evaluate_live_paper_once(
    payload: LivePaperEvaluateRequest | None = None,
    db: Session = Depends(get_db),
) -> dict:
    payload = payload or LivePaperEvaluateRequest()
    return await get_live_paper_simulator_service().evaluate_once(db, payload)


@router.post("/mtm")
async def live_paper_mtm(db: Session = Depends(get_db)) -> dict:
    return await get_live_paper_simulator_service().mtm(db)


@router.get("/open-trades")
async def live_paper_open_trades(db: Session = Depends(get_db)) -> dict:
    return await get_live_paper_simulator_service().open_trades(db)


@router.get("/closed-trades")
def live_paper_closed_trades(db: Session = Depends(get_db)) -> dict:
    return get_live_paper_simulator_service().closed_trades(db)


@router.get("/performance")
def live_paper_performance(db: Session = Depends(get_db)) -> dict:
    return {"ok": True, **get_live_paper_simulator_service().performance(db)}


@router.get("/rejections")
def live_paper_rejections() -> dict:
    return get_live_paper_simulator_service().recent_rejections()


@router.get("/lifecycle")
def live_paper_lifecycle(db: Session = Depends(get_db)) -> dict:
    return get_live_paper_simulator_service().lifecycle(db)


@router.post("/trades/{trade_id}/manual-exit")
async def live_paper_manual_exit(
    trade_id: int,
    payload: LivePaperManualExitRequest | None = None,
    db: Session = Depends(get_db),
) -> dict:
    payload = payload or LivePaperManualExitRequest()
    return await get_live_paper_simulator_service().manual_exit(db, trade_id, payload.exit_price, payload.exit_reason)


from app.models.trade import ComboCreate

@router.post("/combos")
async def create_live_paper_combo(
    payload: ComboCreate,
    db: Session = Depends(get_db)
) -> dict:
    return await get_live_paper_simulator_service().create_combo(db, payload)


@router.get("/combos/open")
def get_open_combos(db: Session = Depends(get_db)) -> dict:
    return get_live_paper_simulator_service().open_combos(db)


@router.get("/combos/closed")
def get_closed_combos(db: Session = Depends(get_db)) -> dict:
    return get_live_paper_simulator_service().closed_combos(db)


@router.post("/combos/{combo_id}/manual-exit")
async def exit_live_paper_combo(
    combo_id: int,
    db: Session = Depends(get_db)
) -> dict:
    return await get_live_paper_simulator_service().exit_combo(db, combo_id)


import json
from app.models.trade import PaperTrade

@router.get("/trades/{trade_id}/birth-certificate")
def get_trade_birth_certificate(trade_id: int, db: Session = Depends(get_db)) -> dict:
    trade = db.get(PaperTrade, trade_id)
    if not trade:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Paper trade not found.")
        
    if not trade.birth_cert_version:
        return {
            "trade_id": str(trade_id),
            "birth_cert_version": None,
            "status": "NO_BIRTH_CERTIFICATE",
            "message": "This trade was created before Phase 3.1. Birth certificates are attached to new trades only."
        }
        
    filter_states = {}
    if trade.filter_states_json:
        try:
            filter_states = json.loads(trade.filter_states_json)
        except Exception:
            pass
            
    return {
        "trade_id": str(trade_id),
        "birth_cert_version": trade.birth_cert_version,
        "confidence_score_at_entry": trade.confidence_score_at_entry,
        "regime_at_entry": trade.regime_at_entry,
        "session_window_at_entry": trade.session_window_at_entry,
        "oi_direction_at_entry": trade.oi_direction_at_entry,
        "market_flow_score_at_entry": trade.market_flow_score_at_entry,
        "pcr_at_entry": trade.pcr_at_entry,
        "spread_pct_at_entry": trade.spread_pct_at_entry,
        "filters_passed_count": trade.filters_passed_count,
        "filter_states": filter_states
    }


@router.post("/reset-session")
async def live_paper_reset_session(db: Session = Depends(get_db)) -> dict:
    return await get_live_paper_simulator_service().reset_session(db)
