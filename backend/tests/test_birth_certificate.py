import os
import sys
import json
import unittest
from datetime import datetime, timezone

# Add backend directory to path
backend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import app
from app.db.database import Base, get_db
from app.models.trade import PaperTrade, PaperTradeCreate, InstrumentType, Direction, OptionType, TradeResult
from app.services.live_paper_simulator_service import get_live_paper_simulator_service, SIMULATOR_SOURCE
from app.schemas.signal_v2 import SelectedOptionCandidate

class TestTradeBirthCertificate(unittest.TestCase):
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

        # Create a mock option candidate and signal
        self.mock_option = SelectedOptionCandidate(
            underlying="NIFTY",
            option_type="CE",
            expiry="2026-06-25",
            strike=23500.0,
            trading_symbol="TEST_BC_NIFTY_CE",
            security_id="12345",
            exchange_segment="NSE_FO",
            ltp=150.0,
            liquidity_score=85.0,
            spread=0.5,
            reason_selected="Liquid CE around ATM"
        )
        
        # Simple Mock Signal object
        class MockSignal:
            def __init__(self, option):
                self.selected_option = option
                self.underlying = "NIFTY"
                self.score = 75.0
                self.decision = "BUY_CALL"
                self.market_state = {
                    "chain_bias": "BULLISH",
                    "target_plan": {"option_target_1": 170.0, "option_target_2": 200.0}
                }
        self.mock_signal = MockSignal(self.mock_option)

    def tearDown(self):
        app.dependency_overrides.pop(get_db, None)
        self.db.query(PaperTrade).delete()
        self.db.commit()
        self.db.close()
        Base.metadata.drop_all(bind=self.engine)
        self.engine.dispose()

    def test_1_birth_certificate_stored_correctly(self):
        """Test 1: Birth certificate is stored correctly in the database"""
        birth_cert = {
            "signal_id": "9999",
            "confidence_score": 75.0,
            "regime": "TRENDING_BULL",
            "session_window": "ACTIVE_MORNING",
            "oi_direction": "BULLISH",
            "market_flow_score": 65.0,
            "pcr": 1.12,
            "spread_pct": 0.33,
            "filters_passed_count": 7,
            "filter_states": {
                "trend_filter": {"passed": True, "score": 0.8, "detail": "EMA bullish"}
            }
        }
        
        simulator = get_live_paper_simulator_service()
        trade = simulator._create_paper_trade(self.db, self.mock_signal, birth_certificate=birth_cert)
        
        # Query database directly to assert storage
        db_trade = self.db.get(PaperTrade, trade.id)
        self.assertIsNotNone(db_trade)
        self.assertEqual(db_trade.birth_cert_version, "1.0")
        self.assertEqual(db_trade.confidence_score_at_entry, 75.0)
        self.assertEqual(db_trade.signal_id, 9999)
        self.assertEqual(db_trade.regime_at_entry, "TRENDING_BULL")
        self.assertEqual(db_trade.session_window_at_entry, "ACTIVE_MORNING")
        self.assertEqual(db_trade.oi_direction_at_entry, "BULLISH")
        self.assertEqual(db_trade.market_flow_score_at_entry, 65.0)
        self.assertEqual(db_trade.pcr_at_entry, 1.12)
        self.assertEqual(db_trade.spread_pct_at_entry, 0.33)
        self.assertEqual(db_trade.filters_passed_count, 7)
        
        # Verify JSON parsed correctly
        parsed_filters = json.loads(db_trade.filter_states_json)
        self.assertEqual(parsed_filters["trend_filter"]["passed"], True)
        self.assertEqual(parsed_filters["trend_filter"]["score"], 0.8)

    def test_2_missing_birth_certificate_does_not_crash(self):
        """Test 2: Trade creation works cleanly with birth_certificate=None"""
        simulator = get_live_paper_simulator_service()
        # This must run without exceptions
        trade = simulator._create_paper_trade(self.db, self.mock_signal, birth_certificate=None)
        
        db_trade = self.db.get(PaperTrade, trade.id)
        self.assertIsNotNone(db_trade)
        self.assertIsNone(db_trade.birth_cert_version)
        self.assertIsNone(db_trade.confidence_score_at_entry)
        self.assertIsNone(db_trade.regime_at_entry)
        self.assertIsNone(db_trade.filter_states_json)

    def test_3_partial_birth_certificate_does_not_crash(self):
        """Test 3: Trade creation with partial fields does not crash and stores what is available"""
        birth_cert = {
            "signal_id": "8888",
            "confidence_score": 82.0,
            "regime": "SIDEWAYS"
            # All other fields are missing
        }
        simulator = get_live_paper_simulator_service()
        trade = simulator._create_paper_trade(self.db, self.mock_signal, birth_certificate=birth_cert)
        
        db_trade = self.db.get(PaperTrade, trade.id)
        self.assertIsNotNone(db_trade)
        self.assertEqual(db_trade.birth_cert_version, "1.0")
        self.assertEqual(db_trade.signal_id, 8888)
        self.assertEqual(db_trade.confidence_score_at_entry, 82.0)
        self.assertEqual(db_trade.regime_at_entry, "SIDEWAYS")
        
        # Stored None/default for missing fields
        self.assertEqual(db_trade.session_window_at_entry, "UNKNOWN")
        self.assertIsNone(db_trade.spread_pct_at_entry)
        self.assertEqual(json.loads(db_trade.filter_states_json), {})

    def test_4_old_trades_still_load_correctly(self):
        """Test 4: Legacy trades (no birth cert fields) load successfully with None values"""
        # Create a trade bypassing the birth cert logic manually (saving legacy row)
        legacy_trade = PaperTrade(
            symbol="TEST_BC_LEGACY",
            instrument_type=InstrumentType.INDEX_OPTION.value,
            exchange="NSE",
            direction=Direction.BUY.value,
            entry_price=100.0,
            quantity=15,
            data_source=SIMULATOR_SOURCE,
            status="CLOSED",
            result=TradeResult.WIN.value
        )
        self.db.add(legacy_trade)
        self.db.commit()
        
        db_trade = self.db.get(PaperTrade, legacy_trade.id)
        self.assertIsNotNone(db_trade)
        self.assertIsNone(db_trade.birth_cert_version)
        self.assertIsNone(db_trade.confidence_score_at_entry)
        self.assertIsNone(db_trade.regime_at_entry)
        self.assertIsNone(db_trade.filter_states_json)

    def test_5_birth_certificate_endpoint_responds_correctly(self):
        """Test 5: Birth certificate endpoint returns expected JSON structure for new and old trades"""
        # 1. Create a trade WITH birth certificate
        birth_cert = {
            "signal_id": "9999",
            "confidence_score": 75.0,
            "regime": "TRENDING_BULL",
            "session_window": "ACTIVE_MORNING",
            "oi_direction": "BULLISH",
            "market_flow_score": 65.0,
            "pcr": 1.12,
            "spread_pct": 0.33,
            "filters_passed_count": 7,
            "filter_states": {
                "trend_filter": {"passed": True, "score": 0.8, "detail": "EMA bullish"}
            }
        }
        simulator = get_live_paper_simulator_service()
        trade_new = simulator._create_paper_trade(self.db, self.mock_signal, birth_certificate=birth_cert)
        
        # 2. Create a trade WITHOUT birth certificate (Legacy)
        trade_old = PaperTrade(
            symbol="TEST_BC_OLD",
            instrument_type=InstrumentType.INDEX_OPTION.value,
            exchange="NSE",
            direction=Direction.BUY.value,
            entry_price=100.0,
            quantity=15,
            data_source=SIMULATOR_SOURCE,
        )
        self.db.add(trade_old)
        self.db.commit()
        
        # 3. Test HTTP GET on new trade
        response_new = self.client.get(f"/api/live-paper/trades/{trade_new.id}/birth-certificate")
        self.assertEqual(response_new.status_code, 200)
        data_new = response_new.json()
        self.assertEqual(data_new["birth_cert_version"], "1.0")
        self.assertEqual(data_new["confidence_score_at_entry"], 75.0)
        self.assertEqual(data_new["regime_at_entry"], "TRENDING_BULL")
        self.assertEqual(data_new["filter_states"]["trend_filter"]["passed"], True)

        # 4. Test HTTP GET on old trade
        response_old = self.client.get(f"/api/live-paper/trades/{trade_old.id}/birth-certificate")
        self.assertEqual(response_old.status_code, 200)
        data_old = response_old.json()
        self.assertIsNone(data_old["birth_cert_version"])
        self.assertEqual(data_old["status"], "NO_BIRTH_CERTIFICATE")
        self.assertIn("created before Phase 3.1", data_old["message"])

    def test_6_paper_trade_count_is_unchanged(self):
        """Test 6: Fetching birth certificates does not mutate or increase paper trade count"""
        # Create a test trade with birth certificate
        birth_cert = {
            "signal_id": "1111",
            "confidence_score": 90.0,
            "regime": "TRENDING_BULL"
        }
        simulator = get_live_paper_simulator_service()
        trade = simulator._create_paper_trade(self.db, self.mock_signal, birth_certificate=birth_cert)
        
        # Record count before running endpoint
        count_before = self.db.scalar(select(func.count()).select_from(PaperTrade))
        
        # Hit birth certificate endpoint
        response = self.client.get(f"/api/live-paper/trades/{trade.id}/birth-certificate")
        self.assertEqual(response.status_code, 200)
        
        # Record count after running endpoint
        count_after = self.db.scalar(select(func.count()).select_from(PaperTrade))
        
        self.assertEqual(count_before, count_after, "Paper trade count mutated during query!")

from sqlalchemy import func

if __name__ == "__main__":
    unittest.main()
