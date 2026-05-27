from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base


def _utcnow() -> datetime:
    return datetime.utcnow()


class SetupDefinition(Base):
    __tablename__ = "setup_definitions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow, nullable=False)
    setup_name: Mapped[str] = mapped_column(String(50), nullable=False, unique=True, index=True)
    display_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    direction: Mapped[str] = mapped_column(String(10), nullable=False)
    required_conditions_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    supporting_conditions_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    min_supporting_required: Mapped[int] = mapped_column(Integer, default=1)
    valid_contexts_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    blocked_contexts_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    context_modifiers_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    min_confidence: Mapped[float] = mapped_column(Float, default=0.60)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)


class SetupMatchLog(Base):
    __tablename__ = "setup_match_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, nullable=False, index=True)
    evaluation_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    signal_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    setup_name: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    matched: Mapped[bool] = mapped_column(Boolean, nullable=False)
    match_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    direction_implied: Mapped[str | None] = mapped_column(String(10), nullable=True)
    required_pass_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    required_total: Mapped[int | None] = mapped_column(Integer, nullable=True)
    supporting_pass_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    supporting_total: Mapped[int | None] = mapped_column(Integer, nullable=True)
    context_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    context_modifier: Mapped[float | None] = mapped_column(Float, nullable=True)
    context_effect: Mapped[str | None] = mapped_column(String(20), nullable=True)
    match_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    evidence_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    signal_v2_decision: Mapped[str | None] = mapped_column(String(20), nullable=True)
    market_result: Mapped[str | None] = mapped_column(String(30), nullable=True)
    outcome_correct: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
