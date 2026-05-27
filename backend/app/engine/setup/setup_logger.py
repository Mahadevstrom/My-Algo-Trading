import json
import logging

from sqlalchemy.orm import Session

from app.engine.setup.models import SetupMatchLog
from app.engine.setup.setup_evidence import SetupMatchEvidence


def log_setup_match(
    db: Session,
    match: SetupMatchEvidence,
    signal_id: str = None,
    signal_v2_decision: str = None,
) -> SetupMatchLog | None:
    try:
        record = SetupMatchLog(
            evaluation_id=match.evaluation_id,
            signal_id=signal_id,
            setup_name=match.setup_name,
            matched=match.matched,
            match_confidence=match.match_confidence,
            direction_implied=match.direction_implied,
            required_pass_count=match.required_pass_count,
            required_total=match.required_total,
            supporting_pass_count=match.supporting_pass_count,
            supporting_total=match.supporting_total,
            context_type=match.context_type,
            context_modifier=match.context_modifier,
            context_effect=match.context_effect,
            match_summary=match.match_summary,
            evidence_json=json.dumps(match.model_dump(mode="json"), default=str),
            signal_v2_decision=signal_v2_decision,
        )
        db.add(record)
        db.commit()
        db.refresh(record)
        return record
    except Exception as exc:
        db.rollback()
        logging.getLogger(__name__).warning("Setup match log failed (non-fatal): %s", exc)
        return None


def update_setup_outcome(db: Session, evaluation_id: str, market_result: str) -> None:
    try:
        record = db.query(SetupMatchLog).filter(SetupMatchLog.evaluation_id == evaluation_id).first()
        if not record:
            return
        record.market_result = market_result
        if record.direction_implied == "PE" and market_result == "PE_WIN":
            record.outcome_correct = True
        elif record.direction_implied == "CE" and market_result == "CE_WIN":
            record.outcome_correct = True
        elif record.direction_implied == "WAIT" and market_result == "NO_TRADE_CORRECT":
            record.outcome_correct = True
        else:
            record.outcome_correct = False
        db.commit()
    except Exception as exc:
        db.rollback()
        logging.getLogger(__name__).warning("Setup outcome update failed (non-fatal): %s", exc)
