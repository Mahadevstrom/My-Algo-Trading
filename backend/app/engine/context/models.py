from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base


def _utcnow() -> datetime:
    return datetime.utcnow()


class ContextClassificationLog(Base):
    __tablename__ = "context_classification_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, nullable=False, index=True)
    evaluation_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    signal_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    context_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    context_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    secondary_context: Mapped[str | None] = mapped_column(String(50), nullable=True)
    ist_time_str: Mapped[str | None] = mapped_column(String(10), nullable=True)
    ist_date_str: Mapped[str | None] = mapped_column(String(20), nullable=True, index=True)
    day_of_week: Mapped[str | None] = mapped_column(String(15), nullable=True)
    is_expiry_day: Mapped[bool] = mapped_column(Boolean, default=False)
    is_monthly_expiry: Mapped[bool] = mapped_column(Boolean, default=False)
    days_to_expiry: Mapped[int | None] = mapped_column(Integer, nullable=True)
    opening_gap_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    vix_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    vix_vs_20day_avg_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    is_known_event_day: Mapped[bool] = mapped_column(Boolean, default=False)
    known_event_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    data_quality_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    confidence_modifier: Mapped[float] = mapped_column(Float, default=0.0)
    context_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    signal_v2_decision: Mapped[str | None] = mapped_column(String(20), nullable=True)
