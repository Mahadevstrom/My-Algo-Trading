from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base


def _utcnow() -> datetime:
    return datetime.utcnow()


class DecisionEngineV2Log(Base):
    __tablename__ = "decision_engine_v2_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, nullable=False, index=True)
    evaluation_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    signal_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    decision: Mapped[str] = mapped_column(String(10), nullable=False, index=True)
    advisory_mode: Mapped[str] = mapped_column(String(20), default="SHADOW")
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    setup_name: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)
    setup_matched: Mapped[bool] = mapped_column(Boolean, default=False)
    setup_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    context_type: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)
    context_modifier: Mapped[float | None] = mapped_column(Float, nullable=True)
    agreement_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    signal_v2_decision: Mapped[str | None] = mapped_column(String(20), nullable=True, index=True)
    agrees_with_signal_v2: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    would_block_signal_v2_trade: Mapped[bool] = mapped_column(Boolean, default=False)
    would_take_trade_when_v2_waited: Mapped[bool] = mapped_column(Boolean, default=False)
    reasoning: Mapped[str | None] = mapped_column(Text, nullable=True)
    reason_codes_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    warnings_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    evidence_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    market_result: Mapped[str | None] = mapped_column(String(30), nullable=True)
    signal_v2_correct: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    decision_v2_correct: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    comparison_verdict: Mapped[str | None] = mapped_column(String(30), nullable=True)
