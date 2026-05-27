import json
import logging
import uuid
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.config import settings
from app.engine.context.context_evidence import ContextEvidence
from app.engine.context.models import ContextClassificationLog
from app.engine.setup.setup_logger import log_setup_match
from app.engine.setup.setup_matcher import SetupMatcher
from app.engine.specialist.base import EngineEvidence
from app.engine.specialist.models import SpecialistEngineLog


def run_setup_matcher_shadow(
    db: Session,
    signal_id: str = None,
    signal_v2_decision: str = None,
) -> None:
    if not settings.enable_setup_matcher:
        return
    try:
        evidence = _latest_evidence(db)
        if evidence is None:
            return
        oc_ev, ms_ev, ctx_ev = evidence
        match = SetupMatcher().safe_match(
            db=db,
            oc_evidence=oc_ev,
            ms_evidence=ms_ev,
            context_evidence=ctx_ev,
            signal_id=signal_id,
            signal_v2_decision=signal_v2_decision,
            evaluation_id=str(uuid.uuid4()),
        )
        log_setup_match(db, match, signal_id=signal_id, signal_v2_decision=signal_v2_decision)
    except Exception as exc:
        logging.getLogger(__name__).warning("Setup matcher shadow failed (non-fatal): %s", exc)


def _latest_evidence(db: Session):
    cutoff = datetime.utcnow() - timedelta(seconds=settings.setup_matcher_evidence_window_seconds)
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
    ctx_log = (
        db.query(ContextClassificationLog)
        .filter(ContextClassificationLog.created_at >= cutoff)
        .order_by(ContextClassificationLog.created_at.desc())
        .first()
    )
    if not (oc_log and ms_log and ctx_log):
        return None
    return _engine_evidence(oc_log), _engine_evidence(ms_log), _context_evidence(ctx_log)


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


def _loads(raw: str | None, default):
    if not raw:
        return default
    try:
        return json.loads(raw)
    except Exception:
        return default
