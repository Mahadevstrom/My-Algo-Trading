import os
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch
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
from app.engine.context.context_classifier import ContextClassifier
from app.engine.context.context_evidence import ContextEvidence
from app.engine.context.context_logger import log_context_classification
from app.engine.context.context_types import ContextType
from app.engine.context.event_calendar import add_event
from app.engine.context.models import ContextClassificationLog
from app.engine.context.routes import router as context_router
from app.models.trade import PaperTrade


IST = ZoneInfo("Asia/Kolkata")


class TestContextClassifier(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(bind=self.engine)
        self.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)
        self.db = self.SessionLocal()
        self.classifier = ContextClassifier()

    def tearDown(self):
        self.db.close()

    def _no_expiry_patches(self):
        return (
            patch("app.engine.context.context_classifier.is_expiry_today", return_value=False),
            patch("app.engine.context.context_classifier.is_monthly_expiry_today", return_value=False),
            patch("app.engine.context.context_classifier.days_to_next_expiry", return_value=5),
            patch("app.engine.context.context_classifier.is_event_day", return_value=(False, None)),
        )

    def test_1_expiry_day_morning_context(self):
        market_data = {"_now_ist": datetime(2026, 1, 29, 10, 15, tzinfo=IST)}
        with patch("app.engine.context.context_classifier.is_expiry_today", return_value=True), patch(
            "app.engine.context.context_classifier.is_monthly_expiry_today", return_value=False
        ), patch("app.engine.context.context_classifier.days_to_next_expiry", return_value=0), patch(
            "app.engine.context.context_classifier.is_event_day", return_value=(False, None)
        ):
            result = self.classifier.safe_classify(self.db, market_data=market_data)
        self.assertEqual(result.context_type, "EXPIRY_DAY_MORNING")
        self.assertGreater(result.context_confidence, 0.8)
        self.assertGreater(result.confidence_modifier, 0)
        self.assertFalse(hasattr(result, "blocking"))

    def test_2_expiry_day_afternoon_context(self):
        market_data = {"_now_ist": datetime(2026, 1, 29, 14, 0, tzinfo=IST)}
        with patch("app.engine.context.context_classifier.is_expiry_today", return_value=True), patch(
            "app.engine.context.context_classifier.is_monthly_expiry_today", return_value=False
        ), patch("app.engine.context.context_classifier.days_to_next_expiry", return_value=0), patch(
            "app.engine.context.context_classifier.is_event_day", return_value=(False, None)
        ):
            result = self.classifier.safe_classify(self.db, market_data=market_data)
        self.assertEqual(result.context_type, "EXPIRY_DAY_AFTERNOON")
        self.assertGreaterEqual(result.confidence_modifier, 0.15)

    def test_3_gap_down_continuation_context(self):
        market_data = {"opening_gap_pct": -0.82, "vix": 14.5, "previous_close": 24000, "open_price": 23803}
        with self._no_expiry_patches()[0], self._no_expiry_patches()[1], self._no_expiry_patches()[2], self._no_expiry_patches()[3]:
            result = self.classifier.safe_classify(self.db, market_data=market_data)
        self.assertEqual(result.context_type, "GAP_DOWN_CONTINUATION")
        self.assertLessEqual(result.confidence_modifier, 0)

    def test_4_gap_up_continuation_context(self):
        market_data = {"opening_gap_pct": 0.75, "vix": 14.0}
        with self._no_expiry_patches()[0], self._no_expiry_patches()[1], self._no_expiry_patches()[2], self._no_expiry_patches()[3]:
            result = self.classifier.safe_classify(self.db, market_data=market_data)
        self.assertEqual(result.context_type, "GAP_UP_CONTINUATION")

    def test_5_high_vix_day_context(self):
        market_data = {"vix": 21.5, "vix_20day_avg": 15.0}
        with self._no_expiry_patches()[0], self._no_expiry_patches()[1], self._no_expiry_patches()[2], self._no_expiry_patches()[3]:
            result = self.classifier.safe_classify(self.db, market_data=market_data)
        self.assertEqual(result.context_type, "HIGH_VIX_DAY")
        self.assertGreaterEqual(result.confidence_modifier, 0.10)

    def test_6_normal_trading_day_default(self):
        market_data = {"vix": 14.0, "opening_gap_pct": 0.2}
        with self._no_expiry_patches()[0], self._no_expiry_patches()[1], self._no_expiry_patches()[2], self._no_expiry_patches()[3]:
            result = self.classifier.safe_classify(self.db, market_data=market_data)
        self.assertEqual(result.context_type, "NORMAL_TRADING_DAY")
        self.assertEqual(result.confidence_modifier, 0.0)

    def test_7_stale_data_overrides_everything(self):
        market_data = {"vix": 21.5, "opening_gap_pct": -1.2, "data_quality_status": "STALE"}
        with self._no_expiry_patches()[0], self._no_expiry_patches()[1], self._no_expiry_patches()[2], self._no_expiry_patches()[3]:
            result = self.classifier.safe_classify(self.db, market_data=market_data)
        self.assertEqual(result.context_type, "STALE_DATA_DAY")
        self.assertGreaterEqual(result.confidence_modifier, 0.20)

    def test_8_safe_classify_never_raises(self):
        market_data = {"_now_ist": datetime(2026, 5, 26, 10, 15, tzinfo=IST)}
        with self._no_expiry_patches()[0], self._no_expiry_patches()[1], self._no_expiry_patches()[2], self._no_expiry_patches()[3]:
            result = self.classifier.safe_classify(db=self.db, market_data=market_data)
        self.assertIsInstance(result, ContextEvidence)
        self.assertIn(result.context_type, ("UNKNOWN", "NORMAL_TRADING_DAY", "PRE_EXPIRY_DAY"))

    def test_9_news_event_day_context(self):
        with tempfile.TemporaryDirectory() as tmp:
            events_path = Path(tmp) / "known_events.json"
            events_path.write_text("[]", encoding="utf-8")
            today = datetime.now(IST).strftime("%Y-%m-%d")
            with patch("app.engine.context.event_calendar.KNOWN_EVENTS_PATH", events_path):
                add_event(today, "Test RBI Event", "HIGH")
                with self._no_expiry_patches()[0], self._no_expiry_patches()[1], self._no_expiry_patches()[2]:
                    result = self.classifier.safe_classify(self.db, market_data={"vix": 14.0})
        self.assertEqual(result.context_type, "NEWS_EVENT_DAY")
        self.assertTrue(result.is_known_event_day)
        self.assertIsNotNone(result.known_event_name)

    def test_10_context_log_does_not_affect_paper_trade_count(self):
        count_before = self.db.scalar(select(func.count()).select_from(PaperTrade))
        with self._no_expiry_patches()[0], self._no_expiry_patches()[1], self._no_expiry_patches()[2], self._no_expiry_patches()[3]:
            context = self.classifier.safe_classify(self.db, market_data={"vix": 14.0})
        context.evaluation_id = "ctx-test-1"
        log_context_classification(self.db, context, signal_id="sig-1", signal_v2_decision="NO_TRADE")
        count_after = self.db.scalar(select(func.count()).select_from(PaperTrade))
        log_count = self.db.scalar(select(func.count()).select_from(ContextClassificationLog))
        self.assertEqual(count_after, count_before)
        self.assertEqual(log_count, 1)

    def test_11_birth_certificate_fields_populated(self):
        trade = PaperTrade(
            symbol="NIFTY",
            instrument_type="INDEX_OPTION",
            exchange="NSE",
            direction="BUY",
            entry_price=100.0,
            quantity=50,
            data_source="TEST",
            context_type_at_entry="GAP_DOWN_CONTINUATION",
            context_confidence_at_entry=0.7,
            confidence_modifier_at_entry=-0.02,
        )
        self.db.add(trade)
        self.db.commit()
        self.db.refresh(trade)
        self.assertEqual(trade.context_type_at_entry, "GAP_DOWN_CONTINUATION")
        self.assertEqual(trade.confidence_modifier_at_entry, -0.02)

    def test_12_context_summary_endpoint_returns_correct_shape(self):
        app = FastAPI()
        app.include_router(context_router, prefix="/api/context")

        def override_db():
            try:
                yield self.db
            finally:
                pass

        app.dependency_overrides[get_db] = override_db
        client = TestClient(app)
        response = client.get("/api/context/summary")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn("period_days", payload)
        self.assertIn("context_distribution", payload)
        self.assertIn("context_win_rates", payload)
        self.assertIn("insight", payload)

    def test_13_cross_index_sensex_expiry_sets_secondary_context(self):
        market_data = {
            "_now_ist": datetime(2026, 5, 26, 10, 15, tzinfo=IST),
            "vix": 14.0,
            "cross_index_expiries": ["SENSEX"],
        }

        with patch("app.engine.context.context_classifier.is_expiry_today", return_value=False), patch(
            "app.engine.context.context_classifier.is_monthly_expiry_today", return_value=False
        ), patch("app.engine.context.context_classifier.days_to_next_expiry", return_value=5), patch(
            "app.engine.context.context_classifier.is_event_day", return_value=(False, None)
        ):
            result = self.classifier.safe_classify(self.db, market_data=market_data, underlying="NIFTY")

        self.assertEqual(result.context_type, ContextType.NORMAL_TRADING_DAY)
        self.assertEqual(result.secondary_context, ContextType.SENSEX_EXPIRY_DAY)
        self.assertGreaterEqual(result.confidence_modifier, 0.03)
        self.assertIn("SENSEX expiry today", result.context_summary)

    def test_14_banknifty_momentum_is_validation_only(self):
        market_data = {
            "_now_ist": datetime(2026, 5, 26, 10, 15, tzinfo=IST),
            "vix": 14.0,
            "banknifty_direction": "BULLISH",
            "banknifty_change_pct": 0.42,
        }
        with self._no_expiry_patches()[0], self._no_expiry_patches()[1], self._no_expiry_patches()[2], self._no_expiry_patches()[3]:
            result = self.classifier.safe_classify(self.db, market_data=market_data, underlying="NIFTY")

        self.assertEqual(result.context_type, ContextType.NORMAL_TRADING_DAY)
        self.assertEqual(result.secondary_context, ContextType.BANKNIFTY_MOMENTUM_VALIDATION)
        self.assertEqual(result.confidence_modifier, 0.0)
        self.assertIn("NIFTY Bank/BANKNIFTY momentum is BULLISH", result.context_summary)
        self.assertIn("not as a trade trigger", result.context_summary)


if __name__ == "__main__":
    unittest.main()
