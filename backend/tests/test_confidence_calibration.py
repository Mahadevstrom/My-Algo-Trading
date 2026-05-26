import os
import sys
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
from app.analytics.confidence_calibration import calculate_confidence_calibration

class TestConfidenceCalibration(unittest.TestCase):
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

    def tearDown(self):
        app.dependency_overrides.pop(get_db, None)
        self.db.query(PaperTrade).delete()
        self.db.commit()
        self.db.close()
        Base.metadata.drop_all(bind=self.engine)
        self.engine.dispose()

    def _create_test_trade(self, symbol, result, confidence, pnl, exit_time=None, has_birth_cert=True):
        if exit_time is None:
            exit_time = datetime.now(timezone.utc)
            
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
            exit_time=exit_time,
            confidence_score_at_entry=confidence,
            birth_cert_version="1.0" if has_birth_cert else None,
            data_source="MOCK"
        )
        self.db.add(trade)
        self.db.commit()
        self.db.refresh(trade)
        return trade

    def test_1_insufficient_data_returns_correct_shape(self):
        """Test 1: Insufficient data returns correct shape"""
        for i in range(8):
            self._create_test_trade(f"TEST_CC_{i}", "WIN", 75.0, 500.0)
            
        result = calculate_confidence_calibration(self.db, min_trades=20)
        self.assertEqual(result["status"], "INSUFFICIENT_DATA")
        self.assertEqual(result["current_count"], 8)
        self.assertEqual(result["trades_needed"], 12)
        self.assertEqual(result["min_required"], 20)
        self.assertIn("Birth certificates are attached", result["note"])

    def test_2_excellent_calibration_grade(self):
        """Test 2: Excellent calibration grade"""
        # 60-65: 5 trades, 2 wins (40% win rate)
        for i in range(2):
            self._create_test_trade(f"TEST_CC_A_W_{i}", "WIN", 62.0, 500.0)
        for i in range(3):
            self._create_test_trade(f"TEST_CC_A_L_{i}", "LOSS", 62.0, -300.0)
            
        # 65-70: 5 trades, 3 wins (60% win rate)
        for i in range(3):
            self._create_test_trade(f"TEST_CC_B_W_{i}", "WIN", 67.0, 500.0)
        for i in range(2):
            self._create_test_trade(f"TEST_CC_B_L_{i}", "LOSS", 67.0, -300.0)
            
        # 70-75: 5 trades, 4 wins (80% win rate)
        for i in range(4):
            self._create_test_trade(f"TEST_CC_C_W_{i}", "WIN", 72.0, 500.0)
        for i in range(1):
            self._create_test_trade(f"TEST_CC_C_L_{i}", "LOSS", 72.0, -300.0)
            
        # 75-80: 5 trades, 5 wins (100% win rate)
        for i in range(5):
            self._create_test_trade(f"TEST_CC_D_W_{i}", "WIN", 77.0, 500.0)
            
        result = calculate_confidence_calibration(self.db, min_trades=5)
        self.assertEqual(result["status"], "OK")
        self.assertEqual(result["calibration_grade"], "EXCELLENT")
        self.assertEqual(result["total_trades_analyzed"], 20)

    def test_3_poor_calibration_grade_inverse_pattern(self):
        """Test 3: Poor calibration grade (inverse pattern)"""
        # 60-65: 5 trades, 4 wins (80%)
        for i in range(4):
            self._create_test_trade(f"TEST_CC_A_W_{i}", "WIN", 62.0, 500.0)
        for i in range(1):
            self._create_test_trade(f"TEST_CC_A_L_{i}", "LOSS", 62.0, -300.0)
            
        # 65-70: 5 trades, 3 wins (60%)
        for i in range(3):
            self._create_test_trade(f"TEST_CC_B_W_{i}", "WIN", 67.0, 500.0)
        for i in range(2):
            self._create_test_trade(f"TEST_CC_B_L_{i}", "LOSS", 67.0, -300.0)
            
        # 70-75: 5 trades, 2 wins (40%)
        for i in range(2):
            self._create_test_trade(f"TEST_CC_C_W_{i}", "WIN", 72.0, 500.0)
        for i in range(3):
            self._create_test_trade(f"TEST_CC_C_L_{i}", "LOSS", 72.0, -300.0)
            
        # 75-80: 5 trades, 1 win (20%)
        for i in range(1):
            self._create_test_trade(f"TEST_CC_D_W_{i}", "WIN", 77.0, 500.0)
        for i in range(4):
            self._create_test_trade(f"TEST_CC_D_L_{i}", "LOSS", 77.0, -300.0)
            
        result = calculate_confidence_calibration(self.db, min_trades=5)
        self.assertEqual(result["calibration_grade"], "POOR")
        self.assertTrue(any(d["type"] == "INVERSE_CALIBRATION" for d in result["danger_signals"]))

    def test_4_bucket_math_precision(self):
        """Test 4: Bucket math precision"""
        # Create exactly 10 trades in 65-70 bucket
        # 7 WIN, 2 LOSS, 1 BREAKEVEN
        # WIN pnl values: [500, 600, 700, 800, 900, 1000, 1100]
        # LOSS pnl values: [-400, -600]
        # BREAKEVEN pnl: [0]
        win_pnls = [500.0, 600.0, 700.0, 800.0, 900.0, 1000.0, 1100.0]
        for p in win_pnls:
            self._create_test_trade("TEST_CC_M_W", "WIN", 67.0, p)
        loss_pnls = [-400.0, -600.0]
        for p in loss_pnls:
            self._create_test_trade("TEST_CC_M_L", "LOSS", 67.0, p)
        self._create_test_trade("TEST_CC_M_B", "BREAKEVEN", 67.0, 0.0)
        
        # Add 10 dummy trades in another bucket to satisfy min_trades=20
        for i in range(10):
            self._create_test_trade(f"TEST_CC_DUMMY_{i}", "WIN", 77.0, 100.0)
            
        result = calculate_confidence_calibration(self.db, min_trades=20)
        
        # Find 65-70 bucket
        bucket = next((b for b in result["buckets"] if b["key"] == "65-70"), None)
        self.assertIsNotNone(bucket)
        self.assertEqual(bucket["win_count"], 7)
        self.assertEqual(bucket["loss_count"], 2)
        self.assertEqual(bucket["breakeven_count"], 1)
        self.assertEqual(bucket["win_rate_pct"], 70.0)
        self.assertEqual(bucket["avg_pnl_wins"], 800.0)
        self.assertEqual(bucket["avg_pnl_losses"], -500.0)

    def test_5_all_6_buckets_present_even_when_empty(self):
        """Test 5: All 6 buckets present even when empty"""
        # Create trades in 60-65 and 80+ buckets
        for i in range(10):
            self._create_test_trade(f"TEST_CC_A_{i}", "WIN", 62.0, 100.0)
        for i in range(10):
            self._create_test_trade(f"TEST_CC_B_{i}", "WIN", 85.0, 200.0)
            
        result = calculate_confidence_calibration(self.db, min_trades=20)
        self.assertEqual(len(result["buckets"]), 6)
        
        # 50-60 is empty
        empty_b = next((b for b in result["buckets"] if b["key"] == "50-60"), None)
        self.assertIsNotNone(empty_b)
        self.assertEqual(empty_b["trade_count"], 0)
        self.assertEqual(empty_b["bar_color"], "gray")
        self.assertIsNone(empty_b["win_rate_pct"])

    def test_6_trades_without_birth_certificates_excluded(self):
        """Test 6: Trades without birth certificates excluded"""
        # Create 15 trades WITH birth cert
        for i in range(15):
            self._create_test_trade(f"TEST_CC_BC_{i}", "WIN", 75.0, 100.0, has_birth_cert=True)
        # Create 10 trades WITHOUT birth cert
        for i in range(10):
            self._create_test_trade(f"TEST_CC_NOBC_{i}", "WIN", 75.0, 100.0, has_birth_cert=False)
            
        result = calculate_confidence_calibration(self.db, min_trades=10)
        self.assertEqual(result["total_trades_analyzed"], 15)

    def test_7_lookback_days_parameter_filters_correctly(self):
        """Test 7: lookback_days parameter filters correctly"""
        now = datetime.now(timezone.utc)
        # 5 trades closed 10 days ago
        for i in range(5):
            self._create_test_trade(f"TEST_CC_10d_{i}", "WIN", 75.0, 100.0, exit_time=now - timedelta(days=10))
        # 5 trades closed 45 days ago
        for i in range(5):
            self._create_test_trade(f"TEST_CC_45d_{i}", "WIN", 75.0, 100.0, exit_time=now - timedelta(days=45))
            
        # lookback=30
        res_30 = calculate_confidence_calibration(self.db, lookback_days=30, min_trades=5)
        self.assertEqual(res_30["total_trades_analyzed"], 5)
        
        # lookback=60
        res_60 = calculate_confidence_calibration(self.db, lookback_days=60, min_trades=5)
        self.assertEqual(res_60["total_trades_analyzed"], 10)

    def test_8_paper_trade_count_unchanged(self):
        """Test 8: Paper trade count unchanged (read-only safety test)"""
        # Create 5 test trades
        for i in range(5):
            self._create_test_trade(f"TEST_CC_RC_{i}", "WIN", 75.0, 100.0)
            
        # Count before
        from sqlalchemy import func
        count_before = self.db.scalar(select(func.count()).select_from(PaperTrade))
        
        # Run calibration calculation
        calculate_confidence_calibration(self.db, min_trades=5)
        
        # Hit the API endpoint
        response = self.client.get("/api/analytics/confidence-calibration?lookback_days=30&min_trades=5")
        self.assertEqual(response.status_code, 200)
        
        # Count after
        count_after = self.db.scalar(select(func.count()).select_from(PaperTrade))
        self.assertEqual(count_before, count_after)

from sqlalchemy import select

if __name__ == "__main__":
    unittest.main()
