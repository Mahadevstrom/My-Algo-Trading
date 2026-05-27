import os
import sys
import unittest
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

backend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from app.db.database import Base, get_db
from app.engine.specialist.base import EngineEvidence
from app.engine.specialist.models import SpecialistEngineLog
from app.engine.specialist.nifty_momentum_engine import (
    NiftyMomentumValidationEngine,
    NiftyMomentumVerdict,
)
from app.engine.specialist.routes import router as specialist_router
from app.engine.specialist.shadow_logger import log_engine_evidence
from app.models.trade import PaperTrade


IST = ZoneInfo("Asia/Kolkata")


def _candles(closes: list[float]) -> list[dict]:
    start = datetime.now(IST).replace(hour=9, minute=15, second=0, microsecond=0)
    output = []
    for index, close in enumerate(closes):
        previous = closes[index - 1] if index else close
        open_price = previous - 0.3 if close >= previous else previous + 0.3
        output.append(
            {
                "timestamp": (start + timedelta(minutes=5 * index)).isoformat(),
                "open": round(open_price, 2),
                "high": round(max(open_price, close) + 0.7, 2),
                "low": round(min(open_price, close) - 0.7, 2),
                "close": round(close, 2),
                "volume": 1000,
            }
        )
    return output


def _breadth(bias: str = "BULLISH", gainers: int = 36, losers: int = 14) -> dict:
    return {
        "ok": True,
        "breadth_bias": bias,
        "risk_on_score": 70 if bias == "BULLISH" else 25,
        "risk_off_score": 25 if bias == "BULLISH" else 70,
        "gainer_count": gainers,
        "loser_count": losers,
        "constituent_count": 50,
    }


class TestNiftyMomentumEngine(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(bind=self.engine)
        self.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)
        self.db = self.SessionLocal()
        self.engine_under_test = NiftyMomentumValidationEngine()

    def tearDown(self):
        self.db.close()

    def test_1_bullish_continuation_with_banknifty_and_breadth(self):
        nifty = _candles([24000 + index * 8 for index in range(24)])
        bank = _candles([51000 + index * 10 for index in range(24)])
        result = self.engine_under_test.safe_evaluate(
            {"nifty_candles": nifty, "banknifty_candles": bank, "breadth": _breadth("BULLISH")}
        )
        self.assertEqual(result.verdict, NiftyMomentumVerdict.BULLISH_CONTINUATION)
        self.assertEqual(result.direction, "BULLISH")
        self.assertGreaterEqual(result.score, 66)
        self.assertFalse(result.blocking)

    def test_2_bearish_continuation_with_banknifty_and_breadth(self):
        nifty = _candles([24200 - index * 8 for index in range(24)])
        bank = _candles([51200 - index * 10 for index in range(24)])
        result = self.engine_under_test.safe_evaluate(
            {"nifty_candles": nifty, "banknifty_candles": bank, "breadth": _breadth("BEARISH", 12, 38)}
        )
        self.assertEqual(result.verdict, NiftyMomentumVerdict.BEARISH_CONTINUATION)
        self.assertEqual(result.direction, "BEARISH")
        self.assertLessEqual(result.score, 34)

    def test_3_banknifty_disagreement_flags_reversal_risk(self):
        nifty = _candles([24000 + index * 6 for index in range(24)])
        bank = _candles([51200 - index * 8 for index in range(24)])
        result = self.engine_under_test.safe_evaluate(
            {"nifty_candles": nifty, "banknifty_candles": bank, "breadth": _breadth("BULLISH")}
        )
        self.assertIn(result.verdict, [NiftyMomentumVerdict.MOMENTUM_WEAKENING, NiftyMomentumVerdict.REVERSAL_RISK])
        self.assertTrue(result.evidence["reversal_risk"])
        self.assertFalse(result.blocking)

    def test_4_insufficient_data_is_non_blocking(self):
        result = self.engine_under_test.safe_evaluate({"nifty_candles": _candles([1, 2, 3])})
        self.assertEqual(result.verdict, NiftyMomentumVerdict.INSUFFICIENT_DATA)
        self.assertEqual(result.confidence, 0.0)
        self.assertFalse(result.blocking)

    def test_5_missing_banknifty_and_breadth_warns(self):
        result = self.engine_under_test.safe_evaluate({"nifty_candles": _candles([24000 + index for index in range(12)])})
        self.assertTrue(any("BANKNIFTY" in warning for warning in result.warnings))
        self.assertTrue(any("breadth" in warning.lower() for warning in result.warnings))

    def test_6_evidence_contains_validation_fields(self):
        result = self.engine_under_test.safe_evaluate(
            {
                "nifty_candles": _candles([24000 + index * 3 for index in range(24)]),
                "banknifty_candles": _candles([51000 + index * 3 for index in range(24)]),
                "breadth": _breadth("BULLISH"),
            }
        )
        for key in [
            "short_change_pct",
            "session_change_pct",
            "vwap_distance_pct",
            "banknifty_confirmation",
            "sector_confirmation",
            "advance_ratio",
            "reversal_risk",
        ]:
            self.assertIn(key, result.evidence)

    def test_7_shadow_logger_does_not_affect_paper_trade_count(self):
        count_before = self.db.scalar(select(func.count()).select_from(PaperTrade))
        evidence = EngineEvidence(
            engine="nifty_momentum_engine",
            score=72.0,
            direction="BULLISH",
            verdict=NiftyMomentumVerdict.BULLISH_CONTINUATION,
            confidence=0.8,
            evidence={"banknifty_confirmation": True},
            warnings=[],
            blocking=False,
            blocking_reason=None,
            evaluated_at=datetime.utcnow(),
            evaluation_id="nifty-momentum-test-1",
        )
        log_engine_evidence(self.db, evidence, signal_id="sig-mom-1", signal_v2_decision="CE")
        count_after = self.db.scalar(select(func.count()).select_from(PaperTrade))
        log = self.db.scalar(select(SpecialistEngineLog).where(SpecialistEngineLog.engine_name == "nifty_momentum_engine"))
        self.assertEqual(count_after, count_before)
        self.assertIsNotNone(log)

    def test_8_endpoint_shape(self):
        app = FastAPI()
        app.include_router(specialist_router, prefix="/api/engine")

        def override_db():
            try:
                yield self.db
            finally:
                pass

        app.dependency_overrides[get_db] = override_db
        client = TestClient(app)
        response = client.get("/api/engine/nifty-momentum-engine/latest")
        self.assertEqual(response.status_code, 200)
        self.assertIn("status", response.json())


if __name__ == "__main__":
    unittest.main()
