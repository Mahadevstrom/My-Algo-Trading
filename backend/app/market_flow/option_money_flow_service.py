from typing import Any


def analyze_option_money_flow(
    strikes: list[dict[str, Any]],
    summary: dict[str, Any],
    min_liquidity_score: int = 60,
    snapshot_changes: dict[str, Any] | None = None,
) -> dict[str, Any]:
    total_ce_oi = _sum(strikes, "ce_oi")
    total_pe_oi = _sum(strikes, "pe_oi")
    total_ce_volume = _sum(strikes, "ce_volume")
    total_pe_volume = _sum(strikes, "pe_volume")
    ce_liquid = [row for row in strikes if (row.get("ce_liquidity_score") or 0) >= min_liquidity_score]
    pe_liquid = [row for row in strikes if (row.get("pe_liquidity_score") or 0) >= min_liquidity_score]
    ce_oi_change_available = any(row.get("ce_oi_change") is not None for row in strikes)
    pe_oi_change_available = any(row.get("pe_oi_change") is not None for row in strikes)
    snapshot_summary = (snapshot_changes or {}).get("summary") or {}
    snapshot_items = (snapshot_changes or {}).get("items") or []
    oi_change_available = bool((snapshot_changes or {}).get("oi_change_available")) or ce_oi_change_available or pe_oi_change_available

    pcr_oi = summary.get("pcr_oi")
    pcr_volume = summary.get("pcr_volume")
    bias, reasons = _flow_bias(pcr_oi, pcr_volume, total_ce_oi, total_pe_oi, total_ce_volume, total_pe_volume)
    if snapshot_summary.get("flow_change_bias") in {"BULLISH_SUPPORT", "BULLISH_BREAKOUT_SUPPORT"}:
        bias = "BULLISH"
        reasons.append(f"Snapshot OI change supports bullish flow: {snapshot_summary['flow_change_bias']}.")
    elif snapshot_summary.get("flow_change_bias") in {"BEARISH_RESISTANCE", "BEARISH_BREAKDOWN_SUPPORT"}:
        bias = "BEARISH"
        reasons.append(f"Snapshot OI change supports bearish flow: {snapshot_summary['flow_change_bias']}.")
    elif snapshot_summary.get("flow_change_bias") == "RANGE_COMPRESSION":
        bias = "RANGE"
        reasons.append("Snapshot OI change shows both CE and PE buildup around the range.")

    return {
        "oi_change_available": oi_change_available,
        "ce_total_oi": round(total_ce_oi, 2),
        "pe_total_oi": round(total_pe_oi, 2),
        "ce_total_volume": round(total_ce_volume, 2),
        "pe_total_volume": round(total_pe_volume, 2),
        "pcr_oi": pcr_oi,
        "pcr_volume": pcr_volume,
        "pcr_oi_change": snapshot_summary.get("pcr_oi_change") if snapshot_summary else _change_ratio(strikes, "pe_oi_change", "ce_oi_change") if oi_change_available else None,
        "pcr_volume_change": snapshot_summary.get("pcr_volume_change"),
        "ce_oi_change": snapshot_summary.get("ce_oi_change"),
        "pe_oi_change": snapshot_summary.get("pe_oi_change"),
        "ce_volume_change": snapshot_summary.get("ce_volume_change"),
        "pe_volume_change": snapshot_summary.get("pe_volume_change"),
        "ce_oi_buildup_strikes": snapshot_summary.get("top_ce_buildup_strikes") or _top(strikes, "ce_oi"),
        "pe_oi_buildup_strikes": snapshot_summary.get("top_pe_buildup_strikes") or _top(strikes, "pe_oi"),
        "ce_volume_buildup_strikes": _top(strikes, "ce_volume"),
        "pe_volume_buildup_strikes": _top(strikes, "pe_volume"),
        "call_writing_pressure": "HIGH" if pcr_oi is not None and pcr_oi <= 0.8 else "MODERATE" if pcr_oi is not None and pcr_oi < 1 else "LOW",
        "put_writing_support": "HIGH" if pcr_oi is not None and pcr_oi >= 1.2 else "MODERATE" if pcr_oi is not None and pcr_oi > 1 else "LOW",
        "call_unwinding": _unwinding_from_changes(snapshot_summary, "CE") if snapshot_summary else "UNKNOWN" if not oi_change_available else _unwinding(strikes, "ce_oi_change"),
        "put_unwinding": _unwinding_from_changes(snapshot_summary, "PE") if snapshot_summary else "UNKNOWN" if not oi_change_available else _unwinding(strikes, "pe_oi_change"),
        "top_ce_unwinding_strikes": snapshot_summary.get("top_ce_unwinding_strikes") or [],
        "top_pe_unwinding_strikes": snapshot_summary.get("top_pe_unwinding_strikes") or [],
        "support_strength_change": snapshot_summary.get("support_strength_change"),
        "resistance_strength_change": snapshot_summary.get("resistance_strength_change"),
        "flow_change_bias": snapshot_summary.get("flow_change_bias", "NO_EDGE" if snapshot_changes else "UNKNOWN"),
        "buildup_summary": snapshot_summary.get("buildup_summary") or {},
        "unwinding_summary": snapshot_summary.get("unwinding_summary") or {},
        "snapshot_change_items_count": len(snapshot_items),
        "liquid_ce_count": len(ce_liquid),
        "liquid_pe_count": len(pe_liquid),
        "liquid_participation": "BOTH_SIDES" if ce_liquid and pe_liquid else "CE_ONLY" if ce_liquid else "PE_ONLY" if pe_liquid else "LOW",
        "option_flow_bias": bias,
        "reasons": reasons,
    }


