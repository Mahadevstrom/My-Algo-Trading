from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from zoneinfo._common import ZoneInfoNotFoundError

from app.schemas.live_candle import LiveCandle, LiveInstrumentMetadata
from app.schemas.live_feed import NormalizedTick


SUPPORTED_LIVE_TIMEFRAMES = {"1m": 1, "3m": 3, "5m": 5, "15m": 15}
try:
    MARKET_TIMEZONE = ZoneInfo("Asia/Kolkata")
except ZoneInfoNotFoundError:
    MARKET_TIMEZONE = timezone(timedelta(hours=5, minutes=30), name="Asia/Kolkata")


class LiveCandleBuilderError(ValueError):
    pass


def parse_timeframe(timeframe: str) -> int:
    cleaned = timeframe.strip().lower()
    if cleaned not in SUPPORTED_LIVE_TIMEFRAMES:
        raise LiveCandleBuilderError("Invalid timeframe. Supported timeframes are: 1m, 3m, 5m, 15m.")
    return SUPPORTED_LIVE_TIMEFRAMES[cleaned]


def normalize_timeframe(timeframe: str) -> str:
    parse_timeframe(timeframe)
    return timeframe.strip().lower()


def tick_timestamp(tick: NormalizedTick) -> datetime:
    value = tick.timestamp or tick.received_at
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def floor_timestamp_to_timeframe(timestamp: datetime, timeframe: str) -> datetime:
    minutes = parse_timeframe(timeframe)
    local = timestamp.astimezone(MARKET_TIMEZONE)
    floored_minute = (local.minute // minutes) * minutes
    return local.replace(minute=floored_minute, second=0, microsecond=0)


def candle_end_time(start_time: datetime, timeframe: str) -> datetime:
    minutes = parse_timeframe(timeframe)
    return start_time + timedelta(minutes=minutes)


class LiveCandleBuilder:
    def build_new_candle(
        self,
        tick: NormalizedTick,
        timeframe: str,
        metadata: LiveInstrumentMetadata | None = None,
    ) -> LiveCandle | None:
        if tick.ltp is None:
            return None
        normalized_timeframe = normalize_timeframe(timeframe)
        start = floor_timestamp_to_timeframe(tick_timestamp(tick), normalized_timeframe)
        now = tick.received_at
        meta = metadata or LiveInstrumentMetadata(
            exchange_segment=tick.exchange_segment,
            security_id=tick.security_id,
            symbol=tick.symbol,
            underlying=tick.symbol,
        )
        return LiveCandle(
            source=tick.source,
            exchange_segment=meta.exchange_segment or tick.exchange_segment,
            security_id=tick.security_id,
            symbol=meta.symbol or tick.symbol,
            underlying=meta.underlying,
            option_type=meta.option_type,
            strike=meta.strike,
            expiry=meta.expiry,
            timeframe=normalized_timeframe,
            start_time=start,
            end_time=candle_end_time(start, normalized_timeframe),
            open=float(tick.ltp),
            high=float(tick.ltp),
            low=float(tick.ltp),
            close=float(tick.ltp),
            volume=0 if tick.volume is not None or tick.last_traded_quantity is not None else None,
            open_interest=tick.open_interest,
            tick_count=1,
            is_closed=False,
            last_tick_at=tick_timestamp(tick),
            created_at=now,
            updated_at=now,
            start_volume=tick.volume,
        )

    def update_candle(self, candle: LiveCandle, tick: NormalizedTick) -> LiveCandle:
        if tick.ltp is None:
            return candle
        price = float(tick.ltp)
        candle.high = max(candle.high, price)
        candle.low = min(candle.low, price)
        candle.close = price
        candle.tick_count += 1
        candle.last_tick_at = tick_timestamp(tick)
        candle.updated_at = tick.received_at
        if tick.open_interest is not None:
            candle.open_interest = tick.open_interest
        if tick.volume is not None:
            if candle.start_volume is None:
                candle.start_volume = tick.volume
            candle.volume = max(0, int(tick.volume) - int(candle.start_volume))
        elif tick.last_traded_quantity is not None:
            candle.volume = (candle.volume or 0) + int(tick.last_traded_quantity)
        return candle
