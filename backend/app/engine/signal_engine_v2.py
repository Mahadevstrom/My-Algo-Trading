from collections import deque
from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.api.routes_option_chain import _build_chain_analysis
from app.audit.audit_logger import AuditLogger
from app.config import settings
from app.engine.dhan_instrument_importer import DhanInstrumentImporter
from app.engine.filters.chop_filter import evaluate_chop
from app.engine.filters.liquidity_filter import evaluate_liquidity
from app.engine.filters.market_flow_filter import evaluate_market_flow_gate
from app.engine.filters.momentum_filter import evaluate_momentum
from app.engine.filters.regime_filter import classify_regime
from app.engine.filters.time_filter import evaluate_time_gate
from app.engine.filters.trend_filter import evaluate_trend
from app.engine.filters.volatility_filter import evaluate_volatility
from app.models.live_candle import LiveCandleRecord
from app.risk.kill_switch import KillSwitch
from app.schemas.live_candle import LiveCandle
from app.schemas.signal_v2 import SelectedOptionCandidate, SignalV2GenerateRequest, SignalV2Result
from app.services.data_quality_service import get_data_quality_service
from app.services.live_market_monitor_service import get_live_market_monitor_service
from app.services.market_flow_service import get_market_flow_service
from app.services.session_gate_service import get_session_gate_service
from app.utils.market_session import india_market_session


