from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator


class NormalizedTick(BaseModel):
    source: str = "DHAN_WS"
    exchange_segment: str | None = None
    security_id: str
    symbol: str | None = None
    ltp: float | None = None
    last_traded_quantity: int | None = None
    volume: int | None = None
    average_traded_price: float | None = None
    open: float | None = None
    high: float | None = None
    low: float | None = None
    close: float | None = None
    bid_price: float | None = None
    ask_price: float | None = None
    bid_quantity: int | None = None
    ask_quantity: int | None = None
    open_interest: int | None = None
    oi_change: int | None = None
    timestamp: datetime | None = None
    received_at: datetime
    raw_payload: dict[str, Any] | str | None = None


class LiveFeedSubscriptionRequest(BaseModel):
    symbols: list[str] = Field(default_factory=list)
    security_ids: list[str] = Field(default_factory=list)

    @field_validator("symbols", mode="before")
    @classmethod
    def normalize_symbols(cls, value: list[str] | None) -> list[str]:
        if not value:
            return []
        return [str(item).strip().upper() for item in value if str(item).strip()]

    @field_validator("security_ids", mode="before")
    @classmethod
    def normalize_security_ids(cls, value: list[str] | None) -> list[str]:
        if not value:
            return []
        return [str(item).strip() for item in value if str(item).strip()]
