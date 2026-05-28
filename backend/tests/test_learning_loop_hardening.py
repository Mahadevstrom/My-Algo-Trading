import os
import sys
import unittest
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

backend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.database import Base
from app.engine.decision.models import DecisionEngineV2Log
from app.engine.setup.models import SetupMatchLog
from app.engine.specialist.label_importer import _process_rows
from app.engine.specialist.models import SpecialistEngineLog
from app.schemas.live_paper import LivePaperEvaluateRequest
from app.schemas.signal_v2 import SignalV2Result
from app.services.live_paper_simulator_service import get_live_paper_simulator_service


class TestLearningLoopHardening(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(bind=self.engine)
        self.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)
        self.db = self.SessionLocal()

    def tearDown(self):
        self.db.close()

    def test_label_import_propagates_outcome_to_all_learning_logs(self):
        now = datetime.utcnow()
        for engine_name, direction in [
            ("option_chain_engine", "BEARISH"),
            ("market_structure_engine", "BEARISH"),
            ("nifty_momentum_engine", "BEARISH"),
        ]:
            self.db.add(
                SpecialistEngineLog(
                    evaluation_id="eval-learn",
                    engine_name=engine_name,
                    score=70.0,
                    direction=direction,
                    verdict="TEST",
                    confidence=0.8,
                    blocking=False,
                    evidence_json="{}",
                    warnings_json="[]",
                    evaluated_at=now,
                    signal_engine_v2_decision="PE",
                )
            )
        self.db.add(
            SetupMatchLog(
                evaluation_id="eval-learn",
                setup_name="PE_BREAKDOWN_CONTINUATION",
                matched=True,
                match_confidence=0.72,
                direction_implied="PE",
                required_pass_count=3,
                required_total=3,
                supporting_pass_count=2,
                supporting_total=3,
                context_type="NORMAL_TRADING_DAY",
                context_modifier=0.0,
                context_effect="NEUTRAL",
                match_summary="test",
                evidence_json="{}",
                signal_v2_decision="PE",
            )
        )
        self.db.add(
            DecisionEngineV2Log(
                evaluation_id="eval-learn",
                decision="PE",
                advisory_mode="SHADOW",
                confidence=0.8,
                setup_name="PE_BREAKDOWN_CONTINUATION",
                setup_matched=True,
                setup_confidence=0.72,
                context_type="NORMAL_TRADING_DAY",
                context_modifier=0.0,
                agreement_score=1.0,
                signal_v2_decision="PE",
                agrees_with_signal_v2=True,
                would_block_signal_v2_trade=False,
                would_take_trade_when_v2_waited=False,
                reasoning="test",
                reason_codes_json="[]",
                warnings_json="[]",
                evidence_json="{}",
            )
        )
        self.db.commit()

        result = _process_rows(
            self.db,
            [
                {
                    "evaluation_id": "eval-learn",
                    "direction": "PE",
                    "result": "WIN",
                    "action_taken": "TAKEN",
                }
            ],
        )

        self.assertEqual(result["matched_to_engine_logs"], 1)
        logs = self.db.query(SpecialistEngineLog).filter(SpecialistEngineLog.evaluation_id == "eval-learn").all()
        self.assertEqual({row.market_result for row in logs}, {"PE_WIN"})
        self.assertTrue(all(row.comparison_verdict in {"AGREEMENT", "ENGINE_BETTER"} for row in logs))
        setup_log = self.db.query(SetupMatchLog).filter(SetupMatchLog.evaluation_id == "eval-learn").first()
        decision_log = self.db.query(DecisionEngineV2Log).filter(DecisionEngineV2Log.evaluation_id == "eval-learn").first()
        self.assertEqual(setup_log.market_result, "PE_WIN")
        self.assertTrue(setup_log.outcome_correct)
        self.assertEqual(decision_log.market_result, "PE_WIN")
        self.assertTrue(decision_log.decision_v2_correct)

    async def test_live_paper_evaluate_once_uses_one_shadow_evaluation_id(self):
        service = get_live_paper_simulator_service()
        signal = SignalV2Result(
            id=123,
            symbol="NIFTY",
            underlying="NIFTY",
            decision="NO_TRADE",
            confidence="LOW",
            score=0.0,
            signal_type="NO_TRADE",
            data_quality_gate_passed=False,
            failed_checks=["TEST"],
        )

        async def fake_generate(_db, _request):
            return signal

        async def fake_async_shadow(**kwargs):
            captured_ids.append(kwargs["evaluation_id"])
            return SimpleNamespace(
                evaluation_id=kwargs["evaluation_id"],
                engine_name="shadow",
                verdict="TEST",
                score=50.0,
            )

        def fake_context_shadow(**kwargs):
            captured_ids.append(kwargs["evaluation_id"])
            return SimpleNamespace(
                evaluation_id=kwargs["evaluation_id"],
                context_type="NORMAL_TRADING_DAY",
                context_confidence=0.8,
                confidence_modifier=0.0,
            )

        def fake_setup_shadow(**kwargs):
            captured_ids.append(kwargs["evaluation_id"])

        def fake_decision_shadow(**kwargs):
            captured_ids.append(kwargs["evaluation_id"])
            return SimpleNamespace(
                evaluation_id=kwargs["evaluation_id"],
                decision="WAIT",
                confidence=0.8,
                agrees_with_signal_v2=True,
                advisory_mode="SHADOW",
            )

        captured_ids: list[str] = []
        with (
            patch(
                "app.services.live_paper_simulator_service.get_signal_engine_v2",
                return_value=SimpleNamespace(generate=fake_generate),
            ),
            patch("app.engine.specialist.option_chain_engine.run_option_chain_shadow", new=AsyncMock(side_effect=fake_async_shadow)),
            patch("app.engine.context.context_classifier.run_context_shadow", side_effect=fake_context_shadow),
            patch("app.engine.specialist.market_structure_engine.run_market_structure_shadow", new=AsyncMock(side_effect=fake_async_shadow)),
            patch("app.engine.specialist.nifty_momentum_engine.run_nifty_momentum_shadow", new=AsyncMock(side_effect=fake_async_shadow)),
            patch("app.engine.setup.setup_shadow_runner.run_setup_matcher_shadow", side_effect=fake_setup_shadow),
            patch("app.engine.decision.decision_engine_v2.run_decision_engine_v2_shadow", side_effect=fake_decision_shadow),
        ):
            result = await service.evaluate_once(
                self.db,
                LivePaperEvaluateRequest(underlying="NIFTY", dry_run=True),
            )

        audit_payload = result["entry"]
        self.assertFalse(audit_payload["entry_allowed"])
        self.assertEqual(len(set(captured_ids)), 1)


if __name__ == "__main__":
    unittest.main()
