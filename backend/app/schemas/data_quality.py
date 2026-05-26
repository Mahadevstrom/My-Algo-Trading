from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


QualityStatus = Literal["OK", "WARNING", "STALE", "BAD_TICK", "MISMATCH", "NO_DATA", "DISCONNECTED", "UNKNOWN"]
QualitySeverity = Literal["INFO", "WARNING", "ERROR", "CRITICAL"]


class DataQualityCheckResult(BaseModel):
    check_name: str
    status: QualityStatus
    severity: QualitySeverity
    passed: bool
    message: str
    symbol: str | None = None
    security_id: str | None = None
    source: str | None = None
    measured_value: float | str | None = None
    expected_value: float | str | None = None
    threshold: float | str | None = None
    age_seconds: float | None = None
    timestamp: datetime
    details: dict[str, Any] = Field(default_factory=dict)


class SymbolQualitySummary(BaseModel):
    symbol: str | None = None
    security_id: str | None = None
    underlying: str | None = None
    option_type: str | None = None
    strike: float | None = None
    expiry: str | None = None
    data_status: QualityStatus
    overall_score: int
    is_tradeable_for_paper_analysis: bool
    live_feed_status: QualityStatus
    live_tick_status: QualityStatus
    live_candle_status: QualityStatus
    rest_cross_check_status: QualityStatus
    stale: bool
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    checks: list[DataQualityCheckResult] = Field(default_factory=list)
    last_tick_at: datetime | None = None
    last_candle_at: datetime | None = None
    last_rest_check_at: datetime | None = None
    market_session: dict[str, Any] = Field(default_factory=dict)


class DataQualityConfigResponse(BaseModel):
    enabled: bool
    rest_cross_check: bool
    rest_cache_seconds: int
    max_rest_checks_per_minute: int
    ltp_mismatch_percent: float
    stale_after_seconds: int
    price_spike_percent: float
    min_candles_for_gap_check: int
    max_history: int
    audit_throttle_seconds: int
