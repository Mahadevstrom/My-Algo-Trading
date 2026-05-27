from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel


class SetupRequirementResult(BaseModel):
    requirement: str
    passed: bool
    actual_value: str
    expected: str


class SetupMatchEvidence(BaseModel):
    setup_name: str
    matched: bool
    match_confidence: float
    direction_implied: str
    required_results: List[SetupRequirementResult]
    supporting_results: List[SetupRequirementResult]
    required_pass_count: int
    required_total: int
    supporting_pass_count: int
    supporting_total: int
    context_type: str
    context_modifier: float
    context_effect: str
    historical_trade_count: int
    historical_win_rate_pct: Optional[float]
    historical_avg_pnl: Optional[float]
    match_summary: str
    evaluated_at: datetime
    evaluation_id: Optional[str]

    model_config = {"use_enum_values": True}
