from typing import Any


def score_market_flow(
    option_summary: dict[str, Any],
    flow: dict[str, Any],
    sr: dict[str, Any],
    trap: dict[str, Any],
    data_quality_status: str,
    live_candle_status: str,
    secondary_data_status: str,
) -> dict[str, Any]:
    score = 0.0
    chain_bias = option_summary.get("chain_bias")
    if chain_bias in {"BULLISH", "BEARISH"}:
        score += 25
    elif chain_bias in {"NEUTRAL", "CHOPPY"}:
        score += 10

    pcr_oi = _num(option_summary.get("pcr_oi"))
    pcr_volume = _num(option_summary.get("pcr_volume"))
    if pcr_oi is not None and pcr_volume is not None and (pcr_oi - 1) * (pcr_volume - 1) > 0:
        score += 15
    elif pcr_oi is not None:
        score += 7

    if sr.get("support_zone") is not None and sr.get("resistance_zone") is not None:
        score += 20 if sr.get("range_state") != "COMPRESSED" else 10

    if flow.get("liquid_participation") in {"BOTH_SIDES", "CE_ONLY", "PE_ONLY"}:
        score += 10

    if flow.get("oi_change_available"):
        flow_change = flow.get("flow_change_bias")
        if flow_change in {"BULLISH_SUPPORT", "BEARISH_RESISTANCE", "BULLISH_BREAKOUT_SUPPORT", "BEARISH_BREAKDOWN_SUPPORT"}:
            score += 5
        elif flow_change == "RANGE_COMPRESSION":
            score += 2

    if live_candle_status == "OK":
        score += 10
    elif live_candle_status in {"NO_DATA", "UNKNOWN"}:
        score += 2

    if data_quality_status == "OK":
        score += 10
    elif data_quality_status == "WARNING":
        score += 5

    if secondary_data_status in {"OK", "CONFIGURED_READ_ONLY"}:
        score += 5
    elif secondary_data_status in {"TOKEN_MISSING", "DISABLED"}:
        score += 2

    if trap.get("trap_risk") == "HIGH":
        score -= 20
    elif trap.get("trap_risk") == "MEDIUM":
        score -= 8
    else:
        score += 5

    score = max(0, min(100, round(score, 2)))
    return {"score": score, "strength": _strength(score), "confidence": int(round(score))}


def _num(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _strength(score: float) -> str:
    if score >= 80:
        return "STRONG_FLOW"
    if score >= 60:
        return "MODERATE_FLOW"
    if score >= 40:
        return "WEAK_OR_MIXED_FLOW"
    return "NO_EDGE_OR_BAD_DATA"
