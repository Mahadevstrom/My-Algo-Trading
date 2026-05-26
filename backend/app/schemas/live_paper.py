from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator


class LivePaperStartRequest(BaseModel):
    underlying: str = "NIFTY"
    mode: str = "PAPER"
    dry_run: bool = False
    max_open_trades: int | None = Field(default=None, ge=1, le=10)
    signal_check_interval_seconds: int | None = Field(default=None, ge=5, le=3600)
    mtm_interval_seconds: int | None = Field(default=None, ge=1, le=300)

    @field_validator("underlying")
    @classmethod
    def normalize_underlying(cls, value: str) -> str:
        cleaned = value.strip().upper()
        if not cleaned:
            raise ValueError("underlying is required.")
        return cleaned

    @field_validator("mode")
    @classmethod
    def paper_only(cls, value: str) -> str:
        cleaned = value.strip().upper()
        if cleaned != "PAPER":
            raise ValueError("Live paper simulator supports PAPER mode only.")
        return cleaned


class LivePaperStopRequest(BaseModel):
    close_open_paper_trades: bool = False
    exit_price: float | None = Field(default=None, gt=0)


class LivePaperEvaluateRequest(BaseModel):
    underlying: str = "NIFTY"
    dry_run: bool = True
    force: bool = False

    @field_validator("underlying")
    @classmethod
    def normalize_underlying(cls, value: str) -> str:
        return value.strip().upper()


class LivePaperManualExitRequest(BaseModel):
    exit_price: float | None = Field(default=None, gt=0)
    exit_reason: str = Field(default="MANUAL_EXIT", max_length=30)


class LivePaperTradeSnapshot(BaseModel):
    trade_id: int
    symbol: str
    underlying: str | None = None
    status: str
    result: str
    entry_price: float
    current_ltp: float | None = None
    quantity: int
    unrealized_pnl: float | None = None
    realized_pnl: float
    stop_loss: float | None = None
    target_1: float | None = None
    target_2: float | None = None
    trailing_stop_price: float | None = None
    last_mtm_at: datetime | None = None
    data_status: str = "UNKNOWN"


class LivePaperRejection(BaseModel):
    timestamp: datetime
    underlying: str
    reason: str
    details: dict[str, Any] = Field(default_factory=dict)

