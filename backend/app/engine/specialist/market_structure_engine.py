import logging
import uuid
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.config import settings
from app.engine.specialist.base import AbstractSpecialistEngine, EngineEvidence
from app.engine.specialist.shadow_logger import log_engine_evidence
from app.models.live_candle import LiveCandleRecord
from app.services.live_market_monitor_service import get_live_market_monitor_service


logger = logging.getLogger(__name__)
IST = ZoneInfo("Asia/Kolkata")


class MSVerdict:
    BULLISH_TREND = "BULLISH_TREND"
    BEARISH_TREND = "BEARISH_TREND"
    ABOVE_VWAP_WEAK = "ABOVE_VWAP_WEAK"
    BELOW_VWAP_WEAK = "BELOW_VWAP_WEAK"
    BREAKDOWN_CONFIRMED = "BREAKDOWN_CONFIRMED"
    BREAKOUT_CONFIRMED = "BREAKOUT_CONFIRMED"
    RETEST_IN_PROGRESS = "RETEST_IN_PROGRESS"
    VWAP_RECLAIM = "VWAP_RECLAIM"
    VWAP_REJECTION = "VWAP_REJECTION"
    RANGING = "RANGING"
    HIGH_VOLATILITY_CHOP = "HIGH_VOLATILITY_CHOP"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"
    ENGINE_ERROR = "ENGINE_ERROR"


