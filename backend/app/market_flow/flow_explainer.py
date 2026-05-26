from typing import Any


def explain_market_flow(summary: dict[str, Any]) -> list[str]:
    reasons = []
    bias = summary.get("market_flow_bias")
    support = (summary.get("support_resistance") or {}).get("support_zone")
    resistance = (summary.get("support_resistance") or {}).get("resistance_zone")
    trap = summary.get("trap_detection") or {}
    score = summary.get("flow_score")
    if bias == "BULLISH":
        reasons.append(f"Put-side OI and PCR context support a bullish option-flow read; support is near {support}.")
    elif bias == "BEARISH":
        reasons.append(f"Call-side OI pressure suggests resistance near {resistance} and a bearish option-flow read.")
    elif bias == "RANGE":
        reasons.append(f"Option OI is defining a range between support {support} and resistance {resistance}.")
    elif bias == "TRAP_POSSIBLE":
        reasons.append("Option flow and location suggest a possible trap; avoid chasing without confirmation.")
    elif bias == "NO_DATA":
        reasons.append("Market-flow engine does not have enough option-chain data.")
    else:
        reasons.append("Market-flow edge is weak or mixed.")
    if trap.get("trap_type") not in {None, "NONE"}:
        reasons.extend(trap.get("trap_reason") or [])
    flow = summary.get("option_money_flow") or {}
    if summary.get("oi_change_available"):
        reasons.append(f"Snapshot OI-change is available; flow-change bias is {flow.get('flow_change_bias', 'UNKNOWN')}.")
    else:
        reasons.append("OI-change snapshots are not yet sufficient; current-OI structure is used.")
    reasons.append(f"Market-flow score is {score}; this is analysis only, not trade approval.")
    return reasons


def decision_support(flow_bias: str, signal_v2: dict[str, Any] | None) -> str:
    decision = (signal_v2 or {}).get("decision")
    if decision in {"BUY_CALL", "BUY_PUT"}:
        if decision == "BUY_CALL" and flow_bias == "BULLISH":
            return "SUPPORTS_SIGNAL_V2_BUY_CALL"
        if decision == "BUY_PUT" and flow_bias == "BEARISH":
            return "SUPPORTS_SIGNAL_V2_BUY_PUT"
        return "CONTRADICTS_OR_DOES_NOT_CONFIRM_SIGNAL_V2"
    if flow_bias in {"BULLISH", "BEARISH"}:
        return "FLOW_PRESENT_BUT_SIGNAL_V2_NOT_CONFIRMED"
    return "NO_ACTIONABLE_SUPPORT"
