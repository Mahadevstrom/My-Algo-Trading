import os
import sys
import unittest
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

backend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.database import Base, get_db
from app.engine.specialist.base import EngineEvidence
from app.engine.specialist.market_structure_engine import MarketStructureEngine, build_market_structure_data
from app.models.live_candle import LiveCandleRecord
from app.engine.specialist.models import SpecialistEngineLog
from app.engine.specialist.routes import router as specialist_router
from app.engine.specialist.shadow_logger import log_engine_evidence
from app.models.trade import PaperTrade


IST = ZoneInfo("Asia/Kolkata")


def _candles_from_closes(closes: list[float], volume: float = 1000.0, start_hour: int = 9) -> list[dict]:
    start = datetime.now(IST).replace(hour=start_hour, minute=15, second=0, microsecond=0)
    candles = []
    for index, close in enumerate(closes):
        previous = closes[index - 1] if index > 0 else close
        open_price = previous - 0.4 if close >= previous else previous + 0.4
        high = max(open_price, close) + 0.8
        low = min(open_price, close) - 0.8
        candles.append(
            {
                "timestamp": (start + timedelta(minutes=5 * index)).isoformat(),
                "open": round(open_price, 2),
                "high": round(high, 2),
                "low": round(low, 2),
                "close": round(close, 2),
                "volume": volume,
            }
        )
    return candles


