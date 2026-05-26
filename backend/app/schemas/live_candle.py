from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator


class LiveInstrumentMetadata(BaseModel):
    exchange_segment: str | None = None
    security_id: str
    symbol: str | None = None
    underlying: str | None = None
    option_type: str | None = None
    strike: float | None = None
    expiry: str | None = None


class LiveCandle(BaseModel):
    source: str = "DHAN_WS"
    exchange_segment: str | None = None
    security_id: str
    symbol: str | None = None
    underlying: str | None = None
    option_type: str | None = None
    strike: float | None = None
    expiry: str | None = None
    timeframe: str
    start_time: datetime
    end_time: datetime
    open: float
    high: float
    low: float
    close: float
    volume: int | None = None
    open_interest: int | None = None
    tick_count: int = 0
    is_closed: bool = False
    last_tick_at: datetime
    created_at: datetime
    updated_at: datetime
    start_volume: int | None = Field(default=None, exclude=True)


class TestTickIngestRequest(BaseModel):
    exchange_segment: str | None = "NSE_EQ"
    security_id: str
    symbol: str | None = None
    ltp: float
    volume: int | None = None
    open_interest: int | None = None
    timestamp: datetime | None = None


class CandleQuery(BaseModel):
    timeframe: str = "5m"
    limit: int = 100

    @field_validator("limit")
    @classmethod
    def validate_limit(cls, value: int) -> int:
        if value < 1 or value > 1000:
            raise ValueError("limit must be between 1 and 1000.")
        return value


class LiveMarketSnapshot(BaseModel):
    symbol: str
    security_id: str | None = None
    exchange_segment: str | None = None
    underlying: str | None = None
    expiry: str | None = None
    strike: float | None = None
    option_type: str | None = None
    ltp: float | None = None
    previous_close: float | None = None
    day_open: float | None = None
    day_high: float | None = None
    day_low: float | None = None
    change: float | None = None
    change_percent: float | None = None
    volume: int | None = None
    open_interest: int | None = None
    latest_tick_at: datetime | None = None
    stale: bool = True
    active_timeframes: list[str] = Field(default_factory=list)
    latest_candles: dict[str, dict[str, Any]] = Field(default_factory=dict)
