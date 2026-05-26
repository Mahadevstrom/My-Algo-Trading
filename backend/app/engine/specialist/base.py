from abc import ABC, abstractmethod
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel


class EngineDirection(str, Enum):
    BULLISH = "BULLISH"
    BEARISH = "BEARISH"
    NEUTRAL = "NEUTRAL"
    UNKNOWN = "UNKNOWN"


class EngineEvidence(BaseModel):
    engine: str
    score: float
    direction: str
    verdict: str
    confidence: float
    evidence: Dict[str, Any]
    warnings: List[str]
    blocking: bool
    blocking_reason: Optional[str]
    evaluated_at: datetime
    evaluation_id: Optional[str]

    model_config = {"use_enum_values": True}


class AbstractSpecialistEngine(ABC):
    @property
    @abstractmethod
    def engine_name(self) -> str:
        pass

    @abstractmethod
    def evaluate(self, market_data: dict) -> EngineEvidence:
        pass

    def safe_evaluate(self, market_data: dict) -> EngineEvidence:
        try:
            return self.evaluate(market_data)
        except Exception as e:
            return EngineEvidence(
                engine=self.engine_name,
                score=0.0,
                direction="UNKNOWN",
                verdict="ENGINE_ERROR",
                confidence=0.0,
                evidence={"error": str(e)},
                warnings=[f"Engine crashed: {str(e)}"],
                blocking=True,
                blocking_reason=f"Engine error: {str(e)}",
                evaluated_at=datetime.utcnow(),
                evaluation_id=None,
            )
