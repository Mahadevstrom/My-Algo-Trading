import json
import logging
import uuid
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy.orm import Session

from app.config import settings
from app.engine.context.models import ContextClassificationLog
from app.engine.decision.decision_evidence import DecisionEngineV2Evidence
from app.engine.decision.decision_logger import log_decision_engine_v2
from app.engine.setup.models import SetupMatchLog
from app.engine.specialist.models import SpecialistEngineLog


WAIT_CONTEXTS = {"STALE_DATA_DAY", "EXPIRY_DAY_AFTERNOON", "RANGING_CHOPPY"}
TRADE_DECISIONS = {"CE", "PE"}


class DecisionEngineV2:
    """Shadow/advisory judge that compares specialist evidence with Signal Engine v2."""

    def decide(
        self,
        db: Session,
        signal_id: str = None,
        signal_v2_decision: str = None,
        evaluation_id: str = None,
    ) -> DecisionEngineV2Evidence:
        evidence = latest_decision_inputs(db)
        if evidence is None:
            return self._insufficient(signal_v2_decision, evaluation_id)

        oc_log, ms_log, momentum_log, ctx_log, setup_log = evidence
        context_type = ctx_log.context_type or "UNKNOWN"
        setup_name = setup_log.setup_name or "NO_SETUP_FOUND"
        setup_direction = _normalize_decision(setup_log.direction_implied)
        signal_v2 = _normalize_decision(signal_v2_decision or setup_log.signal_v2_decision or oc_log.signal_engine_v2_decision)
        votes = {
            "option_chain_engine": _direction_to_decision(oc_log.direction),
            "market_structure_engine": _direction_to_decision(ms_log.direction),
            "nifty_momentum_engine": _direction_to_decision(momentum_log.direction),
            "setup_matcher": setup_direction if setup_log.matched else "WAIT",
            "context": "WAIT" if context_type in WAIT_CONTEXTS else "NEUTRAL",
        }
        reason_codes: list[str] = []
        warnings: list[str] = []

        if oc_log.blocking or ms_log.blocking or momentum_log.blocking:
            decision = "WAIT"
            confidence = 0.0
            reason_codes.append("ENGINE_BLOCKING")
            warnings.append("One or more specialist engines reported blocking data quality.")
        elif context_type in WAIT_CONTEXTS:
            decision = "WAIT"
            confidence = 0.85
            reason_codes.append(f"CONTEXT_BLOCK_{context_type}")
            warnings.append(f"Context {context_type} blocks advisory entries.")
        elif not setup_log.matched:
            decision = "WAIT"
            confidence = 0.65
            reason_codes.append("NO_SETUP_MATCH")
        else:
            decision, confidence, setup_reasons, setup_warnings = self._directional_decision(
                setup_direction=setup_direction,
                setup_confidence=setup_log.match_confidence or 0.0,
                context_modifier=setup_log.context_modifier or 0.0,
                votes=votes,
                momentum_verdict=momentum_log.verdict or "",
            )
            reason_codes.extend(setup_reasons)
            warnings.extend(setup_warnings)

        agreement_score = _agreement_score(decision, votes)
        confidence = max(0.0, min(1.0, round(confidence, 3)))
        if decision in TRADE_DECISIONS and confidence < settings.decision_engine_v2_min_confidence:
            reason_codes.append("CONFIDENCE_BELOW_THRESHOLD")
            warnings.append("Advisory confidence below Decision Engine v2 threshold; downgraded to WAIT.")
            decision = "WAIT"

        agrees = decision == signal_v2 if signal_v2 else None
        would_block = signal_v2 in TRADE_DECISIONS and decision == "WAIT"
        would_take = signal_v2 == "WAIT" and decision in TRADE_DECISIONS
        reasoning = _build_reasoning(decision, setup_name, context_type, votes, confidence, reason_codes)
        return DecisionEngineV2Evidence(
            decision=decision,
            advisory_mode=settings.decision_engine_v2_mode,
            confidence=confidence,
            setup_name=setup_name,
            setup_matched=bool(setup_log.matched),
            setup_confidence=round(setup_log.match_confidence or 0.0, 3),
            context_type=context_type,
            context_modifier=round(ctx_log.confidence_modifier or setup_log.context_modifier or 0.0, 3),
            engine_votes=votes,
            agreement_score=agreement_score,
            signal_v2_decision=signal_v2,
            agrees_with_signal_v2=agrees,
            would_block_signal_v2_trade=would_block,
            would_take_trade_when_v2_waited=would_take,
            reason_codes=reason_codes,
            warnings=warnings,
            reasoning=reasoning,
            evidence={
                "option_chain": _engine_summary(oc_log),
                "market_structure": _engine_summary(ms_log),
                "nifty_momentum": _engine_summary(momentum_log),
                "context": {
                    "context_type": context_type,
                    "secondary_context": ctx_log.secondary_context,
                    "confidence_modifier": ctx_log.confidence_modifier,
                    "data_quality_status": ctx_log.data_quality_status,
                },
                "setup": {
                    "setup_name": setup_name,
                    "matched": setup_log.matched,
                    "direction_implied": setup_log.direction_implied,
                    "match_confidence": setup_log.match_confidence,
                    "summary": setup_log.match_summary,
                },
            },
            evaluated_at=datetime.utcnow(),
            evaluation_id=evaluation_id,
        )

    def safe_decide(
        self,
        db: Session,
        signal_id: str = None,
        signal_v2_decision: str = None,
        evaluation_id: str = None,
    ) -> DecisionEngineV2Evidence:
        try:
            return self.decide(db, signal_id=signal_id, signal_v2_decision=signal_v2_decision, evaluation_id=evaluation_id)
        except Exception as exc:
            logging.getLogger(__name__).warning("Decision Engine v2 failed (non-fatal): %s", exc)
            return DecisionEngineV2Evidence(
                decision="WAIT",
                advisory_mode=settings.decision_engine_v2_mode,
                confidence=0.0,
                setup_name="ENGINE_ERROR",
                setup_matched=False,
                setup_confidence=0.0,
                context_type="UNKNOWN",
                context_modifier=0.0,
                engine_votes={},
                agreement_score=0.0,
                signal_v2_decision=_normalize_decision(signal_v2_decision),
                agrees_with_signal_v2=None,
                would_block_signal_v2_trade=False,
                would_take_trade_when_v2_waited=False,
                reason_codes=["ENGINE_ERROR"],
                warnings=[f"Decision Engine v2 error: {exc}"],
                reasoning=f"Decision Engine v2 failed safely: {exc}",
                evidence={"error": str(exc)},
                evaluated_at=datetime.utcnow(),
                evaluation_id=evaluation_id,
            )

    def _directional_decision(
        self,
        setup_direction: str,
        setup_confidence: float,
        context_modifier: float,
        votes: dict[str, str],
        momentum_verdict: str,
    ) -> tuple[str, float, list[str], list[str]]:
        reasons = ["SETUP_MATCHED"]
        warnings: list[str] = []
        if setup_direction not in TRADE_DECISIONS:
            return "WAIT", 0.6, ["SETUP_IMPLIES_WAIT"], warnings

        aligned = sum(1 for vote in votes.values() if vote == setup_direction)
        opposite = "PE" if setup_direction == "CE" else "CE"
        conflicts = sum(1 for vote in votes.values() if vote == opposite)
        confidence = setup_confidence + (aligned * 0.06) - (conflicts * 0.10) + context_modifier

        if votes.get("nifty_momentum_engine") == opposite or momentum_verdict in {"REVERSAL_RISK", "MOMENTUM_WEAKENING"}:
            confidence -= 0.12
            warnings.append("Momentum validation disagrees or warns of reversal risk.")
            reasons.append("MOMENTUM_PENALTY")
        if conflicts > 0:
            reasons.append("ENGINE_CONFLICT")
        if aligned >= 3:
            reasons.append("MULTI_ENGINE_ALIGNMENT")
        if confidence < settings.decision_engine_v2_min_confidence:
            return "WAIT", confidence, reasons, warnings
        return setup_direction, confidence, reasons, warnings

    def _insufficient(self, signal_v2_decision: str = None, evaluation_id: str = None) -> DecisionEngineV2Evidence:
        signal_v2 = _normalize_decision(signal_v2_decision)
        return DecisionEngineV2Evidence(
            decision="WAIT",
            advisory_mode=settings.decision_engine_v2_mode,
            confidence=0.0,
            setup_name="INSUFFICIENT_ENGINE_DATA",
            setup_matched=False,
            setup_confidence=0.0,
            context_type="UNKNOWN",
            context_modifier=0.0,
            engine_votes={},
            agreement_score=0.0,
            signal_v2_decision=signal_v2,
            agrees_with_signal_v2=(signal_v2 == "WAIT") if signal_v2 else None,
            would_block_signal_v2_trade=signal_v2 in TRADE_DECISIONS,
            would_take_trade_when_v2_waited=False,
            reason_codes=["INSUFFICIENT_ENGINE_DATA"],
            warnings=["Need recent option chain, market structure, momentum, context, and setup evidence."],
            reasoning="Decision Engine v2 stayed WAIT because recent specialist evidence is incomplete.",
            evidence={},
            evaluated_at=datetime.utcnow(),
            evaluation_id=evaluation_id,
        )


