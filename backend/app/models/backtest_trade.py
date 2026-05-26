from datetime import datetime

from pydantic import BaseModel
from sqlalchemy import DateTime, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base


class BacktestTrade(Base):
    __tablename__ = "backtest_trades"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    backtest_run_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    signal_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    underlying: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    expiry: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    signal_type: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    spot_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    selected_strike: Mapped[float | None] = mapped_column(Float, nullable=True)
    option_type: Mapped[str | None] = mapped_column(String(2), nullable=True, index=True)
    entry_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    entry_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    exit_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    exit_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    stop_loss: Mapped[float | None] = mapped_column(Float, nullable=True)
    target_1: Mapped[float | None] = mapped_column(Float, nullable=True)
    target_2: Mapped[float | None] = mapped_column(Float, nullable=True)
    quantity: Mapped[int] = mapped_column(Integer, default=0)
    gross_pnl: Mapped[float] = mapped_column(Float, default=0.0)
    charges: Mapped[float] = mapped_column(Float, default=0.0)
    slippage: Mapped[float] = mapped_column(Float, default=0.0)
    net_pnl: Mapped[float] = mapped_column(Float, default=0.0)
    result: Mapped[str] = mapped_column(String(20), default="OPEN", index=True)
    exit_reason: Mapped[str | None] = mapped_column(String(40), nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    strategy_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    chain_bias: Mapped[str | None] = mapped_column(String(20), nullable=True, index=True)
    reason_json: Mapped[str] = mapped_column(Text, default="[]")


class BacktestTradeRead(BaseModel):
    id: int
    backtest_run_id: int
    signal_time: datetime
    underlying: str
    expiry: str
    signal_type: str
    status: str
    rejection_reason: str | None
    spot_price: float | None
    selected_strike: float | None
    option_type: str | None
    entry_time: datetime | None
    entry_price: float | None
    exit_time: datetime | None
    exit_price: float | None
    stop_loss: float | None
    target_1: float | None
    target_2: float | None
    quantity: int
    gross_pnl: float
    charges: float
    slippage: float
    net_pnl: float
    result: str
    exit_reason: str | None
    confidence: float | None
    strategy_score: float | None
    chain_bias: str | None
    reason_json: str

    model_config = {"from_attributes": True}
