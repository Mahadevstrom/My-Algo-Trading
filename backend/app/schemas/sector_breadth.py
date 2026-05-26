from datetime import datetime
from typing import Any

from pydantic import BaseModel


class SectorSymbolQuote(BaseModel):
    symbol: str
    security_id: str | None = None
    exchange_segment: str | None = None
    ltp: float | None = None
    previous_close: float | None = None
    change_percent: float | None = None
    volume: float | None = None
    data_status: str = "UNKNOWN"
    source: str = "DHAN"
    warning: str | None = None


class SectorStrength(BaseModel):
    sector: str
    symbols_count: int
    available_symbols_count: int
    advancing_count: int
    declining_count: int
    unchanged_count: int
    advance_decline_ratio: float
    average_change_percent: float | None = None
    median_change_percent: float | None = None
    total_volume_if_available: float | None = None
    strongest_symbols: list[dict[str, Any]]
    weakest_symbols: list[dict[str, Any]]
    sector_score: float
    sector_bias: str
    data_status: str
    missing_symbols: list[str]
    last_updated_at: datetime | None = None


class SectorBreadthStatusResponse(BaseModel):
    enabled: bool
    default_index: str
    symbol_count: int
    sector_count: int
    cache_seconds: int
    data_sources: dict[str, Any]
    last_updated_at: datetime | None = None
    live_order_status: str


class SectorRotationSummary(BaseModel):
    index: str
    status: str
    sector_count: int
    leading_sectors: list[str]
    lagging_sectors: list[str]
    improving_sectors: list[str]
    weakening_sectors: list[str]
    rotation_bias: str
    sectors: list[dict[str, Any]]


class HeavyweightContribution(BaseModel):
    tracked_count: int
    available_count: int
    positive_heavyweight_count: int
    negative_heavyweight_count: int
    average_heavyweight_change_percent: float | None = None
    top_positive_contributors: list[dict[str, Any]]
    top_negative_contributors: list[dict[str, Any]]
    heavyweight_confirmation: str
    narrow_leadership_warning: bool
    missing_symbols: list[str]


class NiftyBreadthConfirmation(BaseModel):
    nifty_confirmation: str
    breadth_bias: str
    banking_confirmation: str
    financial_confirmation: str
    it_confirmation: str
    heavyweight_confirmation: str
    divergence: bool
    warnings: list[str]
    reasons: list[str]


class MarketBreadthSummary(BaseModel):
    index: str
    status: str
    breadth_bias: str
    risk_on_score: float
    risk_off_score: float
    sectors: list[dict[str, Any]]
    heavyweight_contribution: dict[str, Any]
    nifty_confirmation: dict[str, Any]
    generated_at: datetime


class SectorBreadthExplainResponse(BaseModel):
    ok: bool
    index: str
    explanation: list[str]
    summary: dict[str, Any]


class SectorHeatmapResponse(BaseModel):
    ok: bool
    index: str
    status: str
    items: list[dict[str, Any]]
    generated_at: datetime | None = None
