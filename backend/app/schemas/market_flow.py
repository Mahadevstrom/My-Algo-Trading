from typing import Any

from pydantic import BaseModel, Field


class MarketFlowStatusResponse(BaseModel):
    enabled: bool
    source: str = "MARKET_FLOW_ENGINE"
    mode: str
    live_order_status: str
    option_chain_available: bool
    data_quality_available: bool
    indstocks_secondary_available: bool
    last_generated_at: str | None = None
    supported_symbols: list[str] = Field(default_factory=list)


class SupportResistanceFlow(BaseModel):
    support_zone: float | None = None
    secondary_support_zone: float | None = None
    resistance_zone: float | None = None
    secondary_resistance_zone: float | None = None
    atm_strike: float | None = None
    spot_distance_to_support: float | None = None
    spot_distance_to_resistance: float | None = None
    near_support: bool = False
    near_resistance: bool = False
    breakout_required_above: float | None = None
    breakdown_required_below: float | None = None
    range_width: float | None = None
    nearest_high_oi_magnet: float | None = None
    range_state: str = "UNKNOWN"


class TrapDetectionResult(BaseModel):
    trap_risk: str = "UNKNOWN"
    trap_type: str = "UNKNOWN"
    trap_reason: list[str] = Field(default_factory=list)


class MarketFlowScore(BaseModel):
    score: float = 0.0
    strength: str = "NO_EDGE_OR_BAD_DATA"
    confidence: int = 0


class OptionMoneyFlowResponse(BaseModel):
    oi_change_available: bool = False
    ce_total_oi: float = 0.0
    pe_total_oi: float = 0.0
    ce_total_volume: float = 0.0
    pe_total_volume: float = 0.0
    pcr_oi: float | None = None
    pcr_volume: float | None = None
    pcr_oi_change: float | None = None
    pcr_volume_change: float | None = None
    ce_oi_buildup_strikes: list[dict[str, Any]] = Field(default_factory=list)
    pe_oi_buildup_strikes: list[dict[str, Any]] = Field(default_factory=list)
    ce_volume_buildup_strikes: list[dict[str, Any]] = Field(default_factory=list)
    pe_volume_buildup_strikes: list[dict[str, Any]] = Field(default_factory=list)
    call_writing_pressure: str = "UNKNOWN"
    put_writing_support: str = "UNKNOWN"
    call_unwinding: str = "UNKNOWN"
    put_unwinding: str = "UNKNOWN"
    liquid_ce_count: int = 0
    liquid_pe_count: int = 0
    liquid_participation: str = "LOW"
    option_flow_bias: str = "NO_EDGE"
    reasons: list[str] = Field(default_factory=list)


class MarketFlowSummaryResponse(BaseModel):
    ok: bool
    status: str
    symbol: str
    underlying: str
    expiry: str | None = None
    spot: float | None = None
    atm_strike: float | None = None
    pcr_oi: float | None = None
    pcr_volume: float | None = None
    option_flow_bias: str = "NO_EDGE"
    market_flow_bias: str = "NO_DATA"
    flow_score: float = 0.0
    flow_strength: str = "NO_EDGE_OR_BAD_DATA"
    confidence: int = 0
    support_resistance: dict[str, Any] = Field(default_factory=dict)
    trap_detection: dict[str, Any] = Field(default_factory=dict)
    data_quality_status: str = "UNKNOWN"
    live_candle_status: str = "UNKNOWN"
    secondary_data_status: str = "UNKNOWN"
    oi_change_available: bool = False
    snapshot_count: int = 0
    latest_snapshot_at: str | None = None
    previous_snapshot_at: str | None = None
    ce_oi_change: float | None = None
    pe_oi_change: float | None = None
    ce_volume_change: float | None = None
    pe_volume_change: float | None = None
    pcr_oi_change: float | None = None
    pcr_volume_change: float | None = None
    top_ce_buildup_strikes: list[dict[str, Any]] = Field(default_factory=list)
    top_pe_buildup_strikes: list[dict[str, Any]] = Field(default_factory=list)
    top_ce_unwinding_strikes: list[dict[str, Any]] = Field(default_factory=list)
    top_pe_unwinding_strikes: list[dict[str, Any]] = Field(default_factory=list)
    support_strength_change: float | None = None
    resistance_strength_change: float | None = None
    flow_change_bias: str | None = None
    buildup_summary: dict[str, int] = Field(default_factory=dict)
    unwinding_summary: dict[str, int] = Field(default_factory=dict)
    missing_data: list[str] = Field(default_factory=list)
    reasons: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    decision_support: str = "NO_ACTIONABLE_SUPPORT"
    generated_at: str


class SmartMoneyBiasResponse(BaseModel):
    ok: bool
    symbol: str
    expiry: str | None = None
    bias: str
    flow_score: float = 0.0
    confidence: int = 0
    reasons: list[str] = Field(default_factory=list)


class MarketFlowExplainResponse(BaseModel):
    ok: bool
    symbol: str
    expiry: str | None = None
    explanation: list[str] = Field(default_factory=list)
    summary: dict[str, Any] = Field(default_factory=dict)
