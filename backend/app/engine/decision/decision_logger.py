import json
import logging

from sqlalchemy.orm import Session

from app.engine.decision.decision_evidence import DecisionEngineV2Evidence
from app.engine.decision.models import DecisionEngineV2Log


def log_decision_engine_v2(
    db: Session,
    decision: DecisionEngineV2Evidence,
    signal_id: str = None,
    signal_v2_decision: str = None,
) -> DecisionEngineV2Log | None:
    try:
        row = DecisionEngineV2Log(
            evaluation_id=decision.evaluation_id,
            signal_id=signal_id,
            decision=decision.decision,
            advisory_mode=decision.advisory_mode,
            confidence=decision.confidence,
            setup_name=decision.setup_name,
            setup_matched=decision.setup_matched,
            setup_confidence=decision.setup_confidence,
            context_type=decision.context_type,
            context_modifier=decision.context_modifier,
            agreement_score=decision.agreement_score,
            signal_v2_decision=_normalize_decision(signal_v2_decision or decision.signal_v2_decision),
            agrees_with_signal_v2=decision.agrees_with_signal_v2,
            would_block_signal_v2_trade=decision.would_block_signal_v2_trade,
            would_take_trade_when_v2_waited=decision.would_take_trade_when_v2_waited,
            reasoning=decision.reasoning,
            reason_codes_json=json.dumps(decision.reason_codes),
            warnings_json=json.dumps(decision.warnings),
            evidence_json=json.dumps(decision.model_dump(mode="json")),
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return row
    except Exception as exc:
        db.rollback()
        logging.getLogger(__name__).warning("Decision Engine v2 logging failed (non-fatal): %s", exc)
        return None


def update_decision_engine_outcome(db: Session, evaluation_id: str, market_result: str) -> None:
    try:
        row = db.query(DecisionEngineV2Log).filter(DecisionEngineV2Log.evaluation_id == evaluation_id).first()
        if not row:
            return
        row.market_result = market_result
        row.signal_v2_correct = _decision_matches_result(row.signal_v2_decision, market_result)
        row.decision_v2_correct = _decision_matches_result(row.decision, market_result)
        if row.signal_v2_correct is True and row.decision_v2_correct is False:
            row.comparison_verdict = "SIGNAL_V2_BETTER"
        elif row.signal_v2_correct is False and row.decision_v2_correct is True:
            row.comparison_verdict = "DECISION_V2_BETTER"
        elif row.signal_v2_correct == row.decision_v2_correct:
            row.comparison_verdict = "TIE"
        else:
            row.comparison_verdict = "UNKNOWN"
        db.commit()
    except Exception as exc:
        db.rollback()
        logging.getLogger(__name__).warning("Decision Engine v2 outcome update failed (non-fatal): %s", exc)


def _decision_matches_result(decision: str | None, market_result: str | None) -> bool | None:
    normalized_decision = _normalize_decision(decision)
    normalized_result = (market_result or "").upper()
    if normalized_decision == "PE":
        return normalized_result in {"PE_WIN", "PE_PROFIT", "BEARISH_WIN"}
    if normalized_decision == "CE":
        return normalized_result in {"CE_WIN", "CE_PROFIT", "BULLISH_WIN"}
    if normalized_decision == "WAIT":
        return normalized_result in {"NO_TRADE_CORRECT", "WAIT_CORRECT"}
    return None


def _normalize_decision(decision: str | None) -> str | None:
    value = (decision or "").upper()
    if value in {"NO_TRADE", "HOLD", "SKIP", "NONE"}:
        return "WAIT"
    if value in {"CALL", "BUY_CE"}:
        return "CE"
    if value in {"PUT", "BUY_PE"}:
        return "PE"
    if value in {"CE", "PE", "WAIT"}:
        return value
    return value or None
