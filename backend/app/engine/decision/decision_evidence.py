from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel


class DecisionEngineV2Evidence(BaseModel):
    decision: str
    advisory_mode: str
    confidence: float
    setup_name: str
    setup_matched: bool
    setup_confidence: float
    context_type: str
    context_modifier: float
    engine_votes: dict[str, str]
    agreement_score: float
    signal_v2_decision: Optional[str]
    agrees_with_signal_v2: Optional[bool]
    would_block_signal_v2_trade: bool
    would_take_trade_when_v2_waited: bool
    reason_codes: list[str]
    warnings: list[str]
    reasoning: str
    evidence: dict[str, Any]
    evaluated_at: datetime
    evaluation_id: Optional[str]

    model_config = {"use_enum_values": True}
