from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, Field, field_validator
from sqlalchemy import DateTime, Float, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base


class TradeStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    TARGET_1_HIT = "TARGET_1_HIT"
    TARGET_2_HIT = "TARGET_2_HIT"
    STOP_LOSS_HIT = "STOP_LOSS_HIT"
    MANUAL_EXIT = "MANUAL_EXIT"
    EXPIRED = "EXPIRED"


class TradeResult(str, Enum):
    WIN = "WIN"
    LOSS = "LOSS"
    BREAKEVEN = "BREAKEVEN"
    OPEN = "OPEN"


class ExitReason(str, Enum):
    TARGET_1_HIT = "TARGET_1_HIT"
    TARGET_2_HIT = "TARGET_2_HIT"
    STOP_LOSS_HIT = "STOP_LOSS_HIT"
    MANUAL_EXIT = "MANUAL_EXIT"
    EXPIRED = "EXPIRED"


class Direction(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class OptionType(str, Enum):
    CE = "CE"
    PE = "PE"


class InstrumentType(str, Enum):
    INDEX_OPTION = "INDEX_OPTION"
    STOCK_OPTION = "STOCK_OPTION"
    FUTURE = "FUTURE"
    EQUITY = "EQUITY"


class PaperTrade(Base):
    __tablename__ = "paper_trades"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    symbol: Mapped[str] = mapped_column(String(50), index=True)
    instrument_type: Mapped[str] = mapped_column(String(30))
    exchange: Mapped[str] = mapped_column(String(20), default="NSE")
    expiry: Mapped[str | None] = mapped_column(String(30), nullable=True)
    strike: Mapped[float | None] = mapped_column(Float, nullable=True)
    option_type: Mapped[str | None] = mapped_column(String(2), nullable=True)
    direction: Mapped[str] = mapped_column(String(4))
    entry_price: Mapped[float] = mapped_column(Float)
    stop_loss: Mapped[float | None] = mapped_column(Float, nullable=True)
    target_1: Mapped[float | None] = mapped_column(Float, nullable=True)
    target_2: Mapped[float | None] = mapped_column(Float, nullable=True)
    quantity: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(30), default=TradeStatus.OPEN.value, index=True)
    entry_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True
    )
    exit_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    exit_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    pnl: Mapped[float] = mapped_column(Float, default=0.0)
    pnl_percent: Mapped[float | None] = mapped_column(Float, nullable=True)
    result: Mapped[str] = mapped_column(String(20), default=TradeResult.OPEN.value, index=True)
    exit_reason: Mapped[str | None] = mapped_column(String(30), nullable=True)
    holding_minutes: Mapped[float | None] = mapped_column(Float, nullable=True)
    unrealized_pnl: Mapped[float | None] = mapped_column(Float, nullable=True)
    current_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    signal_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    underlying: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)
    selected_strike: Mapped[float | None] = mapped_column(Float, nullable=True)
    strategy_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    data_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    final_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    chain_bias: Mapped[str | None] = mapped_column(String(20), nullable=True, index=True)
    signal_type: Mapped[str | None] = mapped_column(String(20), nullable=True, index=True)
    signal_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    signal_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    data_source: Mapped[str] = mapped_column(String(50), default="MOCK")
    combo_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    filter_states_json: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    confidence_score_at_entry: Mapped[float | None] = mapped_column(Float, nullable=True)
    regime_at_entry: Mapped[str | None] = mapped_column(String(50), nullable=True)
    session_window_at_entry: Mapped[str | None] = mapped_column(String(50), nullable=True)
    oi_direction_at_entry: Mapped[str | None] = mapped_column(String(50), nullable=True)
    market_flow_score_at_entry: Mapped[float | None] = mapped_column(Float, nullable=True)
    pcr_at_entry: Mapped[float | None] = mapped_column(Float, nullable=True)
    spread_pct_at_entry: Mapped[float | None] = mapped_column(Float, nullable=True)
    filters_passed_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    birth_cert_version: Mapped[str | None] = mapped_column(String(20), nullable=True)
    context_type_at_entry: Mapped[str | None] = mapped_column(String(50), nullable=True)
    context_confidence_at_entry: Mapped[float | None] = mapped_column(Float, nullable=True)
    confidence_modifier_at_entry: Mapped[float | None] = mapped_column(Float, nullable=True)


