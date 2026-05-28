import os
import sys
import unittest
from datetime import datetime

backend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.database import Base
from app.engine.context.context_evidence import ContextEvidence
from app.engine.context.models import ContextClassificationLog
from app.engine.setup.models import SetupDefinition, SetupMatchLog
from app.engine.setup.routes import _latest_evidence
from app.engine.setup.setup_seeder import seed_core_setups
from app.engine.setup.setup_matcher import SetupMatcher
from app.engine.setup.setup_types import SetupName
from app.engine.setup.setup_logger import log_setup_match
from app.engine.setup.condition_evaluator import evaluate_condition
from app.engine.specialist.base import EngineEvidence
from app.engine.specialist.models import SpecialistEngineLog


class TestSetupMatcher(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(bind=self.engine)
        self.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)
        self.db = self.SessionLocal()
        seed_core_setups(self.db)
        self.matcher = SetupMatcher()

    def tearDown(self):
        self.db.close()

    def test_1_pe_breakdown_continuation_matches_correctly(self):
        oc = EngineEvidence(
            engine="option_chain_engine",
            score=74.0,
            direction="BEARISH",
            verdict="PE_STRONG",
            confidence=0.8,
            evidence={},
            warnings=[],
            blocking=False,
            blocking_reason=None,
            evaluated_at=datetime.utcnow(),
            evaluation_id=None,
        )
        ms = EngineEvidence(
            engine="market_structure_engine",
            score=68.0,
            direction="BEARISH",
            verdict="BEARISH_TREND",
            confidence=0.8,
            evidence={},
            warnings=[],
            blocking=False,
            blocking_reason=None,
            evaluated_at=datetime.utcnow(),
            evaluation_id=None,
        )
        ctx = ContextEvidence(
            context_type="NORMAL_TRADING_DAY",
            context_confidence=0.9,
            secondary_context=None,
            ist_time_str="10:30",
            ist_date_str="2026-05-27",
            day_of_week="WEDNESDAY",
            is_expiry_day=False,
            is_monthly_expiry=False,
            days_to_expiry=1,
            opening_gap_pct=0.0,
            vix_value=15.0,
            vix_vs_20day_avg_pct=0.0,
            previous_day_range_pct=1.2,
            is_known_event_day=False,
            known_event_name=None,
            data_quality_status="CLEAN",
            confidence_modifier=0.0,
            context_summary="",
            evaluated_at=datetime.utcnow(),
            evaluation_id=None,
        )

        match = self.matcher.safe_match(self.db, oc, ms, ctx)
        self.assertTrue(match.matched)
        self.assertEqual(match.setup_name, SetupName.PE_BREAKDOWN_CONTINUATION)
        self.assertEqual(match.direction_implied, "PE")
        self.assertGreater(match.match_confidence, 0.0)

    def test_2_ce_breakout_continuation_matches_correctly(self):
        oc = EngineEvidence(
            engine="option_chain_engine",
            score=72.0,
            direction="BULLISH",
            verdict="CE_STRONG",
            confidence=0.8,
            evidence={},
            warnings=[],
            blocking=False,
            blocking_reason=None,
            evaluated_at=datetime.utcnow(),
            evaluation_id=None,
        )
        ms = EngineEvidence(
            engine="market_structure_engine",
            score=71.0,
            direction="BULLISH",
            verdict="BULLISH_TREND",
            confidence=0.8,
            evidence={},
            warnings=[],
            blocking=False,
            blocking_reason=None,
            evaluated_at=datetime.utcnow(),
            evaluation_id=None,
        )
        ctx = ContextEvidence(
            context_type="NORMAL_TRADING_DAY",
            context_confidence=0.9,
            secondary_context=None,
            ist_time_str="10:30",
            ist_date_str="2026-05-27",
            day_of_week="WEDNESDAY",
            is_expiry_day=False,
            is_monthly_expiry=False,
            days_to_expiry=1,
            opening_gap_pct=0.0,
            vix_value=15.0,
            vix_vs_20day_avg_pct=0.0,
            previous_day_range_pct=1.2,
            is_known_event_day=False,
            known_event_name=None,
            data_quality_status="CLEAN",
            confidence_modifier=0.0,
            context_summary="",
            evaluated_at=datetime.utcnow(),
            evaluation_id=None,
        )

        match = self.matcher.safe_match(self.db, oc, ms, ctx)
        self.assertTrue(match.matched)
        self.assertEqual(match.setup_name, SetupName.CE_BREAKOUT_CONTINUATION)
        self.assertEqual(match.direction_implied, "CE")

    def test_3_expiry_day_afternoon_blocks_pe_breakdown(self):
        oc = EngineEvidence(
            engine="option_chain_engine",
            score=74.0,
            direction="BEARISH",
            verdict="PE_STRONG",
            confidence=0.8,
            evidence={},
            warnings=[],
            blocking=False,
            blocking_reason=None,
            evaluated_at=datetime.utcnow(),
            evaluation_id=None,
        )
        ms = EngineEvidence(
            engine="market_structure_engine",
            score=68.0,
            direction="BEARISH",
            verdict="BEARISH_TREND",
            confidence=0.8,
            evidence={},
            warnings=[],
            blocking=False,
            blocking_reason=None,
            evaluated_at=datetime.utcnow(),
            evaluation_id=None,
        )
        ctx = ContextEvidence(
            context_type="EXPIRY_DAY_AFTERNOON",
            context_confidence=0.9,
            secondary_context=None,
            ist_time_str="14:00",
            ist_date_str="2026-05-27",
            day_of_week="THURSDAY",
            is_expiry_day=True,
            is_monthly_expiry=False,
            days_to_expiry=0,
            opening_gap_pct=0.0,
            vix_value=15.0,
            vix_vs_20day_avg_pct=0.0,
            previous_day_range_pct=1.2,
            is_known_event_day=False,
            known_event_name=None,
            data_quality_status="CLEAN",
            confidence_modifier=0.0,
            context_summary="",
            evaluated_at=datetime.utcnow(),
            evaluation_id=None,
        )

        match = self.matcher.safe_match(self.db, oc, ms, ctx)
        self.assertFalse(match.matched)
        self.assertNotEqual(match.setup_name, SetupName.PE_BREAKDOWN_CONTINUATION)

    def test_4_blocking_engine_returns_no_setup_found(self):
        oc = EngineEvidence(
            engine="option_chain_engine",
            score=50.0,
            direction="NEUTRAL",
            verdict="DATA_MISSING",
            confidence=0.0,
            evidence={},
            warnings=[],
            blocking=True,
            blocking_reason="Missing candles",
            evaluated_at=datetime.utcnow(),
            evaluation_id=None,
        )
        ms = EngineEvidence(
            engine="market_structure_engine",
            score=68.0,
            direction="BEARISH",
            verdict="BEARISH_TREND",
            confidence=0.8,
            evidence={},
            warnings=[],
            blocking=False,
            blocking_reason=None,
            evaluated_at=datetime.utcnow(),
            evaluation_id=None,
        )
        ctx = ContextEvidence(
            context_type="NORMAL_TRADING_DAY",
            context_confidence=0.9,
            secondary_context=None,
            ist_time_str="10:30",
            ist_date_str="2026-05-27",
            day_of_week="WEDNESDAY",
            is_expiry_day=False,
            is_monthly_expiry=False,
            days_to_expiry=1,
            opening_gap_pct=0.0,
            vix_value=15.0,
            vix_vs_20day_avg_pct=0.0,
            previous_day_range_pct=1.2,
            is_known_event_day=False,
            known_event_name=None,
            data_quality_status="CLEAN",
            confidence_modifier=0.0,
            context_summary="",
            evaluated_at=datetime.utcnow(),
            evaluation_id=None,
        )

        match = self.matcher.safe_match(self.db, oc, ms, ctx)
        self.assertFalse(match.matched)
        self.assertEqual(match.setup_name, SetupName.NO_SETUP_FOUND)
        self.assertEqual(match.direction_implied, "WAIT")

    def test_5_no_setup_found_when_engines_disagree(self):
        oc = EngineEvidence(
            engine="option_chain_engine",
            score=72.0,
            direction="BULLISH",
            verdict="CE_STRONG",
            confidence=0.8,
            evidence={},
            warnings=[],
            blocking=False,
            blocking_reason=None,
            evaluated_at=datetime.utcnow(),
            evaluation_id=None,
        )
        ms = EngineEvidence(
            engine="market_structure_engine",
            score=30.0,
            direction="BEARISH",
            verdict="BEARISH_TREND",
            confidence=0.8,
            evidence={},
            warnings=[],
            blocking=False,
            blocking_reason=None,
            evaluated_at=datetime.utcnow(),
            evaluation_id=None,
        )
        ctx = ContextEvidence(
            context_type="NORMAL_TRADING_DAY",
            context_confidence=0.9,
            secondary_context=None,
            ist_time_str="10:30",
            ist_date_str="2026-05-27",
            day_of_week="WEDNESDAY",
            is_expiry_day=False,
            is_monthly_expiry=False,
            days_to_expiry=1,
            opening_gap_pct=0.0,
            vix_value=15.0,
            vix_vs_20day_avg_pct=0.0,
            previous_day_range_pct=1.2,
            is_known_event_day=False,
            known_event_name=None,
            data_quality_status="CLEAN",
            confidence_modifier=0.0,
            context_summary="",
            evaluated_at=datetime.utcnow(),
            evaluation_id=None,
        )

        match = self.matcher.safe_match(self.db, oc, ms, ctx)
        self.assertFalse(match.matched)

    def test_6_pe_expiry_morning_scalp_only_fires_on_expiry_morning(self):
        oc = EngineEvidence(
            engine="option_chain_engine",
            score=68.0,
            direction="BEARISH",
            verdict="PE_STRONG",
            confidence=0.8,
            evidence={},
            warnings=[],
            blocking=False,
            blocking_reason=None,
            evaluated_at=datetime.utcnow(),
            evaluation_id=None,
        )
        ms = EngineEvidence(
            engine="market_structure_engine",
            score=40.0,
            direction="BEARISH",
            verdict="BEARISH_TREND",
            confidence=0.8,
            evidence={},
            warnings=[],
            blocking=False,
            blocking_reason=None,
            evaluated_at=datetime.utcnow(),
            evaluation_id=None,
        )
        ctx = ContextEvidence(
            context_type="EXPIRY_DAY_MORNING",
            context_confidence=0.9,
            secondary_context=None,
            ist_time_str="10:00",
            ist_date_str="2026-05-28",
            day_of_week="THURSDAY",
            is_expiry_day=True,
            is_monthly_expiry=False,
            days_to_expiry=0,
            opening_gap_pct=0.0,
            vix_value=15.0,
            vix_vs_20day_avg_pct=0.0,
            previous_day_range_pct=1.2,
            is_known_event_day=False,
            known_event_name=None,
            data_quality_status="CLEAN",
            confidence_modifier=0.0,
            context_summary="",
            evaluated_at=datetime.utcnow(),
            evaluation_id=None,
        )

        match = self.matcher.safe_match(self.db, oc, ms, ctx)
        self.assertTrue(match.matched)
        self.assertEqual(match.setup_name, SetupName.PE_EXPIRY_MORNING_SCALP)

        # Non-expiry day
        ctx2 = ContextEvidence(
            context_type="NORMAL_TRADING_DAY",
            context_confidence=0.9,
            secondary_context=None,
            ist_time_str="10:00",
            ist_date_str="2026-05-27",
            day_of_week="WEDNESDAY",
            is_expiry_day=False,
            is_monthly_expiry=False,
            days_to_expiry=1,
            opening_gap_pct=0.0,
            vix_value=15.0,
            vix_vs_20day_avg_pct=0.0,
            previous_day_range_pct=1.2,
            is_known_event_day=False,
            known_event_name=None,
            data_quality_status="CLEAN",
            confidence_modifier=0.0,
            context_summary="",
            evaluated_at=datetime.utcnow(),
            evaluation_id=None,
        )
        match2 = self.matcher.safe_match(self.db, oc, ms, ctx2)
        self.assertNotEqual(match2.setup_name, SetupName.PE_EXPIRY_MORNING_SCALP)

    def test_7_context_boost_increases_confidence(self):
        oc = EngineEvidence(
            engine="option_chain_engine",
            score=50.0,
            direction="BEARISH",
            verdict="PE_STRONG",
            confidence=0.8,
            evidence={},
            warnings=[],
            blocking=False,
            blocking_reason=None,
            evaluated_at=datetime.utcnow(),
            evaluation_id=None,
        )
        ms = EngineEvidence(
            engine="market_structure_engine",
            score=68.0,
            direction="BEARISH",
            verdict="BEARISH_TREND",
            confidence=0.8,
            evidence={},
            warnings=[],
            blocking=False,
            blocking_reason=None,
            evaluated_at=datetime.utcnow(),
            evaluation_id=None,
        )
        ctx1 = ContextEvidence(
            context_type="NORMAL_TRADING_DAY",
            context_confidence=0.9,
            secondary_context=None,
            ist_time_str="10:30",
            ist_date_str="2026-05-27",
            day_of_week="WEDNESDAY",
            is_expiry_day=False,
            is_monthly_expiry=False,
            days_to_expiry=1,
            opening_gap_pct=0.0,
            vix_value=15.0,
            vix_vs_20day_avg_pct=0.0,
            previous_day_range_pct=1.2,
            is_known_event_day=False,
            known_event_name=None,
            data_quality_status="CLEAN",
            confidence_modifier=0.0,
            context_summary="",
            evaluated_at=datetime.utcnow(),
            evaluation_id=None,
        )
        ctx2 = ContextEvidence(
            context_type="GAP_DOWN_CONTINUATION",
            context_confidence=0.9,
            secondary_context=None,
            ist_time_str="10:30",
            ist_date_str="2026-05-27",
            day_of_week="WEDNESDAY",
            is_expiry_day=False,
            is_monthly_expiry=False,
            days_to_expiry=1,
            opening_gap_pct=-1.2,
            vix_value=15.0,
            vix_vs_20day_avg_pct=0.0,
            previous_day_range_pct=1.2,
            is_known_event_day=False,
            known_event_name=None,
            data_quality_status="CLEAN",
            confidence_modifier=0.0,
            context_summary="",
            evaluated_at=datetime.utcnow(),
            evaluation_id=None,
        )

        match1 = self.matcher.safe_match(self.db, oc, ms, ctx1)
        match2 = self.matcher.safe_match(self.db, oc, ms, ctx2)

        self.assertTrue(match1.matched)
        self.assertTrue(match2.matched)
        self.assertGreater(match2.match_confidence, match1.match_confidence)
        self.assertEqual(match2.context_effect, "BOOST")

    def test_8_momentum_reversal_risk_reduces_match_confidence(self):
        oc = EngineEvidence(
            engine="option_chain_engine",
            score=74.0,
            direction="BEARISH",
            verdict="PE_STRONG",
            confidence=0.8,
            evidence={},
            warnings=[],
            blocking=False,
            blocking_reason=None,
            evaluated_at=datetime.utcnow(),
            evaluation_id=None,
        )
        ms = EngineEvidence(
            engine="market_structure_engine",
            score=68.0,
            direction="BEARISH",
            verdict="BEARISH_TREND",
            confidence=0.8,
            evidence={},
            warnings=[],
            blocking=False,
            blocking_reason=None,
            evaluated_at=datetime.utcnow(),
            evaluation_id=None,
        )
        ctx = ContextEvidence(
            context_type="NORMAL_TRADING_DAY",
            context_confidence=0.9,
            secondary_context=None,
            ist_time_str="10:30",
            ist_date_str="2026-05-27",
            day_of_week="WEDNESDAY",
            is_expiry_day=False,
            is_monthly_expiry=False,
            days_to_expiry=1,
            opening_gap_pct=0.0,
            vix_value=15.0,
            vix_vs_20day_avg_pct=0.0,
            previous_day_range_pct=1.2,
            is_known_event_day=False,
            known_event_name=None,
            data_quality_status="CLEAN",
            confidence_modifier=0.0,
            context_summary="",
            evaluated_at=datetime.utcnow(),
            evaluation_id=None,
        )
        momentum = EngineEvidence(
            engine="nifty_momentum_engine",
            score=40.0,
            direction="BULLISH",
            verdict="REVERSAL_RISK",
            confidence=0.7,
            evidence={},
            warnings=[],
            blocking=False,
            blocking_reason=None,
            evaluated_at=datetime.utcnow(),
            evaluation_id=None,
        )

        normal_match = self.matcher.safe_match(self.db, oc, ms, ctx)
        penalized_match = self.matcher.safe_match(self.db, oc, ms, ctx, momentum_evidence=momentum)

        self.assertTrue(normal_match.matched)
        self.assertTrue(penalized_match.matched)
        self.assertAlmostEqual(penalized_match.match_confidence, normal_match.match_confidence - 0.08, places=3)
        self.assertIn("Momentum validation warns of reversal risk", penalized_match.match_summary)

    def test_9_missing_momentum_does_not_block_setup_matching(self):
        oc = EngineEvidence(
            engine="option_chain_engine",
            score=74.0,
            direction="BEARISH",
            verdict="PE_STRONG",
            confidence=0.8,
            evidence={},
            warnings=[],
            blocking=False,
            blocking_reason=None,
            evaluated_at=datetime.utcnow(),
            evaluation_id=None,
        )
        ms = EngineEvidence(
            engine="market_structure_engine",
            score=68.0,
            direction="BEARISH",
            verdict="BEARISH_TREND",
            confidence=0.8,
            evidence={},
            warnings=[],
            blocking=False,
            blocking_reason=None,
            evaluated_at=datetime.utcnow(),
            evaluation_id=None,
        )
        ctx = ContextEvidence(
            context_type="NORMAL_TRADING_DAY",
            context_confidence=0.9,
            secondary_context=None,
            ist_time_str="10:30",
            ist_date_str="2026-05-27",
            day_of_week="WEDNESDAY",
            is_expiry_day=False,
            is_monthly_expiry=False,
            days_to_expiry=1,
            opening_gap_pct=0.0,
            vix_value=15.0,
            vix_vs_20day_avg_pct=0.0,
            previous_day_range_pct=1.2,
            is_known_event_day=False,
            known_event_name=None,
            data_quality_status="CLEAN",
            confidence_modifier=0.0,
            context_summary="",
            evaluated_at=datetime.utcnow(),
            evaluation_id=None,
        )

        match = self.matcher.safe_match(self.db, oc, ms, ctx, momentum_evidence=None)

        self.assertTrue(match.matched)
        self.assertEqual(match.setup_name, SetupName.PE_BREAKDOWN_CONTINUATION)
        self.assertNotIn("Momentum validation warns", match.match_summary)

    def test_10_safe_match_never_raises(self):
        # Pass None to force an error internally
        match = self.matcher.safe_match(self.db, None, None, None)
        self.assertFalse(match.matched)
        self.assertEqual(match.setup_name, SetupName.INSUFFICIENT_ENGINE_DATA)
        self.assertEqual(match.direction_implied, "WAIT")

    def test_11_setup_performance_endpoint_returns_correct_shape(self):
        from app.engine.setup.routes import setup_performance
        res = setup_performance(self.db)
        self.assertTrue(res["ok"])
        self.assertIn("setups", res)
        self.assertIn("total_evaluations", res)
        self.assertIn("insight", res)

    def test_12_setup_match_log_is_saved_correctly(self):
        oc = EngineEvidence(
            engine="option_chain_engine",
            score=74.0,
            direction="BEARISH",
            verdict="PE_STRONG",
            confidence=0.8,
            evidence={},
            warnings=[],
            blocking=False,
            blocking_reason=None,
            evaluated_at=datetime.utcnow(),
            evaluation_id=None,
        )
        ms = EngineEvidence(
            engine="market_structure_engine",
            score=68.0,
            direction="BEARISH",
            verdict="BEARISH_TREND",
            confidence=0.8,
            evidence={},
            warnings=[],
            blocking=False,
            blocking_reason=None,
            evaluated_at=datetime.utcnow(),
            evaluation_id=None,
        )
        ctx = ContextEvidence(
            context_type="NORMAL_TRADING_DAY",
            context_confidence=0.9,
            secondary_context=None,
            ist_time_str="10:30",
            ist_date_str="2026-05-27",
            day_of_week="WEDNESDAY",
            is_expiry_day=False,
            is_monthly_expiry=False,
            days_to_expiry=1,
            opening_gap_pct=0.0,
            vix_value=15.0,
            vix_vs_20day_avg_pct=0.0,
            previous_day_range_pct=1.2,
            is_known_event_day=False,
            known_event_name=None,
            data_quality_status="CLEAN",
            confidence_modifier=0.0,
            context_summary="",
            evaluated_at=datetime.utcnow(),
            evaluation_id=None,
        )

        match = self.matcher.safe_match(self.db, oc, ms, ctx, evaluation_id="test-eval-id")
        log_setup_match(self.db, match, signal_id="test-sig-id", signal_v2_decision="PE")

        log = self.db.query(SetupMatchLog).filter(SetupMatchLog.evaluation_id == "test-eval-id").first()
        self.assertIsNotNone(log)
        self.assertEqual(log.setup_name, SetupName.PE_BREAKDOWN_CONTINUATION)
        self.assertEqual(log.signal_id, "test-sig-id")
        self.assertEqual(log.signal_v2_decision, "PE")

    def test_13_no_setup_found_when_all_setups_blocked_by_context(self):
        oc = EngineEvidence(
            engine="option_chain_engine",
            score=74.0,
            direction="BEARISH",
            verdict="PE_STRONG",
            confidence=0.8,
            evidence={},
            warnings=[],
            blocking=False,
            blocking_reason=None,
            evaluated_at=datetime.utcnow(),
            evaluation_id=None,
        )
        ms = EngineEvidence(
            engine="market_structure_engine",
            score=68.0,
            direction="BEARISH",
            verdict="BEARISH_TREND",
            confidence=0.8,
            evidence={},
            warnings=[],
            blocking=False,
            blocking_reason=None,
            evaluated_at=datetime.utcnow(),
            evaluation_id=None,
        )
        ctx = ContextEvidence(
            context_type="STALE_DATA_DAY",
            context_confidence=0.9,
            secondary_context=None,
            ist_time_str="10:30",
            ist_date_str="2026-05-27",
            day_of_week="WEDNESDAY",
            is_expiry_day=False,
            is_monthly_expiry=False,
            days_to_expiry=1,
            opening_gap_pct=0.0,
            vix_value=15.0,
            vix_vs_20day_avg_pct=0.0,
            previous_day_range_pct=1.2,
            is_known_event_day=False,
            known_event_name=None,
            data_quality_status="STALE",
            confidence_modifier=0.0,
            context_summary="",
            evaluated_at=datetime.utcnow(),
            evaluation_id=None,
        )

        match = self.matcher.safe_match(self.db, oc, ms, ctx)
        self.assertFalse(match.matched)
        self.assertEqual(match.setup_name, SetupName.NO_SETUP_FOUND)

    def test_14_condition_evaluator_operators(self):
        oc_dict = {"direction": "BEARISH", "verdict": "PE_STRONG", "score": 74.0}
        ms_dict = {"direction": "BEARISH", "verdict": "BEARISH_TREND", "score": 68.0}
        ctx_dict = {"context_type": "NORMAL_TRADING_DAY", "data_quality_status": "CLEAN"}

        # eq operator
        cond_eq = {"engine": "market_structure_engine", "field": "direction", "operator": "eq", "value": "BEARISH", "description": "test"}
        res = evaluate_condition(cond_eq, oc_dict, ms_dict, ctx_dict)
        self.assertTrue(res.passed)

        # neq operator
        cond_neq = {"engine": "market_structure_engine", "field": "direction", "operator": "neq", "value": "BULLISH", "description": "test"}
        res = evaluate_condition(cond_neq, oc_dict, ms_dict, ctx_dict)
        self.assertTrue(res.passed)

        # in operator
        cond_in = {"engine": "option_chain_engine", "field": "verdict", "operator": "in", "value": ["PE_STRONG", "CE_STRONG"], "description": "test"}
        res = evaluate_condition(cond_in, oc_dict, ms_dict, ctx_dict)
        self.assertTrue(res.passed)

        # gte operator
        cond_gte = {"engine": "option_chain_engine", "field": "score", "operator": "gte", "value": 60, "description": "test"}
        res = evaluate_condition(cond_gte, oc_dict, ms_dict, ctx_dict)
        self.assertTrue(res.passed)

        # lte operator
        cond_lte = {"engine": "market_structure_engine", "field": "score", "operator": "lte", "value": 70, "description": "test"}
        res = evaluate_condition(cond_lte, oc_dict, ms_dict, ctx_dict)
        self.assertTrue(res.passed)

        # field not found
        cond_missing = {"engine": "option_chain_engine", "field": "nonexistent", "operator": "eq", "value": "value", "description": "test"}
        res = evaluate_condition(cond_missing, oc_dict, ms_dict, ctx_dict)
        self.assertFalse(res.passed)
        self.assertEqual(res.actual_value, "FIELD_NOT_FOUND")

    def test_15_current_setup_evidence_includes_optional_momentum(self):
        now = datetime.utcnow()
        self.db.add_all(
            [
                SpecialistEngineLog(
                    evaluation_id="eval-current",
                    created_at=now,
                    engine_name="option_chain_engine",
                    score=74.0,
                    direction="BEARISH",
                    verdict="PE_STRONG",
                    confidence=0.8,
                    blocking=False,
                    evidence_json="{}",
                    warnings_json="[]",
                    evaluated_at=now,
                ),
                SpecialistEngineLog(
                    evaluation_id="eval-current",
                    created_at=now,
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
                SpecialistEngineLog(
                    evaluation_id="eval-current",
                    created_at=now,
                    engine_name="nifty_momentum_engine",
                    score=50.0,
                    direction="NEUTRAL",
                    verdict="REVERSAL_RISK",
                    confidence=0.6,
                    blocking=False,
                    evidence_json="{}",
                    warnings_json="[]",
                    evaluated_at=now,
                ),
                ContextClassificationLog(
                    evaluation_id="eval-current",
                    created_at=now,
                    context_type="NORMAL_TRADING_DAY",
                    context_confidence=0.8,
                    data_quality_status="CLEAN",
                    confidence_modifier=0.0,
                ),
            ]
        )
        self.db.commit()

        evidence = _latest_evidence(self.db, window_seconds=300)

        self.assertIsNotNone(evidence)
        self.assertEqual(len(evidence), 4)
        self.assertIsNotNone(evidence[3])
        self.assertEqual(evidence[3].verdict, "REVERSAL_RISK")


if __name__ == "__main__":
    unittest.main()
