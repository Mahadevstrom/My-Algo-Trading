import os
import sys
import json
import unittest
from datetime import datetime, timezone, timedelta
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# Add backend directory to path
backend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from app.main import app
from app.db.database import Base, get_db
from app.models.trade import PaperTrade
from app.agent_evolution.models import AgentEvolutionRecommendation
from app.agent_evolution.analyzer import run_analysis
from app.agent_evolution.recommendation_engine import generate_recommendations
from app.config import settings

class TestAgentEvolution(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)

    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(bind=self.engine)
        self.TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)
        self.db = self.TestingSessionLocal()

        def override_get_db():
            db = self.TestingSessionLocal()
            try:
                yield db
            finally:
                db.close()

        app.dependency_overrides[get_db] = override_get_db

        # Save original settings
        self.orig_enabled = settings.enable_agent_evolution_engine
        self.orig_auto_apply = settings.agent_evolution_auto_apply
        
        # Reset settings to default test values
        settings.enable_agent_evolution_engine = True
        settings.agent_evolution_auto_apply = False

    def tearDown(self):
        # Restore settings
        settings.enable_agent_evolution_engine = self.orig_enabled
        settings.agent_evolution_auto_apply = self.orig_auto_apply
        
        app.dependency_overrides.pop(get_db, None)
        self.db.query(PaperTrade).delete()
        self.db.query(AgentEvolutionRecommendation).delete()
        self.db.commit()
        self.db.close()
        Base.metadata.drop_all(bind=self.engine)
        self.engine.dispose()

    def _create_test_trade(self, symbol, result, confidence, pnl, regime="UNKNOWN", has_birth_cert=True, filters_count=6):
        trade = PaperTrade(
            symbol=symbol,
            instrument_type="INDEX_OPTION",
            exchange="NSE",
            direction="BUY",
            entry_price=100.0,
            quantity=15,
            status="CLOSED",
            result=result,
            pnl=pnl,
            exit_time=datetime.now(timezone.utc),
            confidence_score_at_entry=confidence,
            birth_cert_version="1.0" if has_birth_cert else None,
            regime_at_entry=regime,
            filters_passed_count=filters_count,
            filter_states_json=json.dumps({
                "trend_filter": {"passed": True, "score": 0.8},
                "momentum_filter": {"passed": True, "score": 0.7},
                "volatility_filter": {"passed": True, "score": 0.6}
            }),
            data_source="MOCK"
        )
        self.db.add(trade)
        self.db.commit()
        self.db.refresh(trade)
        return trade

    def test_1_status_endpoint_returns_correct_shape(self):
        """Test 1: Status endpoint returns correct shape"""
        response = self.client.get("/api/agent-evolution/status")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("enabled", data)
        self.assertIn("auto_apply", data)
        self.assertIn("pending_count", data)
        self.assertIn("config", data)

    def test_2_auto_apply_is_always_false_in_status_response(self):
        """Test 2: auto_apply is always False in status response even if config set to True"""
        settings.agent_evolution_auto_apply = True
        response = self.client.get("/api/agent-evolution/status")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertFalse(data["auto_apply"])

    def test_3_run_analysis_returns_insufficient_data_cleanly(self):
        """Test 3: run-analysis returns INSUFFICIENT_DATA cleanly on empty DB"""
        response = self.client.post("/api/agent-evolution/run-analysis")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["status"], "INSUFFICIENT_DATA")
        self.assertIn("Not enough closed trades", data["message"])
        
        # Verify no recommendations created
        count = self.db.query(AgentEvolutionRecommendation).count()
        self.assertEqual(count, 0)

    def test_4_chop_trap_pattern_generates_recommendation(self):
        """Test 4: Chop trap pattern generates recommendation"""
        # Create 10 SIDEWAYS trades (3 WIN, 7 LOSS) to satisfy min_trades=10
        for i in range(3):
            self._create_test_trade(f"TEST_AE_W_{i}", "WIN", 75.0, 500.0, regime="SIDEWAYS")
        for i in range(7):
            self._create_test_trade(f"TEST_AE_L_{i}", "LOSS", 75.0, -300.0, regime="SIDEWAYS")
            
        report = run_analysis(self.db, min_trades=10)
        self.assertEqual(report["status"], "OK")
        
        # Check that CHOP_TRAP is detected
        patterns = report["failure_patterns"]
        self.assertTrue(any(p["pattern"] == "CHOP_TRAP" for p in patterns))
        
        # Generate recommendations
        recs = generate_recommendations(self.db, report, report["run_id"])
        self.assertTrue(any(r.recommendation_type == "REGIME_THRESHOLD_CHANGE" for r in recs))
        self.assertTrue(any("signal_engine" in r.affected_module for r in recs))

    def test_5_deduplication_works(self):
        """Test 5: Deduplication works"""
        # Setup: Pre-populate PENDING recommendation
        rec = AgentEvolutionRecommendation(
            recommendation_type="REGIME_THRESHOLD_CHANGE",
            affected_module="signal_engine_v2",
            issue_detected="Sideways chop trap",
            evidence_summary="3 wins, 7 losses",
            suggested_change="Raise floor",
            expected_benefit="Fewer chop losses",
            risk_level="LOW",
            confidence=0.85,
            status="PENDING",
            run_id="old-run-id"
        )
        self.db.add(rec)
        self.db.commit()
        
        # Create 10 SIDEWAYS trades (3 WIN, 7 LOSS) to trigger CHOP_TRAP recommendation
        for i in range(3):
            self._create_test_trade(f"TEST_AE_W_{i}", "WIN", 75.0, 500.0, regime="SIDEWAYS")
        for i in range(7):
            self._create_test_trade(f"TEST_AE_L_{i}", "LOSS", 75.0, -300.0, regime="SIDEWAYS")
            
        report = run_analysis(self.db, min_trades=10)
        recs = generate_recommendations(self.db, report, report["run_id"])
        
        # Recommendation of type REGIME_THRESHOLD_CHANGE for signal_engine_v2 should be skipped due to PENDING duplicate
        dups = [r for r in recs if r.recommendation_type == "REGIME_THRESHOLD_CHANGE" and r.affected_module == "signal_engine_v2"]
        self.assertEqual(len(dups), 0)

    def test_6_review_endpoint_approve_works(self):
        """Test 6: Review endpoint — approve works"""
        rec = AgentEvolutionRecommendation(
            recommendation_type="SESSION_WINDOW_ADJUSTMENT",
            affected_module="session_gate",
            issue_detected="Midday weakness",
            evidence_summary="Midday win rate lower",
            suggested_change="Adjust session rules",
            expected_benefit="Improve midday outcome",
            risk_level="LOW",
            confidence=0.80,
            status="PENDING"
        )
        self.db.add(rec)
        self.db.commit()
        self.db.refresh(rec)
        
        response = self.client.post(
            f"/api/agent-evolution/recommendations/{rec.id}/review",
            json={"status": "APPROVED", "note": "Verified by trader"}
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["status"], "APPROVED")
        self.assertEqual(data["review_note"], "Verified by trader")
        self.assertIsNotNone(data["reviewed_at"])
        
        # Ensure database is updated
        self.db.expire_all()
        db_rec = self.db.get(AgentEvolutionRecommendation, rec.id)
        self.assertEqual(db_rec.status, "APPROVED")

    def test_7_review_endpoint_cannot_rereview_approved_rec(self):
        """Test 7: Review endpoint — cannot re-review approved rec"""
        rec = AgentEvolutionRecommendation(
            recommendation_type="SESSION_WINDOW_ADJUSTMENT",
            affected_module="session_gate",
            issue_detected="Midday weakness",
            evidence_summary="Midday win rate lower",
            suggested_change="Adjust session rules",
            expected_benefit="Improve midday outcome",
            risk_level="LOW",
            confidence=0.80,
            status="APPROVED",
            reviewed_by="USER"
        )
        self.db.add(rec)
        self.db.commit()
        self.db.refresh(rec)
        
        response = self.client.post(
            f"/api/agent-evolution/recommendations/{rec.id}/review",
            json={"status": "REJECTED", "note": "Changed mind"}
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("already been reviewed", response.json()["detail"])
        
        # Verify status remained APPROVED
        db_rec = self.db.get(AgentEvolutionRecommendation, rec.id)
        self.assertEqual(db_rec.status, "APPROVED")

    def test_8_recommendations_list_pagination_works(self):
        """Test 8: Recommendations list pagination works"""
        # Create 10 PENDING recommendations
        for i in range(10):
            rec = AgentEvolutionRecommendation(
                recommendation_type=f"REC_TYPE_{i}",
                affected_module="signal_engine_v2",
                issue_detected="Failing setup",
                evidence_summary="Trade details",
                suggested_change="Tune parameters",
                expected_benefit="More profit",
                risk_level="LOW",
                confidence=0.50 + i * 0.05,
                status="PENDING"
            )
            self.db.add(rec)
        self.db.commit()
        
        # Limit = 5, offset = 0
        resp_1 = self.client.get("/api/agent-evolution/recommendations?status=PENDING&limit=5&offset=0")
        self.assertEqual(resp_1.status_code, 200)
        data_1 = resp_1.json()
        self.assertEqual(len(data_1), 5)
        
        # Limit = 5, offset = 5
        resp_2 = self.client.get("/api/agent-evolution/recommendations?status=PENDING&limit=5&offset=5")
        self.assertEqual(resp_2.status_code, 200)
        data_2 = resp_2.json()
        self.assertEqual(len(data_2), 5)
        
        # Verify distinct elements in both pages
        ids_1 = {r["id"] for r in data_1}
        ids_2 = {r["id"] for r in data_2}
        self.assertTrue(ids_1.isdisjoint(ids_2))

    def test_9_paper_trade_count_unchanged_after_full_run(self):
        """Test 9: Paper trade count unchanged after full run"""
        for i in range(10):
            self._create_test_trade(f"TEST_AE_W_{i}", "WIN", 75.0, 100.0)
            
        # Record count before
        from sqlalchemy import func
        count_before = self.db.scalar(select(func.count()).select_from(PaperTrade))
        
        # Run run-analysis and get recommendations
        self.client.post("/api/agent-evolution/run-analysis")
        self.client.get("/api/agent-evolution/recommendations")
        
        # Record count after
        count_after = self.db.scalar(select(func.count()).select_from(PaperTrade))
        self.assertEqual(count_before, count_after)

    def test_10_run_analysis_respects_enable_flag(self):
        """Test 10: run-analysis respects ENABLE flag"""
        settings.enable_agent_evolution_engine = False
        response = self.client.post("/api/agent-evolution/run-analysis")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["status"], "DISABLED")
        self.assertIn("is disabled", data["message"])
        
        # Verify no recommendations created
        count = self.db.query(AgentEvolutionRecommendation).count()
        self.assertEqual(count, 0)

from sqlalchemy import select

if __name__ == "__main__":
    unittest.main()
