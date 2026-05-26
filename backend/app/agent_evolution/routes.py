from datetime import datetime, timezone, timedelta
from typing import Any
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select, and_, func
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.config import settings
from app.audit.audit_logger import AuditLogger
from app.agent_evolution.models import AgentEvolutionRecommendation
from app.agent_evolution.analyzer import run_analysis
from app.agent_evolution.recommendation_engine import generate_recommendations
from app.agent_evolution.failure_patterns import detect_all_patterns
from app.analytics.confidence_calibration import calculate_confidence_calibration
from app.analytics.filter_contribution_scorer import calculate_filter_scorecard
from app.models.trade import PaperTrade
from app.services.ai_analyst_service import ai_analyst_service

router = APIRouter(prefix="/api/agent-evolution", tags=["Agent Evolution"])

class ReviewRequest(BaseModel):
    status: str = Field(..., description="Must be APPROVED, REJECTED, or ARCHIVED")
    note: str | None = Field(default=None, description="Optional reviewer note")

@router.get("/status")
def get_agent_evolution_status(db: Session = Depends(get_db)) -> dict:
    # Get last run at
    stmt = select(AgentEvolutionRecommendation.created_at).order_by(AgentEvolutionRecommendation.created_at.desc())
    last_rec = db.scalars(stmt).first()
    last_run_at = last_rec.isoformat() if last_rec else None
    
    # Get counts
    total = db.scalar(select(func.count(AgentEvolutionRecommendation.id))) or 0
    pending = db.scalar(select(func.count(AgentEvolutionRecommendation.id)).where(AgentEvolutionRecommendation.status == "PENDING")) or 0
    approved = db.scalar(select(func.count(AgentEvolutionRecommendation.id)).where(AgentEvolutionRecommendation.status == "APPROVED")) or 0
    rejected = db.scalar(select(func.count(AgentEvolutionRecommendation.id)).where(AgentEvolutionRecommendation.status == "REJECTED")) or 0
    
    return {
        "enabled": settings.enable_agent_evolution_engine,
        "auto_apply": False,  # Always hardcoded to False in response
        "last_run_at": last_run_at,
        "total_recommendations": total,
        "pending_count": pending,
        "approved_count": approved,
        "rejected_count": rejected,
        "config": {
            "lookback_days": settings.agent_evolution_lookback_days,
            "min_trades": settings.agent_evolution_min_trades,
            "max_recs_per_run": settings.agent_evolution_max_recs_per_run,
            "nightly_run_enabled": settings.agent_evolution_nightly_run,
            "nightly_run_time_ist": settings.agent_evolution_run_time_ist
        }
    }

@router.get("/scorecard")
def get_agent_evolution_scorecard(db: Session = Depends(get_db)) -> dict:
    calibration = calculate_confidence_calibration(db, settings.agent_evolution_lookback_days, settings.agent_evolution_min_trades)
    scorecard = calculate_filter_scorecard(db, settings.agent_evolution_lookback_days, min_trades=5)
    return {
        "confidence_calibration": calibration,
        "filter_scorecard": scorecard
    }

@router.get("/failure-patterns")
def get_agent_evolution_failure_patterns(
    lookback_days: int = Query(default=30, ge=7, le=90),
    db: Session = Depends(get_db)
) -> dict:
    cutoff = datetime.now(timezone.utc) - timedelta(days=lookback_days)
    query = select(PaperTrade).where(
        and_(
            PaperTrade.result.in_(["WIN", "LOSS", "BREAKEVEN"]),
            PaperTrade.birth_cert_version.isnot(None),
            PaperTrade.exit_time >= cutoff
        )
    )
    trades = list(db.scalars(query))
    patterns = detect_all_patterns(trades)
    
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "lookback_days": lookback_days,
        "trade_count_analyzed": len(trades),
        "patterns_detected": len(patterns),
        "patterns": patterns
    }

@router.get("/recommendations")
def get_agent_evolution_recommendations(
    status: str = Query(default="PENDING"),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db)
) -> list:
    stmt = select(AgentEvolutionRecommendation)
    if status != "ALL":
        stmt = stmt.where(AgentEvolutionRecommendation.status == status)
        
    stmt = stmt.order_by(AgentEvolutionRecommendation.created_at.desc()).limit(limit).offset(offset)
    recs = list(db.scalars(stmt))
    
    # Custom serialization to include formatted created_at
    result = []
    for r in recs:
        result.append({
            "id": r.id,
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "recommendation_type": r.recommendation_type,
            "affected_module": r.affected_module,
            "issue_detected": r.issue_detected,
            "evidence_summary": r.evidence_summary,
            "suggested_change": r.suggested_change,
            "expected_benefit": r.expected_benefit,
            "risk_level": r.risk_level,
            "confidence": r.confidence,
            "status": r.status,
            "reviewed_at": r.reviewed_at.isoformat() if r.reviewed_at else None,
            "reviewed_by": r.reviewed_by,
            "review_note": r.review_note,
            "run_id": r.run_id,
            "data_snapshot": r.data_snapshot
        })
    return result

