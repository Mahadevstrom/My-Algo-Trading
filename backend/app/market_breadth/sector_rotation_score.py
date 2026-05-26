from __future__ import annotations

from statistics import median
from typing import Any


def calculate_sector_stats(sector: str, symbols: list[dict[str, Any]], missing_symbols: list[str]) -> dict[str, Any]:
    available = [item for item in symbols if item.get("data_status") == "OK"]
    configured_symbols = {str(item.get("symbol")) for item in symbols if item.get("symbol")}
    configured_symbols.update(missing_symbols)
    changes = [_float(item.get("change_percent")) for item in available if item.get("change_percent") is not None]
    advancing = len([value for value in changes if value > 0.05])
    declining = len([value for value in changes if value < -0.05])
    unchanged = max(0, len(available) - advancing - declining)
    average_change = round(sum(changes) / len(changes), 4) if changes else None
    median_change = round(float(median(changes)), 4) if changes else None
    ratio = round(advancing / declining, 4) if declining else (float(advancing) if advancing else 0.0)
    score = _sector_score(average_change, advancing, declining, len(available))
    sorted_available = sorted(available, key=lambda item: _float(item.get("change_percent")), reverse=True)
    return {
        "sector": sector,
        "symbols_count": len(configured_symbols),
        "available_symbols_count": len(available),
        "advancing_count": advancing,
        "declining_count": declining,
        "unchanged_count": unchanged,
        "advance_decline_ratio": ratio,
        "average_change_percent": average_change,
        "median_change_percent": median_change,
        "total_volume_if_available": _sum_present(available, "volume"),
        "strongest_symbols": sorted_available[:3],
        "weakest_symbols": list(reversed(sorted_available[-3:])),
        "sector_score": score,
        "sector_bias": _sector_bias(score, len(available)),
        "rotation_label": _rotation_label(score, len(available)),
        "data_status": "OK" if available else "NO_DATA",
        "missing_symbols": missing_symbols,
    }


def market_breadth_from_sectors(sectors: list[dict[str, Any]], min_sectors: int) -> dict[str, Any]:
    available = [item for item in sectors if item.get("available_symbols_count", 0) > 0]
    total_advancing = sum(int(item.get("advancing_count") or 0) for item in available)
    total_declining = sum(int(item.get("declining_count") or 0) for item in available)
    total_unchanged = sum(int(item.get("unchanged_count") or 0) for item in available)
    bullish = [item for item in available if item.get("sector_bias") in {"STRONG_BULLISH", "BULLISH"}]
    bearish = [item for item in available if item.get("sector_bias") in {"STRONG_BEARISH", "BEARISH"}]
    ratio = round(total_advancing / total_declining, 4) if total_declining else (float(total_advancing) if total_advancing else 0.0)
    pct_bullish = round((len(bullish) / len(available)) * 100, 2) if available else 0.0
    pct_bearish = round((len(bearish) / len(available)) * 100, 2) if available else 0.0
    risk_on = min(100.0, pct_bullish * 0.7 + min(30.0, ratio * 10))
    risk_off = min(100.0, pct_bearish * 0.7 + (30.0 if ratio < 0.7 and total_declining else 0.0))
    return {
        "total_advancing": total_advancing,
        "total_declining": total_declining,
        "total_unchanged": total_unchanged,
        "advance_decline_ratio": ratio,
        "bullish_sector_percent": pct_bullish,
        "bearish_sector_percent": pct_bearish,
        "risk_on_score": round(risk_on, 2),
        "risk_off_score": round(risk_off, 2),
        "breadth_bias": _breadth_bias(len(available), len(bullish), len(bearish), min_sectors),
        "available_sectors_count": len(available),
        "data_status": "OK" if len(available) >= min_sectors else ("PARTIAL_DATA" if available else "NO_DATA"),
    }


def _sector_score(avg_change: float | None, advancing: int, declining: int, available_count: int) -> float:
    if not available_count or avg_change is None:
        return 0.0
    change_component = max(0.0, min(50.0, 25.0 + avg_change * 10.0))
    breadth_component = (advancing / available_count) * 40.0
    data_component = min(10.0, available_count * 2.0)
    return round(max(0.0, min(100.0, change_component + breadth_component + data_component)), 2)


def _sector_bias(score: float, available_count: int) -> str:
    if available_count == 0:
        return "NO_DATA"
    if score >= 75:
        return "STRONG_BULLISH"
    if score >= 58:
        return "BULLISH"
    if score >= 42:
        return "MIXED"
    if score >= 25:
        return "BEARISH"
    return "STRONG_BEARISH"


def _rotation_label(score: float, available_count: int) -> str:
    if available_count == 0:
        return "NO_DATA"
    if score >= 75:
        return "LEADERS"
    if score >= 58:
        return "IMPROVING"
    if score >= 42:
        return "NEUTRAL"
    if score >= 25:
        return "WEAKENING"
    return "LAGGARDS"


def _breadth_bias(available: int, bullish: int, bearish: int, min_sectors: int) -> str:
    if available == 0:
        return "NO_DATA"
    if available < min_sectors:
        return "MIXED"
    bullish_pct = bullish / available
    bearish_pct = bearish / available
    if bullish_pct >= 0.65:
        return "BROAD_BULLISH"
    if bullish_pct >= 0.4 and bullish > bearish:
        return "SELECTIVE_BULLISH"
    if bearish_pct >= 0.65:
        return "BROAD_BEARISH"
    if bearish_pct >= 0.4 and bearish > bullish:
        return "SELECTIVE_BEARISH"
    return "MIXED"


def _sum_present(items: list[dict[str, Any]], key: str) -> float | None:
    values = [_float(item.get(key)) for item in items if item.get(key) is not None]
    return round(sum(values), 2) if values else None


def _float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0
