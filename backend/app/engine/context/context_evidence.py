from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class ContextEvidence(BaseModel):
    context_type: str
    context_confidence: float
    secondary_context: Optional[str]
    ist_time_str: str
    ist_date_str: str
    day_of_week: str
    is_expiry_day: bool
    is_monthly_expiry: bool
    days_to_expiry: int
    opening_gap_pct: Optional[float]
    vix_value: Optional[float]
    vix_vs_20day_avg_pct: Optional[float]
    previous_day_range_pct: Optional[float]
    is_known_event_day: bool
    known_event_name: Optional[str]
    data_quality_status: str
    confidence_modifier: float
    context_summary: str
    evaluated_at: datetime
    evaluation_id: Optional[str]

    model_config = {"use_enum_values": True}
