from datetime import date, datetime, timezone

from pydantic import BaseModel
from sqlalchemy import Date, DateTime, Float, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base


class ParticipantFlowRecord(Base):
    __tablename__ = "participant_flow_records"
    __table_args__ = (
        Index("ix_part_flow_date_segment", "market_date", "segment"),
        Index("ix_part_flow_participant", "participant_type"),
        Index("ix_part_flow_symbol_date", "symbol", "market_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    source: Mapped[str] = mapped_column(String(40), default="MANUAL", nullable=False, index=True)
    market_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    segment: Mapped[str] = mapped_column(String(40), default="UNKNOWN", nullable=False, index=True)
    participant_type: Mapped[str] = mapped_column(String(20), default="UNKNOWN", nullable=False, index=True)
    category: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    buy_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    sell_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    net_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    buy_qty: Mapped[float | None] = mapped_column(Float, nullable=True)
    sell_qty: Mapped[float | None] = mapped_column(Float, nullable=True)
    net_qty: Mapped[float | None] = mapped_column(Float, nullable=True)
    contracts_buy: Mapped[float | None] = mapped_column(Float, nullable=True)
    contracts_sell: Mapped[float | None] = mapped_column(Float, nullable=True)
    contracts_net: Mapped[float | None] = mapped_column(Float, nullable=True)
    oi_long: Mapped[float | None] = mapped_column(Float, nullable=True)
    oi_short: Mapped[float | None] = mapped_column(Float, nullable=True)
    oi_net: Mapped[float | None] = mapped_column(Float, nullable=True)
    symbol: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    underlying: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    expiry: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    instrument_type: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    data_frequency: Mapped[str] = mapped_column(String(20), default="DAILY", nullable=False, index=True)
    is_provisional: Mapped[bool] = mapped_column(default=False, nullable=False, index=True)
    imported_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    raw_json: Mapped[str | None] = mapped_column(Text, nullable=True)


class ParticipantFlowRecordRead(BaseModel):
    id: int
    source: str
    market_date: date
    segment: str
    participant_type: str
    category: str | None
    buy_value: float | None
    sell_value: float | None
    net_value: float | None
    buy_qty: float | None
    sell_qty: float | None
    net_qty: float | None
    contracts_buy: float | None
    contracts_sell: float | None
    contracts_net: float | None
    oi_long: float | None
    oi_short: float | None
    oi_net: float | None
    symbol: str | None
    underlying: str | None
    expiry: date | None
    instrument_type: str | None
    data_frequency: str
    is_provisional: bool
    imported_at: datetime
    created_at: datetime

    model_config = {"from_attributes": True}
