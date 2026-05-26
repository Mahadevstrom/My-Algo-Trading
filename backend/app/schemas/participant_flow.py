from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator


VALID_PARTICIPANTS = {"FII", "DII", "CLIENT", "PRO", "BANK", "MF", "UNKNOWN"}
VALID_SEGMENTS = {
    "CASH",
    "INDEX_FUTURES",
    "INDEX_OPTIONS",
    "STOCK_FUTURES",
    "STOCK_OPTIONS",
    "FNO_TOTAL",
    "UNKNOWN",
}


class ParticipantFlowRecordCreate(BaseModel):
    market_date: date
    source: str = "MANUAL"
    segment: str = "UNKNOWN"
    participant_type: str = "UNKNOWN"
    category: str | None = None
    buy_value: float | None = None
    sell_value: float | None = None
    net_value: float | None = None
    buy_qty: float | None = None
    sell_qty: float | None = None
    net_qty: float | None = None
    contracts_buy: float | None = None
    contracts_sell: float | None = None
    contracts_net: float | None = None
    oi_long: float | None = None
    oi_short: float | None = None
    oi_net: float | None = None
    symbol: str | None = None
    underlying: str | None = None
    expiry: date | None = None
    instrument_type: str | None = None
    data_frequency: str = "DAILY"
    is_provisional: bool = False

    @field_validator("source", "segment", "participant_type", "symbol", "underlying", "instrument_type", "data_frequency", mode="before")
    @classmethod
    def normalize_text(cls, value: Any) -> Any:
        if value is None:
            return value
        return str(value).strip().upper()

    @field_validator("segment")
    @classmethod
    def validate_segment(cls, value: str) -> str:
        if value not in VALID_SEGMENTS:
            raise ValueError(f"segment must be one of: {', '.join(sorted(VALID_SEGMENTS))}.")
        return value

    @field_validator("participant_type")
    @classmethod
    def validate_participant(cls, value: str) -> str:
        if value not in VALID_PARTICIPANTS:
            raise ValueError(f"participant_type must be one of: {', '.join(sorted(VALID_PARTICIPANTS))}.")
        return value

    @model_validator(mode="after")
    def validate_values(self) -> "ParticipantFlowRecordCreate":
        numeric_values = [
            self.buy_value,
            self.sell_value,
            self.net_value,
            self.buy_qty,
            self.sell_qty,
            self.net_qty,
            self.contracts_buy,
            self.contracts_sell,
            self.contracts_net,
            self.oi_long,
            self.oi_short,
            self.oi_net,
        ]
        if all(value is None for value in numeric_values):
            raise ValueError("At least one numeric flow value is required.")
        if self.net_value is None and self.buy_value is not None and self.sell_value is not None:
            self.net_value = self.buy_value - self.sell_value
        if self.net_qty is None and self.buy_qty is not None and self.sell_qty is not None:
            self.net_qty = self.buy_qty - self.sell_qty
        if self.contracts_net is None and self.contracts_buy is not None and self.contracts_sell is not None:
            self.contracts_net = self.contracts_buy - self.contracts_sell
        if self.oi_net is None and self.oi_long is not None and self.oi_short is not None:
            self.oi_net = self.oi_long - self.oi_short
        return self


class ParticipantFlowImportRequest(BaseModel):
    records: list[ParticipantFlowRecordCreate] = Field(default_factory=list)


class ParticipantFlowRecordResponse(BaseModel):
    id: int
    source: str
    market_date: date
    segment: str
    participant_type: str
    category: str | None = None
    buy_value: float | None = None
    sell_value: float | None = None
    net_value: float | None = None
    buy_qty: float | None = None
    sell_qty: float | None = None
    net_qty: float | None = None
    contracts_buy: float | None = None
    contracts_sell: float | None = None
    contracts_net: float | None = None
    oi_long: float | None = None
    oi_short: float | None = None
    oi_net: float | None = None
    symbol: str | None = None
    underlying: str | None = None
    expiry: date | None = None
    instrument_type: str | None = None
    data_frequency: str
    is_provisional: bool
    imported_at: datetime
    created_at: datetime

    model_config = {"from_attributes": True}


class ParticipantFlowImportResponse(BaseModel):
    ok: bool
    status: str
    inserted: int = 0
    updated: int = 0
    message: str
    items: list[ParticipantFlowRecordResponse] = Field(default_factory=list)


class ParticipantFlowStatusResponse(BaseModel):
    enabled: bool
    data_mode: str
    web_fetch_allowed: bool
    latest_record_date: date | None = None
    latest_import_at: datetime | None = None
    record_count: int = 0
    live_order_status: str
    supported_segments: list[str] = Field(default_factory=list)


class ParticipantContextSummary(BaseModel):
    ok: bool
    status: str
    symbol: str = "NIFTY"
    market_date: date | None = None
    data_freshness: str = "UNKNOWN"
    participant_context_status: str = "NO_DATA"
    participant_bias: str = "NO_DATA"
    participant_score: float = 0.0
    fii_cash_net: float | None = None
    dii_cash_net: float | None = None
    fii_dii_divergence: bool = False
    dii_supporting_fii_selling: bool = False
    derivative_bias: str = "PARTIAL_DATA"
    risk_on_score: float = 0.0
    risk_off_score: float = 0.0
    warnings: list[str] = Field(default_factory=list)
    missing_data: list[str] = Field(default_factory=list)
    reasons: list[str] = Field(default_factory=list)
    generated_at: datetime
