from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


SignalV2Decision = Literal["BUY_CALL", "BUY_PUT", "NO_TRADE"]
SignalV2Confidence = Literal["LOW", "MEDIUM", "HIGH"]


class SignalV2GenerateRequest(BaseModel):
    underlying: str = "NIFTY"
    expiry: str | None = None
    preferred_timeframe: str = "5m"
    use_live_candles: bool = True
    use_option_chain: bool = True
    use_data_quality: bool = True
    use_indstocks_cross_check: bool = True

    @field_validator("underlying")
    @classmethod
    def normalize_underlying(cls, value: str) -> str:
        cleaned = value.strip().upper()
        if not cleaned:
            raise ValueError("underlying is required.")
        return cleaned

    @field_validator("preferred_timeframe")
    @classmethod
    def validate_timeframe(cls, value: str) -> str:
        cleaned = value.strip().lower()
        if cleaned not in {"1m", "3m", "5m", "15m"}:
            raise ValueError("preferred_timeframe must be one of: 1m, 3m, 5m, 15m.")
        return cleaned


class SelectedOptionCandidate(BaseModel):
    underlying: str
    option_type: Literal["CE", "PE"]
    expiry: str
    strike: float
    trading_symbol: str | None = None
    security_id: str | None = None
    exchange_segment: str | None = None
    ltp: float | None = None
    liquidity_score: float | None = None
    spread: float | None = None
    reason_selected: str


class SignalV2Result(BaseModel):
    id: int | None = None
    version: str = "v2"
    symbol: str
    underlying: str
    decision: SignalV2Decision
    confidence: SignalV2Confidence
    score: float
    required_score: float | None = None
    threshold_source: str | None = None
    signal_type: SignalV2Decision
    market_state: dict[str, Any] = Field(default_factory=dict)
    data_quality_gate_passed: bool = False
    data_quality_status: str = "UNKNOWN"
    secondary_data_status: str = "DISABLED"
    trend_status: str = "UNKNOWN"
    momentum_status: str = "UNKNOWN"
    volatility_status: str = "UNKNOWN"
    liquidity_status: str = "UNKNOWN"
    option_chain_status: str = "UNKNOWN"
    risk_gate_status: str = "UNKNOWN"
    session_gate_enabled: bool | None = None
    session_status: str | None = None
    session_allows_new_signal: bool | None = None
    session_allows_paper_entry: bool | None = None
    session_block_reason: str | None = None
    session_caution_reason: str | None = None
    session_next_change: str | None = None
    session_is_market_open: bool | None = None
    market_flow_gate_passed: bool = False
    market_flow_status: str = "UNKNOWN"
    market_flow_bias: str = "UNKNOWN"
    market_flow_score: float | None = None
    market_flow_strength: str = "UNKNOWN"
    market_flow_confirms_signal: bool = False
    market_flow_conflict: bool = False
    trap_risk: str = "UNKNOWN"
    trap_type: str = "UNKNOWN"
    trap_reason: list[str] = Field(default_factory=list)
    oi_change_available: bool = False
    flow_change_bias: str | None = None
    support_zone: float | None = None
    resistance_zone: float | None = None
    near_support: bool = False
    near_resistance: bool = False
    support_strength_change: float | None = None
    resistance_strength_change: float | None = None
    market_flow_adjustment: float = 0.0
    market_flow_reasons: list[str] = Field(default_factory=list)
    market_flow_failed_checks: list[str] = Field(default_factory=list)
    snapshot_count: int = 0
    latest_snapshot_at: str | None = None
    previous_snapshot_at: str | None = None
    selected_option: SelectedOptionCandidate | None = None
    selected_option_present: bool | None = None
    selected_option_reason: str | None = None
    candle_counts_by_timeframe: dict[str, int] = Field(default_factory=dict)
    required_candles_by_timeframe: dict[str, int] = Field(default_factory=dict)
    missing_timeframes: list[str] = Field(default_factory=list)
    candle_warmup_status: str | None = None
    warmup_source: str | None = None
    missed_trade_diagnostics: dict[str, Any] | None = None
    reasons: list[str] = Field(default_factory=list)
    failed_checks: list[str] = Field(default_factory=list)
    supporting_checks: list[str] = Field(default_factory=list)
    atr: float | None = None
    invalidation_level: float | None = None
    suggested_stop_reference: float | None = None
    suggested_target_reference: float | None = None
    invalidation_reference_method: str | None = None
    target_reference_method: str | None = None
    birth_certificate: dict[str, Any] | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class SignalV2StatusResponse(BaseModel):
    enabled: bool
    mode: str
    live_order_status: str
    data_quality_enabled: bool
    live_monitor_available: bool
    indstocks_secondary_enabled: bool
    latest_signal_at: datetime | None = None
    market_flow_gate_enabled: bool = False
    market_flow_required: bool = False
    oi_change_required: bool = False
    market_flow_min_score: int = 55
    latest_market_flow_at: str | None = None
    version: str = "v2"
