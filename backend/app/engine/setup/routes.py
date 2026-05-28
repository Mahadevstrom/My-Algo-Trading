import json
import uuid
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.config import settings
from app.db.database import get_db
from app.engine.context.context_evidence import ContextEvidence
from app.engine.context.models import ContextClassificationLog
from app.engine.setup.models import SetupDefinition, SetupMatchLog
from app.engine.setup.setup_matcher import SetupMatcher
from app.engine.specialist.base import EngineEvidence
from app.engine.specialist.models import SpecialistEngineLog


router = APIRouter(tags=["setup"])


@router.get("/definitions")
def setup_definitions(db: Session = Depends(get_db)) -> dict:
    rows = (
        db.query(SetupDefinition)
        .filter(SetupDefinition.is_active == True)  # noqa: E712
        .order_by(SetupDefinition.id.asc())
        .all()
    )
    return {"ok": True, "count": len(rows), "items": [_definition_dict(item) for item in rows]}


@router.get("/definitions/{setup_name}")
def setup_definition(setup_name: str, db: Session = Depends(get_db)) -> dict:
    row = db.query(SetupDefinition).filter(SetupDefinition.setup_name == setup_name).first()
    if not row:
        raise HTTPException(status_code=404, detail="Setup definition not found")
    return {"ok": True, "item": _definition_dict(row)}


@router.post("/definitions/{setup_name}/toggle")
def toggle_setup_definition(setup_name: str, db: Session = Depends(get_db)) -> dict:
    row = db.query(SetupDefinition).filter(SetupDefinition.setup_name == setup_name).first()
    if not row:
        raise HTTPException(status_code=404, detail="Setup definition not found")
    row.is_active = not row.is_active
    db.commit()
    db.refresh(row)
    return {"ok": True, "item": _definition_dict(row)}


@router.get("/match/latest")
def latest_setup_match(db: Session = Depends(get_db)) -> dict:
    row = db.query(SetupMatchLog).order_by(SetupMatchLog.created_at.desc()).first()
    if not row:
        return {"ok": True, "status": "NO_DATA"}
    return {"ok": True, "item": _match_dict(row)}


@router.get("/match/history")
def setup_match_history(
    days: int = Query(default=7, ge=1, le=365),
    limit: int = Query(default=50, ge=1, le=200),
    matched_only: bool = Query(default=False),
    db: Session = Depends(get_db),
) -> dict:
    cutoff = datetime.utcnow() - timedelta(days=days)
    query = db.query(SetupMatchLog).filter(SetupMatchLog.created_at >= cutoff)
    if matched_only:
        query = query.filter(SetupMatchLog.matched == True)  # noqa: E712
    rows = query.order_by(SetupMatchLog.created_at.desc()).limit(limit).all()
    return {"ok": True, "count": len(rows), "items": [_match_dict(item) for item in rows]}


@router.get("/match/current")
def current_setup_match(db: Session = Depends(get_db)) -> dict:
    evidence = _latest_evidence(db, window_seconds=300)
    if not evidence:
        return {
            "ok": True,
            "status": "INSUFFICIENT_ENGINE_DATA",
            "message": "Need option chain, market structure, and context evidence from the last 5 minutes.",
        }
    oc_ev, ms_ev, ctx_ev, momentum_ev = evidence
    match = SetupMatcher().safe_match(
        db=db,
        oc_evidence=oc_ev,
        ms_evidence=ms_ev,
        context_evidence=ctx_ev,
        momentum_evidence=momentum_ev,
        evaluation_id=str(uuid.uuid4()),
    )
    return {"ok": True, "match": match.model_dump(mode="json")}


@router.get("/performance")
def setup_performance(db: Session = Depends(get_db)) -> dict:
    definitions = db.query(SetupDefinition).order_by(SetupDefinition.id.asc()).all()
    items = []
    total_evaluations = int(db.query(func.count(SetupMatchLog.id)).scalar() or 0)
    for definition in definitions:
        logs = db.query(SetupMatchLog).filter(SetupMatchLog.setup_name == definition.setup_name).all()
        matched = [item for item in logs if item.matched]
        labelled = [item for item in matched if item.market_result is not None]
        wins = [item for item in labelled if item.outcome_correct]
        items.append(
            {
                "setup_name": definition.setup_name,
                "display_name": definition.display_name,
                "total_evaluations": len(logs),
                "matched_count": len(matched),
                "match_rate_pct": round(len(matched) / len(logs) * 100, 1) if logs else None,
                "labelled_count": len(labelled),
                "win_count": len(wins),
                "win_rate_pct": round(len(wins) / len(labelled) * 100, 1) if labelled else None,
                "avg_pnl": None,
                "best_context": _best_context(labelled),
                "worst_context": _worst_context(labelled),
            }
        )
    matched_items = [item for item in items if item["matched_count"] > 0]
    most_matched = max(matched_items, key=lambda item: item["matched_count"], default=None)
    win_rate_items = [item for item in items if item["win_rate_pct"] is not None]
    highest_win_rate = max(win_rate_items, key=lambda item: item["win_rate_pct"], default=None)
    return {
        "ok": True,
        "generated_at": datetime.utcnow().isoformat(),
        "setups": items,
        "total_evaluations": total_evaluations,
        "most_matched_setup": most_matched["setup_name"] if most_matched else None,
        "highest_win_rate_setup": highest_win_rate["setup_name"] if highest_win_rate else None,
        "insight": "Setup performance needs labelled outcomes before win rates are meaningful."
        if not win_rate_items
        else "Setup performance is based on labelled setup outcomes.",
    }


