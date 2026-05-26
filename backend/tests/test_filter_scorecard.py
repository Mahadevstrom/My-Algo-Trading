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
from app.analytics.filter_contribution_scorer import calculate_filter_scorecard

class TestFilterContributionScorer(unittest.TestCase):
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

        # Default 8 filters with passed=False
        self.default_states = {
            "trend_filter": {"passed": False, "score": 0.0},
            "momentum_filter": {"passed": False, "score": 0.0},
            "chop_filter": {"passed": False, "score": 0.0},
            "volatility_filter": {"passed": False, "score": 0.0},
            "time_filter": {"passed": False, "score": 0.0},
            "market_flow_filter": {"passed": False, "score": 0.0},
            "liquidity_filter": {"passed": False, "score": 0.0},
            "option_chain_filter": {"passed": False, "score": 0.0}
        }

    def tearDown(self):
        app.dependency_overrides.pop(get_db, None)
        self.db.query(PaperTrade).delete()
        self.db.commit()
        self.db.close()
        Base.metadata.drop_all(bind=self.engine)
        self.engine.dispose()

    def _create_test_trade_with_filters(self, symbol, result, filter_states, regime="UNKNOWN", exit_time=None, raw_json=None):
        if exit_time is None:
            exit_time = datetime.now(timezone.utc)
        if raw_json is None:
            raw_json = json.dumps(filter_states)
            
        trade = PaperTrade(
            symbol=symbol,
            instrument_type="INDEX_OPTION",
            exchange="NSE",
            direction="BUY",
            entry_price=100.0,
            quantity=15,
            status="CLOSED",
            result=result,
            pnl=100.0 if result == "WIN" else (-100.0 if result == "LOSS" else 0.0),
            exit_time=exit_time,
            filter_states_json=raw_json,
            birth_cert_version="1.0",
            regime_at_entry=regime,
            data_source="MOCK"
        )
        self.db.add(trade)
        self.db.commit()
        self.db.refresh(trade)
        return trade

    def test_1_insufficient_data(self):
        """Test 1: Insufficient data"""
        for i in range(5):
            self._create_test_trade_with_filters(f"TEST_FS_{i}", "WIN", self.default_states)
            
        result = calculate_filter_scorecard(self.db, min_trades=15)
        self.assertEqual(result["status"], "INSUFFICIENT_DATA")
        self.assertEqual(result["trades_needed"], 10)
        self.assertEqual(result["min_required"], 15)

    def test_2_high_value_filter_detection(self):
        """Test 2: High-value filter detection"""
        # trend_filter passed in 9 of 10 wins (90%)
        # trend_filter passed in 4 of 10 losses (40%)
        # edge_score = 90 - 40 = 50.0
        
        # wins
        for i in range(9):
            states = self.default_states.copy()
            states["trend_filter"] = {"passed": True, "score": 0.8}
            self._create_test_trade_with_filters(f"TEST_FS_W_P_{i}", "WIN", states)
        for i in range(1):
            states = self.default_states.copy()
            states["trend_filter"] = {"passed": False, "score": 0.2}
            self._create_test_trade_with_filters(f"TEST_FS_W_NP_{i}", "WIN", states)
            
        # losses
        for i in range(4):
            states = self.default_states.copy()
            states["trend_filter"] = {"passed": True, "score": 0.8}
            self._create_test_trade_with_filters(f"TEST_FS_L_P_{i}", "LOSS", states)
        for i in range(6):
            states = self.default_states.copy()
            states["trend_filter"] = {"passed": False, "score": 0.2}
            self._create_test_trade_with_filters(f"TEST_FS_L_NP_{i}", "LOSS", states)
            
        result = calculate_filter_scorecard(self.db, min_trades=20)
        self.assertEqual(result["status"], "OK")
        
        trend_f = next((f for f in result["filters"] if f["filter_name"] == "trend_filter"), None)
        self.assertIsNotNone(trend_f)
        self.assertEqual(trend_f["edge_score"], 50.0)
        self.assertEqual(trend_f["verdict"], "HIGH_VALUE")

    def test_3_harmful_filter_detection(self):
        """Test 3: Harmful filter detection"""
        # market_flow_filter passed in 3 of 10 wins (30%)
        # market_flow_filter passed in 9 of 10 losses (90%)
        # edge_score = 30 - 90 = -60.0
        
        # wins
        for i in range(3):
            states = self.default_states.copy()
            states["market_flow_filter"] = {"passed": True, "score": 0.7}
            self._create_test_trade_with_filters(f"TEST_FS_W_P_{i}", "WIN", states)
        for i in range(7):
            states = self.default_states.copy()
            states["market_flow_filter"] = {"passed": False, "score": 0.1}
            self._create_test_trade_with_filters(f"TEST_FS_W_NP_{i}", "WIN", states)
            
        # losses
        for i in range(9):
            states = self.default_states.copy()
            states["market_flow_filter"] = {"passed": True, "score": 0.7}
            self._create_test_trade_with_filters(f"TEST_FS_L_P_{i}", "LOSS", states)
        for i in range(1):
            states = self.default_states.copy()
            states["market_flow_filter"] = {"passed": False, "score": 0.1}
            self._create_test_trade_with_filters(f"TEST_FS_L_NP_{i}", "LOSS", states)
            
        result = calculate_filter_scorecard(self.db, min_trades=20)
        self.assertEqual(result["status"], "OK")
        
        mf_f = next((f for f in result["filters"] if f["filter_name"] == "market_flow_filter"), None)
        self.assertIsNotNone(mf_f)
        self.assertEqual(mf_f["edge_score"], -60.0)
        self.assertEqual(mf_f["verdict"], "HARMFUL")
        self.assertIn("market_flow_filter", result["harmful_filters"])

    def test_4_all_8_filters_present_in_output(self):
        """Test 4: All 8 filters present in output"""
        # Create 20 baseline trades
        for i in range(10):
            self._create_test_trade_with_filters(f"TEST_FS_W_{i}", "WIN", self.default_states)
        for i in range(10):
            self._create_test_trade_with_filters(f"TEST_FS_L_{i}", "LOSS", self.default_states)
            
        result = calculate_filter_scorecard(self.db, min_trades=20)
        self.assertEqual(len(result["filters"]), 8)
        
        filter_names = [f["filter_name"] for f in result["filters"]]
        THE_8_FILTERS = [
            "trend_filter", "momentum_filter", "chop_filter",
            "volatility_filter", "time_filter", "market_flow_filter",
            "liquidity_filter", "option_chain_filter"
        ]
        for name in THE_8_FILTERS:
            self.assertIn(name, filter_names)

    def test_5_malformed_json_handled_gracefully(self):
        """Test 5: Malformed JSON handled gracefully"""
        # 17 trades with valid JSON
        for i in range(9):
            self._create_test_trade_with_filters(f"TEST_FS_W_{i}", "WIN", self.default_states)
        for i in range(8):
            self._create_test_trade_with_filters(f"TEST_FS_L_{i}", "LOSS", self.default_states)
        # 3 trades with malformed JSON
        for i in range(3):
            self._create_test_trade_with_filters(f"TEST_FS_MAL_{i}", "WIN", {}, raw_json="not valid json")
            
        result = calculate_filter_scorecard(self.db, min_trades=20)
        self.assertEqual(result["status"], "OK")
        self.assertEqual(result["malformed_birth_cert_count"], 3)
        self.assertEqual(result["total_trades_analyzed"], 17)

    def test_6_filters_sorted_by_edge_score_descending(self):
        """Test 6: Filters sorted by edge_score descending"""
        # Create trades to make trend_filter have high edge and momentum_filter have low edge
        # Wins: trend passed, momentum not
        # Losses: trend not, momentum passed
        for i in range(10):
            states = self.default_states.copy()
            states["trend_filter"] = {"passed": True, "score": 0.8}
            states["momentum_filter"] = {"passed": False, "score": 0.1}
            self._create_test_trade_with_filters(f"TEST_FS_W_{i}", "WIN", states)
            
        for i in range(10):
            states = self.default_states.copy()
            states["trend_filter"] = {"passed": False, "score": 0.1}
            states["momentum_filter"] = {"passed": True, "score": 0.8}
            self._create_test_trade_with_filters(f"TEST_FS_L_{i}", "LOSS", states)
            
        result = calculate_filter_scorecard(self.db, min_trades=20)
        
        # Check sorting
        scores = [f["edge_score"] for f in result["filters"]]
        self.assertEqual(scores, sorted(scores, reverse=True))

    def test_7_regime_breakdown_is_correct(self):
        """Test 7: Regime breakdown is correct"""
        # 10 TRENDING_BULL: 8 wins, 2 losses (80% win rate -> FAVORABLE)
        for i in range(8):
            self._create_test_trade_with_filters(f"TEST_FS_R1_W_{i}", "WIN", self.default_states, regime="TRENDING_BULL")
        for i in range(2):
            self._create_test_trade_with_filters(f"TEST_FS_R1_L_{i}", "LOSS", self.default_states, regime="TRENDING_BULL")
            
        # 10 SIDEWAYS: 3 wins, 7 losses (30% win rate -> UNFAVORABLE)
        for i in range(3):
            self._create_test_trade_with_filters(f"TEST_FS_R2_W_{i}", "WIN", self.default_states, regime="SIDEWAYS")
        for i in range(7):
            self._create_test_trade_with_filters(f"TEST_FS_R2_L_{i}", "LOSS", self.default_states, regime="SIDEWAYS")
            
        result = calculate_filter_scorecard(self.db, min_trades=20)
        self.assertEqual(len(result["regime_breakdown"]), 2)
        
        bull_regime = next((r for r in result["regime_breakdown"] if r["regime"] == "TRENDING_BULL"), None)
        self.assertIsNotNone(bull_regime)
        self.assertEqual(bull_regime["win_rate_pct"], 80.0)
        self.assertEqual(bull_regime["verdict"], "FAVORABLE")
        
        side_regime = next((r for r in result["regime_breakdown"] if r["regime"] == "SIDEWAYS"), None)
        self.assertIsNotNone(side_regime)
        self.assertEqual(side_regime["win_rate_pct"], 30.0)
        self.assertEqual(side_regime["verdict"], "UNFAVORABLE")

    def test_8_paper_trade_count_unchanged(self):
        """Test 8: Paper trade count unchanged"""
        for i in range(10):
            self._create_test_trade_with_filters(f"TEST_FS_W_{i}", "WIN", self.default_states)
        for i in range(10):
            self._create_test_trade_with_filters(f"TEST_FS_L_{i}", "LOSS", self.default_states)
            
        # Record count before
        from sqlalchemy import func
        count_before = self.db.scalar(select(func.count()).select_from(PaperTrade))
        
        # Call scorecard engine calculation
        calculate_filter_scorecard(self.db, min_trades=20)
        
        # Hit the API endpoint
        response = self.client.get("/api/analytics/filter-scorecard?lookback_days=30&min_trades=20")
        self.assertEqual(response.status_code, 200)
        
        # Record count after
        count_after = self.db.scalar(select(func.count()).select_from(PaperTrade))
        self.assertEqual(count_before, count_after)

from sqlalchemy import select

if __name__ == "__main__":
    unittest.main()
