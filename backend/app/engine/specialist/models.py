from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base


def _utcnow() -> datetime:
    return datetime.utcnow()


class SpecialistEngineLog(Base):
    __tablename__ = "specialist_engine_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, nullable=False, index=True)
    evaluation_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    signal_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    engine_name: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    score: Mapped[float | None] = mapped_column(Float, nullable=True)
    direction: Mapped[str | None] = mapped_column(String(20), nullable=True)
    verdict: Mapped[str | None] = mapped_column(String(50), nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    blocking: Mapped[bool] = mapped_column(Boolean, default=False)
    blocking_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    warnings_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    evidence_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    evaluated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    signal_engine_v2_decision: Mapped[str | None] = mapped_column(String(20), nullable=True)
    market_result: Mapped[str | None] = mapped_column(String(30), nullable=True)
    label_source: Mapped[str | None] = mapped_column(String(20), nullable=True)
    comparison_verdict: Mapped[str | None] = mapped_column(String(30), nullable=True)


class LabelRecord(Base):
    __tablename__ = "specialist_label_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, nullable=False)
    imported_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    date_str: Mapped[str | None] = mapped_column(String(20), nullable=True)
    time_str: Mapped[str | None] = mapped_column(String(10), nullable=True)
    signal_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    evaluation_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    instrument: Mapped[str | None] = mapped_column(String(20), nullable=True)
    setup: Mapped[str | None] = mapped_column(String(50), nullable=True)
    action_taken: Mapped[str | None] = mapped_column(String(30), nullable=True)
    direction: Mapped[str | None] = mapped_column(String(10), nullable=True)
    strike: Mapped[int | None] = mapped_column(Integer, nullable=True)
    entry_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    exit_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    result: Mapped[str | None] = mapped_column(String(20), nullable=True)
    r_multiple: Mapped[float | None] = mapped_column(Float, nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    wrong_block_reason: Mapped[str | None] = mapped_column(String(100), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    label_source: Mapped[str | None] = mapped_column(String(20), nullable=True)
