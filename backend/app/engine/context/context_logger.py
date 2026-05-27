import logging

from sqlalchemy.orm import Session

from app.engine.context.context_evidence import ContextEvidence
from app.engine.context.models import ContextClassificationLog

logger = logging.getLogger(__name__)


def log_context_classification(
    db: Session,
    context: ContextEvidence,
    signal_id: str = None,
    signal_v2_decision: str = None,
) -> ContextClassificationLog | None:
    try:
        record = ContextClassificationLog(
            evaluation_id=context.evaluation_id,
            signal_id=signal_id,
            context_type=context.context_type,
            context_confidence=context.context_confidence,
            secondary_context=context.secondary_context,
            ist_time_str=context.ist_time_str,
            ist_date_str=context.ist_date_str,
            day_of_week=context.day_of_week,
            is_expiry_day=context.is_expiry_day,
            is_monthly_expiry=context.is_monthly_expiry,
            days_to_expiry=context.days_to_expiry,
            opening_gap_pct=context.opening_gap_pct,
            vix_value=context.vix_value,
            vix_vs_20day_avg_pct=context.vix_vs_20day_avg_pct,
            is_known_event_day=context.is_known_event_day,
            known_event_name=context.known_event_name,
            data_quality_status=context.data_quality_status,
            confidence_modifier=context.confidence_modifier,
            context_summary=context.context_summary,
            signal_v2_decision=_normalize_signal_decision(signal_v2_decision),
        )
        db.add(record)
        db.commit()
        db.refresh(record)
        return record
    except Exception as exc:
        db.rollback()
        logger.warning(f"Context classification log failed (non-fatal): {exc}")
        return None


def _normalize_signal_decision(decision: str | None) -> str | None:
    if decision is None:
        return None
    value = str(decision).upper()
    if value in ("PE", "BUY_PUT", "PUT"):
        return "PE"
    if value in ("CE", "BUY_CALL", "CALL"):
        return "CE"
    if value in ("WAIT", "NO_TRADE", "SKIP"):
        return "WAIT"
    return value
