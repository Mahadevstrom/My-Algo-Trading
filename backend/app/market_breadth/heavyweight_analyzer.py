from __future__ import annotations

from typing import Any

from app.market_breadth.sector_universe import NIFTY_HEAVYWEIGHTS


def analyze_heavyweights(quotes_by_symbol: dict[str, dict[str, Any]]) -> dict[str, Any]:
    items = []
    missing = []
    for symbol in NIFTY_HEAVYWEIGHTS:
        quote = quotes_by_symbol.get(symbol)
        if quote is None or quote.get("data_status") != "OK":
            missing.append(symbol)
            continue
        items.append(quote)

    positives = [item for item in items if _float(item.get("change_percent")) > 0.05]
    negatives = [item for item in items if _float(item.get("change_percent")) < -0.05]
    avg_change = round(sum(_float(item.get("change_percent")) for item in items) / len(items), 4) if items else None
    sorted_items = sorted(items, key=lambda item: _float(item.get("change_percent")), reverse=True)
    narrow_warning = bool(items and len(positives) <= 3 and avg_change is not None and avg_change > 0)
    return {
        "tracked_count": len(NIFTY_HEAVYWEIGHTS),
        "available_count": len(items),
        "positive_heavyweight_count": len(positives),
        "negative_heavyweight_count": len(negatives),
        "average_heavyweight_change_percent": avg_change,
        "top_positive_contributors": sorted_items[:5],
        "top_negative_contributors": list(reversed(sorted_items[-5:])),
        "heavyweight_confirmation": _confirmation(len(items), len(positives), len(negatives), avg_change),
        "narrow_leadership_warning": narrow_warning,
        "missing_symbols": missing,
        "weighting_mode": "EQUAL_WEIGHT",
        "data_status": "OK" if items else "NO_DATA",
    }


def _confirmation(available: int, positives: int, negatives: int, avg_change: float | None) -> str:
    if available == 0 or avg_change is None:
        return "NO_DATA"
    if positives >= max(4, int(available * 0.6)) and avg_change > 0:
        return "CONFIRMING_BULLISH"
    if negatives >= max(4, int(available * 0.6)) and avg_change < 0:
        return "CONFIRMING_BEARISH"
    if positives > negatives and avg_change > 0:
        return "WEAK_BULLISH_CONFIRMATION"
    if negatives > positives and avg_change < 0:
        return "WEAK_BEARISH_CONFIRMATION"
    return "MIXED"


def _float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0
