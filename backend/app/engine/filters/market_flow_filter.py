from typing import Any

from app.config import settings


def evaluate_market_flow_gate(direction: str, market_flow: dict[str, Any] | None) -> dict[str, Any]:
    if not settings.enable_signal_v2_market_flow_gate or not settings.signal_v2_use_market_flow:
        return {
            "status": "DISABLED",
            "passed": True,
            "confirms_signal": False,
            "conflict": False,
            "hard_reject": False,
            "adjustment_score": 0,
            "reasons": ["Market-flow gate is disabled by config."],
            "failed_checks": [],
        }

    if not market_flow or not market_flow.get("ok"):
        status = (market_flow or {}).get("status", "NO_DATA")
        failed = [f"MARKET_FLOW_{status}"]
        return {
            "status": status,
            "passed": not settings.signal_v2_require_market_flow,
            "confirms_signal": False,
            "conflict": False,
            "hard_reject": settings.signal_v2_require_market_flow,
            "adjustment_score": -settings.signal_v2_market_flow_conflict_penalty if settings.signal_v2_require_market_flow else 0,
            "reasons": [(market_flow or {}).get("message", "Market-flow data is unavailable.")],
            "failed_checks": failed if settings.signal_v2_require_market_flow else [],
        }

    reasons: list[str] = []
    failed: list[str] = []
    adjustment = 0
    bias = market_flow.get("market_flow_bias", "UNKNOWN")
    score = _float(market_flow.get("flow_score")) or 0
    trap = market_flow.get("trap_detection") or {}
    trap_risk = trap.get("trap_risk", market_flow.get("trap_risk", "UNKNOWN"))
    trap_type = trap.get("trap_type", market_flow.get("trap_type", "UNKNOWN"))
    sr = market_flow.get("support_resistance") or {}
    option_flow = market_flow.get("option_money_flow") or {}
    status = market_flow.get("status", "UNKNOWN")
    oi_available = bool(market_flow.get("oi_change_available"))

    if status != "OK":
        reasons.append(f"Market-flow status is {status}.")
        if not settings.signal_v2_allow_partial_market_flow:
            failed.append(f"MARKET_FLOW_{status}")

    if score < settings.signal_v2_market_flow_min_score:
        reasons.append(f"Market-flow score {score} is below minimum {settings.signal_v2_market_flow_min_score}.")
        if settings.signal_v2_require_market_flow:
            failed.append("MARKET_FLOW_SCORE_LOW")

    if settings.signal_v2_require_oi_change and not oi_available:
        failed.append("OI_CHANGE_REQUIRED")
        reasons.append("OI-change snapshots are required but not available.")
    elif oi_available:
        adjustment += settings.signal_v2_oi_change_bonus
        reasons.append("Snapshot OI-change is available and included in Signal v2 context.")
    else:
        reasons.append("OI-change snapshots are not available; current-OI market flow is used.")

    confirms = _confirms(direction, bias, option_flow)
    conflict = _conflicts(direction, bias, option_flow)
    if confirms:
        adjustment += settings.signal_v2_market_flow_confirm_bonus
        reasons.append(f"Market-flow bias {bias} confirms {direction}.")
    if conflict:
        adjustment -= settings.signal_v2_market_flow_conflict_penalty
        failed.append("MARKET_FLOW_CONFLICT")
        reasons.append(f"Market-flow bias {bias} conflicts with {direction}.")

    hard_reject = False
    if trap_risk == "HIGH":
        adjustment -= settings.signal_v2_market_flow_high_trap_penalty
        reasons.extend(trap.get("trap_reason") or ["High market-flow trap risk detected."])
        if settings.signal_v2_no_trade_on_high_trap:
            hard_reject = True
            failed.append(f"HIGH_TRAP_{trap_type}")

    if direction == "BULLISH" and sr.get("near_resistance"):
        adjustment -= settings.signal_v2_near_resistance_call_penalty
        reasons.append("BUY_CALL candidate is near option-flow resistance.")
        if option_flow.get("call_writing_pressure") == "HIGH" or (sr.get("resistance_strength_change") or 0) > 0:
            failed.append("CALL_NEAR_STRENGTHENING_RESISTANCE")
    if direction == "BEARISH" and sr.get("near_support"):
        adjustment -= settings.signal_v2_near_support_put_penalty
        reasons.append("BUY_PUT candidate is near option-flow support.")
        if option_flow.get("put_writing_support") == "HIGH" or (sr.get("support_strength_change") or 0) > 0:
            failed.append("PUT_NEAR_STRENGTHENING_SUPPORT")

    passed = not hard_reject and not any(
        item in failed
        for item in {
            "MARKET_FLOW_SCORE_LOW",
            "OI_CHANGE_REQUIRED",
            "CALL_NEAR_STRENGTHENING_RESISTANCE",
            "PUT_NEAR_STRENGTHENING_SUPPORT",
        }
    )
    if settings.signal_v2_require_market_flow and (conflict or score < settings.signal_v2_market_flow_min_score):
        passed = False

    return {
        "status": status,
        "passed": passed,
        "confirms_signal": confirms,
        "conflict": conflict,
        "hard_reject": hard_reject,
        "adjustment_score": adjustment,
        "reasons": reasons,
        "failed_checks": failed,
    }


def _confirms(direction: str, bias: str, option_flow: dict[str, Any]) -> bool:
    flow_change = option_flow.get("flow_change_bias")
    if direction == "BULLISH":
        return bias in {"BULLISH", "BULLISH_BREAKOUT_SUPPORT", "BULLISH_BUT_OVEREXTENDED"} or flow_change in {
            "BULLISH_SUPPORT",
            "BULLISH_BREAKOUT_SUPPORT",
        }
    if direction == "BEARISH":
        return bias in {"BEARISH", "BEARISH_BREAKDOWN_SUPPORT", "BEARISH_BUT_OVERSOLD"} or flow_change in {
            "BEARISH_RESISTANCE",
            "BEARISH_BREAKDOWN_SUPPORT",
        }
    return False


def _conflicts(direction: str, bias: str, option_flow: dict[str, Any]) -> bool:
    flow_change = option_flow.get("flow_change_bias")
    if direction == "BULLISH":
        return bias in {"BEARISH", "BEARISH_BREAKDOWN_SUPPORT", "TRAP_POSSIBLE", "NO_EDGE"} or flow_change in {
            "BEARISH_RESISTANCE",
            "BEARISH_BREAKDOWN_SUPPORT",
        }
    if direction == "BEARISH":
        return bias in {"BULLISH", "BULLISH_BREAKOUT_SUPPORT", "TRAP_POSSIBLE", "NO_EDGE"} or flow_change in {
            "BULLISH_SUPPORT",
            "BULLISH_BREAKOUT_SUPPORT",
        }
    return bias in {"TRAP_POSSIBLE"}


def _float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