def _sum(rows: list[dict[str, Any]], key: str) -> float:
    return sum(_num(row.get(key)) or 0 for row in rows)


def _num(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _top(rows: list[dict[str, Any]], key: str, limit: int = 5) -> list[dict[str, Any]]:
    ranked = sorted(rows, key=lambda row: _num(row.get(key)) or 0, reverse=True)
    return [
        {"strike": row.get("strike"), "value": row.get(key), "activity": row.get(key.replace("_oi", "_activity").replace("_volume", "_activity"))}
        for row in ranked[:limit]
        if (_num(row.get(key)) or 0) > 0
    ]


def _change_ratio(rows: list[dict[str, Any]], numerator_key: str, denominator_key: str) -> float | None:
    numerator = _sum(rows, numerator_key)
    denominator = _sum(rows, denominator_key)
    if denominator <= 0:
        return None
    return round(numerator / denominator, 2)


def _unwinding(rows: list[dict[str, Any]], key: str) -> str:
    total = _sum(rows, key)
    return "YES" if total < 0 else "NO"


def _unwinding_from_changes(summary: dict[str, Any], option_type: str) -> str:
    key = f"top_{option_type.lower()}_unwinding_strikes"
    return "YES" if summary.get(key) else "NO"


def _flow_bias(pcr_oi: Any, pcr_volume: Any, ce_oi: float, pe_oi: float, ce_volume: float, pe_volume: float) -> tuple[str, list[str]]:
    reasons = []
    pcr_oi_value = _num(pcr_oi)
    pcr_volume_value = _num(pcr_volume)
    if pcr_oi_value is None:
        return "NO_EDGE", ["PCR OI is unavailable, so option-flow bias is limited."]
    if pcr_oi_value >= 1.25 and (pcr_volume_value is None or pcr_volume_value >= 0.9):
        reasons.append("Put OI dominates call OI, suggesting support from put writers.")
        return "BULLISH", reasons
    if pcr_oi_value <= 0.75 and (pcr_volume_value is None or pcr_volume_value <= 1.1):
        reasons.append("Call OI dominates put OI, suggesting resistance from call writers.")
        return "BEARISH", reasons
    if 0.9 <= pcr_oi_value <= 1.1:
        reasons.append("PCR OI is balanced, suggesting a range or no directional edge.")
        return "RANGE", reasons
    reasons.append("Option OI/volume is mixed and does not provide a clean directional edge.")
    return "NO_EDGE", reasons