class TestMarketStructureEngine(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(bind=self.engine)
        self.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)
        self.db = self.SessionLocal()
        self.engine_under_test = MarketStructureEngine()

    def tearDown(self):
        self.db.close()

    def test_1_bullish_trend_verdict(self):
        closes = [24000 + (idx * 3) for idx in range(30)]
        result = self.engine_under_test.safe_evaluate({"candles": _candles_from_closes(closes), "spot_price": closes[-1]})
        self.assertEqual(result.verdict, "BULLISH_TREND")
        self.assertEqual(result.direction, "BULLISH")
        self.assertGreaterEqual(result.score, 70)
        self.assertFalse(result.blocking)

    def test_2_bearish_trend_verdict(self):
        closes = [24090 - (idx * 3) for idx in range(30)]
        result = self.engine_under_test.safe_evaluate({"candles": _candles_from_closes(closes), "spot_price": closes[-1]})
        self.assertEqual(result.verdict, "BEARISH_TREND")
        self.assertEqual(result.direction, "BEARISH")
        self.assertLessEqual(result.score, 30)

    def test_3_insufficient_data_verdict(self):
        result = self.engine_under_test.safe_evaluate({"candles": _candles_from_closes([100, 101, 102, 103, 104])})
        self.assertEqual(result.verdict, "INSUFFICIENT_DATA")
        self.assertFalse(result.blocking)
        self.assertEqual(result.confidence, 0.0)

    def test_4_empty_candles_does_not_crash(self):
        result = self.engine_under_test.safe_evaluate({"candles": [], "spot_price": 24000})
        self.assertEqual(result.verdict, "INSUFFICIENT_DATA")
        self.assertFalse(result.blocking)

    def test_5_ranging_verdict(self):
        closes = [100, 101, 99, 101.2, 98.8, 101.1, 99.1, 100.9, 99.2, 100.8, 99.4, 100.7, 99.3, 100.6, 99.5, 100.5, 99.6, 100.4, 100.1, 100.2]
        result = self.engine_under_test.safe_evaluate({"candles": _candles_from_closes(closes), "spot_price": closes[-1]})
        self.assertIn(result.verdict, ["RANGING", "HIGH_VOLATILITY_CHOP"])
        self.assertEqual(result.direction, "NEUTRAL")

    def test_6_vwap_reclaim_verdict(self):
        closes = [100] * 24 + [96, 97, 98, 99, 99.2, 104]
        candles = _candles_from_closes(closes)
        result = self.engine_under_test.safe_evaluate({"candles": candles, "spot_price": closes[-1]})
        self.assertEqual(result.verdict, "VWAP_RECLAIM")
        self.assertEqual(result.direction, "BULLISH")

    def test_7_breakdown_confirmed_verdict(self):
        closes = [100 + (idx % 3) * 0.2 for idx in range(22)] + [96, 95, 94]
        candles = _candles_from_closes(closes, volume=1000)
        for candle in candles[-3:]:
            candle["volume"] = 3000
            candle["open"] = candle["close"] + 1.2
            candle["high"] = candle["open"] + 0.4
            candle["low"] = candle["close"] - 1.0
        result = self.engine_under_test.safe_evaluate({"candles": candles, "spot_price": closes[-1]})
        self.assertEqual(result.verdict, "BREAKDOWN_CONFIRMED")
        self.assertEqual(result.direction, "BEARISH")
        self.assertLessEqual(result.score, 40)

    def test_8_safe_evaluate_never_raises(self):
        result = self.engine_under_test.safe_evaluate({"candles": None})
        self.assertIsInstance(result, EngineEvidence)
        self.assertIn(result.verdict, ["INSUFFICIENT_DATA", "ENGINE_ERROR"])
        self.assertFalse(result.blocking)

    def test_9_evidence_dict_contains_required_keys(self):
        closes = [24000 + (idx * 2) for idx in range(30)]
        result = self.engine_under_test.safe_evaluate({"candles": _candles_from_closes(closes), "spot_price": closes[-1]})
        required = [
            "current_price",
            "ema9",
            "ema21",
            "vwap",
            "atr",
            "alignment_score",
            "alignment_max",
            "alignment_ratio",
            "vwap_event",
            "breakdown_detected",
            "breakout_detected",
            "ranging",
            "candle_count",
        ]
        for key in required:
            self.assertIn(key, result.evidence)

    def test_10_score_stays_within_zero_to_hundred(self):
        sample_sets = [
            [100 + idx * 10 for idx in range(30)],
            [300 - idx * 10 for idx in range(30)],
            [100 + ((-1) ** idx) * 20 for idx in range(30)],
            [1 + idx * 0.1 for idx in range(30)],
            [10000 - idx * 50 for idx in range(30)],
            [24000 + idx for idx in range(30)],
            [24000 - idx for idx in range(30)],
            [100 + (idx % 2) for idx in range(30)],
            [100 + (idx % 5) * 2 for idx in range(30)],
            [500 - (idx % 4) * 3 for idx in range(30)],
        ]
        for closes in sample_sets:
            result = self.engine_under_test.safe_evaluate({"candles": _candles_from_closes(closes), "spot_price": closes[-1]})
            self.assertGreaterEqual(result.score, 0.0)
            self.assertLessEqual(result.score, 100.0)

    def test_11_shadow_logger_does_not_affect_paper_trade_count(self):
        count_before = self.db.scalar(select(func.count()).select_from(PaperTrade))
        evidence = EngineEvidence(
            engine="market_structure_engine",
            score=68.0,
            direction="BEARISH",
            verdict="BEARISH_TREND",
            confidence=0.8,
            evidence={"current_price": 23950},
            warnings=[],
            blocking=False,
            blocking_reason=None,
            evaluated_at=datetime.utcnow(),
            evaluation_id="ms-test-eval-1",
        )
        log_engine_evidence(self.db, evidence, signal_id="sig-ms-1", signal_v2_decision="PE")
        count_after = self.db.scalar(select(func.count()).select_from(PaperTrade))
        log = self.db.scalar(select(SpecialistEngineLog).where(SpecialistEngineLog.engine_name == "market_structure_engine"))
        self.assertEqual(count_after, count_before)
        self.assertIsNotNone(log)
        self.assertEqual(log.engine_name, "market_structure_engine")

    def test_12_multi_engine_endpoint_returns_correct_shape(self):
        app = FastAPI()
        app.include_router(specialist_router, prefix="/api/engine")

        def override_db():
            try:
                yield self.db
            finally:
                pass

        app.dependency_overrides[get_db] = override_db
        client = TestClient(app)
        response = client.get("/api/engine/shadow-comparison/multi-engine")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIsInstance(payload, list)
        if payload:
            self.assertIn("engines", payload[0])

    def test_13_nifty_bank_alias_finds_persisted_candles(self):
        start = datetime.now(timezone.utc).replace(hour=4, minute=0, second=0, microsecond=0)
        for index in range(12):
            self.db.add(
                LiveCandleRecord(
                    source="TEST",
                    exchange_segment="IDX_I",
                    security_id="NIFTY BANK",
                    symbol="NIFTY BANK",
                    underlying="NIFTY BANK",
                    timeframe="5m",
                    start_time=start + timedelta(minutes=5 * index),
                    end_time=start + timedelta(minutes=5 * (index + 1)),
                    open=54000 + index,
                    high=54010 + index,
                    low=53990 + index,
                    close=54005 + index,
                    volume=1000,
                    is_closed=True,
                )
            )
        self.db.commit()

        data = __import__("asyncio").run(build_market_structure_data(self.db, "BANKNIFTY", "5min"))
        self.assertGreaterEqual(data["candle_count"], 10)
        self.assertEqual(data["candles"][-1]["close"], 54016.0)

    def test_14_multi_engine_endpoint_groups_by_signal_id(self):
        now = datetime.utcnow()
        self.db.add_all(
            [
                SpecialistEngineLog(
                    evaluation_id="eval-oc",
                    signal_id="signal-shared",
                    engine_name="option_chain_engine",
                    score=70.0,
                    direction="BEARISH",
                    verdict="PE_STRONG",
                    confidence=0.8,
                    blocking=False,
                    evidence_json="{}",
                    warnings_json="[]",
                    evaluated_at=now,
                ),
                SpecialistEngineLog(
                    evaluation_id="eval-ms",
                    signal_id="signal-shared",
                    engine_name="market_structure_engine",
                    score=68.0,
                    direction="BEARISH",
                    verdict="BEARISH_TREND",
                    confidence=0.8,
                    blocking=False,
                    evidence_json="{}",
                    warnings_json="[]",
                    evaluated_at=now,
                ),
            ]
        )
        self.db.commit()
        app = FastAPI()
        app.include_router(specialist_router, prefix="/api/engine")

        def override_db():
            try:
                yield self.db
            finally:
                pass

        app.dependency_overrides[get_db] = override_db
        client = TestClient(app)

        response = client.get("/api/engine/shadow-comparison/multi-engine")

        self.assertEqual(response.status_code, 200)
        groups = response.json()
        shared = next(item for item in groups if item["evaluation_id"] == "signal-shared")
        self.assertIn("option_chain_engine", shared["engines"])
        self.assertIn("market_structure_engine", shared["engines"])


if __name__ == "__main__":
    unittest.main()
