import os
import sys
import unittest
from datetime import datetime

backend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from sqlalchemy import create_engine, select, func
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.database import Base
from app.engine.specialist.base import EngineEvidence
from app.engine.specialist.models import SpecialistEngineLog
from app.engine.specialist.option_chain_engine import OptionChainEngine
from app.engine.specialist.shadow_logger import log_engine_evidence
from app.models.trade import PaperTrade


class TestOptionChainEngine(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(bind=self.engine)
        self.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)
        self.db = self.SessionLocal()
        self.engine_under_test = OptionChainEngine()

    def tearDown(self):
        self.db.close()

    def test_1_ce_strong_verdict(self):
        market_data = {
            "option_chain": [
                {"strike": 24000, "ce_oi": 50000, "pe_oi": 20000, "ce_ltp": 85.0, "pe_ltp": 55.0}
            ],
            "oi_change": {"pe_change": -5000, "ce_change": 8000},
            "spot_price": 24050,
            "oi_snapshot": {"dummy": True},
            "expiry": "2026-01-30",
        }
        result = self.engine_under_test.safe_evaluate(market_data)
        self.assertEqual(result.verdict, "CE_STRONG")
        self.assertEqual(result.direction, "BULLISH")
        self.assertFalse(result.blocking)
        self.assertGreater(result.confidence, 0)

    def test_2_pe_strong_verdict(self):
        market_data = {
            "option_chain": [
                {"strike": 24000, "ce_oi": 20000, "pe_oi": 50000, "ce_ltp": 55.0, "pe_ltp": 85.0}
            ],
            "oi_change": {"pe_change": 8000, "ce_change": -5000},
            "spot_price": 24050,
            "oi_snapshot": {"dummy": True},
            "expiry": "2026-01-30",
        }
        result = self.engine_under_test.safe_evaluate(market_data)
        self.assertEqual(result.verdict, "PE_STRONG")
        self.assertEqual(result.direction, "BEARISH")
        self.assertFalse(result.blocking)

    def test_3_data_missing_when_option_chain_is_none(self):
        result = self.engine_under_test.safe_evaluate({"option_chain": None, "spot_price": 24050})
        self.assertEqual(result.verdict, "DATA_MISSING")
        self.assertTrue(result.blocking)
        self.assertIsNotNone(result.blocking_reason)

    def test_4_data_missing_when_option_chain_is_empty(self):
        result = self.engine_under_test.safe_evaluate({"option_chain": [], "spot_price": 24050})
        self.assertEqual(result.verdict, "DATA_MISSING")
        self.assertTrue(result.blocking)

    def test_5_premium_weak_verdict(self):
        market_data = {
            "option_chain": [
                {"strike": 24000, "ce_oi": 30000, "pe_oi": 30000, "ce_ltp": 15.0, "pe_ltp": 14.0}
            ],
            "oi_change": {"pe_change": 100, "ce_change": 100},
            "spot_price": 24050,
            "oi_snapshot": {"dummy": True},
            "expiry": "2026-01-30",
        }
        result = self.engine_under_test.safe_evaluate(market_data)
        self.assertEqual(result.verdict, "PREMIUM_WEAK")
        self.assertFalse(result.blocking)
        self.assertTrue(any("thin" in warning.lower() or "premium" in warning.lower() for warning in result.warnings))
        self.assertTrue(any("waiting" in warning.lower() or "build" in warning.lower() for warning in result.warnings))

    def test_6_safe_evaluate_never_raises_on_broken_input(self):
        result = self.engine_under_test.safe_evaluate({})
        self.assertIsInstance(result, EngineEvidence)
        self.assertIn(result.verdict, ("DATA_MISSING", "ENGINE_ERROR"))
        self.assertTrue(result.blocking)

    def test_7_engine_evidence_schema_is_valid(self):
        market_data = {
            "option_chain": [
                {"strike": 24000, "ce_oi": 20000, "pe_oi": 50000, "ce_ltp": 55.0, "pe_ltp": 85.0}
            ],
            "oi_change": {"pe_change": 8000, "ce_change": -5000},
            "spot_price": 24050,
            "oi_snapshot": {"dummy": True},
            "expiry": "2026-01-30",
        }
        result = self.engine_under_test.safe_evaluate(market_data)
        self.assertGreaterEqual(result.score, 0.0)
        self.assertLessEqual(result.score, 100.0)
        self.assertGreaterEqual(result.confidence, 0.0)
        self.assertLessEqual(result.confidence, 1.0)
        self.assertFalse(result.blocking)
        self.assertIsNone(result.blocking_reason)
        self.assertIsInstance(result.evidence, dict)
        self.assertIsInstance(result.warnings, list)
        self.assertEqual(result.engine, "option_chain_engine")

    def test_8_shadow_logger_does_not_change_paper_trade_count(self):
        count_before = self.db.scalar(select(func.count()).select_from(PaperTrade))
        evidence = EngineEvidence(
            engine="option_chain_engine",
            score=72.0,
            direction="BEARISH",
            verdict="PE_STRONG",
            confidence=0.8,
            evidence={"pcr": 1.4},
            warnings=[],
            blocking=False,
            blocking_reason=None,
            evaluated_at=datetime.utcnow(),
            evaluation_id="test-eval-1",
        )
        log_engine_evidence(self.db, evidence, signal_id="sig-1", signal_v2_decision="PE")
        count_after = self.db.scalar(select(func.count()).select_from(PaperTrade))
        log_count = self.db.scalar(select(func.count()).select_from(SpecialistEngineLog))
        self.assertEqual(count_after, count_before)
        self.assertEqual(log_count, 1)


if __name__ == "__main__":
    unittest.main()
