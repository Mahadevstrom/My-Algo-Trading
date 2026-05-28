import json
from datetime import datetime

from sqlalchemy.orm import Session

from app.config import settings
from app.engine.context.context_evidence import ContextEvidence
from app.engine.setup.condition_evaluator import evaluate_condition
from app.engine.setup.models import SetupDefinition, SetupMatchLog
from app.engine.setup.setup_evidence import SetupMatchEvidence
from app.engine.setup.setup_types import SetupName
from app.engine.specialist.base import EngineEvidence


class SetupMatcher:
    def match(
        self,
        db: Session,
        oc_evidence: EngineEvidence,
        ms_evidence: EngineEvidence,
        context_evidence: ContextEvidence,
        momentum_evidence: EngineEvidence | None = None,
        signal_id: str = None,
        signal_v2_decision: str = None,
        evaluation_id: str = None,
    ) -> SetupMatchEvidence:
        oc_dict = {
            "direction": oc_evidence.direction,
            "verdict": oc_evidence.verdict,
            "score": oc_evidence.score,
            "confidence": oc_evidence.confidence,
            "blocking": oc_evidence.blocking,
            **(oc_evidence.evidence or {}),
        }
        ms_dict = {
            "direction": ms_evidence.direction,
            "verdict": ms_evidence.verdict,
            "score": ms_evidence.score,
            "confidence": ms_evidence.confidence,
            "blocking": ms_evidence.blocking,
            **(ms_evidence.evidence or {}),
        }
        ctx_dict = {
            "context_type": context_evidence.context_type,
            "data_quality_status": context_evidence.data_quality_status,
            "is_expiry_day": context_evidence.is_expiry_day,
            "confidence_modifier": context_evidence.confidence_modifier,
            "vix_value": context_evidence.vix_value,
            "opening_gap_pct": context_evidence.opening_gap_pct,
        }

        if oc_evidence.blocking or ms_evidence.blocking:
            return _empty_match(
                setup_name=SetupName.NO_SETUP_FOUND,
                context_evidence=context_evidence,
                evaluation_id=evaluation_id,
                summary="Engine blocking condition active. No setup valid when data is missing.",
            )

        setups = (
            db.query(SetupDefinition)
            .filter(SetupDefinition.is_active == True)  # noqa: E712
            .all()
        )
        if not setups:
            return _empty_match(
                setup_name=SetupName.INSUFFICIENT_ENGINE_DATA,
                context_evidence=context_evidence,
                evaluation_id=evaluation_id,
                summary="No setup definitions in database. Run setup seeder.",
            )

        setups = sorted(setups, key=lambda item: _setup_priority(item, context_evidence.context_type))
        for setup in setups:
            blocked_contexts = _loads(setup.blocked_contexts_json, [])
            if context_evidence.context_type in blocked_contexts:
                continue
            valid_contexts = _loads(setup.valid_contexts_json, [])
            if valid_contexts and context_evidence.context_type not in valid_contexts:
                continue

            required_conditions = _loads(setup.required_conditions_json, [])
            required_results = [
                evaluate_condition(condition, oc_dict, ms_dict, ctx_dict) for condition in required_conditions
            ]
            required_pass_count = sum(1 for item in required_results if item.passed)
            required_total = len(required_results)
            if required_pass_count != required_total:
                continue

            supporting_conditions = _loads(setup.supporting_conditions_json, [])
            supporting_results = [
                evaluate_condition(condition, oc_dict, ms_dict, ctx_dict) for condition in supporting_conditions
            ]
            supporting_pass_count = sum(1 for item in supporting_results if item.passed)
            supporting_total = len(supporting_results)
            if supporting_pass_count < (setup.min_supporting_required or 0):
                continue

            base_confidence = (required_pass_count / max(required_total, 1)) * 0.6
            base_confidence += (supporting_pass_count / max(supporting_total, 1)) * 0.4
            context_modifiers = _loads(setup.context_modifiers_json, {})
            ctx_mod = float(context_modifiers.get(context_evidence.context_type, 0.0) or 0.0)
            momentum_penalty, momentum_warning = _momentum_penalty(momentum_evidence)
            final_confidence = round(max(0.0, min(1.0, base_confidence + ctx_mod + momentum_penalty)), 3)
            if final_confidence < (setup.min_confidence or 0.0):
                continue

            context_effect = "BOOST" if ctx_mod > 0 else "PENALTY" if ctx_mod < 0 else "NEUTRAL"
            hist_count, hist_win_rate, hist_avg_pnl = _historical_performance(db, setup.setup_name)
            summary = (
                f"{setup.display_name} matched. Required: {required_pass_count}/{required_total} pass. "
                f"Supporting: {supporting_pass_count}/{supporting_total} pass. "
                f"Confidence: {final_confidence:.0%}. Context: {context_evidence.context_type} ({context_effect})."
            )
            if hist_count >= settings.setup_matcher_min_historical_trades:
                summary += f" Historical: {hist_win_rate}% win rate over {hist_count} trades."
            else:
                summary += " Historical: insufficient data yet."
            if momentum_warning:
                summary += f" {momentum_warning}"

            return SetupMatchEvidence(
                setup_name=setup.setup_name,
                matched=True,
                match_confidence=final_confidence,
                direction_implied=setup.direction,
                required_results=required_results,
                supporting_results=supporting_results,
                required_pass_count=required_pass_count,
                required_total=required_total,
                supporting_pass_count=supporting_pass_count,
                supporting_total=supporting_total,
                context_type=context_evidence.context_type,
                context_modifier=ctx_mod,
                context_effect=context_effect,
                historical_trade_count=hist_count,
                historical_win_rate_pct=hist_win_rate,
                historical_avg_pnl=hist_avg_pnl,
                match_summary=summary,
                evaluated_at=datetime.utcnow(),
                evaluation_id=evaluation_id,
            )

        return _empty_match(
            setup_name=SetupName.NO_SETUP_FOUND,
            context_evidence=context_evidence,
            evaluation_id=evaluation_id,
            summary="No setup pattern matched current market conditions. WAIT is correct.",
        )

    def safe_match(
        self,
        db: Session,
        oc_evidence: EngineEvidence,
        ms_evidence: EngineEvidence,
        context_evidence: ContextEvidence,
        momentum_evidence: EngineEvidence | None = None,
        signal_id: str = None,
        signal_v2_decision: str = None,
        evaluation_id: str = None,
    ) -> SetupMatchEvidence:
        try:
            return self.match(
                db=db,
                oc_evidence=oc_evidence,
                ms_evidence=ms_evidence,
                context_evidence=context_evidence,
                momentum_evidence=momentum_evidence,
                signal_id=signal_id,
                signal_v2_decision=signal_v2_decision,
                evaluation_id=evaluation_id,
            )
        except Exception as exc:
            return SetupMatchEvidence(
                setup_name=SetupName.INSUFFICIENT_ENGINE_DATA,
                matched=False,
                match_confidence=0.0,
                direction_implied="WAIT",
                required_results=[],
                supporting_results=[],
                required_pass_count=0,
                required_total=0,
                supporting_pass_count=0,
                supporting_total=0,
                context_type=getattr(context_evidence, "context_type", "UNKNOWN"),
                context_modifier=getattr(context_evidence, "confidence_modifier", 0.0) or 0.0,
                context_effect="NEUTRAL",
                historical_trade_count=0,
                historical_win_rate_pct=None,
                historical_avg_pnl=None,
                match_summary=f"Setup matcher error: {exc}",
                evaluated_at=datetime.utcnow(),
                evaluation_id=evaluation_id,
            )


