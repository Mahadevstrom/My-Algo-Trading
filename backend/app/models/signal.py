from enum import Enum
from datetime import date, datetime, timezone

from pydantic import BaseModel, Field, field_validator
from sqlalchemy import Date, DateTime, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base


class SignalType(str, Enum):
    BUY_CE = "BUY_CE"
    BUY_PE = "BUY_PE"
    NO_TRADE = "NO_TRADE"


class SignalStatus(str, Enum):
    SIGNAL = "SIGNAL"
    WATCHLIST = "WATCHLIST"
    NO_TRADE = "NO_TRADE"


class SignalGenerateRequest(BaseModel):
    symbol: str = Field(default="NIFTY", min_length=1, max_length=50)
    instrument_type: str = Field(default="INDEX_OPTION", max_length=30)
    exchange: str = Field(default="NSE", max_length=20)
    expiry: str | None = None
    data_source: str = Field(default="MOCK", max_length=50)

    @field_validator("symbol", "exchange", mode="before")
    @classmethod
    def normalize_upper(cls, value: str) -> str:
        return value.strip().upper()


class SignalResponse(BaseModel):
    symbol: str
    signal_type: SignalType
    confidence: float
    entry: float | None
    stop_loss: float | None
    target_1: float | None
    target_2: float | None
    reason: str
    strategy_score: float
    data_confidence: float
    final_confidence: float


class SignalAnalysisRequest(BaseModel):
    underlying: str = Field(..., min_length=1, max_length=50)
    expiry: date | None = None
    capital: float = Field(..., gt=0)
    max_risk_per_trade: float = Field(..., gt=0)
    lot_size: int = Field(..., gt=0)
    mode: str = Field(default="PAPER", max_length=20)

    @field_validator("underlying", "mode", mode="before")
    @classmethod
    def normalize_upper(cls, value: str) -> str:
        return str(value).strip().upper()


class SignalAnalysisResponse(BaseModel):
    ok: bool
    signal_type: str
    status: str
    underlying: str
    expiry: str | None
    spot_price: float | None
    atm_strike: float | None
    selected_strike: float | None
    option_type: str | None
    entry: float | None
    stop_loss: float | None
    target_1: float | None
    target_2: float | None
    quantity: int
    strategy_score: float
    data_confidence: float
    final_confidence: float
    risk_reward: float | None
    chain_bias: str | None
    reason: list[str]
    warnings: list[str]
    signal_id: int | None = None
    paper_trade_id: int | None = None


class SignalAnalyzeAndPaperResponse(BaseModel):
    signal: SignalAnalysisResponse
    paper_trade: dict | None = None
    message: str


class SignalRecord(Base):
    __tablename__ = "signals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    underlying: Mapped[str] = mapped_column(String(50), index=True)
    expiry: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    signal_type: Mapped[str] = mapped_column(String(20), index=True)
    status: Mapped[str] = mapped_column(String(20), index=True)
    spot_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    atm_strike: Mapped[float | None] = mapped_column(Float, nullable=True)
    selected_strike: Mapped[float | None] = mapped_column(Float, nullable=True)
    option_type: Mapped[str | None] = mapped_column(String(2), nullable=True)
    entry: Mapped[float | None] = mapped_column(Float, nullable=True)
    stop_loss: Mapped[float | None] = mapped_column(Float, nullable=True)
    target_1: Mapped[float | None] = mapped_column(Float, nullable=True)
    target_2: Mapped[float | None] = mapped_column(Float, nullable=True)
    quantity: Mapped[int] = mapped_column(Integer, default=0)
    strategy_score: Mapped[float] = mapped_column(Float, default=0.0)
    data_confidence: Mapped[float] = mapped_column(Float, default=0.0)
    final_confidence: Mapped[float] = mapped_column(Float, default=0.0)
    risk_reward: Mapped[float | None] = mapped_column(Float, nullable=True)
    chain_bias: Mapped[str | None] = mapped_column(String(20), nullable=True)
    reason_json: Mapped[str] = mapped_column(Text, default="[]")
    warnings_json: Mapped[str] = mapped_column(Text, default="[]")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True
    )
    paper_trade_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)


class SignalRecordRead(BaseModel):
    id: int
    underlying: str
    expiry: date | None
    signal_type: str
    status: str
    spot_price: float | None
    atm_strike: float | None
    selected_strike: float | None
    option_type: str | None
    entry: float | None
    stop_loss: float | None
    target_1: float | None
    target_2: float | None
    quantity: int
    strategy_score: float
    data_confidence: float
    final_confidence: float
    risk_reward: float | None
    chain_bias: str | None
    reason_json: str
    warnings_json: str
    created_at: datetime
    paper_trade_id: int | None

    model_config = {"from_attributes": True}
