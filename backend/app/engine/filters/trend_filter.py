from typing import Any


# Backup: before EMA crossover, evaluate_trend used 5m close vs a simple recent moving average plus 15m confirmation and VWAP.
# Original evaluate_trend signature: def evaluate_trend(primary_candles: list[Any], confirm_candles: list[Any]) -> dict:
def calculate_vwap(candles: list) -> float | None:
    total_price_volume = 0.0
    total_volume = 0.0
    for candle in candles:
        high = _value(candle, "high")
        low = _value(candle, "low")
        close = _value(candle, "close")
        volume = _value(candle, "volume")
        if high is None or low is None or close is None or volume is None:
            return None
        typical_price = (high + low + close) / 3
        total_price_volume += typical_price * volume
        total_volume += volume
    if total_volume == 0:
        return None
    return total_price_volume / total_volume


def calculate_ema(candles: list[Any], period: int) -> float | None:
    if len(candles) < period:
        return None
    closes = [_value(candle, "close") for candle in candles]
    if any(close is None for close in closes):
        return None

    multiplier = 2 / (period + 1)
    ema = sum(closes[:period]) / period
    for close in closes[period:]:
        ema = (close - ema) * multiplier + ema
    return ema


def evaluate_ema_cross(candles: list[Any]) -> dict:
    ema9 = calculate_ema(candles, 9)
    ema21 = calculate_ema(candles, 21)
    if ema9 is None or ema21 is None:
        return {"cross_status": "UNAVAILABLE", "ema9": ema9, "ema21": ema21, "score_bonus": 0}
    if ema9 > ema21:
        return {"cross_status": "BULLISH_CROSS", "ema9": ema9, "ema21": ema21, "score_bonus": 5}
    if ema9 < ema21:
        return {"cross_status": "BEARISH_CROSS", "ema9": ema9, "ema21": ema21, "score_bonus": 5}
    return {"cross_status": "FLAT", "ema9": ema9, "ema21": ema21, "score_bonus": 0}


def evaluate_trend(primary_candles: list[Any], confirm_candles: list[Any], vwap_candles: list[Any] | None = None) -> dict:
    vwap = calculate_vwap(vwap_candles if vwap_candles is not None else primary_candles)
    ema_cross = evaluate_ema_cross(primary_candles)
    if len(primary_candles) < 5 or len(confirm_candles) < 3:
        return {
            "status": "INSUFFICIENT_DATA",
            "direction": "UNKNOWN",
            "score": 0,
            "message": "Not enough primary or confirmation candles for trend analysis.",
            "ema_cross": ema_cross,
            "vwap": vwap,
            "vwap_above": None,
            "vwap_status": "AVAILABLE" if vwap is not None else "UNAVAILABLE",
        }

    primary_closes = [_value(candle, "close") for candle in primary_candles[-5:]]
    confirm_closes = [_value(candle, "close") for candle in confirm_candles[-3:]]
    primary_highs = [_value(candle, "high") for candle in primary_candles[-3:]]
    primary_lows = [_value(candle, "low") for candle in primary_candles[-3:]]
    if any(value is None for value in primary_closes + confirm_closes + primary_highs + primary_lows):
        return {
            "status": "INVALID_DATA",
            "direction": "UNKNOWN",
            "score": 0,
            "message": "Trend candles have missing OHLC values.",
            "ema_cross": ema_cross,
            "vwap": vwap,
            "vwap_above": None,
            "vwap_status": "AVAILABLE" if vwap is not None else "UNAVAILABLE",
        }

    moving_average = sum(primary_closes[:-1]) / max(len(primary_closes[:-1]), 1)
    last_close = primary_closes[-1]
    higher_highs = primary_highs[-1] > primary_highs[0]
    higher_lows = primary_lows[-1] > primary_lows[0]
    lower_highs = primary_highs[-1] < primary_highs[0]
    lower_lows = primary_lows[-1] < primary_lows[0]
    confirm_up = confirm_closes[-1] > confirm_closes[0]
    confirm_down = confirm_closes[-1] < confirm_closes[0]

    if last_close > moving_average and higher_highs and higher_lows and confirm_up:
        return _with_ema_cross_confirmation(
            _with_vwap_confirmation(
                {"status": "BULLISH", "direction": "BULLISH", "score": 20, "message": "5m trend and 15m confirmation are bullish."},
                last_close,
                vwap,
            ),
            ema_cross,
        )
    if last_close < moving_average and lower_highs and lower_lows and confirm_down:
        return _with_ema_cross_confirmation(
            _with_vwap_confirmation(
                {"status": "BEARISH", "direction": "BEARISH", "score": 20, "message": "5m trend and 15m confirmation are bearish."},
                last_close,
                vwap,
            ),
            ema_cross,
        )
    if last_close > moving_average and confirm_up:
        return _with_ema_cross_confirmation(
            _with_vwap_confirmation(
                {"status": "WEAK_BULLISH", "direction": "BULLISH", "score": 12, "message": "Trend is mildly bullish but structure is not strong."},
                last_close,
                vwap,
            ),
            ema_cross,
        )
    if last_close < moving_average and confirm_down:
        return _with_ema_cross_confirmation(
            _with_vwap_confirmation(
                {"status": "WEAK_BEARISH", "direction": "BEARISH", "score": 12, "message": "Trend is mildly bearish but structure is not strong."},
                last_close,
                vwap,
            ),
            ema_cross,
        )
    return _with_ema_cross_confirmation(
        _with_vwap_confirmation(
            {"status": "SIDEWAYS", "direction": "SIDEWAYS", "score": 4, "message": "Trend is sideways or mixed."},
            last_close,
            vwap,
        ),
        ema_cross,
    )


