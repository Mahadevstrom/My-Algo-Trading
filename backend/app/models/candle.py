from datetime import datetime, timezone

from pydantic import BaseModel
from sqlalchemy import DateTime, Float, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base


class Candle(Base):
    __tablename__ = "candles"
    __table_args__ = (
        UniqueConstraint(
            "source",
            "security_id",
            "exchange_segment",
            "instrument",
            "interval",
            "timestamp",
            name="uq_candles_key",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    source: Mapped[str] = mapped_column(String(30), default="DHAN", nullable=False, index=True)
    symbol: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    security_id: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    exchange_segment: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    instrument: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    interval: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    open: Mapped[float] = mapped_column(Float, nullable=False)
    high: Mapped[float] = mapped_column(Float, nullable=False)
    low: Mapped[float] = mapped_column(Float, nullable=False)
    close: Mapped[float] = mapped_column(Float, nullable=False)
    volume: Mapped[float | None] = mapped_column(Float, nullable=True)
    open_interest: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )


class CandleRead(BaseModel):
    id: int
    source: str
    symbol: str
    security_id: str
    exchange_segment: str
    instrument: str
    interval: str
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float | None
    open_interest: float | None
    created_at: datetime

    model_config = {"from_attributes": True}
