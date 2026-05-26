from typing import Any


def analyze_support_resistance(
    strikes: list[dict[str, Any]],
    summary: dict[str, Any],
    snapshot_changes: dict[str, Any] | None = None,
) -> dict[str, Any]:
    spot = _num(summary.get("spot_price"))
    atm = _num(summary.get("atm_strike"))
    sorted_rows = sorted([row for row in strikes if _num(row.get("strike")) is not None], key=lambda row: _num(row.get("strike")) or 0)
    if not sorted_rows:
        return _empty()

    support_rows = [row for row in sorted_rows if spot is None or (_num(row.get("strike")) or 0) <= spot]
    resistance_rows = [row for row in sorted_rows if spot is None or (_num(row.get("strike")) or 0) >= spot]
    major_support = _max_by(support_rows or sorted_rows, "pe_oi")
    secondary_support = _second_by(support_rows or sorted_rows, "pe_oi")
    major_resistance = _max_by(resistance_rows or sorted_rows, "ce_oi")
    secondary_resistance = _second_by(resistance_rows or sorted_rows, "ce_oi")
    support = _strike(major_support) or summary.get("support_strike")
    resistance = _strike(major_resistance) or summary.get("resistance_strike")
    near_support = _near(spot, support)
    near_resistance = _near(spot, resistance)
    range_width = round(float(resistance) - float(support), 2) if support is not None and resistance is not None else None
    range_state = "UNKNOWN"
    if support is not None and resistance is not None and spot:
        width_pct = abs(float(resistance) - float(support)) / spot * 100
        range_state = "COMPRESSED" if width_pct <= 1.0 else "DEFINED_RANGE" if width_pct <= 3.0 else "WIDE_RANGE"

    change_summary = (snapshot_changes or {}).get("summary") or {}
    support_change = change_summary.get("support_strength_change")
    resistance_change = change_summary.get("resistance_strength_change")
    return {
        "support_zone": support,
        "secondary_support_zone": _strike(secondary_support),
        "resistance_zone": resistance,
        "secondary_resistance_zone": _strike(secondary_resistance),
        "atm_strike": atm,
        "spot_distance_to_support": _distance(spot, support),
        "spot_distance_to_resistance": _distance(spot, resistance),
        "near_support": near_support,
        "near_resistance": near_resistance,
        "breakout_required_above": resistance,
        "breakdown_required_below": support,
        "range_width": range_width,
        "nearest_high_oi_magnet": _nearest_high_oi(sorted_rows, spot),
        "range_state": range_state,
        "support_strength_change": support_change,
        "resistance_strength_change": resistance_change,
        "support_strength": _strength_label(support_change),
        "resistance_strength": _strength_label(resistance_change),
    }


def _empty() -> dict[str, Any]:
    return {
        "support_zone": None,
        "secondary_support_zone": None,
        "resistance_zone": None,
        "secondary_resistance_zone": None,
        "atm_strike": None,
        "spot_distance_to_support": None,
        "spot_distance_to_resistance": None,
        "near_support": False,
        "near_resistance": False,
        "breakout_required_above": None,
        "breakdown_required_below": None,
        "range_width": None,
        "nearest_high_oi_magnet": None,
        "range_state": "NO_DATA",
        "support_strength_change": None,
        "resistance_strength_change": None,
        "support_strength": "UNKNOWN",
        "resistance_strength": "UNKNOWN",
    }


def _num(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _max_by(rows: list[dict[str, Any]], key: str) -> dict[str, Any] | None:
    rows = [row for row in rows if (_num(row.get(key)) or 0) > 0]
    return max(rows, key=lambda row: _num(row.get(key)) or 0) if rows else None


def _second_by(rows: list[dict[str, Any]], key: str) -> dict[str, Any] | None:
    rows = sorted([row for row in rows if (_num(row.get(key)) or 0) > 0], key=lambda row: _num(row.get(key)) or 0, reverse=True)
    return rows[1] if len(rows) > 1 else None


def _strike(row: dict[str, Any] | None) -> float | None:
    return _num(row.get("strike")) if row else None


def _distance(spot: float | None, strike: float | None) -> float | None:
    return round(float(spot) - float(strike), 2) if spot is not None and strike is not None else None


def _near(spot: float | None, strike: float | None) -> bool:
    if spot is None or strike is None or spot <= 0:
        return False
    return abs(spot - strike) / spot * 100 <= 0.35


def _nearest_high_oi(rows: list[dict[str, Any]], spot: float | None) -> float | None:
    if spot is None:
        return None
    candidates = []
    for row in rows:
        strike = _num(row.get("strike"))
        total_oi = (_num(row.get("ce_oi")) or 0) + (_num(row.get("pe_oi")) or 0)
        if strike is not None and total_oi > 0:
            candidates.append((abs(strike - spot), -total_oi, strike))
    return sorted(candidates)[0][2] if candidates else None


def _strength_label(value: float | None) -> str:
    if value is None:
        return "UNKNOWN"
    if value > 0:
        return "STRENGTHENING"
    if value < 0:
        return "WEAKENING"
    return "UNCHANGED"