def _num(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _field(candle: Any, name: str) -> Any:
    if isinstance(candle, dict):
        return candle.get(name)
    return getattr(candle, name, None)


def _timestamp(candle: Any) -> datetime | None:
    value = _field(candle, "timestamp") or _field(candle, "start_time")
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    return None


def _to_ist_date(value: datetime | None):
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(IST).date()


def _normalize_timeframe(timeframe: str) -> str:
    mapping = {"1min": "1m", "3min": "3m", "5min": "5m", "15min": "15m"}
    cleaned = (timeframe or "5m").strip().lower()
    return mapping.get(cleaned, cleaned)


def _candle_to_dict(candle: Any) -> dict[str, Any] | None:
    open_price = _num(_field(candle, "open"))
    high = _num(_field(candle, "high"))
    low = _num(_field(candle, "low"))
    close = _num(_field(candle, "close"))
    if None in {open_price, high, low, close}:
        return None
    timestamp = _timestamp(candle)
    return {
        "timestamp": timestamp.isoformat() if timestamp else None,
        "open": open_price,
        "high": high,
        "low": low,
        "close": close,
        "volume": _num(_field(candle, "volume")) or 0.0,
    }


def calculate_ema_series(prices: list[float], period: int) -> list[float | None]:
    if len(prices) < period:
        return []
    multiplier = 2 / (period + 1)
    ema = sum(prices[:period]) / period
    output: list[float | None] = [None] * (period - 1) + [ema]
    for price in prices[period:]:
        ema = (price - ema) * multiplier + ema
        output.append(ema)
    return output


def calculate_vwap(candles: list[dict[str, Any]]) -> float | None:
    today_ist = datetime.now(IST).date()
    session_candles = [candle for candle in candles if _to_ist_date(_timestamp(candle)) == today_ist]
    if not session_candles:
        return None
    total_price_volume = 0.0
    total_volume = 0.0
    for candle in session_candles:
        high = _num(candle.get("high"))
        low = _num(candle.get("low"))
        close = _num(candle.get("close"))
        volume = _num(candle.get("volume"))
        if high is None or low is None or close is None or volume is None:
            return None
        typical_price = (high + low + close) / 3
        total_price_volume += typical_price * volume
        total_volume += volume
    if total_volume <= 0:
        return None
    return total_price_volume / total_volume


def calculate_atr(candles: list[dict[str, Any]], period: int = 14) -> float | None:
    if len(candles) < period + 1:
        return None
    ranges: list[float] = []
    for index in range(1, len(candles)):
        high = _num(candles[index].get("high"))
        low = _num(candles[index].get("low"))
        previous_close = _num(candles[index - 1].get("close"))
        if high is None or low is None or previous_close is None:
            continue
        ranges.append(max(high - low, abs(high - previous_close), abs(low - previous_close)))
    if len(ranges) < period:
        return None
    return sum(ranges[-period:]) / period


def _is_ranging(closes: list[float], ema9: list[float | None], period: int = 10) -> bool:
    if len(closes) < period + 1 or len(ema9) < len(closes):
        return False
    crossings = 0
    start = len(closes) - period
    for index in range(start + 1, len(closes)):
        current_ema = ema9[index]
        previous_ema = ema9[index - 1]
        if current_ema is None or previous_ema is None:
            continue
        if (closes[index] > current_ema) != (closes[index - 1] > previous_ema):
            crossings += 1
    return crossings >= settings.ms_engine_ranging_crossings


def _candle_body_ratio(candle: dict[str, Any]) -> float:
    open_price = _num(candle.get("open")) or 0.0
    close = _num(candle.get("close")) or 0.0
    high = _num(candle.get("high")) or 0.0
    low = _num(candle.get("low")) or 0.0
    total = high - low
    if total <= 0:
        return 0.0
    return abs(close - open_price) / total


def _volume_confirmed(volumes: list[float]) -> bool:
    if len(volumes) < 6:
        return True
    average = sum(volumes[-20:-5] or volumes[:-5]) / max(len(volumes[-20:-5] or volumes[:-5]), 1)
    return volumes[-1] >= average * 1.1 if average > 0 else True


class MarketStructureEngine(AbstractSpecialistEngine):
    @property
    def engine_name(self) -> str:
        return "market_structure_engine"

    def evaluate(self, market_data: dict) -> EngineEvidence:
        candles = market_data.get("candles", []) if isinstance(market_data, dict) else []
        spot_price = _num(market_data.get("spot_price")) if isinstance(market_data, dict) else None

        if not candles or len(candles) < settings.ms_engine_min_candles:
            return EngineEvidence(
                engine=self.engine_name,
                score=50.0,
                direction="NEUTRAL",
                verdict=MSVerdict.INSUFFICIENT_DATA,
                confidence=0.0,
                evidence={"candle_count": len(candles) if candles else 0},
                warnings=["Insufficient candle data for market structure analysis"],
                blocking=False,
                blocking_reason=None,
                evaluated_at=datetime.utcnow(),
                evaluation_id=None,
            )

        normalized = [_candle_to_dict(candle) for candle in candles]
        normalized_candles = [candle for candle in normalized if candle is not None]
        if len(normalized_candles) < settings.ms_engine_min_candles:
            return EngineEvidence(
                engine=self.engine_name,
                score=50.0,
                direction="NEUTRAL",
                verdict=MSVerdict.INSUFFICIENT_DATA,
                confidence=0.0,
                evidence={"candle_count": len(normalized_candles)},
                warnings=["Insufficient valid OHLC candle data for market structure analysis"],
                blocking=False,
                blocking_reason=None,
                evaluated_at=datetime.utcnow(),
                evaluation_id=None,
            )

        closes = [float(candle["close"]) for candle in normalized_candles]
        highs = [float(candle["high"]) for candle in normalized_candles]
        lows = [float(candle["low"]) for candle in normalized_candles]
        volumes = [float(candle.get("volume", 0) or 0) for candle in normalized_candles]
        current_price = spot_price or closes[-1]

        ema9 = calculate_ema_series(closes, settings.ms_engine_ema_fast)
        ema21 = calculate_ema_series(closes, settings.ms_engine_ema_slow)
        ema50 = calculate_ema_series(closes, settings.ms_engine_ema_trend) if len(closes) >= settings.ms_engine_ema_trend else []
        current_ema9 = ema9[-1] if ema9 else None
        current_ema21 = ema21[-1] if ema21 else None
        current_ema50 = ema50[-1] if ema50 else None
        if current_ema21 is None and len(closes) >= settings.ms_engine_min_candles:
            current_ema21 = sum(closes) / len(closes)
        if current_ema9 is None or current_ema21 is None:
            return EngineEvidence(
                engine=self.engine_name,
                score=50.0,
                direction="NEUTRAL",
                verdict=MSVerdict.INSUFFICIENT_DATA,
                confidence=0.0,
                evidence={"candle_count": len(normalized_candles)},
                warnings=["Insufficient candle data for EMA calculation"],
                blocking=False,
                blocking_reason=None,
                evaluated_at=datetime.utcnow(),
                evaluation_id=None,
            )

        vwap = calculate_vwap(normalized_candles)
        atr = calculate_atr(normalized_candles, settings.ms_engine_atr_period)

        alignment_score = 0
        alignment_max = 4
        if current_price > current_ema9:
            alignment_score += 1
        if current_price > current_ema21:
            alignment_score += 1
        if current_ema9 > current_ema21:
            alignment_score += 1
        if current_ema50 is not None:
            if current_price > current_ema50:
                alignment_score += 1
            if current_ema21 > current_ema50:
                alignment_score += 1
            alignment_max = 6
        if vwap is not None:
            if current_price > vwap:
                alignment_score += 1
            alignment_max += 1

        vwap_event = None
        if vwap is not None and len(closes) >= 3:
            previous_close = closes[-2]
            if previous_close < vwap and current_price > vwap:
                vwap_event = "RECLAIM"
            elif previous_close > vwap and current_price < vwap:
                vwap_event = "REJECTION"

        recent_highs = highs[-20:-5] if len(highs) >= 25 else highs[:-5]
        recent_lows = lows[-20:-5] if len(lows) >= 25 else lows[:-5]
        resistance_level = max(recent_highs) if recent_highs else None
        support_level = min(recent_lows) if recent_lows else None
        last_5_closes = closes[-5:]
        last_5_lows = lows[-5:]
        last_5_highs = highs[-5:]
        threshold = max((atr or 0) * 0.2, current_price * 0.0002)
        volume_ok = _volume_confirmed(volumes)
        breakdown_detected = bool(
            support_level is not None
            and min(last_5_lows) < support_level - threshold
            and last_5_closes[-1] < support_level - threshold
            and volume_ok
        )
        breakout_detected = bool(
            resistance_level is not None
            and max(last_5_highs) > resistance_level + threshold
            and last_5_closes[-1] > resistance_level + threshold
            and volume_ok
        )

        ranging = _is_ranging(closes, ema9)
        last_candle = normalized_candles[-1]
        last_body_ratio = _candle_body_ratio(last_candle)
        last_is_bullish = float(last_candle["close"]) > float(last_candle["open"])
        strong_candle = last_body_ratio > settings.ms_engine_strong_candle_ratio

        alignment_ratio = alignment_score / alignment_max if alignment_max else 0.5
        if alignment_ratio >= 0.80:
            trend_contribution = 30.0
        elif alignment_ratio >= 0.60:
            trend_contribution = 15.0
        elif alignment_ratio >= 0.40:
            trend_contribution = 0.0
        elif alignment_ratio >= 0.20:
            trend_contribution = -15.0
        else:
            trend_contribution = -30.0

        vwap_contribution = 10.0 if vwap is not None and current_price > vwap else -10.0 if vwap is not None else 0.0
        structure_contribution = 10.0 if breakout_detected else -10.0 if breakdown_detected else 0.0
        candle_contribution = 5.0 if strong_candle and last_is_bullish else -5.0 if strong_candle else 0.0
        ranging_contribution = -5.0 if ranging else 0.0
        final_score = max(
            0.0,
            min(
                100.0,
                50.0
                + trend_contribution
                + vwap_contribution
                + structure_contribution
                + candle_contribution
                + ranging_contribution,
            ),
        )

        if vwap_event == "RECLAIM":
            verdict = MSVerdict.VWAP_RECLAIM
            direction = "BULLISH"
        elif vwap_event == "REJECTION":
            verdict = MSVerdict.VWAP_REJECTION
            direction = "BEARISH"
        elif breakdown_detected:
            verdict = MSVerdict.BREAKDOWN_CONFIRMED
            direction = "BEARISH"
        elif breakout_detected:
            verdict = MSVerdict.BREAKOUT_CONFIRMED
            direction = "BULLISH"
        elif ranging:
            verdict = MSVerdict.HIGH_VOLATILITY_CHOP if atr and atr > current_price * 0.003 else MSVerdict.RANGING
            direction = "NEUTRAL"
        elif final_score >= 70:
            verdict = MSVerdict.BULLISH_TREND
            direction = "BULLISH"
        elif final_score <= 30:
            verdict = MSVerdict.BEARISH_TREND
            direction = "BEARISH"
        elif final_score > 50 and vwap is not None and current_price > vwap:
            verdict = MSVerdict.ABOVE_VWAP_WEAK
            direction = "BULLISH"
        elif final_score < 50 and vwap is not None and current_price < vwap:
            verdict = MSVerdict.BELOW_VWAP_WEAK
            direction = "BEARISH"
        else:
            verdict = MSVerdict.RANGING
            direction = "NEUTRAL"

        confidence = 1.0
        if len(normalized_candles) < settings.ms_engine_ema_slow:
            confidence -= 0.3
        if vwap is None:
            confidence -= 0.2
        if ranging:
            confidence -= 0.15
        confidence = round(max(0.0, confidence), 3)

        warnings = []
        if len(normalized_candles) < settings.ms_engine_ema_slow:
            warnings.append("Less than 21 candles; EMA21 may not be reliable")
        if vwap is None:
            warnings.append("VWAP unavailable; no intraday candles from today")
        if ranging:
            warnings.append("Price is ranging; trend signals are less reliable")
        if atr and atr > current_price * settings.ms_engine_high_atr_threshold:
            warnings.append("High ATR; elevated volatility, wider stops needed")

        return EngineEvidence(
            engine=self.engine_name,
            score=round(final_score, 2),
            direction=direction,
            verdict=verdict,
            confidence=confidence,
            evidence={
                "current_price": current_price,
                "ema9": round(current_ema9, 2),
                "ema21": round(current_ema21, 2),
                "ema50": round(current_ema50, 2) if current_ema50 is not None else None,
                "vwap": round(vwap, 2) if vwap is not None else None,
                "atr": round(atr, 2) if atr is not None else None,
                "alignment_score": alignment_score,
                "alignment_max": alignment_max,
                "alignment_ratio": round(alignment_ratio, 3),
                "vwap_event": vwap_event,
                "breakdown_detected": breakdown_detected,
                "breakout_detected": breakout_detected,
                "ranging": ranging,
                "support_level": round(support_level, 2) if support_level is not None else None,
                "resistance_level": round(resistance_level, 2) if resistance_level is not None else None,
                "last_candle_bullish": last_is_bullish,
                "last_candle_body_ratio": round(last_body_ratio, 3),
                "candle_count": len(normalized_candles),
            },
            warnings=warnings,
            blocking=False,
            blocking_reason=None,
            evaluated_at=datetime.utcnow(),
            evaluation_id=None,
        )


def _merge_candles(persisted_items: list[Any], memory_items: list[Any], limit: int) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for candle in list(persisted_items) + list(memory_items):
        normalized = _candle_to_dict(candle)
        if normalized is None:
            continue
        key = normalized.get("timestamp") or str(len(merged))
        merged[key] = normalized
    return sorted(merged.values(), key=lambda item: item.get("timestamp") or "")[-limit:]


def _persisted_candles(db: Session, underlying: str, timeframe: str, limit: int) -> list[LiveCandleRecord]:
    aliases = _underlying_aliases(underlying)
    try:
        return list(
            db.scalars(
                select(LiveCandleRecord)
                .where(
                    LiveCandleRecord.timeframe == timeframe,
                    LiveCandleRecord.close > 0,
                    or_(
                        LiveCandleRecord.symbol.in_(aliases),
                        LiveCandleRecord.security_id.in_(aliases),
                        LiveCandleRecord.underlying.in_(aliases),
                    ),
                )
                .order_by(LiveCandleRecord.start_time.desc())
                .limit(limit)
            )
        )[::-1]
    except Exception as exc:
        logger.warning(f"MS engine persisted candle lookup failed (non-fatal): {exc}")
        return []


async def build_market_structure_data(
    db: Session,
    underlying: str = "NIFTY",
    timeframe: str = "5min",
) -> dict[str, Any]:
    normalized_timeframe = _normalize_timeframe(timeframe)
    aliases = _underlying_aliases(underlying)
    try:
        memory_items = []
        for alias in aliases:
            memory_items = await get_live_market_monitor_service().store.get_candles(alias, normalized_timeframe, 80)
            if memory_items:
                break
    except Exception as exc:
        logger.warning(f"MS engine live candle lookup failed (non-fatal): {exc}")
        memory_items = []
    persisted_items = _persisted_candles(db, underlying, normalized_timeframe, 80)
    candles = _merge_candles(persisted_items, memory_items, 80)
    return {
        "candles": candles,
        "spot_price": candles[-1]["close"] if candles else None,
        "timeframe": timeframe,
        "candle_count": len(candles),
        "data_source": "LIVE_MARKET_MONITOR" if candles else "UNAVAILABLE",
    }


def _underlying_aliases(underlying: str) -> list[str]:
    normalized = (underlying or "NIFTY").strip().upper().replace("_", " ")
    aliases = {
        "BANKNIFTY": ["BANKNIFTY", "NIFTY BANK", "NIFTYBANK"],
        "NIFTY BANK": ["BANKNIFTY", "NIFTY BANK", "NIFTYBANK"],
        "NIFTYBANK": ["BANKNIFTY", "NIFTY BANK", "NIFTYBANK"],
        "NIFTY": ["NIFTY", "NIFTY 50"],
        "NIFTY 50": ["NIFTY", "NIFTY 50"],
    }
    return aliases.get(normalized, [normalized])


async def run_market_structure_shadow(
    db: Session,
    underlying: str = "NIFTY",
    signal_id: str | None = None,
    signal_v2_decision: str | None = None,
    evaluation_id: str | None = None,
):
    try:
        market_data = await build_market_structure_data(db, underlying)
        evidence = MarketStructureEngine().safe_evaluate(market_data)
        evidence.evaluation_id = evaluation_id or str(uuid.uuid4())
        return log_engine_evidence(
            db=db,
            evidence=evidence,
            signal_id=signal_id,
            signal_v2_decision=signal_v2_decision,
        )
    except Exception as exc:
        logger.warning(f"MS engine shadow failed (non-fatal): {exc}")
        return None