def _latest_evidence(db: Session, window_seconds: int | None = None):
    seconds = window_seconds or settings.setup_matcher_evidence_window_seconds
    cutoff = datetime.utcnow() - timedelta(seconds=seconds)
    oc_log = (
        db.query(SpecialistEngineLog)
        .filter(SpecialistEngineLog.engine_name == "option_chain_engine", SpecialistEngineLog.created_at >= cutoff)
        .order_by(SpecialistEngineLog.created_at.desc())
        .first()
    )
    ms_log = (
        db.query(SpecialistEngineLog)
        .filter(SpecialistEngineLog.engine_name == "market_structure_engine", SpecialistEngineLog.created_at >= cutoff)
        .order_by(SpecialistEngineLog.created_at.desc())
        .first()
    )
    momentum_log = (
        db.query(SpecialistEngineLog)
        .filter(SpecialistEngineLog.engine_name == "nifty_momentum_engine", SpecialistEngineLog.created_at >= cutoff)
        .order_by(SpecialistEngineLog.created_at.desc())
        .first()
    )
    ctx_log = (
        db.query(ContextClassificationLog)
        .filter(ContextClassificationLog.created_at >= cutoff)
        .order_by(ContextClassificationLog.created_at.desc())
        .first()
    )
    if not (oc_log and ms_log and ctx_log):
        return None
    momentum_evidence = _engine_evidence(momentum_log) if momentum_log else None
    return _engine_evidence(oc_log), _engine_evidence(ms_log), _context_evidence(ctx_log), momentum_evidence


def _engine_evidence(row: SpecialistEngineLog) -> EngineEvidence:
    return EngineEvidence(
        engine=row.engine_name,
        score=row.score or 50.0,
        direction=row.direction or "NEUTRAL",
        verdict=row.verdict or "NEUTRAL",
        confidence=row.confidence or 0.5,
        evidence=_loads(row.evidence_json, {}),
        warnings=_loads(row.warnings_json, []),
        blocking=row.blocking or False,
        blocking_reason=row.blocking_reason,
        evaluated_at=row.evaluated_at or row.created_at,
        evaluation_id=row.evaluation_id,
    )


def _context_evidence(row: ContextClassificationLog) -> ContextEvidence:
    return ContextEvidence(
        context_type=row.context_type,
        context_confidence=row.context_confidence or 0.7,
        secondary_context=row.secondary_context,
        ist_time_str=row.ist_time_str or "00:00",
        ist_date_str=row.ist_date_str or "2026-01-01",
        day_of_week=row.day_of_week or "MONDAY",
        is_expiry_day=row.is_expiry_day or False,
        is_monthly_expiry=row.is_monthly_expiry or False,
        days_to_expiry=row.days_to_expiry if row.days_to_expiry is not None else 7,
        opening_gap_pct=row.opening_gap_pct,
        vix_value=row.vix_value,
        vix_vs_20day_avg_pct=row.vix_vs_20day_avg_pct,
        previous_day_range_pct=None,
        is_known_event_day=row.is_known_event_day or False,
        known_event_name=row.known_event_name,
        data_quality_status=row.data_quality_status or "UNKNOWN",
        confidence_modifier=row.confidence_modifier or 0.0,
        context_summary=row.context_summary or "",
        evaluated_at=row.created_at,
        evaluation_id=row.evaluation_id,
    )


def _definition_dict(row: SetupDefinition) -> dict:
    return {
        "id": row.id,
        "setup_name": row.setup_name,
        "display_name": row.display_name,
        "description": row.description,
        "direction": row.direction,
        "required_conditions": _loads(row.required_conditions_json, []),
        "supporting_conditions": _loads(row.supporting_conditions_json, []),
        "min_supporting_required": row.min_supporting_required,
        "valid_contexts": _loads(row.valid_contexts_json, []),
        "blocked_contexts": _loads(row.blocked_contexts_json, []),
        "context_modifiers": _loads(row.context_modifiers_json, {}),
        "min_confidence": row.min_confidence,
        "is_active": row.is_active,
        "version": row.version,
    }


def _match_dict(row: SetupMatchLog) -> dict:
    return {
        "id": row.id,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "evaluation_id": row.evaluation_id,
        "signal_id": row.signal_id,
        "setup_name": row.setup_name,
        "matched": row.matched,
        "match_confidence": row.match_confidence,
        "direction_implied": row.direction_implied,
        "context_type": row.context_type,
        "context_effect": row.context_effect,
        "signal_v2_decision": row.signal_v2_decision,
        "market_result": row.market_result,
        "outcome_correct": row.outcome_correct,
        "match_summary": row.match_summary,
        "evidence": _loads(row.evidence_json, {}),
    }


def _loads(raw: str | None, default):
    if not raw:
        return default
    try:
        return json.loads(raw)
    except Exception:
        return default


def _best_context(logs: list[SetupMatchLog]) -> str | None:
    return _context_by_outcome(logs, True)


def _worst_context(logs: list[SetupMatchLog]) -> str | None:
    return _context_by_outcome(logs, False)


def _context_by_outcome(logs: list[SetupMatchLog], outcome: bool) -> str | None:
    counts: dict[str, int] = {}
    for item in logs:
        if item.outcome_correct is outcome and item.context_type:
            counts[item.context_type] = counts.get(item.context_type, 0) + 1
    if not counts:
        return None
    return max(counts, key=lambda k: counts[k])
