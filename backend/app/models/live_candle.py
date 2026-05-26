from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Float, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base


class LiveCandleRecord(Base):
    __tablename__ = "live_candles"
    __table_args__ = (
        UniqueConstraint(
            "source",
            "security_id",
            "timeframe",
            "start_time",
            name="uq_live_candles_key",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    source: Mapped[str] = mapped_column(String(30), default="DHAN_WS", nullable=False, index=True)
    exchange_segment: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    security_id: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    symbol: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    underlying: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    expiry: Mapped[str | None] = mapped_column(String(20), nullable=True, index=True)
    strike: Mapped[float | None] = mapped_column(Float, nullable=True, index=True)
    option_type: Mapped[str | None] = mapped_column(String(2), nullable=True, index=True)
    timeframe: Mapped[str] = mapped_column(String(10), nullable=False, index=True)
    start_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    end_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    open: Mapped[float] = mapped_column(Float, nullable=False)
    high: Mapped[float] = mapped_column(Float, nullable=False)
    low: Mapped[float] = mapped_column(Float, nullable=False)
    close: Mapped[float] = mapped_column(Float, nullable=False)
    volume: Mapped[int | None] = mapped_column(Integer, nullable=True)
    open_interest: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tick_count: Mapped[int] = mapped_column(Integer, default=0)
    is_closed: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
