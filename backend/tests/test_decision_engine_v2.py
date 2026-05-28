import json
import os
import sys
import unittest
from datetime import datetime, timedelta

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

backend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from app.config import settings
from app.db.database import Base, get_db
from app.engine.context.models import ContextClassificationLog
from app.engine.decision.decision_engine_v2 import DecisionEngineV2, latest_decision_inputs
from app.engine.decision.decision_evidence import DecisionEngineV2Evidence
from app.engine.decision.decision_logger import log_decision_engine_v2, update_decision_engine_outcome
from app.engine.decision.models import DecisionEngineV2Log
from app.engine.decision.routes import router as decision_router
from app.engine.setup.models import SetupMatchLog
from app.engine.specialist.models import SpecialistEngineLog
from app.models.trade import PaperTrade


class TestDecisionEngineV2(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(bind=self.engine)
        self.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)
        self.db = self.SessionLocal()
        self.original = {
            "enable_decision_engine_v2": settings.enable_decision_engine_v2,
            "decision_engine_v2_mode": settings.decision_engine_v2_mode,
            "decision_engine_v2_evidence_window_seconds": settings.decision_engine_v2_evidence_window_seconds,
            "decision_engine_v2_min_confidence": settings.decision_engine_v2_min_confidence,
        }
        settings.enable_decision_engine_v2 = True
        settings.decision_engine_v2_mode = "SHADOW"
        settings.decision_engine_v2_evidence_window_seconds = 300
        settings.decision_engine_v2_min_confidence = 0.62

    def tearDown(self):
        for key, value in self.original.items():
            setattr(settings, key, value)
        self.db.close()

    def test_1_pe_recommendation_when_engines_align(self):
        self._seed_latest(
            oc_direction="BEARISH",
            ms_direction="BEARISH",
            momentum_direction="BEARISH",
            context_type="NORMAL_TRADING_DAY",
            setup_name="PE_BREAKDOWN_CONTINUATION",
            setup_direction="PE",
            setup_matched=True,
            setup_confidence=0.72,
            signal_v2_decision="PE",
        )

        decision = DecisionEngineV2().safe_decide(self.db, signal_v2_decision="PE")

        self.assertEqual(decision.decision, "PE")
        self.assertTrue(decision.agrees_with_signal_v2)
        self.assertGreaterEqual(decision.confidence, 0.62)
        self.assertIn("MULTI_ENGINE_ALIGNMENT", decision.reason_codes)

    def test_2_stale_context_forces_wait_advisory(self):
        self._seed_latest(context_type="STALE_DATA_DAY", signal_v2_decision="PE")

        decision = DecisionEngineV2().safe_decide(self.db, signal_v2_decision="PE")

        self.assertEqual(decision.decision, "WAIT")
        self.assertTrue(decision.would_block_signal_v2_trade)
        self.assertIn("CONTEXT_BLOCK_STALE_DATA_DAY", decision.reason_codes)

    def test_3_momentum_reversal_adds_penalty_warning(self):
        self._seed_latest(
            oc_direction="BEARISH",
            ms_direction="BEARISH",
            momentum_direction="BULLISH",
            momentum_verdict="REVERSAL_RISK",
            setup_direction="PE",
            setup_confidence=0.68,
        )

        decision = DecisionEngineV2().safe_decide(self.db, signal_v2_decision="PE")

        self.assertIn("MOMENTUM_PENALTY", decision.reason_codes)
        self.assertTrue(any("Momentum" in warning for warning in decision.warnings))

    def test_4_insufficient_data_returns_wait(self):
        decision = DecisionEngineV2().safe_decide(self.db, signal_v2_decision="CE")

        self.assertEqual(decision.decision, "WAIT")
        self.assertEqual(decision.setup_name, "INSUFFICIENT_ENGINE_DATA")
        self.assertTrue(decision.would_block_signal_v2_trade)

    def test_5_logger_saves_row_without_paper_trade_change(self):
        before_trades = self.db.scalar(func.count(PaperTrade.id)) or 0
        decision = DecisionEngineV2Evidence(
            decision="WAIT",
            advisory_mode="SHADOW",
            confidence=0.5,
            setup_name="NO_SETUP_FOUND",
            setup_matched=False,
            setup_confidence=0.0,
            context_type="NORMAL_TRADING_DAY",
            context_modifier=0.0,
            engine_votes={},
            agreement_score=0.0,
            signal_v2_decision="PE",
            agrees_with_signal_v2=False,
            would_block_signal_v2_trade=True,
            would_take_trade_when_v2_waited=False,
            reason_codes=["TEST"],
            warnings=[],
            reasoning="test",
            evidence={},
            evaluated_at=datetime.utcnow(),
            evaluation_id="eval-1",
        )

        row = log_decision_engine_v2(self.db, decision, signal_id="sig-1", signal_v2_decision="PE")
        after_trades = self.db.scalar(func.count(PaperTrade.id)) or 0

        self.assertIsNotNone(row)
        self.assertEqual(before_trades, after_trades)
        self.assertEqual(row.decision, "WAIT")

    def test_6_outcome_update_marks_decision_v2_better(self):
        decision = DecisionEngineV2Evidence(
            decision="WAIT",
            advisory_mode="SHADOW",
            confidence=0.8,
            setup_name="NO_SETUP_FOUND",
            setup_matched=False,
            setup_confidence=0.0,
            context_type="STALE_DATA_DAY",
            context_modifier=0.2,
            engine_votes={},
            agreement_score=0.0,
            signal_v2_decision="PE",
            agrees_with_signal_v2=False,
            would_block_signal_v2_trade=True,
            would_take_trade_when_v2_waited=False,
            reason_codes=["TEST"],
            warnings=[],
            reasoning="test",
            evidence={},
            evaluated_at=datetime.utcnow(),
            evaluation_id="eval-outcome",
        )
        log_decision_engine_v2(self.db, decision, signal_id="sig-1", signal_v2_decision="PE")

        update_decision_engine_outcome(self.db, "eval-outcome", "NO_TRADE_CORRECT")
        row = self.db.query(DecisionEngineV2Log).filter(DecisionEngineV2Log.evaluation_id == "eval-outcome").first()

        self.assertTrue(row.decision_v2_correct)
        self.assertFalse(row.signal_v2_correct)
        self.assertEqual(row.comparison_verdict, "DECISION_V2_BETTER")

    def test_7_current_endpoint_returns_shape(self):
        self._seed_latest()
        app = FastAPI()
        app.include_router(decision_router, prefix="/api/decision-v2")

        def override_db():
            try:
                yield self.db
            finally:
                pass

        app.dependency_overrides[get_db] = override_db
        client = TestClient(app)

        response = client.get("/api/decision-v2/current")

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["ok"])
        self.assertIn("decision", data)
        self.assertIn(data["decision"]["decision"], ["CE", "PE", "WAIT"])

    def test_8_comparison_endpoint_handles_zero_labels(self):
        app = FastAPI()
        app.include_router(decision_router, prefix="/api/decision-v2")

        def override_db():
            try:
                yield self.db
            finally:
                pass

        app.dependency_overrides[get_db] = override_db
        client = TestClient(app)

        response = client.get("/api/decision-v2/comparison")

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["ok"])
        self.assertEqual(data["labelled_count"], 0)
        self.assertIn("insight", data)

    def test_9_evaluation_id_keeps_decision_inputs_together(self):
        self._seed_latest(
            evaluation_id="eval-pe",
            oc_direction="BEARISH",
            ms_direction="BEARISH",
            momentum_direction="BEARISH",
            setup_direction="PE",
            setup_confidence=0.72,
            signal_v2_decision="PE",
        )
        self._seed_latest(
            evaluation_id="eval-ce",
            oc_direction="BULLISH",
            ms_direction="BULLISH",
            momentum_direction="BULLISH",
            setup_name="CE_BREAKOUT_CONTINUATION",
            setup_direction="CE",
            setup_confidence=0.72,
            signal_v2_decision="CE",
            created_at=datetime.utcnow() + timedelta(seconds=5),
        )

        inputs = latest_decision_inputs(self.db, evaluation_id="eval-pe")
        decision = DecisionEngineV2().safe_decide(
            self.db,
            signal_v2_decision="PE",
            evaluation_id="eval-pe",
        )

        self.assertIsNotNone(inputs)
        self.assertEqual(inputs[0].evaluation_id, "eval-pe")
        self.assertEqual(inputs[1].evaluation_id, "eval-pe")
        self.assertEqual(inputs[2].evaluation_id, "eval-pe")
        self.assertEqual(inputs[3].evaluation_id, "eval-pe")
        self.assertEqual(inputs[4].evaluation_id, "eval-pe")
        self.assertEqual(decision.decision, "PE")

    def _seed_latest(
        self,
        oc_direction: str = "BEARISH",
        ms_direction: str = "BEARISH",
        momentum_direction: str = "BEARISH",
        momentum_verdict: str = "BEARISH_CONTINUATION",
        context_type: str = "NORMAL_TRADING_DAY",
        setup_name: str = "PE_BREAKDOWN_CONTINUATION",
        setup_direction: str = "PE",
        setup_matched: bool = True,
        setup_confidence: float = 0.72,
        signal_v2_decision: str = "PE",
        evaluation_id: str = "eval-shared",
        created_at: datetime | None = None,
    ) -> None:
        now = created_at or datetime.utcnow()
        self.db.add_all(
            [
                SpecialistEngineLog(
                    evaluation_id=evaluation_id,
                    created_at=now,
                    engine_name="option_chain_engine",
                    score=74.0,
                    direction=oc_direction,
                    verdict="PE_STRONG" if oc_direction == "BEARISH" else "CE_STRONG",
                    confidence=0.8,
                    blocking=False,
                    evidence_json=json.dumps({}),
                    warnings_json=json.dumps([]),
                    evaluated_at=now,
                    signal_engine_v2_decision=signal_v2_decision,
                ),
                SpecialistEngineLog(
                    evaluation_id=evaluation_id,
                    created_at=now,
                    engine_name="market_structure_engine",
                    score=68.0,
                    direction=ms_direction,
                    verdict="BEARISH_TREND" if ms_direction == "BEARISH" else "BULLISH_TREND",
                    confidence=0.8,
                    blocking=False,
                    evidence_json=json.dumps({}),
                    warnings_json=json.dumps([]),
                    evaluated_at=now,
                    signal_engine_v2_decision=signal_v2_decision,
                ),
                SpecialistEngineLog(
                    evaluation_id=evaluation_id,
                    created_at=now,
                    engine_name="nifty_momentum_engine",
                    score=65.0,
                    direction=momentum_direction,
                    verdict=momentum_verdict,
                    confidence=0.75,
                    blocking=False,
                    evidence_json=json.dumps({}),
                    warnings_json=json.dumps([]),
                    evaluated_at=now,
                    signal_engine_v2_decision=signal_v2_decision,
                ),
                ContextClassificationLog(
                    evaluation_id=evaluation_id,
                    created_at=now,
                    context_type=context_type,
                    context_confidence=0.8,
                    data_quality_status="STALE" if context_type == "STALE_DATA_DAY" else "CLEAN",
                    confidence_modifier=0.2 if context_type == "STALE_DATA_DAY" else 0.0,
                    signal_v2_decision=signal_v2_decision,
                ),
                SetupMatchLog(
                    evaluation_id=evaluation_id,
                    created_at=now,
                    setup_name=setup_name,
                    matched=setup_matched,
                    match_confidence=setup_confidence,
                    direction_implied=setup_direction,
                    required_pass_count=3,
                    required_total=3,
                    supporting_pass_count=2,
                    supporting_total=3,
                    context_type=context_type,
                    context_modifier=0.0,
                    context_effect="NEUTRAL",
                    match_summary="test setup",
                    evidence_json=json.dumps({}),
                    signal_v2_decision=signal_v2_decision,
                ),
            ]
        )
        self.db.commit()


if __name__ == "__main__":
    unittest.main()
