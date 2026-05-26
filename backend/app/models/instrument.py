from datetime import date, datetime, timezone

from pydantic import BaseModel, Field, field_validator
from sqlalchemy import Date, DateTime, Float, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base


class InstrumentMaster(Base):
    __tablename__ = "instruments"
    __table_args__ = (
        UniqueConstraint(
            "security_id",
            "exchange",
            "segment",
            "source",
            name="uq_instruments_security_exchange_segment_source",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    exchange: Mapped[str] = mapped_column(String(20), index=True)
    segment: Mapped[str] = mapped_column(String(40), index=True)
    security_id: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    trading_symbol: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    display_name: Mapped[str | None] = mapped_column(String(160), nullable=True)
    underlying_symbol: Mapped[str] = mapped_column(String(60), nullable=False, index=True)
    instrument_type: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    option_type: Mapped[str | None] = mapped_column(String(2), nullable=True, index=True)
    expiry: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    strike: Mapped[float | None] = mapped_column(Float, nullable=True, index=True)
    lot_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tick_size: Mapped[float | None] = mapped_column(Float, nullable=True)
    source: Mapped[str] = mapped_column(String(60), default="LOCAL_CSV")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


class InstrumentRead(BaseModel):
    id: int
    exchange: str
    segment: str
    security_id: str
    trading_symbol: str
    display_name: str | None
    underlying_symbol: str
    instrument_type: str
    option_type: str | None
    expiry: date | None
    strike: float | None
    lot_size: int | None
    tick_size: float | None
    source: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class InstrumentSearchResponse(BaseModel):
    query: str
    count: int
    items: list[InstrumentRead]
    message: str | None = None


class UnderlyingsResponse(BaseModel):
    count: int
    underlyings: list[str]
    message: str | None = None


class ExpiriesResponse(BaseModel):
    underlying: str
    count: int
    expiries: list[date]
    message: str | None = None


class OptionChainSymbolsResponse(BaseModel):
    underlying: str
    expiry: date
    count: int
    items: list[InstrumentRead]
    message: str | None = None


class InstrumentImportRequest(BaseModel):
    file_name: str = Field(default="instruments.csv", max_length=120)

    @field_validator("file_name")
    @classmethod
    def only_csv_file_name(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned.endswith(".csv") or "/" in cleaned or "\\" in cleaned:
            raise ValueError("file_name must be a CSV file name inside backend/data.")
        return cleaned


class InstrumentImportResponse(BaseModel):
    imported_count: int
    skipped_count: int
    source_file: str
    message: str
