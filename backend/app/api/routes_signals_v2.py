from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.engine.signal_engine_v2 import get_signal_engine_v2
from app.schemas.signal_v2 import SignalV2GenerateRequest


router = APIRouter(prefix="/api/signals-v2", tags=["signals-v2"])


async def _log_option_chain_shadow(db: Session, underlying: str, signal_result) -> None:
    try:
        from app.engine.specialist.option_chain_engine import run_option_chain_shadow

        await run_option_chain_shadow(
            db=db,
            underlying=underlying,
            signal_id=str(getattr(signal_result, "id", "")) if getattr(signal_result, "id", None) is not None else None,
            signal_v2_decision=getattr(signal_result, "decision", None),
        )
    except Exception:
        pass


def _log_context_shadow(db: Session, underlying: str, signal_result) -> None:
    try:
        from app.engine.context.context_classifier import run_context_shadow

        run_context_shadow(
            db=db,
            underlying=underlying,
            signal_result=signal_result,
            signal_id=str(getattr(signal_result, "id", "")) if getattr(signal_result, "id", None) is not None else None,
            signal_v2_decision=getattr(signal_result, "decision", None),
        )
    except Exception:
        pass


async def _log_market_structure_shadow(db: Session, underlying: str, signal_result) -> None:
    try:
        from app.engine.specialist.market_structure_engine import run_market_structure_shadow

        await run_market_structure_shadow(
            db=db,
            underlying=underlying,
            signal_id=str(getattr(signal_result, "id", "")) if getattr(signal_result, "id", None) is not None else None,
            signal_v2_decision=getattr(signal_result, "decision", None),
        )
    except Exception:
        pass


async def _log_nifty_momentum_shadow(db: Session, underlying: str, signal_result) -> None:
    try:
        from app.engine.specialist.nifty_momentum_engine import run_nifty_momentum_shadow

        await run_nifty_momentum_shadow(
            db=db,
            underlying=underlying,
            signal_id=str(getattr(signal_result, "id", "")) if getattr(signal_result, "id", None) is not None else None,
            signal_v2_decision=getattr(signal_result, "decision", None),
        )
    except Exception:
        pass


def _log_setup_matcher_shadow(db: Session, signal_result) -> None:
    try:
        from app.engine.setup.setup_shadow_runner import run_setup_matcher_shadow

        run_setup_matcher_shadow(
            db=db,
            signal_id=str(getattr(signal_result, "id", "")) if getattr(signal_result, "id", None) is not None else None,
            signal_v2_decision=getattr(signal_result, "decision", None),
        )
    except Exception:
        pass


def _log_decision_engine_v2_shadow(db: Session, signal_result) -> None:
    try:
        from app.engine.decision.decision_engine_v2 import run_decision_engine_v2_shadow

        run_decision_engine_v2_shadow(
            db=db,
            signal_id=str(getattr(signal_result, "id", "")) if getattr(signal_result, "id", None) is not None else None,
            signal_v2_decision=getattr(signal_result, "decision", None),
        )
    except Exception:
        pass


@router.get("/status")
async def signal_v2_status() -> dict:
    return await get_signal_engine_v2().status()


@router.post("/generate")
async def generate_signal_v2(
    request: SignalV2GenerateRequest,
    db: Session = Depends(get_db),
) -> dict:
    result = await get_signal_engine_v2().generate(db, request)
    await _log_option_chain_shadow(db, request.underlying, result)
    _log_context_shadow(db, request.underlying, result)
    await _log_market_structure_shadow(db, request.underlying, result)
    await _log_nifty_momentum_shadow(db, request.underlying, result)
    _log_setup_matcher_shadow(db, result)
    _log_decision_engine_v2_shadow(db, result)
    return {"ok": True, "signal": result.model_dump(mode="json")}


@router.post("/analyze-nifty")
async def analyze_nifty_v2(db: Session = Depends(get_db)) -> dict:
    result = await get_signal_engine_v2().analyze_nifty(db)
    await _log_option_chain_shadow(db, "NIFTY", result)
    _log_context_shadow(db, "NIFTY", result)
    await _log_market_structure_shadow(db, "NIFTY", result)
    await _log_nifty_momentum_shadow(db, "NIFTY", result)
    _log_setup_matcher_shadow(db, result)
    _log_decision_engine_v2_shadow(db, result)
    return {"ok": True, "signal": result.model_dump(mode="json")}


@router.get("/latest")
def latest_signal_v2(limit: int = Query(default=20, ge=1, le=100)) -> dict:
    return get_signal_engine_v2().latest(limit)


@router.get("/explain/{signal_id}")
def explain_signal_v2(signal_id: int) -> dict:
    return get_signal_engine_v2().explain(signal_id)


@router.post("/compare-v1")
async def compare_signal_v1_v2(
    request: SignalV2GenerateRequest,
    db: Session = Depends(get_db),
) -> dict:
    return await get_signal_engine_v2().compare_v1(db, request)
