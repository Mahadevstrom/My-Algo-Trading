from typing import Any


# Original evaluate_chop signature: def evaluate_chop(candles: list[Any]) -> dict:


def calculate_adx(candles: list, period: int = 14) -> dict | None:
    if len(candles) < period * 2:
        return None

    true_ranges: list[float] = []
    plus_dm_values: list[float] = []
    minus_dm_values: list[float] = []

    for index in range(1, len(candles)):
        current = candles[index]
        previous = candles[index - 1]
        high = _value(current, "high")
        low = _value(current, "low")
        previous_high = _value(previous, "high")
        previous_low = _value(previous, "low")
        previous_close = _value(previous, "close")
        if None in {high, low, previous_high, previous_low, previous_close}:
            return None

        up_move = max(high - previous_high, 0.0)
        down_move = max(previous_low - low, 0.0)
        true_ranges.append(max(high - low, abs(high - previous_close), abs(low - previous_close)))
        plus_dm_values.append(up_move if up_move > down_move else 0.0)
        minus_dm_values.append(down_move if down_move > up_move else 0.0)

    smoothed_tr = sum(true_ranges[:period])
    smoothed_plus_dm = sum(plus_dm_values[:period])
    smoothed_minus_dm = sum(minus_dm_values[:period])
    dx_values: list[float] = []
    latest_plus_di = 0.0
    latest_minus_di = 0.0

    for index in range(period - 1, len(true_ranges)):
        if index >= period:
            smoothed_tr = smoothed_tr - (smoothed_tr / period) + true_ranges[index]
            smoothed_plus_dm = smoothed_plus_dm - (smoothed_plus_dm / period) + plus_dm_values[index]
            smoothed_minus_dm = smoothed_minus_dm - (smoothed_minus_dm / period) + minus_dm_values[index]

        if smoothed_tr == 0:
            plus_di = 0.0
            minus_di = 0.0
        else:
            plus_di = 100 * smoothed_plus_dm / smoothed_tr
            minus_di = 100 * smoothed_minus_dm / smoothed_tr

        di_total = plus_di + minus_di
        dx = 0.0 if di_total == 0 else 100 * abs(plus_di - minus_di) / di_total
        dx_values.append(dx)
        latest_plus_di = plus_di
        latest_minus_di = minus_di

    if len(dx_values) < period:
        return None

    adx = sum(dx_values[:period]) / period
    for dx in dx_values[period:]:
        adx = ((adx * (period - 1)) + dx) / period

    return {"adx": adx, "plus_di": latest_plus_di, "minus_di": latest_minus_di}


def evaluate_chop(candles: list[Any]) -> dict:
    adx_result = calculate_adx(candles)
    if adx_result is not None:
        adx = adx_result["adx"]
        adx_label = f"{adx:.2f}"
        if adx < 20:
            return {
                "status": "CHOPPY_ADX",
                "choppy": True,
                "adx": adx,
                "plus_di": adx_result["plus_di"],
                "minus_di": adx_result["minus_di"],
                "message": f"ADX {adx_label} indicates a choppy, low-trend market.",
            }
        if adx < 25:
            return {
                "status": "WEAK_TREND",
                "choppy": True,
                "adx": adx,
                "plus_di": adx_result["plus_di"],
                "minus_di": adx_result["minus_di"],
                "score_penalty": -5,
                "message": f"ADX {adx_label} shows weak trend strength; reduce confidence.",
            }
        return {
            "status": "TRENDING_ADX",
            "choppy": False,
            "adx": adx,
            "plus_di": adx_result["plus_di"],
            "minus_di": adx_result["minus_di"],
            "message": f"ADX {adx_label} confirms trending conditions.",
        }

    if len(candles) < 5:
        return {"status": "INSUFFICIENT_DATA", "choppy": True, "adx": None, "message": "Not enough candles to rule out chop."}
    recent = candles[-6:]
    direction_flips = 0
    previous_direction = None
    overlapping = 0
    for index, candle in enumerate(recent):
        open_price = _value(candle, "open")
        high = _value(candle, "high")
        low = _value(candle, "low")
        close = _value(candle, "close")
        if None in {open_price, high, low, close}:
            return {"status": "INVALID_DATA", "choppy": True, "adx": None, "message": "Chop filter candles have missing OHLC values."}
        direction = "UP" if close > open_price else "DOWN" if close < open_price else "FLAT"
        if previous_direction and direction != "FLAT" and previous_direction != "FLAT" and direction != previous_direction:
            direction_flips += 1
        previous_direction = direction
        if index > 0:
            previous = recent[index - 1]
            previous_high = _value(previous, "high")
            previous_low = _value(previous, "low")
            if previous_high is not None and previous_low is not None and high <= previous_high and low >= previous_low:
                overlapping += 1
    if direction_flips >= 3 or overlapping >= 3:
        return {"status": "CHOPPY", "choppy": True, "adx": None, "message": "Recent candles are overlapping or flipping direction too often."}
    return {"status": "CLEAN", "choppy": False, "adx": None, "message": "Recent candles are not excessively choppy."}


def _value(candle: Any, field: str) -> float | None:
    value = getattr(candle, field, None)
    if value is None and isinstance(candle, dict):
        value = candle.get(field)
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
