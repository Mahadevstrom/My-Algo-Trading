from datetime import date, datetime, timezone

from pydantic import BaseModel
from sqlalchemy import Date, DateTime, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base


class OptionChainSnapshot(Base):
    __tablename__ = "option_chain_snapshots"
    __table_args__ = (
        Index("ix_oc_snap_symbol_expiry_time", "symbol", "expiry", "snapshot_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    source: Mapped[str] = mapped_column(String(30), default="DHAN", nullable=False, index=True)
    symbol: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    underlying: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    expiry: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    spot_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    atm_strike: Mapped[float | None] = mapped_column(Float, nullable=True)
    pcr_oi: Mapped[float | None] = mapped_column(Float, nullable=True)
    pcr_volume: Mapped[float | None] = mapped_column(Float, nullable=True)
    total_ce_oi: Mapped[float | None] = mapped_column(Float, nullable=True)
    total_pe_oi: Mapped[float | None] = mapped_column(Float, nullable=True)
    total_ce_volume: Mapped[float | None] = mapped_column(Float, nullable=True)
    total_pe_volume: Mapped[float | None] = mapped_column(Float, nullable=True)
    support_strike: Mapped[float | None] = mapped_column(Float, nullable=True)
    resistance_strike: Mapped[float | None] = mapped_column(Float, nullable=True)
    chain_bias: Mapped[str | None] = mapped_column(String(30), nullable=True)
    snapshot_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    raw_summary_json: Mapped[str | None] = mapped_column(Text, nullable=True)


class OptionChainStrikeSnapshot(Base):
    __tablename__ = "option_chain_strike_snapshots"
    __table_args__ = (
        Index("ix_oc_strike_snap_key", "symbol", "expiry", "strike", "option_type", "snapshot_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    snapshot_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("option_chain_snapshots.id", name="fk_oc_strike_snapshot", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    source: Mapped[str] = mapped_column(String(30), default="DHAN", nullable=False, index=True)
    symbol: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    underlying: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    expiry: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    strike: Mapped[float] = mapped_column(Float, nullable=False, index=True)
    option_type: Mapped[str] = mapped_column(String(2), nullable=False, index=True)
    security_id: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)
    trading_symbol: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    ltp: Mapped[float | None] = mapped_column(Float, nullable=True)
    oi: Mapped[float | None] = mapped_column(Float, nullable=True)
    volume: Mapped[float | None] = mapped_column(Float, nullable=True)
    iv: Mapped[float | None] = mapped_column(Float, nullable=True)
    bid_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    ask_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    bid_qty: Mapped[float | None] = mapped_column(Float, nullable=True)
    ask_qty: Mapped[float | None] = mapped_column(Float, nullable=True)
    liquidity_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    moneyness: Mapped[str | None] = mapped_column(String(20), nullable=True)
    distance_from_spot: Mapped[float | None] = mapped_column(Float, nullable=True)
    snapshot_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    raw_json: Mapped[str | None] = mapped_column(Text, nullable=True)


class OptionChainSnapshotRead(BaseModel):
    id: int
    source: str
    symbol: str
    underlying: str
    expiry: date
    spot_price: float | None
    atm_strike: float | None
    pcr_oi: float | None
    pcr_volume: float | None
    total_ce_oi: float | None
    total_pe_oi: float | None
    total_ce_volume: float | None
    total_pe_volume: float | None
    support_strike: float | None
    resistance_strike: float | None
    chain_bias: str | None
    snapshot_at: datetime
    created_at: datetime

    model_config = {"from_attributes": True}


class OptionChainStrikeSnapshotRead(BaseModel):
    id: int
    snapshot_id: int
    source: str
    symbol: str
    underlying: str
    expiry: date
    strike: float
    option_type: str
    security_id: str | None
    trading_symbol: str | None
    ltp: float | None
    oi: float | None
    volume: float | None
    iv: float | None
    bid_price: float | None
    ask_price: float | None
    bid_qty: float | None
    ask_qty: float | None
    liquidity_score: float | None
    moneyness: str | None
    distance_from_spot: float | None
    snapshot_at: datetime
    created_at: datetime

    model_config = {"from_attributes": True}
