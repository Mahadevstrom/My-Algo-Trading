from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, Field


class SnapshotCaptureRequest(BaseModel):
    symbol: str = "NIFTY"
    expiry: date | None = None
    max_strikes: int | None = None


class OptionChainSnapshotSummary(BaseModel):
    id: int
    source: str
    symbol: str
    underlying: str
    expiry: date
    spot_price: float | None = None
    atm_strike: float | None = None
    pcr_oi: float | None = None
    pcr_volume: float | None = None
    total_ce_oi: float | None = None
    total_pe_oi: float | None = None
    total_ce_volume: float | None = None
    total_pe_volume: float | None = None
    support_strike: float | None = None
    resistance_strike: float | None = None
    chain_bias: str | None = None
    snapshot_at: datetime
    created_at: datetime

    model_config = {"from_attributes": True}


class StrikeSnapshotSummary(BaseModel):
    id: int
    snapshot_id: int
    symbol: str
    expiry: date
    strike: float
    option_type: str
    security_id: str | None = None
    trading_symbol: str | None = None
    ltp: float | None = None
    oi: float | None = None
    volume: float | None = None
    iv: float | None = None
    bid_price: float | None = None
    ask_price: float | None = None
    liquidity_score: float | None = None
    moneyness: str | None = None
    distance_from_spot: float | None = None
    snapshot_at: datetime

    model_config = {"from_attributes": True}


class SnapshotChangeResponse(BaseModel):
    ok: bool
    status: str
    symbol: str
    expiry: str | None = None
    latest_snapshot_at: str | None = None
    previous_snapshot_at: str | None = None
    oi_change_available: bool = False
    summary: dict[str, Any] = Field(default_factory=dict)
    items: list[dict[str, Any]] = Field(default_factory=list)
    message: str | None = None
