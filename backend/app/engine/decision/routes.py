import json
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.engine.decision.decision_engine_v2 import DecisionEngineV2
from app.engine.decision.models import DecisionEngineV2Log


router = APIRouter(tags=["decision-engine-v2"])


@router.get("/current")
def current_decision_engine_v2(db: Session = Depends(get_db)) -> dict:
    decision = DecisionEngineV2().safe_decide(db=db)
    return {"ok": True, "decision": decision.model_dump(mode="json")}


@router.get("/latest")
def latest_decision_engine_v2(db: Session = Depends(get_db)) -> dict:
    row = db.query(DecisionEngineV2Log).order_by(DecisionEngineV2Log.created_at.desc()).first()
    if not row:
        return {"ok": True, "status": "NO_DATA"}
    return {"ok": True, "item": _row_dict(row)}


@router.get("/history")
def decision_engine_v2_history(
    days: int = Query(default=7, ge=1, le=365),
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
) -> dict:
    cutoff = datetime.utcnow() - timedelta(days=days)
    rows = (
        db.query(DecisionEngineV2Log)
        .filter(DecisionEngineV2Log.created_at >= cutoff)
        .order_by(DecisionEngineV2Log.created_at.desc())
        .limit(limit)
        .all()
    )
    return {"ok": True, "count": len(rows), "items": [_row_dict(row) for row in rows]}


@router.get("/comparison")
def decision_engine_v2_comparison(
    days: int = Query(default=30, ge=1, le=365),
    db: Session = Depends(get_db),
) -> dict:
    cutoff = datetime.utcnow() - timedelta(days=days)
    rows = db.query(DecisionEngineV2Log).filter(DecisionEngineV2Log.created_at >= cutoff).all()
    labelled = [row for row in rows if row.market_result is not None]
    v2_better = sum(1 for row in labelled if row.comparison_verdict == "DECISION_V2_BETTER")
    signal_better = sum(1 for row in labelled if row.comparison_verdict == "SIGNAL_V2_BETTER")
    ties = sum(1 for row in labelled if row.comparison_verdict == "TIE")
    decision_counts = dict(
        db.query(DecisionEngineV2Log.decision, func.count(DecisionEngineV2Log.id))
        .filter(DecisionEngineV2Log.created_at >= cutoff)
        .group_by(DecisionEngineV2Log.decision)
        .all()
    )
    return {
        "ok": True,
        "period_days": days,
        "total_evaluations": len(rows),
        "labelled_count": len(labelled),
        "decision_distribution": decision_counts,
        "decision_v2_better_count": v2_better,
        "signal_v2_better_count": signal_better,
        "tie_count": ties,
        "decision_v2_better_pct": round(v2_better / len(labelled) * 100, 1) if labelled else None,
        "insight": "Need labelled outcomes before Decision Engine v2 comparison is meaningful."
        if not labelled
        else "Comparison is based on labelled outcomes only.",
    }


def _row_dict(row: DecisionEngineV2Log) -> dict:
    return {
        "id": row.id,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "evaluation_id": row.evaluation_id,
        "signal_id": row.signal_id,
        "decision": row.decision,
        "advisory_mode": row.advisory_mode,
        "confidence": row.confidence,
        "setup_name": row.setup_name,
        "setup_matched": row.setup_matched,
        "context_type": row.context_type,
        "agreement_score": row.agreement_score,
        "signal_v2_decision": row.signal_v2_decision,
        "agrees_with_signal_v2": row.agrees_with_signal_v2,
        "would_block_signal_v2_trade": row.would_block_signal_v2_trade,
        "would_take_trade_when_v2_waited": row.would_take_trade_when_v2_waited,
        "reasoning": row.reasoning,
        "reason_codes": _loads(row.reason_codes_json, []),
        "warnings": _loads(row.warnings_json, []),
        "market_result": row.market_result,
        "comparison_verdict": row.comparison_verdict,
        "evidence": _loads(row.evidence_json, {}),
    }


def _loads(raw: str | None, default):
    if not raw:
        return default
    try:
        return json.loads(raw)
    except Exception:
        return default
