from typing import Any


def detect_trap(
    flow: dict[str, Any],
    sr: dict[str, Any],
    signal_v2: dict[str, Any] | None,
    data_quality_status: str,
    snapshot_changes: dict[str, Any] | None = None,
) -> dict[str, Any]:
    signal_decision = (signal_v2 or {}).get("decision")
    flow_bias = flow.get("option_flow_bias")
    near_resistance = sr.get("near_resistance")
    near_support = sr.get("near_support")
    reasons = []
    trap_type = "NONE"
    risk = "LOW"

    if signal_decision == "BUY_CALL" and near_resistance and flow_bias not in {"BULLISH"}:
        trap_type = "BULL_TRAP"
        risk = "HIGH"
        reasons.append("Signal wants BUY_CALL near call-side resistance without option-flow confirmation.")
    elif signal_decision == "BUY_PUT" and near_support and flow_bias not in {"BEARISH"}:
        trap_type = "BEAR_TRAP"
        risk = "HIGH"
        reasons.append("Signal wants BUY_PUT near put-side support without option-flow confirmation.")
    elif sr.get("range_state") in {"COMPRESSED", "DEFINED_RANGE"} and flow_bias in {"RANGE", "NO_EDGE"}:
        trap_type = "RANGE_TRAP"
        risk = "MEDIUM"
        reasons.append("Spot is inside a defined option OI range with weak directional flow.")

    flow_change_bias = ((snapshot_changes or {}).get("summary") or {}).get("flow_change_bias")
    if flow_change_bias == "RANGE_COMPRESSION" and risk != "HIGH":
        trap_type = "RANGE_TRAP"
        risk = "MEDIUM"
        reasons.append("OI-change snapshots show both CE and PE buildup, raising range-trap risk.")
    if flow_change_bias in {"BULLISH_SUPPORT", "BULLISH_BREAKOUT_SUPPORT"} and trap_type == "BULL_TRAP":
        risk = "MEDIUM"
        reasons.append("Snapshot OI change partially confirms bullish flow, reducing but not removing trap risk.")
    if flow_change_bias in {"BEARISH_RESISTANCE", "BEARISH_BREAKDOWN_SUPPORT"} and trap_type == "BEAR_TRAP":
        risk = "MEDIUM"
        reasons.append("Snapshot OI change partially confirms bearish flow, reducing but not removing trap risk.")

    if data_quality_status in {"WARNING", "STALE", "NO_DATA", "MISMATCH", "BAD_TICK"} and risk != "HIGH":
        risk = "MEDIUM"
        reasons.append(f"Data quality is {data_quality_status}, so trap risk is elevated.")

    return {"trap_risk": risk, "trap_type": trap_type, "trap_reason": reasons or ["No major trap condition detected."]}