@router.get("/recommendations/{rec_id}")
def get_recommendation_by_id(rec_id: int, db: Session = Depends(get_db)) -> dict:
    rec = db.get(AgentEvolutionRecommendation, rec_id)
    if not rec:
        raise HTTPException(status_code=404, detail="Recommendation not found.")
        
    return {
        "id": rec.id,
        "created_at": rec.created_at.isoformat() if rec.created_at else None,
        "recommendation_type": rec.recommendation_type,
        "affected_module": rec.affected_module,
        "issue_detected": rec.issue_detected,
        "evidence_summary": rec.evidence_summary,
        "suggested_change": rec.suggested_change,
        "expected_benefit": rec.expected_benefit,
        "risk_level": rec.risk_level,
        "confidence": rec.confidence,
        "status": rec.status,
        "reviewed_at": rec.reviewed_at.isoformat() if rec.reviewed_at else None,
        "reviewed_by": rec.reviewed_by,
        "review_note": rec.review_note,
        "run_id": rec.run_id,
        "data_snapshot": rec.data_snapshot
    }

@router.post("/recommendations/{rec_id}/review")
def review_recommendation(
    rec_id: int,
    payload: ReviewRequest,
    db: Session = Depends(get_db)
) -> dict:
    rec = db.get(AgentEvolutionRecommendation, rec_id)
    if not rec:
        raise HTTPException(status_code=404, detail="Recommendation not found.")
        
    if payload.status not in ["APPROVED", "REJECTED", "ARCHIVED"]:
        raise HTTPException(status_code=400, detail="Invalid status. Must be APPROVED, REJECTED, or ARCHIVED.")
        
    if rec.status in ["APPROVED", "REJECTED"]:
        raise HTTPException(status_code=400, detail="Recommendation has already been reviewed and finalized.")
        
    rec.status = payload.status
    rec.reviewed_at = datetime.now(timezone.utc)
    rec.reviewed_by = "USER"
    rec.review_note = payload.note
    
    # Log to audit logger
    AuditLogger().log(
        db,
        event_type="RECOMMENDATION_REVIEWED",
        severity="INFO",
        source="AGENT_EVOLUTION",
        message=f"Recommendation {rec_id} reviewed and status updated to {payload.status}.",
        entity_type="AgentEvolutionRecommendation",
        entity_id=rec_id,
        payload={"status": payload.status, "note": payload.note},
        commit=False
    )
    
    db.commit()
    db.refresh(rec)
    
    return {
        "id": rec.id,
        "created_at": rec.created_at.isoformat() if rec.created_at else None,
        "recommendation_type": rec.recommendation_type,
        "affected_module": rec.affected_module,
        "issue_detected": rec.issue_detected,
        "evidence_summary": rec.evidence_summary,
        "suggested_change": rec.suggested_change,
        "expected_benefit": rec.expected_benefit,
        "risk_level": rec.risk_level,
        "confidence": rec.confidence,
        "status": rec.status,
        "reviewed_at": rec.reviewed_at.isoformat() if rec.reviewed_at else None,
        "reviewed_by": rec.reviewed_by,
        "review_note": rec.review_note,
        "run_id": rec.run_id,
        "data_snapshot": rec.data_snapshot
    }

@router.post("/run-analysis")
async def trigger_agent_evolution_analysis(db: Session = Depends(get_db)) -> dict:
    if not settings.enable_agent_evolution_engine:
        return {
            "status": "DISABLED",
            "message": "Agent Evolution Engine is disabled in config. Set ENABLE_AGENT_EVOLUTION_ENGINE=true to enable."
        }
        
    report = run_analysis(db, settings.agent_evolution_lookback_days, settings.agent_evolution_min_trades)
    
    if report.get("status") == "INSUFFICIENT_DATA":
        return report
        
    recs = generate_recommendations(
        db,
        report,
        report["run_id"],
        settings.agent_evolution_max_recs_per_run
    )
    
    # Custom serialization for recommendations in response
    serialized_recs = []
    for r in recs:
        serialized_recs.append({
            "id": r.id,
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "recommendation_type": r.recommendation_type,
            "affected_module": r.affected_module,
            "issue_detected": r.issue_detected,
            "evidence_summary": r.evidence_summary,
            "suggested_change": r.suggested_change,
            "expected_benefit": r.expected_benefit,
            "risk_level": r.risk_level,
            "confidence": r.confidence,
            "status": r.status,
            "run_id": r.run_id
        })
    synthesis = None
    if ai_analyst_service.is_ready():
        synthesis = await ai_analyst_service.synthesize_agent_evolution(report, serialized_recs)
        
    return {
        "status": "OK",
        "run_id": report["run_id"],
        "recommendations_generated": len(recs),
        "recommendations": serialized_recs,
        "nightly_synthesis": synthesis,
        "ai_provider": ai_analyst_service.default_provider if synthesis is not None else None,
        "ai_model": settings.gemini_model_name if synthesis is not None else None,
        "trade_summary": report.get("trade_summary"),
        "patterns_detected": len(report.get("failure_patterns", []))
    }