def _empty_match(
    setup_name: str,
    context_evidence: ContextEvidence,
    evaluation_id: str | None,
    summary: str,
) -> SetupMatchEvidence:
    return SetupMatchEvidence(
        setup_name=setup_name,
        matched=False,
        match_confidence=0.0,
        direction_implied="WAIT",
        required_results=[],
        supporting_results=[],
        required_pass_count=0,
        required_total=0,
        supporting_pass_count=0,
        supporting_total=0,
        context_type=getattr(context_evidence, "context_type", "UNKNOWN"),
        context_modifier=getattr(context_evidence, "confidence_modifier", 0.0) or 0.0,
        context_effect="NEUTRAL",
        historical_trade_count=0,
        historical_win_rate_pct=None,
        historical_avg_pnl=None,
        match_summary=summary,
        evaluated_at=datetime.utcnow(),
        evaluation_id=evaluation_id,
    )


def _loads(raw: str | None, default):
    if not raw:
        return default
    try:
        return json.loads(raw)
    except Exception:
        return default


def _setup_priority(setup: SetupDefinition, context_type: str) -> tuple[int, int]:
    valid_contexts = _loads(setup.valid_contexts_json, [])
    if valid_contexts and context_type in valid_contexts:
        return (0, setup.id or 0)
    return (1, setup.id or 0)


def _historical_performance(db: Session, setup_name: str) -> tuple[int, float | None, float | None]:
    trades = (
        db.query(SetupMatchLog)
        .filter(
            SetupMatchLog.setup_name == setup_name,
            SetupMatchLog.matched == True,  # noqa: E712
            SetupMatchLog.market_result != None,  # noqa: E711
        )
        .all()
    )
    count = len(trades)
    if count < settings.setup_matcher_min_historical_trades:
        return count, None, None
    wins = sum(1 for item in trades if item.outcome_correct)
    return count, round(wins / count * 100, 1), None


def _momentum_penalty(momentum_evidence: EngineEvidence | None) -> tuple[float, str | None]:
    if not momentum_evidence:
        return 0.0, None
    if momentum_evidence.verdict in {"REVERSAL_RISK", "MOMENTUM_WEAKENING"}:
        return -0.08, "Momentum validation warns of reversal risk - confidence reduced."
    return 0.0, None
