import json
import logging
import uuid

from sqlalchemy.orm import Session

from app.engine.specialist.base import EngineEvidence
from app.engine.specialist.models import SpecialistEngineLog

logger = logging.getLogger(__name__)


def _json_dump(value) -> str:
    return json.dumps(value, default=str)


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


def log_engine_evidence(
    db: Session,
    evidence: EngineEvidence,
    signal_id: str = None,
    signal_v2_decision: str = None,
) -> SpecialistEngineLog | None:
    try:
        record = SpecialistEngineLog(
            evaluation_id=evidence.evaluation_id or str(uuid.uuid4()),
            signal_id=signal_id,
            engine_name=evidence.engine,
            score=evidence.score,
            direction=evidence.direction,
            verdict=evidence.verdict,
            confidence=evidence.confidence,
            blocking=evidence.blocking,
            blocking_reason=evidence.blocking_reason,
            warnings_json=_json_dump(evidence.warnings),
            evidence_json=_json_dump(evidence.evidence),
            evaluated_at=evidence.evaluated_at,
            signal_engine_v2_decision=_normalize_signal_decision(signal_v2_decision),
            market_result=None,
            label_source=None,
            comparison_verdict=None,
        )
        db.add(record)
        db.commit()
        db.refresh(record)
        return record
    except Exception as e:
        db.rollback()
        logger.warning(f"Shadow log failed (non-fatal): {e}")
        return None


def update_market_result(
    db: Session,
    evaluation_id: str,
    engine_name: str,
    market_result: str,
    label_source: str = "AUTO",
) -> None:
    try:
        record = (
            db.query(SpecialistEngineLog)
            .filter(
                SpecialistEngineLog.evaluation_id == evaluation_id,
                SpecialistEngineLog.engine_name == engine_name,
            )
            .first()
        )
        if not record:
            return
        record.market_result = market_result
        record.label_source = label_source
        engine_dir = record.direction
        sv2 = _normalize_signal_decision(record.signal_engine_v2_decision)
        if market_result in ("PE_WIN", "CE_WIN"):
            winner_dir = "BEARISH" if market_result.startswith("PE") else "BULLISH"
            winner_signal = "PE" if winner_dir == "BEARISH" else "CE"
            if engine_dir == winner_dir and sv2 == winner_signal:
                record.comparison_verdict = "AGREEMENT"
            elif engine_dir == winner_dir:
                record.comparison_verdict = "ENGINE_BETTER"
            elif sv2 == winner_signal:
                record.comparison_verdict = "SIGNAL_V2_BETTER"
            else:
                record.comparison_verdict = "BOTH_WRONG"
        elif market_result in ("PE_LOSS", "CE_LOSS"):
            record.comparison_verdict = "BOTH_WRONG"
        elif market_result == "NO_TRADE_CORRECT":
            record.comparison_verdict = "AGREEMENT"
        elif market_result == "NO_TRADE_MISSED":
            if record.direction in ("BEARISH", "BULLISH"):
                record.comparison_verdict = "ENGINE_BETTER"
            else:
                record.comparison_verdict = "SIGNAL_V2_BETTER"
        db.commit()
    except Exception as e:
        db.rollback()
        logger.warning(f"update_market_result failed (non-fatal): {e}")
