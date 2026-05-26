from typing import Any


# Original evaluate_momentum signature: def evaluate_momentum(candles_1m: list[Any], candles_3m: list[Any], direction: str) -> dict:
# Original helper signature: def _value(candle: Any, field: str) -> float | None:
def calculate_rsi(candles: list, period: int = 14) -> float | None:
    if len(candles) < period + 1:
        return None
    closes = [_value(candle, "close") for candle in candles]
    if any(close is None for close in closes):
        return None

    deltas = [closes[index] - closes[index - 1] for index in range(1, len(closes))]
    seed = deltas[:period]
    average_gain = sum(max(delta, 0.0) for delta in seed) / period
    average_loss = sum(abs(min(delta, 0.0)) for delta in seed) / period

    for delta in deltas[period:]:
        gain = max(delta, 0.0)
        loss = abs(min(delta, 0.0))
        average_gain = ((average_gain * (period - 1)) + gain) / period
        average_loss = ((average_loss * (period - 1)) + loss) / period

    if average_loss == 0:
        return 100.0
    relative_strength = average_gain / average_loss
    return max(0.0, min(100.0, 100 - (100 / (1 + relative_strength))))


def evaluate_momentum(candles_1m: list[Any], candles_3m: list[Any], direction: str, rsi_candles: list[Any] | None = None) -> dict:
    rsi = calculate_rsi(rsi_candles if rsi_candles is not None else (candles_3m or candles_1m))
    candles = (candles_3m or candles_1m)[-4:]
    if len(candles) < 3:
        return _with_rsi_gate(
            {"status": "INSUFFICIENT_DATA", "score": 0, "message": "Not enough 1m/3m candles for momentum analysis."},
            direction,
            rsi,
        )
    bodies = []
    closes_near_extreme = 0
    aligned = 0
    for candle in candles:
        open_price = _value(candle, "open")
        high = _value(candle, "high")
        low = _value(candle, "low")
        close = _value(candle, "close")
        if None in {open_price, high, low, close} or high <= low:
            return _with_rsi_gate(
                {"status": "INVALID_DATA", "score": 0, "message": "Momentum candles have invalid OHLC values."},
                direction,
                rsi,
            )
        body = abs(close - open_price)
        bodies.append(body)
        if direction == "BULLISH" and close > open_price:
            aligned += 1
            if (high - close) / (high - low) <= 0.35:
                closes_near_extreme += 1
        elif direction == "BEARISH" and close < open_price:
            aligned += 1
            if (close - low) / (high - low) <= 0.35:
                closes_near_extreme += 1
    expanding = len(bodies) >= 2 and bodies[-1] >= max(sum(bodies[:-1]) / len(bodies[:-1]), 0)
    if aligned >= 2 and closes_near_extreme >= 1 and expanding:
        return _with_rsi_gate(
            {"status": "STRONG", "score": 15, "message": "Entry timeframe momentum is aligned and expanding."},
            direction,
            rsi,
        )
    if aligned >= 2:
        return _with_rsi_gate(
            {"status": "MODERATE", "score": 9, "message": "Entry timeframe momentum is directionally aligned but not strong."},
            direction,
            rsi,
        )
    return _with_rsi_gate(
        {"status": "WEAK", "score": 3, "message": "Entry timeframe momentum is weak or mixed."},
        direction,
        rsi,
    )


def _with_rsi_gate(result: dict, direction: str, rsi: float | None) -> dict:
    enriched = {**result, "rsi": rsi, "rsi_confirms": False}
    if rsi is None:
        return enriched

    warnings = list(enriched.get("warnings", []))
    normalized_direction = direction.upper()
    if normalized_direction == "BULLISH" and rsi > 75:
        warnings.append("MOMENTUM_RSI_OVERBOUGHT")
        return {**enriched, "score": max(0, enriched["score"] - 5), "warnings": warnings}
    if normalized_direction == "BEARISH" and rsi < 25:
        warnings.append("MOMENTUM_RSI_OVERSOLD")
        return {**enriched, "score": max(0, enriched["score"] - 5), "warnings": warnings}
    if normalized_direction == "BULLISH" and 50 <= rsi <= 70:
        return {**enriched, "score": enriched["score"] + 3, "rsi_confirms": True, "warnings": warnings}
    if normalized_direction == "BEARISH" and 30 <= rsi <= 50:
        return {**enriched, "score": enriched["score"] + 3, "rsi_confirms": True, "warnings": warnings}
    return {**enriched, "warnings": warnings}


def _value(candle: Any, field: str) -> float | None:
    value = getattr(candle, field, None)
    if value is None and isinstance(candle, dict):
        value = candle.get(field)
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