def latest_decision_inputs(db: Session, window_seconds: int | None = None):
    seconds = window_seconds or settings.decision_engine_v2_evidence_window_seconds
    cutoff = datetime.utcnow() - timedelta(seconds=seconds)

    def latest_engine(name: str):
        return (
            db.query(SpecialistEngineLog)
            .filter(SpecialistEngineLog.engine_name == name, SpecialistEngineLog.created_at >= cutoff)
            .order_by(SpecialistEngineLog.created_at.desc())
            .first()
        )

    oc_log = latest_engine("option_chain_engine")
    ms_log = latest_engine("market_structure_engine")
    momentum_log = latest_engine("nifty_momentum_engine")
    ctx_log = (
        db.query(ContextClassificationLog)
        .filter(ContextClassificationLog.created_at >= cutoff)
        .order_by(ContextClassificationLog.created_at.desc())
        .first()
    )
    setup_log = (
        db.query(SetupMatchLog)
        .filter(SetupMatchLog.created_at >= cutoff)
        .order_by(SetupMatchLog.created_at.desc())
        .first()
    )
    if not (oc_log and ms_log and momentum_log and ctx_log and setup_log):
        return None
    return oc_log, ms_log, momentum_log, ctx_log, setup_log


def run_decision_engine_v2_shadow(
    db: Session,
    signal_id: str = None,
    signal_v2_decision: str = None,
) -> Any:
    if not settings.enable_decision_engine_v2:
        return None
    try:
        decision = DecisionEngineV2().safe_decide(
            db=db,
            signal_id=signal_id,
            signal_v2_decision=signal_v2_decision,
            evaluation_id=str(uuid.uuid4()),
        )
        return log_decision_engine_v2(db, decision, signal_id=signal_id, signal_v2_decision=signal_v2_decision)
    except Exception as exc:
        logging.getLogger(__name__).warning("Decision Engine v2 shadow failed (non-fatal): %s", exc)
        return None


