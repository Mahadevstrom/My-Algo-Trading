from typing import Any


# Original evaluate_volatility signature: def evaluate_volatility(candles: list[Any]) -> dict:
def calculate_bb_width(candles, period=20, std_dev=2) -> dict | None:
    if len(candles) < period:
        return None
    closes = [_value(candle, "close") for candle in candles[-period:]]
    if any(close is None for close in closes):
        return None
    sma = sum(closes) / period
    if sma == 0:
        return None
    variance = sum((close - sma) ** 2 for close in closes) / period
    standard_deviation = variance ** 0.5
    upper = sma + (std_dev * standard_deviation)
    lower = sma - (std_dev * standard_deviation)
    bb_width = (upper - lower) / sma * 100
    return {"bb_width": bb_width, "upper": upper, "lower": lower, "sma": sma}


def evaluate_volatility(candles: list[Any]) -> dict:
    bb = calculate_bb_width(candles)
    if len(candles) < 5:
        return {
            "status": "INSUFFICIENT_DATA",
            "score": 0,
            "message": "Not enough candles for volatility analysis.",
            "bb_width": None,
        }
    ranges = []
    for candle in candles[-8:]:
        high = _value(candle, "high")
        low = _value(candle, "low")
        close = _value(candle, "close")
        if None in {high, low, close} or high < low or close <= 0:
            return {
                "status": "INVALID_DATA",
                "score": 0,
                "message": "Volatility candles have invalid OHLC values.",
                "bb_width": bb["bb_width"] if bb else None,
            }
        ranges.append((high - low) / close * 100)
    avg_range = sum(ranges) / len(ranges)
    last_range = ranges[-1]
    if avg_range < 0.05:
        return _with_bb_width(
            {
                "status": "TOO_LOW",
                "score": 1,
                "message": "Recent candle range is too low for a clean intraday setup.",
                "avg_range_percent": round(avg_range, 4),
            },
            bb,
        )
    if last_range > max(avg_range * 3, 1.5):
        return _with_bb_width(
            {
                "status": "SPIKE",
                "score": 1,
                "message": "Latest candle looks like a volatility spike.",
                "avg_range_percent": round(avg_range, 4),
            },
            bb,
        )
    return _with_bb_width(
        {
            "status": "NORMAL",
            "score": 5,
            "message": "Volatility is within acceptable intraday range.",
            "avg_range_percent": round(avg_range, 4),
        },
        bb,
    )


def _with_bb_width(result: dict, bb: dict | None) -> dict:
    if bb is None:
        return {**result, "bb_width": None}

    bb_width = bb["bb_width"]
    enriched = {**result, "bb_width": bb_width}
    if bb_width < 1.0:
        return {
            **enriched,
            "status": f"{result['status']}_BB_SQUEEZE",
            "score": max(0, result["score"] - 3),
            "warning": "Bollinger Band squeeze - low volatility breakout risk",
        }
    if bb_width > 5.0:
        return {
            **enriched,
            "status": f"{result['status']}_BB_EXPANSION",
            "score": result["score"] + 3,
            "message": "Bollinger Bands expanding - volatility confirms move",
        }
    return enriched


def _value(candle: Any, field: str) -> float | None:
    value = getattr(candle, field, None)
    if value is None and isinstance(candle, dict):
        value = candle.get(field)
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