def _with_vwap_confirmation(result: dict, current_close: float, vwap: float | None) -> dict:
    if vwap is None:
        return {**result, "vwap": None, "vwap_above": None, "vwap_status": "UNAVAILABLE"}

    vwap_above = current_close > vwap
    enriched = {**result, "vwap": vwap, "vwap_above": vwap_above, "vwap_status": "AVAILABLE"}
    if result.get("direction") == "BULLISH":
        if vwap_above:
            return {**enriched, "score": 20, "message": "5m bullish above VWAP - institutional level confirmed"}
        return {**enriched, "score": 10, "message": "5m bullish but below VWAP - caution"}
    if result.get("direction") == "BEARISH":
        if not vwap_above:
            return {**enriched, "score": 20, "message": "5m bearish below VWAP - institutional level confirmed"}
        return {**enriched, "score": 10, "message": "5m bearish but above VWAP - caution"}
    return enriched


def _with_ema_cross_confirmation(result: dict, ema_cross: dict) -> dict:
    enriched = {**result, "ema_cross": ema_cross}
    cross_status = ema_cross.get("cross_status")
    direction = result.get("direction")
    if direction == "BULLISH" and cross_status == "BULLISH_CROSS":
        return {
            **enriched,
            "score": result.get("score", 0) + 5,
            "message": f"{result.get('message', '')} EMA 9/21 cross confirms bullish",
        }
    if direction == "BEARISH" and cross_status == "BEARISH_CROSS":
        return {
            **enriched,
            "score": result.get("score", 0) + 5,
            "message": f"{result.get('message', '')} EMA 9/21 cross confirms bearish",
        }
    if direction == "BULLISH" and cross_status == "BEARISH_CROSS":
        return {**enriched, "score": max(0, result.get("score", 0) - 3)}
    if direction == "BEARISH" and cross_status == "BULLISH_CROSS":
        return {**enriched, "score": max(0, result.get("score", 0) - 3)}
    return enriched


def _value(candle: Any, field: str) -> float | None:
    value = getattr(candle, field, None)
    if value is None and isinstance(candle, dict):
        value = candle.get(field)
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
