import asyncio
import os
import sys
import unittest

backend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.routes_feed_reliability import router as feed_reliability_router
from app.config import settings
from app.db.database import Base, get_db
from app.services.dhan_rest_quota_service import get_dhan_rest_quota_service
from app.services.feed_reliability_service import get_feed_reliability_service


class TestFeedReliability(unittest.TestCase):
    def setUp(self):
        self.original = {
            "enable_dhan_rest_quota_guard": settings.enable_dhan_rest_quota_guard,
            "dhan_rest_quota_per_minute": settings.dhan_rest_quota_per_minute,
            "dhan_rest_min_gap_seconds": settings.dhan_rest_min_gap_seconds,
            "dhan_rest_response_cache_seconds": settings.dhan_rest_response_cache_seconds,
            "enable_dhan_websocket": settings.enable_dhan_websocket,
            "enable_feed_watchdog": settings.enable_feed_watchdog,
            "feed_watchdog_auto_recover": settings.feed_watchdog_auto_recover,
            "live_monitor_auto_start": settings.live_monitor_auto_start,
        }
        settings.enable_dhan_rest_quota_guard = True
        settings.dhan_rest_quota_per_minute = 2
        settings.dhan_rest_min_gap_seconds = 0.0
        settings.dhan_rest_response_cache_seconds = 5.0
        settings.enable_dhan_websocket = False
        settings.enable_feed_watchdog = True
        settings.feed_watchdog_auto_recover = False
        settings.live_monitor_auto_start = False
        get_dhan_rest_quota_service().reset_for_tests()

        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(bind=self.engine)
        self.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)
        self.db = self.SessionLocal()

    def tearDown(self):
        asyncio.run(get_feed_reliability_service().stop())
        self.db.close()
        get_dhan_rest_quota_service().reset_for_tests()
        for key, value in self.original.items():
            setattr(settings, key, value)

    def test_1_rest_quota_blocks_after_limit(self):
        quota = get_dhan_rest_quota_service()

        async def run():
            first = await quota.acquire("/marketfeed/ltp", {"a": 1})
            second = await quota.acquire("/marketfeed/quote", {"a": 2})
            third = await quota.acquire("/optionchain", {"a": 3})
            return first, second, third

        first, second, third = asyncio.run(run())
        self.assertTrue(first["allowed"])
        self.assertTrue(second["allowed"])
        self.assertFalse(third["allowed"])
        self.assertEqual(third["status"], "LOCAL_QUOTA_EXHAUSTED")

    def test_2_rest_quota_cache_returns_copy(self):
        quota = get_dhan_rest_quota_service()
        response = {"ok": True, "status": "CONNECTED", "data": {"value": 1}}
        quota.record_response("/marketfeed/ltp", {"x": 1}, response)
        cached = asyncio.run(quota.cached_response("/marketfeed/ltp", {"x": 1}))
        self.assertIsNotNone(cached)
        cached["data"]["value"] = 99
        cached_again = asyncio.run(quota.cached_response("/marketfeed/ltp", {"x": 1}))
        self.assertEqual(cached_again["data"]["value"], 1)

    def test_3_rest_quota_cooldown_after_429(self):
        quota = get_dhan_rest_quota_service()
        quota.record_response("/marketfeed/ltp", {"x": 1}, {"ok": False, "status": "RATE_LIMITED", "http_status": 429})
        blocked = asyncio.run(quota.acquire("/marketfeed/ltp", {"x": 2}))
        self.assertFalse(blocked["allowed"])
        self.assertEqual(blocked["status"], "COOLDOWN_ACTIVE")

    def test_4_watchdog_status_shape(self):
        status = asyncio.run(get_feed_reliability_service().status())
        self.assertIn("live_feed", status)
        self.assertIn("live_monitor", status)
        self.assertIn("dhan_rest_quota", status)
        self.assertEqual(status["live_order_status"], "BLOCKED")

    def test_5_watchdog_check_once_does_not_raise_when_ws_disabled(self):
        result = asyncio.run(get_feed_reliability_service().check_once(self.db, auto_recover=True))
        self.assertTrue(result["ok"])
        self.assertEqual(result["status"], "WEBSOCKET_DISABLED")

    def test_6_feed_reliability_routes_return_status(self):
        app = FastAPI()
        app.include_router(feed_reliability_router)

        def override_db():
            try:
                yield self.db
            finally:
                pass

        app.dependency_overrides[get_db] = override_db
        client = TestClient(app)

        status_response = client.get("/api/feed-reliability/status")
        quota_response = client.get("/api/feed-reliability/rest-quota")
        check_response = client.post("/api/feed-reliability/check-once")

        self.assertEqual(status_response.status_code, 200)
        self.assertEqual(quota_response.status_code, 200)
        self.assertEqual(check_response.status_code, 200)
        self.assertIn("dhan_rest_quota", quota_response.json())


if __name__ == "__main__":
    unittest.main()