def _direction_to_decision(direction: str | None) -> str:
    value = (direction or "").upper()
    if value == "BULLISH":
        return "CE"
    if value == "BEARISH":
        return "PE"
    if value in {"CE", "PE", "WAIT"}:
        return value
    return "NEUTRAL"


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


def _agreement_score(decision: str, votes: dict[str, str]) -> float:
    directional_votes = [vote for vote in votes.values() if vote in {"CE", "PE", "WAIT"}]
    if not directional_votes:
        return 0.0
    return round(sum(1 for vote in directional_votes if vote == decision) / len(directional_votes), 3)


def _engine_summary(row: SpecialistEngineLog) -> dict[str, Any]:
    return {
        "verdict": row.verdict,
        "score": row.score,
        "direction": row.direction,
        "confidence": row.confidence,
        "blocking": row.blocking,
        "evidence": _loads(row.evidence_json, {}),
    }


def _build_reasoning(
    decision: str,
    setup_name: str,
    context_type: str,
    votes: dict[str, str],
    confidence: float,
    reason_codes: list[str],
) -> str:
    vote_text = ", ".join(f"{engine}={vote}" for engine, vote in votes.items()) or "no votes"
    reasons = ", ".join(reason_codes) or "NO_REASON_CODES"
    return (
        f"Decision Engine v2 recommends {decision} in {settings.decision_engine_v2_mode} mode. "
        f"Setup={setup_name}; context={context_type}; confidence={confidence:.0%}. "
        f"Votes: {vote_text}. Reasons: {reasons}."
    )


def _loads(raw: str | None, default):
    if not raw:
        return default
    try:
        return json.loads(raw)
    except Exception:
        return default