class PaperTradeCreate(BaseModel):
    symbol: str = Field(..., min_length=1, max_length=50)
    instrument_type: InstrumentType = InstrumentType.INDEX_OPTION
    exchange: str = Field(default="NSE", min_length=1, max_length=20)
    expiry: str | None = None
    strike: float | None = Field(default=None, ge=0)
    option_type: OptionType | None = None
    direction: Direction
    entry_price: float = Field(..., gt=0)
    stop_loss: float | None = Field(default=None, ge=0)
    target_1: float | None = Field(default=None, ge=0)
    target_2: float | None = Field(default=None, ge=0)
    quantity: int = Field(..., gt=0)
    signal_confidence: float | None = Field(default=None, ge=0, le=100)
    signal_id: int | None = None
    underlying: str | None = None
    selected_strike: float | None = Field(default=None, ge=0)
    strategy_score: float | None = Field(default=None, ge=0, le=100)
    data_confidence: float | None = Field(default=None, ge=0, le=100)
    final_confidence: float | None = Field(default=None, ge=0, le=100)
    chain_bias: str | None = Field(default=None, max_length=20)
    signal_type: str | None = Field(default=None, max_length=20)
    signal_reason: str | None = Field(default=None, max_length=500)
    data_source: str = Field(default="MOCK", max_length=50)
    context_type_at_entry: str | None = Field(default=None, max_length=50)
    context_confidence_at_entry: float | None = Field(default=None, ge=0, le=1)
    confidence_modifier_at_entry: float | None = None

    @field_validator("symbol", "exchange", mode="before")
    @classmethod
    def normalize_upper(cls, value: str) -> str:
        return value.strip().upper()


class PaperTradeExit(BaseModel):
    exit_price: float = Field(..., gt=0)
    exit_reason: ExitReason = ExitReason.MANUAL_EXIT


class PaperTradeRead(BaseModel):
    id: int
    symbol: str
    instrument_type: str
    exchange: str
    expiry: str | None
    strike: float | None
    option_type: str | None
    direction: str
    entry_price: float
    stop_loss: float | None
    target_1: float | None
    target_2: float | None
    quantity: int
    status: str
    entry_time: datetime
    exit_time: datetime | None
    exit_price: float | None
    pnl: float
    pnl_percent: float | None
    result: str
    exit_reason: str | None
    holding_minutes: float | None
    unrealized_pnl: float | None
    current_price: float | None
    signal_id: int | None
    underlying: str | None
    selected_strike: float | None
    strategy_score: float | None
    data_confidence: float | None
    final_confidence: float | None
    chain_bias: str | None
    signal_type: str | None
    signal_confidence: float | None
    signal_reason: str | None
    data_source: str
    combo_id: int | None = None
    filter_states_json: str | None = None
    confidence_score_at_entry: float | None = None
    regime_at_entry: str | None = None
    session_window_at_entry: str | None = None
    oi_direction_at_entry: str | None = None
    market_flow_score_at_entry: float | None = None
    pcr_at_entry: float | None = None
    spread_pct_at_entry: float | None = None
    filters_passed_count: int | None = None
    birth_cert_version: str | None = None
    context_type_at_entry: str | None = None
    context_confidence_at_entry: float | None = None
    confidence_modifier_at_entry: float | None = None

    model_config = {"from_attributes": True}


class PerformanceRead(BaseModel):
    total_trades: int
    wins: int
    losses: int
    win_rate: float
    total_virtual_pnl: float


class PaperOptionCombo(Base):
    __tablename__ = "paper_option_combos"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="OPEN", index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc)
    )
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    margin_required: Mapped[float] = mapped_column(Float, default=0.0)
    net_premium: Mapped[float] = mapped_column(Float, default=0.0)
    pnl: Mapped[float] = mapped_column(Float, default=0.0)
    unrealized_pnl: Mapped[float] = mapped_column(Float, default=0.0)


class ComboLegCreate(BaseModel):
    symbol: str
    expiry: str | None = None
    strike: float | None = Field(default=None, ge=0)
    option_type: OptionType | None = None
    direction: Direction
    entry_price: float = Field(..., gt=0)
    quantity: int = Field(..., gt=0)


class ComboCreate(BaseModel):
    name: str
    legs: list[ComboLegCreate]


class ComboRead(BaseModel):
    id: int
    name: str
    status: str
    created_at: datetime
    closed_at: datetime | None
    margin_required: float
    net_premium: float
    pnl: float
    unrealized_pnl: float
    legs: list[PaperTradeRead] = []

    model_config = {"from_attributes": True}
