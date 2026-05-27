import asyncio
import os
import sys
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

backend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.routes_market_backfill import router as market_backfill_router
from app.config import settings
from app.db.database import Base, get_db
from app.market.live_candle_store import LiveCandleStore
from app.models.candle import Candle
from app.schemas.live_candle import LiveInstrumentMetadata
from app.services.startup_market_backfill_service import (
    _project_candles,
    get_startup_market_backfill_service,
)


class TestMarketBackfill(unittest.TestCase):
    def setUp(self):
        self.original = {
            "enable_startup_market_backfill": settings.enable_startup_market_backfill,
            "market_backfill_symbols": settings.market_backfill_symbols,
            "market_backfill_source_interval": settings.market_backfill_source_interval,
            "live_candle_timeframes": settings.live_candle_timeframes,
            "dhan_data_enabled": settings.dhan_data_enabled,
            "dhan_client_id": settings.dhan_client_id,
            "dhan_access_token": settings.dhan_access_token,
        }
        settings.enable_startup_market_backfill = True
        settings.market_backfill_symbols = "NIFTY"
        settings.market_backfill_source_interval = "1"
        settings.live_candle_timeframes = "1m,5m,15m"
        settings.dhan_data_enabled = True
        settings.dhan_client_id = "test-client"
        settings.dhan_access_token = "test-token"

        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(bind=self.engine)
        self.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)
        self.db = self.SessionLocal()
        self._insert_candles()

    def tearDown(self):
        self.db.close()
        for key, value in self.original.items():
            setattr(settings, key, value)

    def test_1_project_candles_builds_target_timeframes(self):
        candles = list(self.db.scalars(select(Candle).order_by(Candle.timestamp)))
        metadata = LiveInstrumentMetadata(
            exchange_segment="IDX_I",
            security_id="13",
            symbol="NIFTY",
            underlying="NIFTY",
        )
        projected = _project_candles(candles, metadata, ["1m", "5m", "15m"])
        timeframes = {item.timeframe for item in projected}
        self.assertEqual(timeframes, {"1m", "5m", "15m"})
        self.assertTrue(all(item.source == "DHAN_BACKFILL" for item in projected))
        self.assertTrue(all(item.is_closed for item in projected))

    def test_2_live_store_accepts_backfilled_candles(self):
        candles = list(self.db.scalars(select(Candle).order_by(Candle.timestamp)))
        metadata = LiveInstrumentMetadata(exchange_segment="IDX_I", security_id="13", symbol="NIFTY", underlying="NIFTY")
        projected = _project_candles(candles, metadata, ["1m", "5m"])
        store = LiveCandleStore(timeframes=["1m", "5m"])
        count = asyncio.run(store.upsert_backfilled_candles(projected, metadata))
        latest = asyncio.run(store.get_latest_candle("NIFTY", "5m"))
        self.assertEqual(count, len(projected))
        self.assertIsNotNone(latest)
        self.assertEqual(latest.source, "DHAN_BACKFILL")

    def test_3_backfill_today_uses_existing_historical_service_and_projects(self):
        service = get_startup_market_backfill_service()
        fake_status = SimpleNamespace(now_ist="2026-05-27T11:00:00+05:30")

        with patch("app.services.startup_market_backfill_service.get_session_gate_service") as gate, patch(
            "app.services.startup_market_backfill_service.HistoricalDataService.download_intraday",
            new=AsyncMock(return_value={"ok": True, "total_candles_saved": 10}),
        ):
            gate.return_value.status.return_value = fake_status
            result = asyncio.run(service.backfill_today(self.db, symbols=["NIFTY"], source_interval="1"))

        self.assertTrue(result["ok"])
        self.assertEqual(result["status"], "COMPLETED")
        self.assertGreater(result["live_candles_projected"], 0)
        self.assertIn("Backfilled candles recover price structure only", result["data_quality_note"])

    def test_4_disabled_auto_backfill_skips_cleanly(self):
        settings.enable_startup_market_backfill = False
        result = asyncio.run(get_startup_market_backfill_service().auto_backfill_if_configured(self.db))
        self.assertTrue(result["ok"])
        self.assertEqual(result["status"], "DISABLED")

    def test_5_status_contains_safety_fields(self):
        status = get_startup_market_backfill_service().status()
        self.assertIn("live_order_status", status)
        self.assertEqual(status["live_order_status"], "BLOCKED")
        self.assertIn("symbols", status)

    def test_6_market_backfill_routes_return_shape(self):
        app = FastAPI()
        app.include_router(market_backfill_router)

        def override_db():
            try:
                yield self.db
            finally:
                pass

        app.dependency_overrides[get_db] = override_db
        client = TestClient(app)
        response = client.get("/api/market-backfill/status")
        self.assertEqual(response.status_code, 200)
        self.assertIn("symbols", response.json())

    def _insert_candles(self):
        start = datetime(2026, 5, 27, 9, 15, tzinfo=timezone.utc)
        for index in range(15):
            close = 24000 + index
            self.db.add(
                Candle(
                    source="DHAN",
                    symbol="NIFTY",
                    security_id="13",
                    exchange_segment="IDX_I",
                    instrument="INDEX",
                    interval="1",
                    timestamp=start + timedelta(minutes=index),
                    open=close - 0.5,
                    high=close + 1.0,
                    low=close - 1.0,
                    close=close,
                    volume=1000 + index,
                    open_interest=None,
                )
            )
        self.db.commit()


if __name__ == "__main__":
    unittest.main()