class SignalEngineV2:
    """Strict read-only signal generator for NIFTY F&O paper analysis."""

    def __init__(self) -> None:
        self._latest: deque[SignalV2Result] = deque(maxlen=100)
        self._next_id = 1

    async def status(self) -> dict[str, Any]:
        monitor_status = await get_live_market_monitor_service().status()
        latest_signal_at = self._latest[-1].created_at if self._latest else None
        session_gate = get_session_gate_service().decision()
        return {
            "enabled": settings.enable_signal_engine_v2,
            "mode": settings.trading_mode,
            "live_order_status": settings.safety_status["live_order_status"],
            "data_quality_enabled": settings.enable_data_quality_engine,
            "live_monitor_available": bool(monitor_status),
            "indstocks_secondary_enabled": settings.signal_v2_use_indstocks_cross_check
            and settings.indstocks_use_as_secondary_data,
            "latest_signal_at": latest_signal_at,
            "market_flow_gate_enabled": settings.enable_signal_v2_market_flow_gate,
            "market_flow_required": settings.signal_v2_require_market_flow,
            "oi_change_required": settings.signal_v2_require_oi_change,
            "market_flow_min_score": settings.signal_v2_market_flow_min_score,
            "latest_market_flow_at": (
                get_market_flow_service()._last_generated_at.isoformat()
                if getattr(get_market_flow_service(), "_last_generated_at", None)
                else None
            ),
            "session_gate_enabled": settings.enable_signal_v2_session_gate,
            "session_gate_hard_block": settings.signal_v2_session_gate_hard_block,
            "session_gate_analysis_when_blocked": settings.signal_v2_allow_analysis_when_session_blocked,
            "session_gate_allows_new_signal": session_gate.allow_new_signal,
            "session_status": session_gate.session_status,
            "session_block_reason": session_gate.block_reason,
            "version": "v2",
        }

    async def analyze_nifty(self, db: Session) -> SignalV2Result:
        return await self.generate(db, SignalV2GenerateRequest(underlying="NIFTY"))

    async def generate(self, db: Session, request: SignalV2GenerateRequest) -> SignalV2Result:
        session_gate = get_session_gate_service().status()
        if not settings.enable_signal_engine_v2:
            result = _base_result(request, "NO_TRADE", "Signal Engine v2 is disabled by config.")
            self._apply_session_context(result, session_gate)
            return self._store_and_audit(db, result, event_type="SIGNAL_V2_NO_TRADE")

        reasons: list[str] = []
        failed_checks: list[str] = []
        supporting_checks: list[str] = []
        score = 0.0
        risk_gate = self._risk_gate(db)
        if not risk_gate["passed"]:
            result = _base_result(
                request,
                "NO_TRADE",
                "Risk or safety gate rejected Signal v2 analysis.",
                failed_checks=risk_gate["failed_checks"],
                reasons=risk_gate["reasons"],
                risk_gate_status=risk_gate["status"],
            )
            self._apply_session_context(result, session_gate)
            return self._store_and_audit(db, result, event_type="SIGNAL_V2_RISK_REJECTED")
        score += 10
        supporting_checks.append("Risk and paper-only safety gates passed.")

        session_gate_blocks_new_signal = (
            settings.enable_signal_v2_session_gate
            and settings.signal_v2_session_gate_hard_block
            and not session_gate.allow_new_signal
        )
        session_block_check = f"SESSION_GATE_{session_gate.session_status}"
        session_block_message = f"Session gate blocked new signal: {session_gate.block_reason or session_gate.session_status}."
        if settings.enable_signal_v2_session_gate and settings.signal_v2_session_gate_hard_block:
            if session_gate_blocks_new_signal and not settings.signal_v2_allow_analysis_when_session_blocked:
                result = _base_result(
                    request,
                    "NO_TRADE",
                    session_block_message,
                    failed_checks=[session_block_check],
                    reasons=[
                        session_block_message,
                        "Signal v2 session gate is configured as a hard block for new paper signals.",
                    ],
                    risk_gate_status="SESSION_BLOCKED",
                    market_state={"session_gate": session_gate.model_dump(mode="json")},
                )
                self._apply_session_context(result, session_gate)
                return self._store_and_audit(db, result, event_type="SIGNAL_V2_SESSION_GATE_BLOCKED")
            if session_gate_blocks_new_signal:
                failed_checks.append(session_block_check)
                reasons.extend(
                    [
                        session_block_message,
                        "Signal v2 is collecting diagnostics because analysis-when-session-blocked is enabled.",
                    ]
                )
            else:
                supporting_checks.append(f"Session gate allows new signals in {session_gate.session_status}.")

        session = {"session_gate": session_gate.model_dump(mode="json")}
        legacy_session = india_market_session()
        if (
            not settings.enable_signal_v2_session_gate
            and settings.signal_v2_market_session_only
            and not legacy_session["is_market_open"]
        ):
            result = _base_result(
                request,
                "NO_TRADE",
                "Market session is not open.",
                failed_checks=[f"MARKET_SESSION_{legacy_session['session_status']}"],
                reasons=[f"Indian market session is {legacy_session['session_status']}; Signal v2 is configured for market-session-only analysis."],
                risk_gate_status="MARKET_CLOSED",
                market_state={"session": legacy_session},
            )
            self._apply_session_context(result, session_gate)
            result = await self._enrich_result_with_market_flow(db, request, result)
            return self._store_and_audit(db, result, event_type="SIGNAL_V2_NO_TRADE")

        # TIME GATE WIRED
        time_gate = evaluate_time_gate()
        if not time_gate["allowed"] and time_gate["window_name"] != "MARKET_CLOSED":
            failed_checks.append(time_gate["window_name"])
            if time_gate.get("warning"):
                reasons.append(time_gate["warning"])
            if settings.signal_v2_session_gate_hard_block:
                time_gate_result = _base_result(
                    request,
                    "NO_TRADE",
                    time_gate.get("warning") or f"Time gate blocked: {time_gate['window_name']}",
                    failed_checks=[time_gate["window_name"]],
                    reasons=reasons,
                    risk_gate_status="TIME_GATE_BLOCKED",
                    market_state={"time_gate": time_gate},
                )
                self._apply_session_context(time_gate_result, session_gate)
                return self._store_and_audit(
                    db, time_gate_result, event_type="SIGNAL_V2_TIME_GATE_BLOCKED"
                )
        elif time_gate["allowed"]:
            score += time_gate["bonus_score"]
            supporting_checks.append(
                f"Time window {time_gate['window_name']} quality {time_gate['quality']}"
            )

        data_quality = None
        data_quality_passed = True
        if request.use_data_quality and settings.signal_v2_require_data_quality:
            data_quality = await get_data_quality_service().check_symbol(
                db,
                request.underlying,
                rest_cross_check=settings.data_quality_rest_cross_check,
            )
            data_quality_passed = self._data_quality_passed(data_quality)
            if not data_quality_passed:
                dq_failed_checks = [f"DATA_QUALITY_{data_quality.data_status}"]
                dq_reasons = data_quality.errors + data_quality.warnings or ["Data quality is not acceptable for paper analysis."]
                risk_status = "PASSED"
                if session_gate_blocks_new_signal:
                    dq_failed_checks.append(session_block_check)
                    dq_reasons.append(session_block_message)
                    risk_status = "SESSION_BLOCKED"
                result = _base_result(
                    request,
                    "NO_TRADE",
                    "Data quality gate rejected the setup.",
                    failed_checks=dq_failed_checks,
                    reasons=dq_reasons,
                    data_quality_status=data_quality.data_status,
                    data_quality_gate_passed=False,
                    risk_gate_status=risk_status,
                )
                result.score = min(float(data_quality.overall_score) * 0.25, 25)
                result.secondary_data_status = self._secondary_data_status()
                self._apply_session_context(result, session_gate)
                result = await self._enrich_result_with_market_flow(db, request, result)
                return self._store_and_audit(db, result, event_type="SIGNAL_V2_DATA_QUALITY_REJECTED")
            data_score = min(float(data_quality.overall_score) * 0.25, 25)
            score += data_score
            supporting_checks.append(f"Data quality gate passed with score {data_quality.overall_score}.")
        else:
            score += 12
            supporting_checks.append("Data quality gate is not required by this request/config.")

        candles = await self._live_candles(db, request.underlying)
        candle_diagnostics = self._candle_diagnostics(candles)
        if request.use_live_candles and settings.signal_v2_use_live_candles:
            candle_failure = self._candle_failure(candle_diagnostics)
            if candle_failure:
                candle_failed_checks = ["LIVE_CANDLES_INSUFFICIENT"]
                candle_reasons = [candle_failure]
                risk_status = "PASSED"
                if session_gate_blocks_new_signal:
                    candle_failed_checks.append(session_block_check)
                    candle_reasons.append(session_block_message)
                    risk_status = "SESSION_BLOCKED"
                result = _base_result(
                    request,
                    "NO_TRADE",
                    candle_failure,
                    failed_checks=candle_failed_checks,
                    reasons=candle_reasons,
                    data_quality_status=data_quality.data_status if data_quality else "UNKNOWN",
                    data_quality_gate_passed=data_quality_passed,
                    risk_gate_status=risk_status,
                )
                result.secondary_data_status = self._secondary_data_status()
                self._apply_candle_context(result, candle_diagnostics)
                result.selected_option_reason = "Direction and option selection were skipped because candle warmup is incomplete."
                self._apply_session_context(result, session_gate)
                result = await self._enrich_result_with_market_flow(db, request, result)
                return self._store_and_audit(db, result, event_type="SIGNAL_V2_NO_TRADE")
        trend = evaluate_trend(
            candles["5m"],
            candles["15m"],
            vwap_candles=candles.get("5m", []),
        )
        momentum = evaluate_momentum(
            candles["1m"],
            candles["3m"],
            trend["direction"],
        )
        volatility = evaluate_volatility(candles["5m"])
        chop = evaluate_chop(candles["5m"])
        regime = classify_regime(
            _float(chop.get("adx")),
            _float(volatility.get("bb_width")),
            _float(volatility.get("avg_range_percent")),
        )
        required_score = float(regime.get("recommended_min_score") or self._required_score())

        score += trend["score"] + momentum["score"] + volatility["score"]
        chop_penalty = float(chop.get("score_penalty") or 0.0)
        if chop_penalty:
            score += chop_penalty
        reasons.extend([trend["message"], momentum["message"], volatility["message"], chop["message"]])
        if chop_penalty:
            reasons.append(f"ADX weak-trend penalty applied: {chop_penalty}.")
        if chop.get("choppy") and chop.get("status") != "WEAK_TREND":
            failed_checks.append("CHOP_FILTER")
        elif chop.get("status") == "WEAK_TREND":
            supporting_checks.append("ADX is weak; score was reduced without hard-rejecting the setup.")
        if regime.get("bonus_context"):
            supporting_checks.append(str(regime["bonus_context"]))
        if regime.get("warning"):
            reasons.append(str(regime["warning"]))

        chain_result = await self._option_chain(db, request)
        candidate = None
        selected_option_reason = "Direction was not confirmed, so option selection was skipped."
        option_chain_status = chain_result["status"]
        chain_bias = chain_result.get("chain_bias", "UNKNOWN")
        chain_summary = chain_result.get("summary") or {}
        support = _float(chain_summary.get("support_strike"))
        resistance = _float(chain_summary.get("resistance_strike"))
        spot = _float(chain_summary.get("spot_price"))
        direction = self._resolve_direction(trend["direction"], chain_bias)
        trade_location = self._trade_location_filter(direction, spot, support, resistance)
        market_structure = self._market_structure_filter(candles["5m"], direction)
        retest_entry = self._retest_entry_filter(candles["5m"], direction, trend, support, resistance)
        score += trade_location["score_adjustment"]
        reasons.extend(trade_location["reasons"])
        failed_checks.extend(trade_location["failed_checks"])
        supporting_checks.extend(trade_location["supporting_checks"])
        for diagnostic in (market_structure, retest_entry):
            score += diagnostic["score_adjustment"]
            reasons.extend(diagnostic["reasons"])
            failed_checks.extend(diagnostic["failed_checks"])
            supporting_checks.extend(diagnostic["supporting_checks"])
        if request.use_option_chain and settings.signal_v2_use_option_chain:
            if not chain_result["ok"]:
                failed_checks.append(f"OPTION_CHAIN_{chain_result['status']}")
                reasons.append(chain_result["message"])
            else:
                option_score = self._option_chain_score(direction, chain_result["summary"])
                score += option_score
                supporting_checks.append(f"Option-chain context is {chain_bias}.")
                if direction in {"BULLISH", "BEARISH"}:
                    candidate, selected_option_reason = self._select_option_candidate(db, request, direction, chain_result)
                    liquidity = evaluate_liquidity(candidate.model_dump() if candidate else None)
                    score += liquidity["score"]
                    reasons.append(liquidity["message"])
                    if liquidity["score"] <= 0:
                        failed_checks.append(f"LIQUIDITY_{liquidity['status']}")
        else:
            option_chain_status = "SKIPPED"
            reasons.append("Option-chain context is not required by request/config.")

        entry_candle = self._entry_candle_quality(candles["5m"], direction)
        option_confirmation = self._option_ltp_confirmation(candidate, direction, trend, momentum)
        option_quality = self._selected_option_quality(db, candidate, direction)
        target_plan = self._dynamic_target_plan(db, candidate, direction, support, resistance)
        chase_filter = self._chase_filter(candles["5m"], direction, trend, volatility)
        for diagnostic in (entry_candle, option_confirmation, option_quality, chase_filter):
            score += diagnostic["score_adjustment"]
            reasons.extend(diagnostic["reasons"])
            failed_checks.extend(diagnostic["failed_checks"])
            supporting_checks.extend(diagnostic["supporting_checks"])

        market_flow = await self._market_flow(db, request)
        market_flow_gate = evaluate_market_flow_gate(direction, market_flow)
        score += market_flow_gate["adjustment_score"]
        reasons.extend(market_flow_gate["reasons"])
        failed_checks.extend(market_flow_gate["failed_checks"])
        if market_flow_gate["confirms_signal"]:
            supporting_checks.append("Market-flow/OI-change context confirms the candidate direction.")
        if market_flow_gate["hard_reject"]:
            failed_checks.append("MARKET_FLOW_HARD_REJECT")
        if settings.enable_signal_v2_market_flow_gate and settings.signal_v2_use_market_flow:
            self._audit_market_flow_gate(db, market_flow_gate, market_flow)
        trap_filter = self._false_breakout_trap_filter(
            candles["5m"],
            direction,
            chain_bias,
            support,
            resistance,
            option_quality["context"],
            market_flow,
        )
        score += trap_filter["score_adjustment"]
        reasons.extend(trap_filter["reasons"])
        failed_checks.extend(trap_filter["failed_checks"])
        supporting_checks.extend(trap_filter["supporting_checks"])

        decision = self._decision(direction, score, failed_checks, required_score)
        if market_flow_gate["hard_reject"]:
            decision = "NO_TRADE"
            reasons.append("Signal v2 rejected the setup because market-flow trap/conflict risk is too high.")
        if session_gate_blocks_new_signal:
            decision = "NO_TRADE"
            reasons.append("Signal v2 forced NO_TRADE because the session gate blocks new paper entries.")
        if decision == "NO_TRADE":
            reasons.append("Signal v2 rejected the setup because score or filters were not strong enough.")
        elif candidate is None:
            decision = "NO_TRADE"
            failed_checks.append("NO_OPTION_CANDIDATE")
            reasons.append("No valid NIFTY option candidate was found.")

        atr = self._calculate_atr(candles["5m"])
        if atr is not None:
            atr = round(atr, 2)
        reference_method = "ATR" if atr is not None else "SWING_3_CANDLE"
        invalidation_reference = self._invalidation_reference(candles["5m"], direction)
        target_reference = self._target_reference(candles["5m"], direction)

        market_state = {"session": session, "chain_bias": chain_bias, "direction": direction, "time_gate": time_gate}
        market_state["support_strike"] = support
        market_state["resistance_strike"] = resistance
        market_state["vwap"] = trend.get("vwap")
        market_state["vwap_above"] = trend.get("vwap_above")
        market_state["rsi"] = momentum.get("rsi")
        market_state["rsi_confirms"] = momentum.get("rsi_confirms")
        market_state["adx"] = chop.get("adx")
        market_state["bb_width"] = volatility.get("bb_width")
        market_state["avg_range_percent"] = volatility.get("avg_range_percent")
        market_state["regime"] = regime
        market_state["recommended_min_score"] = required_score
        market_state["ema_cross"] = trend.get("ema_cross")
        market_state["trade_location"] = trade_location["context"]
        market_state["market_structure"] = market_structure["context"]
        market_state["retest_entry"] = retest_entry["context"]
        market_state["entry_candle"] = entry_candle["context"]
        market_state["option_confirmation"] = option_confirmation["context"]
        market_state["option_quality"] = option_quality["context"]
        market_state["target_plan"] = target_plan["context"]
        market_state["false_breakout_trap"] = trap_filter["context"]
        market_state["chase_filter"] = chase_filter["context"]

        result = SignalV2Result(
            id=None,
            symbol=request.underlying,
            underlying=request.underlying,
            decision=decision,
            signal_type=decision,
            confidence=_confidence(score),
            score=round(score, 2),
            required_score=required_score,
            threshold_source=f"REGIME_FILTER_{regime.get('regime', 'NEUTRAL')}",
            market_state=market_state,
            data_quality_gate_passed=data_quality_passed,
            data_quality_status=data_quality.data_status if data_quality else "UNKNOWN",
            secondary_data_status=self._secondary_data_status(),
            trend_status=trend["status"],
            momentum_status=momentum["status"],
            volatility_status=volatility["status"],
            liquidity_status="ACCEPTABLE" if candidate and not any(item.startswith("LIQUIDITY_") for item in failed_checks) else "UNKNOWN",
            option_chain_status=option_chain_status,
            risk_gate_status="SESSION_BLOCKED" if session_gate_blocks_new_signal else "PASSED",
            market_flow_gate_passed=bool(market_flow_gate["passed"]),
            market_flow_status=(market_flow or {}).get("status", market_flow_gate["status"]),
            market_flow_bias=(market_flow or {}).get("market_flow_bias", "UNKNOWN"),
            market_flow_score=_float((market_flow or {}).get("flow_score")),
            market_flow_strength=(market_flow or {}).get("flow_strength", "UNKNOWN"),
            market_flow_confirms_signal=bool(market_flow_gate["confirms_signal"]),
            market_flow_conflict=bool(market_flow_gate["conflict"]),
            trap_risk=((market_flow or {}).get("trap_detection") or {}).get("trap_risk", "UNKNOWN"),
            trap_type=((market_flow or {}).get("trap_detection") or {}).get("trap_type", "UNKNOWN"),
            trap_reason=((market_flow or {}).get("trap_detection") or {}).get("trap_reason", []),
            oi_change_available=bool((market_flow or {}).get("oi_change_available")),
            flow_change_bias=(market_flow or {}).get("flow_change_bias"),
            support_zone=((market_flow or {}).get("support_resistance") or {}).get("support_zone"),
            resistance_zone=((market_flow or {}).get("support_resistance") or {}).get("resistance_zone"),
            near_support=bool(((market_flow or {}).get("support_resistance") or {}).get("near_support")),
            near_resistance=bool(((market_flow or {}).get("support_resistance") or {}).get("near_resistance")),
            support_strength_change=(market_flow or {}).get("support_strength_change"),
            resistance_strength_change=(market_flow or {}).get("resistance_strength_change"),
            market_flow_adjustment=round(float(market_flow_gate["adjustment_score"]), 2),
            market_flow_reasons=_dedupe(market_flow_gate["reasons"]),
            market_flow_failed_checks=_dedupe(market_flow_gate["failed_checks"]),
            snapshot_count=int((market_flow or {}).get("snapshot_count") or 0),
            latest_snapshot_at=(market_flow or {}).get("latest_snapshot_at"),
            previous_snapshot_at=(market_flow or {}).get("previous_snapshot_at"),
            selected_option=candidate if decision != "NO_TRADE" else candidate,
            selected_option_present=bool(candidate),
            selected_option_reason=selected_option_reason,
            reasons=_dedupe(reasons),
            failed_checks=_dedupe(failed_checks),
            supporting_checks=_dedupe(supporting_checks),
            atr=atr,
            invalidation_level=invalidation_reference,
            suggested_stop_reference=invalidation_reference,
            suggested_target_reference=target_reference,
            invalidation_reference_method=reference_method,
            target_reference_method=reference_method,
        )
        self._apply_candle_context(result, candle_diagnostics)
        self._apply_session_context(result, session_gate)

        # Construct Trade Birth Certificate (Phase 3.1)
        spread_pct_val = None
        if candidate and candidate.ltp and candidate.spread is not None:
            try:
                spread_pct_val = round((candidate.spread / candidate.ltp) * 100, 4)
            except Exception:
                pass

        filter_states = {
            "trend_filter": {
                "passed": bool(trend.get("direction") in {"BULLISH", "BEARISH"}) if "trend" in locals() and trend else False,
                "score": _float(trend.get("score", 0.0)) if "trend" in locals() and trend else 0.0,
                "detail": trend.get("message", "") if "trend" in locals() and trend else ""
            },
            "momentum_filter": {
                "passed": bool(momentum.get("direction") in {"BULLISH", "BEARISH"}) if "momentum" in locals() and momentum else False,
                "score": _float(momentum.get("score", 0.0)) if "momentum" in locals() and momentum else 0.0,
                "detail": momentum.get("message", "") if "momentum" in locals() and momentum else ""
            },
            "chop_filter": {
                "passed": not chop.get("choppy", False) if "chop" in locals() and chop else False,
                "score": _float(chop.get("adx", 0.0)) if "chop" in locals() and chop else 0.0,
                "detail": chop.get("message", "") if "chop" in locals() and chop else ""
            },
            "volatility_filter": {
                "passed": volatility.get("status") != "HIGH_VOLATILITY" if "volatility" in locals() and volatility else False,
                "score": _float(volatility.get("score", 0.0)) if "volatility" in locals() and volatility else 0.0,
                "detail": volatility.get("message", "") if "volatility" in locals() and volatility else ""
            },
            "time_filter": {
                "passed": time_gate.get("allowed", False) if "time_gate" in locals() and time_gate else False,
                "score": _float(time_gate.get("bonus_score", 0.0)) if "time_gate" in locals() and time_gate else 0.0,
                "detail": time_gate.get("window_name", "") if "time_gate" in locals() and time_gate else ""
            },
            "market_flow_filter": {
                "passed": bool(market_flow_gate.get("passed", False)) if "market_flow_gate" in locals() and market_flow_gate else False,
                "score": _float(market_flow_gate.get("adjustment_score", 0.0)) if "market_flow_gate" in locals() and market_flow_gate else 0.0,
                "detail": ", ".join(market_flow_gate.get("reasons", [])) if "market_flow_gate" in locals() and market_flow_gate else ""
            },
            "liquidity_filter": {
                "passed": bool(liquidity.get("score", 0) > 0) if "liquidity" in locals() and liquidity else False,
                "score": _float(liquidity.get("score", 0)) if "liquidity" in locals() and liquidity else 0.0,
                "detail": liquidity.get("message", "") if "liquidity" in locals() and liquidity else "skipped"
            },
            "option_chain_filter": {
                "passed": bool(chain_result.get("ok", False)) if "chain_result" in locals() and chain_result else False,
                "score": _float(option_score) if "option_score" in locals() else 0.0,
                "detail": chain_result.get("message", "") if "chain_result" in locals() and chain_result else "skipped"
            }
        }
        passed_count = sum(1 for f in filter_states.values() if f["passed"])

        result.birth_certificate = {
            "signal_id": str(self._next_id),
            "filter_states": filter_states,
            "confidence_score": round(float(score), 2),
            "regime": (regime.get("regime") or "UNKNOWN") if "regime" in locals() and regime else "UNKNOWN",
            "session_window": session_gate.session_status or "UNKNOWN",
            "oi_direction": chain_bias or "UNKNOWN",
            "market_flow_score": _float((market_flow or {}).get("flow_score")) if "market_flow" in locals() and market_flow else None,
            "pcr": _float(chain_result.get("summary", {}).get("pcr_oi")) if "chain_result" in locals() and chain_result and isinstance(chain_result, dict) else None,
            "spread_pct": spread_pct_val,
            "filters_passed_count": passed_count
        }

        event = "SIGNAL_V2_NO_TRADE" if result.decision == "NO_TRADE" else "SIGNAL_V2_GENERATED"
        if result.selected_option and result.decision != "NO_TRADE":
            AuditLogger().log(
                db,
                "SIGNAL_V2_OPTION_SELECTED",
                "Signal v2 selected a paper-analysis option candidate.",
                source="SIGNAL_V2",
                payload=result.selected_option.model_dump(mode="json"),
            )
        return self._store_and_audit(db, result, event_type=event)

    def latest(self, limit: int = 20) -> dict[str, Any]:
        items = list(self._latest)[-max(1, min(limit, 100)) :]
        return {"ok": True, "count": len(items), "items": [item.model_dump(mode="json") for item in reversed(items)]}

    def explain(self, signal_id: int) -> dict[str, Any]:
        for item in self._latest:
            if item.id == signal_id:
                return {
                    "ok": True,
                    "signal": item.model_dump(mode="json"),
                    "explanation": {
                        "decision": item.decision,
                        "why": item.reasons,
                        "failed_checks": item.failed_checks,
                        "supporting_checks": item.supporting_checks,
                    },
                }
        return {"ok": False, "status": "NOT_FOUND", "message": "Signal v2 result is not available in memory."}

    async def compare_v1(self, db: Session, request: SignalV2GenerateRequest) -> dict[str, Any]:
        v2 = await self.generate(db, request)
        return {
            "ok": True,
            "v1": {
                "status": "NOT_RUN",
                "message": "Signal v1 comparison is intentionally side-effect free here; use /api/signals/analyze for v1.",
            },
            "v2": v2.model_dump(mode="json"),
            "comparison": "Signal v2 is stricter and uses live candles plus data quality gates before accepting a setup.",
        }

    def _store_and_audit(self, db: Session, result: SignalV2Result, event_type: str) -> SignalV2Result:
        self._attach_threshold_context(result)
        self._attach_missed_trade_diagnostics(result)
        result.id = self._next_id
        self._next_id += 1
        self._latest.append(result)
        if result.decision == "NO_TRADE":
            AuditLogger().log(
                db,
                "SIGNAL_V2_MISSED_TRADE_DIAGNOSTIC",
                "Signal v2 produced NO_TRADE with diagnostic context.",
                source="SIGNAL_V2",
                payload=result.missed_trade_diagnostics or {},
            )
        AuditLogger().log(
            db,
            event_type,
            f"Signal Engine v2 decision: {result.decision}.",
            source="SIGNAL_V2",
            payload=result.model_dump(mode="json"),
        )
        return result

    def _apply_session_context(self, result: SignalV2Result, session_gate) -> SignalV2Result:
        result.session_gate_enabled = settings.enable_signal_v2_session_gate
        result.session_status = session_gate.session_status
        result.session_allows_new_signal = session_gate.allow_new_signal
        result.session_allows_paper_entry = session_gate.allow_paper_entry
        result.session_block_reason = session_gate.block_reason
        result.session_caution_reason = session_gate.caution_reason
        result.session_next_change = session_gate.next_session_change
        result.session_is_market_open = session_gate.is_market_open
        state = dict(result.market_state or {})
        state["session_gate"] = session_gate.model_dump(mode="json")
        result.market_state = state
        return result

    def _risk_gate(self, db: Session) -> dict[str, Any]:
        reasons = []
        failed = []
        if not settings.is_paper_mode:
            failed.append("TRADING_MODE_NOT_PAPER")
            reasons.append("Trading mode is not PAPER.")
        if settings.allow_live_orders or settings.enable_dhan_order_placement:
            failed.append("LIVE_ORDER_FLAGS_ENABLED")
            reasons.append("Live order flags are enabled; Signal v2 refuses to run.")
        if settings.signal_v2_no_trade_on_kill_switch and KillSwitch().get_state(db).kill_switch_enabled:
            failed.append("KILL_SWITCH_ENABLED")
            reasons.append("Kill switch is enabled.")
        return {"passed": not failed, "failed_checks": failed, "reasons": reasons, "status": "PASSED" if not failed else "REJECTED"}

    def _data_quality_passed(self, summary) -> bool:
        if summary is None:
            return False
        if summary.data_status == "OK" and summary.is_tradeable_for_paper_analysis:
            return True
        if settings.signal_v2_allow_warning_data_quality and summary.data_status == "WARNING":
            return True
        return False

    async def _live_candles(self, db: Session, underlying: str) -> dict[str, list[Any]]:
        store = get_live_market_monitor_service().store
        candles = {
            "1m": await store.get_candles(underlying, "1m", 20),
            "3m": await store.get_candles(underlying, "3m", 20),
            "5m": await store.get_candles(underlying, "5m", 20),
            "15m": await store.get_candles(underlying, "15m", 20),
        }
        required = self._required_candles()
        today = datetime.now(timezone.utc).date()
        for timeframe, minimum in required.items():
            if len(candles.get(timeframe, [])) < minimum:
                candles[timeframe] = self._merge_persisted_candles(db, underlying, timeframe, candles.get(timeframe, []), today)
        return candles

    def _required_candles(self) -> dict[str, int]:
        return {
            "1m": max(1, settings.signal_v2_min_1m_candles),
            "3m": max(1, settings.signal_v2_min_3m_candles),
            "5m": max(1, settings.signal_v2_min_5m_candles),
            "15m": max(1, settings.signal_v2_min_15m_candles),
        }

    def _candle_diagnostics(self, candles: dict[str, list[Any]]) -> dict[str, Any]:
        required = self._required_candles()
        counts = {timeframe: len(candles.get(timeframe, [])) for timeframe in required}
        missing = [timeframe for timeframe, minimum in required.items() if counts.get(timeframe, 0) < minimum]
        return {
            "counts": counts,
            "required": required,
            "missing": missing,
            "status": "READY" if not missing else "WARMING_UP",
            "source": "LIVE_OR_TODAY_DB_WARMUP",
        }

    def _candle_failure(self, diagnostics: dict[str, Any]) -> str | None:
        missing = diagnostics["missing"]
        if missing:
            details = [
                f"{timeframe} candles available {diagnostics['counts'].get(timeframe, 0)} / required {diagnostics['required'].get(timeframe)}"
                for timeframe in missing
            ]
            return "Not enough live candles for Signal v2 analysis. Missing/short timeframes: " + ", ".join(missing) + ". " + " ".join(details)
        return None

    def _merge_persisted_candles(
        self,
        db: Session,
        underlying: str,
        timeframe: str,
        live_items: list[Any],
        trading_date: date,
    ) -> list[Any]:
        live_by_start = {getattr(item, "start_time", None): item for item in live_items}
        rows = list(
            db.scalars(
                select(LiveCandleRecord)
                .where(
                    LiveCandleRecord.timeframe == timeframe,
                    or_(
                        LiveCandleRecord.symbol == underlying.upper(),
                        LiveCandleRecord.underlying == underlying.upper(),
                    ),
                )
                .order_by(LiveCandleRecord.start_time.desc())
                .limit(40)
            )
        )
        for row in rows:
            row_date = row.start_time.astimezone(timezone.utc).date() if row.start_time.tzinfo else row.start_time.date()
            if row_date != trading_date:
                continue
            if row.start_time in live_by_start:
                continue
            live_by_start[row.start_time] = LiveCandle(
                source=row.source,
                exchange_segment=row.exchange_segment,
                security_id=row.security_id,
                symbol=row.symbol,
                underlying=row.underlying,
                option_type=row.option_type,
                strike=row.strike,
                expiry=row.expiry,
                timeframe=row.timeframe,
                start_time=row.start_time,
                end_time=row.end_time,
                open=row.open,
                high=row.high,
                low=row.low,
                close=row.close,
                volume=row.volume,
                open_interest=row.open_interest,
                tick_count=row.tick_count,
                is_closed=row.is_closed,
                last_tick_at=row.updated_at,
                created_at=row.created_at,
                updated_at=row.updated_at,
            )
        return sorted(live_by_start.values(), key=lambda item: getattr(item, "start_time", datetime.min.replace(tzinfo=timezone.utc)))[-20:]

    async def _option_chain(self, db: Session, request: SignalV2GenerateRequest) -> dict[str, Any]:
        expiry = self._resolve_expiry(db, request.underlying, request.expiry)
        if expiry is None:
            return {"ok": False, "status": "NO_VALID_EXPIRY", "message": "No valid expiry found for option-chain analysis."}
        chain = await _build_chain_analysis(db, request.underlying, expiry)
        if not chain.get("ok"):
            return {"ok": False, "status": chain.get("status", "OPTION_CHAIN_ERROR"), "message": chain.get("message", "Option chain unavailable.")}
        summary = chain["summary"]
        return {
            "ok": True,
            "status": "OK",
            "message": "Option-chain context is available.",
            "expiry": expiry,
            "summary": summary,
            "strikes": chain["strikes"],
            "chain_bias": summary.get("chain_bias", "UNKNOWN"),
        }

    async def _market_flow(self, db: Session, request: SignalV2GenerateRequest) -> dict[str, Any] | None:
        if not settings.enable_signal_v2_market_flow_gate or not settings.signal_v2_use_market_flow:
            return None
        try:
            expiry = None
            if request.expiry:
                try:
                    expiry = date.fromisoformat(request.expiry)
                except ValueError:
                    expiry = None
            return await get_market_flow_service().summary(db, request.underlying, expiry)
        except Exception as exc:
            return {
                "ok": False,
                "status": "MARKET_FLOW_ERROR",
                "message": f"Market-flow gate could not run: {type(exc).__name__}.",
            }

    async def _enrich_result_with_market_flow(
        self,
        db: Session,
        request: SignalV2GenerateRequest,
        result: SignalV2Result,
    ) -> SignalV2Result:
        market_flow = await self._market_flow(db, request)
        if not market_flow:
            return result
        result.market_flow_status = market_flow.get("status", "UNKNOWN")
        result.market_flow_bias = market_flow.get("market_flow_bias", "UNKNOWN")
        result.market_flow_score = _float(market_flow.get("flow_score"))
        result.market_flow_strength = market_flow.get("flow_strength", "UNKNOWN")
        result.trap_risk = (market_flow.get("trap_detection") or {}).get("trap_risk", "UNKNOWN")
        result.trap_type = (market_flow.get("trap_detection") or {}).get("trap_type", "UNKNOWN")
        result.trap_reason = (market_flow.get("trap_detection") or {}).get("trap_reason", [])
        result.oi_change_available = bool(market_flow.get("oi_change_available"))
        result.flow_change_bias = market_flow.get("flow_change_bias")
        result.support_zone = (market_flow.get("support_resistance") or {}).get("support_zone")
        result.resistance_zone = (market_flow.get("support_resistance") or {}).get("resistance_zone")
        result.near_support = bool((market_flow.get("support_resistance") or {}).get("near_support"))
        result.near_resistance = bool((market_flow.get("support_resistance") or {}).get("near_resistance"))
        result.support_strength_change = market_flow.get("support_strength_change")
        result.resistance_strength_change = market_flow.get("resistance_strength_change")
        result.snapshot_count = int(market_flow.get("snapshot_count") or 0)
        result.latest_snapshot_at = market_flow.get("latest_snapshot_at")
        result.previous_snapshot_at = market_flow.get("previous_snapshot_at")
        result.market_flow_reasons = market_flow.get("explanation", [])
        result.supporting_checks.append("Market-flow context was attached to the NO_TRADE response without changing execution behavior.")
        return result

    def _resolve_expiry(self, db: Session, underlying: str, requested: str | None) -> date | None:
        if requested:
            try:
                return date.fromisoformat(requested)
            except ValueError:
                return None
        today = datetime.now(timezone.utc).date()
        expiries = DhanInstrumentImporter().expiries(db, underlying)
        future = [item for item in expiries if item >= today]
        return future[0] if future else expiries[0] if expiries else None

    def _resolve_direction(self, trend_direction: str, chain_bias: str) -> str:
        if chain_bias == "CHOPPY":
            return "SIDEWAYS"
        if trend_direction == "BULLISH" and chain_bias in {"BULLISH", "NEUTRAL"}:
            return "BULLISH"
        if trend_direction == "BEARISH" and chain_bias in {"BEARISH", "NEUTRAL"}:
            return "BEARISH"
        if trend_direction in {"BULLISH", "BEARISH"} and chain_bias == "UNKNOWN":
            return trend_direction
        return "SIDEWAYS"

    def _option_chain_score(self, direction: str, summary: dict[str, Any]) -> int:
        bias = summary.get("chain_bias")
        if direction == "BULLISH" and bias == "BULLISH":
            return 20
        if direction == "BEARISH" and bias == "BEARISH":
            return 20
        if direction in {"BULLISH", "BEARISH"} and bias == "NEUTRAL":
            return 10
        return 2

    def _select_option_candidate(
        self,
        db: Session,
        request: SignalV2GenerateRequest,
        direction: str,
        chain_result: dict[str, Any],
    ) -> tuple[SelectedOptionCandidate | None, str]:
        option_type = "CE" if direction == "BULLISH" else "PE"
        atm = chain_result["summary"].get("atm_strike")
        strikes = chain_result.get("strikes") or []
        if not strikes:
            return None, "No option-chain strike rows were available."
        if not atm:
            return None, "ATM strike was unavailable, so near-ATM option selection could not run."
        rows = [
            row for row in strikes
            if row.get(f"{option_type.lower()}_ltp")
            and (row.get(f"{option_type.lower()}_liquidity_score") or 0) >= 60
        ]
        if not rows:
            return None, f"No valid liquid {option_type} candidate found near ATM; missing LTP or liquidity score below 60."
        rows.sort(key=lambda row: (abs(float(row["strike"]) - float(atm or row["strike"])), -float(row.get(f"{option_type.lower()}_liquidity_score") or 0)))
        row = rows[0]
        instrument = self._find_option_instrument(db, request.underlying, chain_result["expiry"], float(row["strike"]), option_type)
        candidate = SelectedOptionCandidate(
            underlying=request.underlying,
            option_type=option_type,
            expiry=str(chain_result["expiry"]),
            strike=float(row["strike"]),
            trading_symbol=instrument.trading_symbol if instrument else None,
            security_id=instrument.security_id if instrument else None,
            exchange_segment=instrument.segment if instrument else None,
            ltp=_float(row.get(f"{option_type.lower()}_ltp")),
            liquidity_score=_float(row.get(f"{option_type.lower()}_liquidity_score")),
            spread=_float(row.get(f"{option_type.lower()}_spread")),
            reason_selected=f"Nearest liquid {option_type} around ATM strike {atm}.",
        )
        if instrument is None:
            return candidate, f"Selected {option_type} strike {row['strike']} from chain, but instrument mapping was unavailable."
        return candidate, candidate.reason_selected

    def _find_option_instrument(self, db: Session, underlying: str, expiry: date, strike: float, option_type: str):
        options = DhanInstrumentImporter().options(db, underlying, expiry)
        for item in options:
            if item.option_type == option_type and item.strike is not None and abs(float(item.strike) - strike) < 0.01:
                return item
        return None

    def _market_structure_filter(self, candles: list[Any], direction: str) -> dict[str, Any]:
        context = {
            "status": "UNAVAILABLE",
            "swing_highs": [],
            "swing_lows": [],
            "fallback_used": False,
            "latest_close": None,
        }
        result = _diagnostic_result(context=context)
        if direction not in {"BULLISH", "BEARISH"}:
            return result
        if len(candles) < 7:
            result["score_adjustment"] -= 6
            result["failed_checks"].append("MARKET_STRUCTURE_INSUFFICIENT_DATA")
            result["reasons"].append("Not enough 5m candles to confirm higher-high/higher-low or lower-high/lower-low structure.")
            context["status"] = "INSUFFICIENT_DATA"
            return result

        latest_close = _candle_float(candles[-1], "close")
        context["latest_close"] = latest_close
        swing_highs: list[dict[str, Any]] = []
        swing_lows: list[dict[str, Any]] = []
        recent = candles[-14:]
        for index in range(1, len(recent) - 1):
            previous_high = _candle_float(recent[index - 1], "high")
            current_high = _candle_float(recent[index], "high")
            next_high = _candle_float(recent[index + 1], "high")
            previous_low = _candle_float(recent[index - 1], "low")
            current_low = _candle_float(recent[index], "low")
            next_low = _candle_float(recent[index + 1], "low")
            candle_time = getattr(recent[index], "start_time", None)
            if None not in {previous_high, current_high, next_high} and current_high > previous_high and current_high >= next_high:
                swing_highs.append({"value": current_high, "time": candle_time.isoformat() if candle_time else None})
            if None not in {previous_low, current_low, next_low} and current_low < previous_low and current_low <= next_low:
                swing_lows.append({"value": current_low, "time": candle_time.isoformat() if candle_time else None})

        context["swing_highs"] = swing_highs[-3:]
        context["swing_lows"] = swing_lows[-3:]
        if len(swing_highs) >= 2 and len(swing_lows) >= 2:
            high_1, high_2 = swing_highs[-2]["value"], swing_highs[-1]["value"]
            low_1, low_2 = swing_lows[-2]["value"], swing_lows[-1]["value"]
            bullish_structure = high_2 > high_1 and low_2 > low_1 and (latest_close is None or latest_close >= low_2)
            bearish_structure = high_2 < high_1 and low_2 < low_1 and (latest_close is None or latest_close <= high_2)
            context.update({"last_high_change": round(high_2 - high_1, 2), "last_low_change": round(low_2 - low_1, 2)})
            if direction == "BULLISH" and bullish_structure:
                result["score_adjustment"] += 8
                context["status"] = "BULLISH_STRUCTURE"
                result["supporting_checks"].append("Market structure confirms CE: higher high and higher low.")
                return result
            if direction == "BEARISH" and bearish_structure:
                result["score_adjustment"] += 8
                context["status"] = "BEARISH_STRUCTURE"
                result["supporting_checks"].append("Market structure confirms PE: lower high and lower low.")
                return result

            result["score_adjustment"] -= 10
            failed = "MARKET_STRUCTURE_NOT_BULLISH" if direction == "BULLISH" else "MARKET_STRUCTURE_NOT_BEARISH"
            result["failed_checks"].append(failed)
            result["reasons"].append("Market structure does not confirm the selected CE/PE direction.")
            context["status"] = "STRUCTURE_CONFLICT"
            return result

        return self._market_structure_fallback(candles, direction, result, context)

    def _market_structure_fallback(
        self,
        candles: list[Any],
        direction: str,
        result: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        context["fallback_used"] = True
        previous = candles[-7:-3]
        latest = candles[-3:]
        previous_highs = [_candle_float(candle, "high") for candle in previous]
        latest_highs = [_candle_float(candle, "high") for candle in latest]
        previous_lows = [_candle_float(candle, "low") for candle in previous]
        latest_lows = [_candle_float(candle, "low") for candle in latest]
        if any(value is None for value in previous_highs + latest_highs + previous_lows + latest_lows):
            result["score_adjustment"] -= 6
            result["failed_checks"].append("MARKET_STRUCTURE_INVALID_DATA")
            result["reasons"].append("Market structure fallback has invalid OHLC values.")
            context["status"] = "INVALID_DATA"
            return result
        higher_range = max(latest_highs) > max(previous_highs) and min(latest_lows) > min(previous_lows)
        lower_range = max(latest_highs) < max(previous_highs) and min(latest_lows) < min(previous_lows)
        context.update(
            {
                "previous_range": {"high": max(previous_highs), "low": min(previous_lows)},
                "latest_range": {"high": max(latest_highs), "low": min(latest_lows)},
            }
        )
        if direction == "BULLISH" and higher_range:
            result["score_adjustment"] += 4
            context["status"] = "BULLISH_FALLBACK_STRUCTURE"
            result["supporting_checks"].append("Recent 5m range structure leans bullish.")
        elif direction == "BEARISH" and lower_range:
            result["score_adjustment"] += 4
            context["status"] = "BEARISH_FALLBACK_STRUCTURE"
            result["supporting_checks"].append("Recent 5m range structure leans bearish.")
        else:
            result["score_adjustment"] -= 8
            failed = "MARKET_STRUCTURE_NOT_BULLISH" if direction == "BULLISH" else "MARKET_STRUCTURE_NOT_BEARISH"
            result["failed_checks"].append(failed)
            result["reasons"].append("Recent 5m range structure does not confirm the selected direction.")
            context["status"] = "STRUCTURE_CONFLICT"
        return result

    def _retest_entry_filter(
        self,
        candles: list[Any],
        direction: str,
        trend: dict[str, Any],
        support: float | None,
        resistance: float | None,
    ) -> dict[str, Any]:
        context = {
            "status": "UNAVAILABLE",
            "levels": [],
            "matched_level": None,
            "tolerance": None,
            "latest_close": None,
            "latest_body_pct": None,
        }
        result = _diagnostic_result(context=context)
        if direction not in {"BULLISH", "BEARISH"}:
            return result
        if len(candles) < 6:
            result["score_adjustment"] -= 8
            result["failed_checks"].append("RETEST_INSUFFICIENT_DATA")
            result["reasons"].append("Not enough 5m candles to verify retest entry.")
            context["status"] = "INSUFFICIENT_DATA"
            return result

        latest = candles[-1]
        latest_open = _candle_float(latest, "open")
        latest_high = _candle_float(latest, "high")
        latest_low = _candle_float(latest, "low")
        latest_close = _candle_float(latest, "close")
        if None in {latest_open, latest_high, latest_low, latest_close} or latest_close <= 0 or latest_high <= latest_low:
            result["score_adjustment"] -= 8
            result["failed_checks"].append("RETEST_INVALID_DATA")
            result["reasons"].append("Latest 5m candle cannot be used for retest confirmation.")
            context["status"] = "INVALID_DATA"
            return result

        avg_range = _average_candle_range(candles[-6:])
        tolerance = max(latest_close * 0.0015, (avg_range or 0) * 0.35)
        context["tolerance"] = round(tolerance, 4)
        context["latest_close"] = latest_close
        latest_body_pct = abs(latest_close - latest_open) / (latest_high - latest_low) * 100
        context["latest_body_pct"] = round(latest_body_pct, 2)
        ema9 = _ema_from_candles(candles, 9)
        vwap = _float(trend.get("vwap"))
        levels = []
        if vwap is not None and vwap > 0:
            levels.append({"name": "VWAP", "value": vwap})
        if ema9 is not None and ema9 > 0:
            levels.append({"name": "EMA9", "value": ema9})
        if direction == "BULLISH" and support is not None and support > 0:
            levels.append({"name": "SUPPORT", "value": support})
        if direction == "BEARISH" and resistance is not None and resistance > 0:
            levels.append({"name": "RESISTANCE", "value": resistance})
        context["levels"] = [{"name": item["name"], "value": round(item["value"], 2)} for item in levels]
        if not levels:
            result["score_adjustment"] -= 8
            result["failed_checks"].append("RETEST_NO_REFERENCE_LEVEL")
            result["reasons"].append("No VWAP/EMA/support-resistance reference level is available for retest entry.")
            context["status"] = "NO_REFERENCE_LEVEL"
            return result

        recent = candles[-4:]
        for level in levels:
            value = level["value"]
            for candle in recent:
                open_price = _candle_float(candle, "open")
                high = _candle_float(candle, "high")
                low = _candle_float(candle, "low")
                close = _candle_float(candle, "close")
                if None in {open_price, high, low, close}:
                    continue
                if direction == "BULLISH":
                    touched = low <= value + tolerance
                    reclaimed = close > value and latest_close > value and latest_close >= latest_open
                    if touched and reclaimed:
                        result["score_adjustment"] += 8
                        context["status"] = "RETEST_CONFIRMED"
                        context["matched_level"] = {"name": level["name"], "value": round(value, 2)}
                        result["supporting_checks"].append(f"CE entry waited for retest/reclaim of {level['name']}.")
                        return result
                else:
                    touched = high >= value - tolerance
                    rejected = close < value and latest_close < value and latest_close <= latest_open
                    if touched and rejected:
                        result["score_adjustment"] += 8
                        context["status"] = "RETEST_CONFIRMED"
                        context["matched_level"] = {"name": level["name"], "value": round(value, 2)}
                        result["supporting_checks"].append(f"PE entry waited for retest/rejection of {level['name']}.")
                        return result

        nearest_distance_pct = min(abs(latest_close - level["value"]) / latest_close * 100 for level in levels)
        context["nearest_level_distance_pct"] = round(nearest_distance_pct, 4)
        impulse_without_retest = latest_body_pct >= 55 and nearest_distance_pct > 0.35
        result["score_adjustment"] -= 10 if impulse_without_retest else 7
        result["failed_checks"].append("RETEST_ENTRY_NOT_CONFIRMED")
        if impulse_without_retest:
            result["reasons"].append("Entry is still in impulse/chase mode; wait for VWAP/EMA/support-resistance retest.")
            context["status"] = "IMPULSE_NO_RETEST"
        else:
            result["reasons"].append("No confirmed VWAP/EMA/support-resistance retest before entry.")
            context["status"] = "RETEST_MISSING"
        return result

    def _trade_location_filter(
        self,
        direction: str,
        spot: float | None,
        support: float | None,
        resistance: float | None,
    ) -> dict[str, Any]:
        context = {
            "status": "UNAVAILABLE",
            "spot": spot,
            "support": support,
            "resistance": resistance,
            "distance_to_support_pct": None,
            "distance_to_resistance_pct": None,
        }
        result = _diagnostic_result(context=context)
        if direction not in {"BULLISH", "BEARISH"} or spot is None or spot <= 0:
            return result

        support_distance = ((spot - support) / spot * 100) if support is not None else None
        resistance_distance = ((resistance - spot) / spot * 100) if resistance is not None else None
        context.update(
            {
                "status": "CHECKED",
                "distance_to_support_pct": round(support_distance, 4) if support_distance is not None else None,
                "distance_to_resistance_pct": round(resistance_distance, 4) if resistance_distance is not None else None,
            }
        )

        if direction == "BULLISH":
            if resistance_distance is not None and 0 <= resistance_distance < 0.5:
                result["score_adjustment"] -= 10
                result["failed_checks"].append("NEAR_RESISTANCE")
                result["reasons"].append(f"NIFTY is within 0.5% of resistance {resistance} - CE risk elevated")
                context["status"] = "CE_NEAR_RESISTANCE"
            if support_distance is not None and support_distance < 0:
                result["score_adjustment"] -= 8
                result["failed_checks"].append("BELOW_SUPPORT_CE_RISK")
                result["reasons"].append(f"NIFTY is below support {support}; CE location is weak.")
                context["status"] = "CE_BELOW_SUPPORT"
            elif support_distance is not None and 0 <= support_distance <= 0.75:
                result["score_adjustment"] += 5
                result["supporting_checks"].append(f"CE has nearby support cushion at {support}.")
                context["status"] = "CE_SUPPORT_CUSHION"
        elif direction == "BEARISH":
            if support_distance is not None and 0 <= support_distance < 0.5:
                result["score_adjustment"] -= 10
                result["failed_checks"].append("NEAR_SUPPORT")
                result["reasons"].append(f"NIFTY is within 0.5% of support {support} - PE risk elevated")
                context["status"] = "PE_NEAR_SUPPORT"
            if resistance_distance is not None and resistance_distance < 0:
                result["score_adjustment"] -= 8
                result["failed_checks"].append("ABOVE_RESISTANCE_PE_RISK")
                result["reasons"].append(f"NIFTY is above resistance {resistance}; PE location is weak.")
                context["status"] = "PE_ABOVE_RESISTANCE"
            elif resistance_distance is not None and 0 <= resistance_distance <= 0.75:
                result["score_adjustment"] += 5
                result["supporting_checks"].append(f"PE has nearby resistance cushion at {resistance}.")
                context["status"] = "PE_RESISTANCE_CUSHION"
        return result

    def _entry_candle_quality(self, candles: list[Any], direction: str) -> dict[str, Any]:
        context = {"status": "UNAVAILABLE", "body_ratio_pct": None, "close_location_pct": None}
        result = _diagnostic_result(context=context)
        if direction not in {"BULLISH", "BEARISH"} or not candles:
            return result

        candle = candles[-1]
        open_price = _candle_float(candle, "open")
        high = _candle_float(candle, "high")
        low = _candle_float(candle, "low")
        close = _candle_float(candle, "close")
        if None in {open_price, high, low, close} or high <= low:
            context["status"] = "INVALID_DATA"
            result["failed_checks"].append("ENTRY_CANDLE_INVALID")
            result["reasons"].append("Latest entry candle has invalid OHLC values.")
            return result

        candle_range = high - low
        body_ratio = abs(close - open_price) / candle_range * 100
        close_location = (close - low) / candle_range * 100
        context.update(
            {
                "status": "CHECKED",
                "body_ratio_pct": round(body_ratio, 2),
                "close_location_pct": round(close_location, 2),
                "open": open_price,
                "high": high,
                "low": low,
                "close": close,
            }
        )
        bullish_quality = close > open_price and body_ratio >= 45 and close_location >= 70
        bearish_quality = close < open_price and body_ratio >= 45 and close_location <= 30
        if direction == "BULLISH" and bullish_quality:
            result["score_adjustment"] += 6
            result["supporting_checks"].append("Latest 5m candle closes strong for CE entry.")
            context["status"] = "BULLISH_CONFIRMED"
        elif direction == "BEARISH" and bearish_quality:
            result["score_adjustment"] += 6
            result["supporting_checks"].append("Latest 5m candle closes strong for PE entry.")
            context["status"] = "BEARISH_CONFIRMED"
        else:
            result["score_adjustment"] -= 5
            result["failed_checks"].append("ENTRY_CANDLE_NOT_CONFIRMED")
            result["reasons"].append("Latest 5m candle does not confirm entry direction cleanly.")
            context["status"] = "NOT_CONFIRMED"
        return result

    def _option_ltp_confirmation(
        self,
        candidate: SelectedOptionCandidate | None,
        direction: str,
        trend: dict[str, Any],
        momentum: dict[str, Any],
    ) -> dict[str, Any]:
        context = {"status": "UNAVAILABLE", "spread_pct": None, "ltp": None}
        result = _diagnostic_result(context=context)
        if direction not in {"BULLISH", "BEARISH"}:
            return result
        if candidate is None:
            context["status"] = "NO_CANDIDATE"
            return result

        ltp = _float(candidate.ltp)
        spread = _float(candidate.spread)
        context.update({"status": "CHECKED", "ltp": ltp, "spread": spread})
        if ltp is None or ltp <= 0:
            result["score_adjustment"] -= 10
            result["failed_checks"].append("OPTION_LTP_UNAVAILABLE")
            result["reasons"].append("Selected option has no valid LTP confirmation.")
            context["status"] = "LTP_UNAVAILABLE"
            return result

        if spread is not None and ltp > 0:
            spread_pct = spread / ltp * 100
            context["spread_pct"] = round(spread_pct, 2)
            if spread_pct > 8:
                result["score_adjustment"] -= 8
                result["failed_checks"].append("OPTION_SPREAD_WIDE")
                result["reasons"].append(f"Selected option spread is wide at {spread_pct:.2f}% of LTP.")
                context["status"] = "WIDE_SPREAD"
            elif spread_pct <= 3:
                result["score_adjustment"] += 3
                result["supporting_checks"].append("Selected option spread is tight enough for paper entry.")

        ema_status = (trend.get("ema_cross") or {}).get("cross_status")
        vwap_above = trend.get("vwap_above")
        rsi_confirms = bool(momentum.get("rsi_confirms"))
        if direction == "BULLISH":
            if ema_status == "BULLISH_CROSS":
                result["score_adjustment"] += 3
                result["supporting_checks"].append("Option entry confirms CE with bullish EMA cross.")
            if vwap_above is True:
                result["score_adjustment"] += 3
                result["supporting_checks"].append("Option entry confirms CE with spot above VWAP.")
            if ema_status == "BEARISH_CROSS" and vwap_above is False:
                result["score_adjustment"] -= 6
                result["failed_checks"].append("OPTION_CONFIRMATION_CONFLICT")
                result["reasons"].append("CE candidate conflicts with EMA/VWAP confirmation.")
        if direction == "BEARISH":
            if ema_status == "BEARISH_CROSS":
                result["score_adjustment"] += 3
                result["supporting_checks"].append("Option entry confirms PE with bearish EMA cross.")
            if vwap_above is False:
                result["score_adjustment"] += 3
                result["supporting_checks"].append("Option entry confirms PE with spot below VWAP.")
            if ema_status == "BULLISH_CROSS" and vwap_above is True:
                result["score_adjustment"] -= 6
                result["failed_checks"].append("OPTION_CONFIRMATION_CONFLICT")
                result["reasons"].append("PE candidate conflicts with EMA/VWAP confirmation.")
        if rsi_confirms:
            result["score_adjustment"] += 2
            result["supporting_checks"].append("RSI momentum confirms selected option direction.")
        if not result["failed_checks"]:
            context["status"] = "CONFIRMED"
        return result

    def _selected_option_quality(
        self,
        db: Session,
        candidate: SelectedOptionCandidate | None,
        direction: str,
    ) -> dict[str, Any]:
        context = {
            "status": "UNAVAILABLE",
            "symbol": candidate.trading_symbol if candidate else None,
            "security_id": candidate.security_id if candidate else None,
            "option_type": candidate.option_type if candidate else None,
            "timeframe": None,
            "candle_count": 0,
            "candle_source": "NONE",
            "ema9": None,
            "ema21": None,
            "vwap": None,
            "latest_close": None,
            "spread_pct": None,
            "quality_score": None,
            "components": {},
        }
        result = _diagnostic_result(context=context)
        if direction not in {"BULLISH", "BEARISH"}:
            return result
        if candidate is None:
            context["status"] = "NO_CANDIDATE"
            return result

        candle_pack = self._selected_option_candles(db, candidate)
        option_candles = candle_pack["candles"]
        context["timeframe"] = candle_pack["timeframe"]
        context["candle_count"] = len(option_candles)
        context["candle_source"] = candle_pack["source"]

        ltp = _float(candidate.ltp)
        spread = _float(candidate.spread)
        if ltp is not None and ltp > 0 and spread is not None:
            spread_pct = spread / ltp * 100
            context["spread_pct"] = round(spread_pct, 2)
            if spread_pct <= 3:
                result["score_adjustment"] += 4
                context["components"]["spread"] = 4
            elif spread_pct <= 8:
                result["score_adjustment"] -= 3
                context["components"]["spread"] = -3
                result["reasons"].append(f"Selected option spread/slippage is moderate at {spread_pct:.2f}% of LTP.")
            else:
                result["score_adjustment"] -= 8
                context["components"]["spread"] = -8
                result["failed_checks"].append("OPTION_QUALITY_SLIPPAGE_RISK")
                result["reasons"].append(f"Selected option spread/slippage is high at {spread_pct:.2f}% of LTP.")

        if len(option_candles) < 5:
            result["score_adjustment"] -= 12
            result["failed_checks"].append("OPTION_QUALITY_NO_CANDLES")
            result["reasons"].append("Selected option has insufficient positive option candles for CE/PE quality scoring.")
            context["status"] = "NO_OPTION_CANDLES"
            context["quality_score"] = max(0, min(100, 50 + result["score_adjustment"] * 2))
            return result

        latest = option_candles[-1]
        latest_close = _candle_float(latest, "close")
        context["latest_close"] = latest_close
        ema9 = _ema_from_candles(option_candles, 9)
        ema21 = _ema_from_candles(option_candles, 21)
        context["ema9"] = round(ema9, 2) if ema9 is not None else None
        context["ema21"] = round(ema21, 2) if ema21 is not None else None
        if latest_close is not None and latest_close > 0:
            if ema9 is not None and ema21 is not None:
                if ema9 > ema21 and latest_close >= ema9:
                    result["score_adjustment"] += 6
                    context["components"]["option_trend"] = 6
                    result["supporting_checks"].append("Selected option premium trend confirms with EMA 9 above EMA 21.")
                elif ema9 < ema21:
                    result["score_adjustment"] -= 6
                    context["components"]["option_trend"] = -6
                    result["failed_checks"].append("OPTION_QUALITY_TREND_WEAK")
                    result["reasons"].append("Selected option premium trend is weak: EMA 9 is below EMA 21.")
            elif ema9 is not None:
                previous_close = _candle_float(option_candles[-5], "close")
                if previous_close is not None and latest_close > previous_close and latest_close >= ema9:
                    result["score_adjustment"] += 3
                    context["components"]["option_trend"] = 3
                    result["supporting_checks"].append("Selected option premium is rising above short EMA.")
                else:
                    result["score_adjustment"] -= 3
                    context["components"]["option_trend"] = -3
                    result["reasons"].append("Selected option short-term premium trend is not rising cleanly.")

        vwap = _vwap_from_candles(option_candles)
        context["vwap"] = round(vwap, 2) if vwap is not None else None
        if latest_close is not None and vwap is not None:
            if latest_close >= vwap:
                result["score_adjustment"] += 4
                context["components"]["option_vwap"] = 4
                result["supporting_checks"].append("Selected option premium is above its option VWAP.")
            else:
                result["score_adjustment"] -= 4
                context["components"]["option_vwap"] = -4
                result["failed_checks"].append("OPTION_QUALITY_BELOW_VWAP")
                result["reasons"].append("Selected option premium is below option VWAP.")

        candle_score = self._option_candle_strength(option_candles)
        result["score_adjustment"] += candle_score["score_adjustment"]
        context["components"]["option_candle"] = candle_score["score_adjustment"]
        context["candle_strength"] = candle_score["context"]
        result["reasons"].extend(candle_score["reasons"])
        result["failed_checks"].extend(candle_score["failed_checks"])
        result["supporting_checks"].extend(candle_score["supporting_checks"])

        participation = self._option_participation_score(option_candles)
        result["score_adjustment"] += participation["score_adjustment"]
        context["components"]["option_participation"] = participation["score_adjustment"]
        context["participation"] = participation["context"]
        result["reasons"].extend(participation["reasons"])
        result["failed_checks"].extend(participation["failed_checks"])
        result["supporting_checks"].extend(participation["supporting_checks"])

        result["score_adjustment"] = max(-20, min(20, result["score_adjustment"]))
        context["quality_score"] = round(max(0, min(100, 50 + result["score_adjustment"] * 2)), 2)
        if any(check.startswith("OPTION_QUALITY_") for check in result["failed_checks"]):
            context["status"] = "WEAK"
        elif result["score_adjustment"] >= 8:
            context["status"] = "STRONG"
        elif result["score_adjustment"] >= 0:
            context["status"] = "ACCEPTABLE"
        else:
            context["status"] = "CAUTION"
        return result

    def _selected_option_candles(self, db: Session, candidate: SelectedOptionCandidate) -> dict[str, Any]:
        security_id = str(candidate.security_id) if candidate.security_id else None
        symbol = candidate.trading_symbol
        for timeframe, limit in (("5m", 30), ("3m", 30), ("1m", 45)):
            if security_id:
                exact = self._load_option_candles(db, timeframe, limit, security_id=security_id)
                if len(exact) >= 5:
                    return {"candles": exact, "timeframe": timeframe, "source": "EXACT_SECURITY_ID"}
            if symbol:
                fallback = self._load_option_candles(db, timeframe, limit, symbol=symbol)
                if len(fallback) >= 5:
                    return {"candles": fallback, "timeframe": timeframe, "source": "SYMBOL_FALLBACK"}
        if security_id:
            exact_any = self._load_option_candles(db, "1m", 45, security_id=security_id)
            if exact_any:
                return {"candles": exact_any, "timeframe": "1m", "source": "EXACT_SECURITY_ID_SHORT"}
        if symbol:
            fallback_any = self._load_option_candles(db, "1m", 45, symbol=symbol)
            if fallback_any:
                return {"candles": fallback_any, "timeframe": "1m", "source": "SYMBOL_FALLBACK_SHORT"}
        return {"candles": [], "timeframe": None, "source": "NONE"}

    def _load_option_candles(
        self,
        db: Session,
        timeframe: str,
        limit: int,
        security_id: str | None = None,
        symbol: str | None = None,
    ) -> list[LiveCandleRecord]:
        filters = [LiveCandleRecord.timeframe == timeframe, LiveCandleRecord.close > 0]
        if security_id:
            filters.append(LiveCandleRecord.security_id == security_id)
        elif symbol:
            filters.append(LiveCandleRecord.symbol == symbol)
        else:
            return []
        rows = list(
            db.scalars(
                select(LiveCandleRecord)
                .where(*filters)
                .order_by(LiveCandleRecord.start_time.desc())
                .limit(limit)
            )
        )
        return list(reversed(rows))

    def _option_candle_strength(self, candles: list[Any]) -> dict[str, Any]:
        context = {"status": "UNAVAILABLE", "body_ratio_pct": None, "close_location_pct": None}
        result = _diagnostic_result(context=context)
        if not candles:
            return result
        candle = candles[-1]
        open_price = _candle_float(candle, "open")
        high = _candle_float(candle, "high")
        low = _candle_float(candle, "low")
        close = _candle_float(candle, "close")
        if None in {open_price, high, low, close} or high <= low:
            context["status"] = "INVALID_DATA"
            return result
        candle_range = high - low
        body_ratio = abs(close - open_price) / candle_range * 100
        close_location = (close - low) / candle_range * 100
        context.update({"body_ratio_pct": round(body_ratio, 2), "close_location_pct": round(close_location, 2)})
        if close > open_price and body_ratio >= 45 and close_location >= 70:
            result["score_adjustment"] += 5
            context["status"] = "STRONG_BULLISH"
            result["supporting_checks"].append("Selected option latest candle shows strong premium buying.")
        elif close >= open_price and close_location >= 55:
            result["score_adjustment"] += 2
            context["status"] = "MILD_BULLISH"
        else:
            result["score_adjustment"] -= 5
            context["status"] = "WEAK"
            result["failed_checks"].append("OPTION_QUALITY_CANDLE_WEAK")
            result["reasons"].append("Selected option latest candle does not show strong premium buying.")
        return result

    def _option_participation_score(self, candles: list[Any]) -> dict[str, Any]:
        context = {"status": "UNAVAILABLE", "latest_volume": None, "avg_volume": None, "latest_oi": None, "previous_oi": None}
        result = _diagnostic_result(context=context)
        if len(candles) < 3:
            return result
        volumes = [_candle_float(candle, "volume") for candle in candles[-6:-1]]
        volumes = [value for value in volumes if value is not None and value > 0]
        latest_volume = _candle_float(candles[-1], "volume")
        latest_oi = _candle_float(candles[-1], "open_interest")
        previous_oi = _candle_float(candles[-2], "open_interest")
        context.update({"latest_volume": latest_volume, "latest_oi": latest_oi, "previous_oi": previous_oi})
        if volumes and latest_volume is not None and latest_volume > 0:
            avg_volume = sum(volumes) / len(volumes)
            context["avg_volume"] = round(avg_volume, 2)
            if latest_volume >= avg_volume * 1.2:
                result["score_adjustment"] += 3
                result["supporting_checks"].append("Selected option volume is above recent average.")
            elif latest_volume < avg_volume * 0.5:
                result["score_adjustment"] -= 3
                result["failed_checks"].append("OPTION_QUALITY_LOW_VOLUME")
                result["reasons"].append("Selected option latest volume is weak versus recent average.")
        if latest_oi is not None and previous_oi is not None and previous_oi > 0:
            oi_change_pct = (latest_oi - previous_oi) / previous_oi * 100
            context["oi_change_pct"] = round(oi_change_pct, 2)
            if oi_change_pct >= 0:
                result["score_adjustment"] += 2
                result["supporting_checks"].append("Selected option open interest is stable or expanding.")
            elif oi_change_pct < -5:
                result["score_adjustment"] -= 2
                result["reasons"].append("Selected option open interest is contracting.")
        context["status"] = "CHECKED" if result["score_adjustment"] != 0 else "NO_VOLUME_OI_EDGE"
        return result

    def _dynamic_target_plan(
        self,
        db: Session,
        candidate: SelectedOptionCandidate | None,
        direction: str,
        support: float | None,
        resistance: float | None,
    ) -> dict[str, Any]:
        context = {
            "status": "UNAVAILABLE",
            "method": "NONE",
            "entry_price": None,
            "option_target_1": None,
            "option_target_2": None,
            "underlying_target_reference": None,
            "trail_after_target_1": True,
            "early_exit_on_option_momentum_fade": True,
            "swing_highs": [],
        }
        result = _diagnostic_result(context=context)
        if candidate is None or direction not in {"BULLISH", "BEARISH"}:
            context["status"] = "NO_CANDIDATE"
            return result
        entry = _float(candidate.ltp)
        if entry is None or entry <= 0:
            context["status"] = "NO_ENTRY_LTP"
            return result

        context["entry_price"] = entry
        context["underlying_target_reference"] = resistance if direction == "BULLISH" else support
        fallback_t1 = round(entry * (1 + (settings.live_paper_target_percent * 0.50) / 100), 2)
        fallback_t2 = round(entry * (1 + settings.live_paper_target_percent / 100), 2)
        candle_pack = self._selected_option_candles(db, candidate)
        option_candles = candle_pack["candles"]
        context["candle_source"] = candle_pack["source"]
        context["timeframe"] = candle_pack["timeframe"]
        context["candle_count"] = len(option_candles)

        swing_highs = _recent_swing_highs(option_candles)
        useful_highs = sorted({round(value, 2) for value in swing_highs if value > entry * 1.05})
        context["swing_highs"] = useful_highs[-5:]
        target_1 = useful_highs[0] if useful_highs else fallback_t1
        target_2_candidates = [value for value in useful_highs if value > target_1 * 1.03]
        target_2 = target_2_candidates[0] if target_2_candidates else max(fallback_t2, round(target_1 + (target_1 - entry) * 1.25, 2))
        if target_2 <= target_1:
            target_2 = round(target_1 * 1.12, 2)

        context["option_target_1"] = round(target_1, 2)
        context["option_target_2"] = round(target_2, 2)
        if useful_highs:
            context["status"] = "SWING_TARGETS"
            context["method"] = "OPTION_PREMIUM_SWING_HIGH"
            result["supporting_checks"].append("Targets planned from selected option premium swing highs.")
        else:
            context["status"] = "FALLBACK_TARGETS"
            context["method"] = "PERCENT_FALLBACK"
            result["reasons"].append("No usable option swing high above entry; fallback percent targets were planned.")
        return result

    def _false_breakout_trap_filter(
        self,
        candles: list[Any],
        direction: str,
        chain_bias: str,
        support: float | None,
        resistance: float | None,
        option_quality: dict[str, Any],
        market_flow: dict[str, Any] | None,
    ) -> dict[str, Any]:
        context = {
            "status": "CLEAR",
            "patterns": [],
            "chain_bias": chain_bias,
            "support": support,
            "resistance": resistance,
            "option_quality_status": option_quality.get("status"),
            "market_flow_bias": (market_flow or {}).get("market_flow_bias"),
        }
        result = _diagnostic_result(context=context)
        if direction not in {"BULLISH", "BEARISH"} or len(candles) < 4:
            context["status"] = "UNAVAILABLE"
            return result

        latest = candles[-1]
        previous = candles[-2]
        latest_close = _candle_float(latest, "close")
        previous_close = _candle_float(previous, "close")
        latest_high = _candle_float(latest, "high")
        latest_low = _candle_float(latest, "low")
        context.update({"latest_close": latest_close, "previous_close": previous_close})
        if latest_close is None or latest_close <= 0:
            context["status"] = "INVALID_DATA"
            return result

        if direction == "BULLISH" and resistance is not None and latest_close > resistance:
            broke_now = previous_close is None or previous_close <= resistance or (latest_high is not None and latest_high > resistance)
            if broke_now and chain_bias != "BULLISH":
                self._add_trap(
                    result,
                    context,
                    "BREAKOUT_CHAIN_NOT_CONFIRMED",
                    "TRAP_BREAKOUT_CHAIN_NOT_CONFIRMED",
                    "Price broke resistance, but option-chain bias does not confirm CE breakout.",
                    -12,
                )

        if direction == "BEARISH" and support is not None and latest_close <= support * 1.005:
            components = option_quality.get("components") or {}
            option_trend = _float(components.get("option_trend"))
            option_candle = _float(components.get("option_candle"))
            weak_premium = option_quality.get("status") in {"WEAK", "CAUTION", "NO_OPTION_CANDLES"} or (option_trend is not None and option_trend <= 0) or (option_candle is not None and option_candle <= 0)
            if weak_premium:
                self._add_trap(
                    result,
                    context,
                    "PE_PREMIUM_NOT_RISING_AT_SUPPORT",
                    "TRAP_PE_PREMIUM_NOT_RISING",
                    "Price is near support, but selected PE premium is not rising cleanly.",
                    -10,
                )

        move_pct = _recent_move_pct(candles[-4:])
        avg_range = _average_candle_range(candles[-8:]) or 0.0
        avg_range_pct = (avg_range / latest_close * 100) if latest_close else 0.0
        participation = option_quality.get("participation") or {}
        participation_component = _float((option_quality.get("components") or {}).get("option_participation"))
        low_participation = participation.get("status") in {"NO_VOLUME_OI_EDGE", "UNAVAILABLE"} or (participation_component is not None and participation_component <= 0)
        oi_missing = not bool((market_flow or {}).get("oi_change_available"))
        if move_pct is not None and move_pct > max(0.8, avg_range_pct * 3) and (low_participation or oi_missing):
            self._add_trap(
                result,
                context,
                "SUDDEN_MOVE_LOW_PARTICIPATION",
                "TRAP_SUDDEN_MOVE_LOW_PARTICIPATION",
                "Sudden move has weak option volume/OI confirmation; false breakout risk is high.",
                -10,
            )

        market_trap = (market_flow or {}).get("trap_detection") or {}
        if market_trap.get("trap_risk") == "HIGH":
            self._add_trap(
                result,
                context,
                "MARKET_FLOW_HIGH_TRAP",
                "TRAP_MARKET_FLOW_HIGH",
                "Market-flow engine reports high trap risk.",
                -12,
            )

        if result["failed_checks"]:
            context["status"] = "TRAP_RISK"
        else:
            result["supporting_checks"].append("No false-breakout trap pattern detected.")
        return result

    def _add_trap(
        self,
        result: dict[str, Any],
        context: dict[str, Any],
        pattern: str,
        failed_check: str,
        reason: str,
        penalty: float,
    ) -> None:
        result["score_adjustment"] += penalty
        result["failed_checks"].append(failed_check)
        result["reasons"].append(reason)
        context["patterns"].append(pattern)

    def _chase_filter(
        self,
        candles: list[Any],
        direction: str,
        trend: dict[str, Any],
        volatility: dict[str, Any],
    ) -> dict[str, Any]:
        context = {"status": "UNAVAILABLE", "distance_from_vwap_pct": None, "three_candle_move_pct": None}
        result = _diagnostic_result(context=context)
        if direction not in {"BULLISH", "BEARISH"} or len(candles) < 4:
            return result

        latest_close = _candle_float(candles[-1], "close")
        prior_close = _candle_float(candles[-4], "close")
        vwap = _float(trend.get("vwap"))
        if latest_close is None or latest_close <= 0:
            return result
        context["status"] = "CHECKED"

        if vwap is not None and vwap > 0:
            distance_from_vwap = abs(latest_close - vwap) / vwap * 100
            context["distance_from_vwap_pct"] = round(distance_from_vwap, 4)
            if distance_from_vwap > 1.0:
                result["score_adjustment"] -= 8
                result["failed_checks"].append("CHASE_DISTANCE_FROM_VWAP")
                result["reasons"].append(f"Price is {distance_from_vwap:.2f}% away from VWAP; avoid chasing.")

        if prior_close is not None and prior_close > 0:
            three_candle_move = abs(latest_close - prior_close) / prior_close * 100
            avg_range = _float(volatility.get("avg_range_percent")) or 0.0
            chase_threshold = max(0.8, avg_range * 3)
            context["three_candle_move_pct"] = round(three_candle_move, 4)
            context["chase_threshold_pct"] = round(chase_threshold, 4)
            if three_candle_move > chase_threshold:
                result["score_adjustment"] -= 8
                result["failed_checks"].append("CHASE_AFTER_BIG_MOVE")
                result["reasons"].append(f"Recent 5m move is {three_candle_move:.2f}%; wait for pullback instead of chasing.")

        if not result["failed_checks"]:
            result["supporting_checks"].append("No chase condition detected near the current candle.")
            context["status"] = "CLEAN"
        else:
            context["status"] = "CHASE_RISK"
        return result

    def _decision(self, direction: str, score: float, failed_checks: list[str], required_score: float | None = None) -> str:
        critical_prefixes = (
            "LIVE_CANDLES_",
            "DATA_QUALITY_",
            "OPTION_CHAIN_",
            "LIQUIDITY_",
            "CHOP_",
            "OPTION_QUALITY_",
            "MARKET_STRUCTURE_",
            "RETEST_",
            "TRAP_",
        )
        if any(check.startswith(critical_prefixes) for check in failed_checks):
            return "NO_TRADE"
        if "MARKET_FLOW_HARD_REJECT" in failed_checks or "OI_CHANGE_REQUIRED" in failed_checks:
            return "NO_TRADE"
        if settings.signal_v2_require_market_flow and any(check.startswith("MARKET_FLOW_") for check in failed_checks):
            return "NO_TRADE"
        if score < (required_score if required_score is not None else self._required_score()):
            return "NO_TRADE"
        if direction == "BULLISH":
            return "BUY_CALL"
        if direction == "BEARISH":
            return "BUY_PUT"
        return "NO_TRADE"

    def _secondary_data_status(self) -> str:
        if not settings.signal_v2_use_indstocks_cross_check or not settings.indstocks_use_as_secondary_data:
            return "DISABLED"
        if not settings.indstocks_enabled:
            return "DISABLED"
        if not settings.has_indstocks_credentials:
            return "TOKEN_MISSING"
        return "CONFIGURED_READ_ONLY"

    # Original _calculate_atr signature: not present before ATR reference support.
    def _calculate_atr(self, candles: list, period: int = 14) -> float | None:
        if len(candles) < period + 1:
            return None

        true_ranges: list[float] = []
        for index in range(1, len(candles)):
            current = candles[index]
            previous = candles[index - 1]
            high = _float(getattr(current, "high", None))
            low = _float(getattr(current, "low", None))
            previous_close = _float(getattr(previous, "close", None))
            if None in {high, low, previous_close}:
                return None
            true_ranges.append(max(high - low, abs(high - previous_close), abs(low - previous_close)))

        if len(true_ranges) < period:
            return None
        return sum(true_ranges[-period:]) / period

    # Original _invalidation_reference signature: def _invalidation_reference(self, candles: list[Any], direction: str) -> float | None:
    def _invalidation_reference(self, candles: list[Any], direction: str) -> float | None:
        if not candles:
            return None
        last = candles[-1]
        entry_price = _float(getattr(last, "close", None))
        atr = self._calculate_atr(candles)
        if entry_price is not None and atr is not None:
            if direction == "BULLISH":
                return entry_price - (1.5 * atr)
            if direction == "BEARISH":
                return entry_price + (1.5 * atr)

        recent = candles[-3:]
        if direction == "BULLISH":
            values = [_float(getattr(candle, "low", None)) for candle in recent]
            values = [value for value in values if value is not None]
            return min(values) if values else None
        if direction == "BEARISH":
            values = [_float(getattr(candle, "high", None)) for candle in recent]
            values = [value for value in values if value is not None]
            return max(values) if values else None
        return None

    # Original _target_reference signature: def _target_reference(self, candles: list[Any], direction: str) -> float | None:
    def _target_reference(self, candles: list[Any], direction: str) -> float | None:
        if not candles:
            return None
        last = candles[-1]
        entry_price = _float(getattr(last, "close", None))
        atr = self._calculate_atr(candles)
        if entry_price is not None and atr is not None:
            if direction == "BULLISH":
                return entry_price + (2.5 * atr)
            if direction == "BEARISH":
                return entry_price - (2.5 * atr)

        invalidation = self._invalidation_reference(candles, direction)
        if entry_price is None or invalidation is None:
            return None
        risk = abs(entry_price - invalidation)
        if risk <= 0:
            return None
        return entry_price + risk * 1.5 if direction == "BULLISH" else entry_price - risk * 1.5

    def _required_score(self) -> int:
        return settings.signal_v2_paper_min_score if settings.is_paper_mode else settings.signal_v2_min_score

    def _threshold_source(self) -> str:
        return "SIGNAL_V2_PAPER_MIN_SCORE" if settings.is_paper_mode else "SIGNAL_V2_MIN_SCORE"

    def _attach_threshold_context(self, result: SignalV2Result) -> None:
        if result.required_score is None:
            result.required_score = float(self._required_score())
        if result.threshold_source is None:
            result.threshold_source = self._threshold_source()
        result.selected_option_present = bool(result.selected_option)
        if result.selected_option_reason is None:
            result.selected_option_reason = (
                result.selected_option.reason_selected
                if result.selected_option
                else "No option was selected because the setup did not reach a valid trade direction."
            )

    def _apply_candle_context(self, result: SignalV2Result, diagnostics: dict[str, Any]) -> None:
        result.candle_counts_by_timeframe = diagnostics["counts"]
        result.required_candles_by_timeframe = diagnostics["required"]
        result.missing_timeframes = diagnostics["missing"]
        result.candle_warmup_status = diagnostics["status"]
        result.warmup_source = diagnostics["source"]

    def _attach_missed_trade_diagnostics(self, result: SignalV2Result) -> None:
        blocked_by_session = bool(result.session_gate_enabled and result.session_allows_new_signal is False)
        failed = result.failed_checks or []
        result.missed_trade_diagnostics = {
            "final_decision": result.decision,
            "score": result.score,
            "required_score": result.required_score,
            "threshold_source": result.threshold_source,
            "selected_option_present": bool(result.selected_option),
            "selected_option_reason": result.selected_option_reason,
            "failed_checks": failed,
            "blocked_by_session_gate": blocked_by_session,
            "blocked_by_data_quality": any(check.startswith("DATA_QUALITY_") for check in failed),
            "blocked_by_candle_warmup": any(check.startswith("LIVE_CANDLES_") for check in failed),
            "blocked_by_market_flow": any(check.startswith("MARKET_FLOW_") for check in failed),
            "blocked_by_option_chain": any(check.startswith("OPTION_CHAIN_") or check == "NO_OPTION_CANDIDATE" for check in failed),
            "blocked_by_risk": result.risk_gate_status not in {"PASSED", "UNKNOWN"},
            "candle_counts_by_timeframe": result.candle_counts_by_timeframe,
            "required_candles_by_timeframe": result.required_candles_by_timeframe,
            "missing_timeframes": result.missing_timeframes,
            "trend_status": result.trend_status,
            "momentum_status": result.momentum_status,
            "volatility_status": result.volatility_status,
            "liquidity_status": result.liquidity_status,
            "option_chain_status": result.option_chain_status,
            "market_flow_bias": result.market_flow_bias,
            "chain_bias": (result.market_state or {}).get("chain_bias"),
            "suggested_next_fix_or_reason": self._suggest_next_fix(result),
        }

    def _suggest_next_fix(self, result: SignalV2Result) -> str:
        failed = result.failed_checks or []
        if any(check.startswith("LIVE_CANDLES_") for check in failed):
            return "Wait for candle warmup or verify live feed auto-subscription and today's persisted candle warmup."
        if any(check.startswith("DATA_QUALITY_") for check in failed):
            return "Fix live data freshness/mismatch before accepting paper entries."
        if "NO_OPTION_CANDIDATE" in failed or result.selected_option is None:
            return result.selected_option_reason or "Option candidate was not selected."
        required_score = result.required_score or float(self._required_score())
        if result.score < required_score:
            return f"Signal score {result.score} is below required score {required_score}."
        if result.decision == "NO_TRADE":
            return "Signal filters did not confirm a paper-trade setup."
        return "Signal is actionable for paper evaluation if live-paper gates also pass."

    def _audit_market_flow_gate(
        self,
        db: Session,
        gate: dict[str, Any],
        market_flow: dict[str, Any] | None,
    ) -> None:
        if gate.get("hard_reject"):
            event = "SIGNAL_V2_HIGH_TRAP_REJECTED"
        elif gate.get("conflict"):
            event = "SIGNAL_V2_MARKET_FLOW_CONFLICT"
        elif gate.get("confirms_signal"):
            event = "SIGNAL_V2_MARKET_FLOW_CONFIRMED"
        elif not gate.get("passed"):
            event = "SIGNAL_V2_MARKET_FLOW_REJECTED"
        elif (market_flow or {}).get("status") == "PARTIAL_DATA":
            event = "SIGNAL_V2_MARKET_FLOW_PARTIAL"
        else:
            event = None
        if event:
            AuditLogger().log(
                db,
                event,
                "Signal v2 market-flow gate evaluated.",
                source="SIGNAL_V2",
                payload={
                    "market_flow_status": (market_flow or {}).get("status"),
                    "market_flow_bias": (market_flow or {}).get("market_flow_bias"),
                    "flow_score": (market_flow or {}).get("flow_score"),
                    "oi_change_available": (market_flow or {}).get("oi_change_available"),
                    "adjustment_score": gate.get("adjustment_score"),
                    "failed_checks": gate.get("failed_checks", []),
                },
            )
        if (market_flow or {}).get("oi_change_available"):
            AuditLogger().log(
                db,
                "SIGNAL_V2_OI_CHANGE_USED",
                "Signal v2 used option-chain OI-change context.",
                source="SIGNAL_V2",
                payload={
                    "snapshot_count": (market_flow or {}).get("snapshot_count"),
                    "flow_change_bias": (market_flow or {}).get("flow_change_bias"),
                },
            )


def _base_result(
    request: SignalV2GenerateRequest,
    decision: str,
    message: str,
    failed_checks: list[str] | None = None,
    reasons: list[str] | None = None,
    data_quality_status: str = "UNKNOWN",
    data_quality_gate_passed: bool = False,
    risk_gate_status: str = "UNKNOWN",
    market_state: dict[str, Any] | None = None,
) -> SignalV2Result:
    return SignalV2Result(
        symbol=request.underlying,
        underlying=request.underlying,
        decision=decision,
        signal_type=decision,
        confidence="LOW",
        score=0,
        market_state=market_state or {},
        data_quality_gate_passed=data_quality_gate_passed,
        data_quality_status=data_quality_status,
        risk_gate_status=risk_gate_status,
        reasons=_dedupe((reasons or []) + [message]),
        failed_checks=_dedupe(failed_checks or []),
    )


def _confidence(score: float) -> str:
    if score >= 85:
        return "HIGH"
    if score >= 70:
        return "MEDIUM"
    return "LOW"


def _dedupe(items: list[str]) -> list[str]:
    seen = set()
    output = []
    for item in items:
        if item and item not in seen:
            seen.add(item)
            output.append(item)
    return output


def _float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _candle_float(candle: Any, field: str) -> float | None:
    value = getattr(candle, field, None)
    if value is None and isinstance(candle, dict):
        value = candle.get(field)
    return _float(value)


def _diagnostic_result(context: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "score_adjustment": 0.0,
        "reasons": [],
        "failed_checks": [],
        "supporting_checks": [],
        "context": context or {},
    }


def _ema_from_candles(candles: list[Any], period: int) -> float | None:
    if len(candles) < period:
        return None
    closes = [_candle_float(candle, "close") for candle in candles]
    if any(close is None for close in closes):
        return None
    multiplier = 2 / (period + 1)
    ema = sum(closes[:period]) / period
    for close in closes[period:]:
        ema = (close - ema) * multiplier + ema
    return ema


def _vwap_from_candles(candles: list[Any]) -> float | None:
    total_price_volume = 0.0
    total_volume = 0.0
    for candle in candles:
        high = _candle_float(candle, "high")
        low = _candle_float(candle, "low")
        close = _candle_float(candle, "close")
        volume = _candle_float(candle, "volume")
        if None in {high, low, close, volume} or volume <= 0:
            continue
        total_price_volume += ((high + low + close) / 3) * volume
        total_volume += volume
    if total_volume <= 0:
        return None
    return total_price_volume / total_volume


def _average_candle_range(candles: list[Any]) -> float | None:
    ranges: list[float] = []
    for candle in candles:
        high = _candle_float(candle, "high")
        low = _candle_float(candle, "low")
        if high is not None and low is not None and high >= low:
            ranges.append(high - low)
    return sum(ranges) / len(ranges) if ranges else None


def _recent_swing_highs(candles: list[Any]) -> list[float]:
    highs: list[float] = []
    if len(candles) < 3:
        return highs
    for index in range(1, len(candles) - 1):
        previous_high = _candle_float(candles[index - 1], "high")
        current_high = _candle_float(candles[index], "high")
        next_high = _candle_float(candles[index + 1], "high")
        if None not in {previous_high, current_high, next_high} and current_high > previous_high and current_high >= next_high:
            highs.append(current_high)
    recent_high = max((_candle_float(candle, "high") or 0.0) for candle in candles[-8:])
    if recent_high > 0:
        highs.append(recent_high)
    return highs


def _recent_move_pct(candles: list[Any]) -> float | None:
    if len(candles) < 2:
        return None
    first_close = _candle_float(candles[0], "close")
    last_close = _candle_float(candles[-1], "close")
    if first_close is None or first_close <= 0 or last_close is None:
        return None
    return abs(last_close - first_close) / first_close * 100


signal_engine_v2 = SignalEngineV2()


def get_signal_engine_v2() -> SignalEngineV2:
    return signal_engine_v2
