import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.routes_dhan_auth import router as dhan_auth_router
from app.brokers.dhan_data import DhanDataAdapter
from app.config import settings
from app.services.dhan_auth_service import DhanAuthService


class FakeResponse:
    def __init__(self, status_code: int, payload: dict):
        self.status_code = status_code
        self._payload = payload
        self.text = ""

    def json(self) -> dict:
        return self._payload


class TestDhanAuthService(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.original = {
            "enable_dhan_api_key_auth": settings.enable_dhan_api_key_auth,
            "dhan_client_id": settings.dhan_client_id,
            "dhan_access_token": settings.dhan_access_token,
            "dhan_api_key": settings.dhan_api_key,
            "dhan_api_secret": settings.dhan_api_secret,
            "dhan_token_cache_path": settings.dhan_token_cache_path,
            "dhan_auth_base_url": settings.dhan_auth_base_url,
        }
        settings.enable_dhan_api_key_auth = True
        settings.dhan_client_id = "test-client"
        settings.dhan_access_token = None
        settings.dhan_api_key = "test-api-key"
        settings.dhan_api_secret = "test-api-secret"
        settings.dhan_auth_base_url = "https://auth.test"
        settings.dhan_token_cache_path = str(Path(self.temp_dir.name) / "dhan_token.json")

    def tearDown(self):
        for key, value in self.original.items():
            setattr(settings, key, value)
        self.temp_dir.cleanup()

    def test_1_generate_consent_returns_login_url_without_exposing_secret(self):
        service = DhanAuthService(settings)

        async def run():
            with patch("httpx.AsyncClient.request", new=AsyncMock(return_value=FakeResponse(200, {
                "consentAppId": "abc-123",
                "consentAppStatus": "GENERATED",
                "status": "success",
            }))):
                return await service.generate_consent()

        import asyncio
        result = asyncio.run(run())

        self.assertTrue(result["ok"])
        self.assertEqual(result["status"], "CONSENT_GENERATED")
        self.assertIn("consentAppId=abc-123", result["login_url"])
        self.assertFalse(result["token_exposed"])
        self.assertNotIn("test-api-secret", str(result))

    def test_2_consume_token_id_caches_access_token_and_adapter_uses_it(self):
        expiry = (datetime.now(timezone.utc) + timedelta(hours=12)).isoformat()
        service = DhanAuthService(settings)

        async def run():
            with patch("httpx.AsyncClient.request", new=AsyncMock(return_value=FakeResponse(200, {
                "dhanClientId": "test-client",
                "accessToken": "runtime-token",
                "expiryTime": expiry,
            }))):
                return await service.consume_token_id("token-id-1")

        import asyncio
        result = asyncio.run(run())

        self.assertTrue(result["ok"])
        self.assertEqual(result["status"], "TOKEN_READY")
        self.assertFalse(result["token_exposed"])
        self.assertEqual(service.active_access_token(), "runtime-token")
        self.assertTrue(DhanDataAdapter(settings).has_credentials())

    def test_3_status_reports_missing_api_credentials_cleanly(self):
        settings.dhan_api_secret = None
        service = DhanAuthService(settings)

        import asyncio
        result = asyncio.run(service.generate_consent())

        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], "CREDENTIALS_MISSING")
        self.assertIn("DHAN_API_SECRET", result["message"])

    def test_4_status_reports_needs_reauth_when_api_ready_but_no_token(self):
        service = DhanAuthService(settings)

        status = service.status()

        self.assertEqual(status["status"], "NEEDS_REAUTH")
        self.assertFalse(status["active_token_available"])
        self.assertEqual(status["order_placement"], "DISABLED")

    def test_5_data_adapter_preflight_reports_needs_reauth(self):
        result = DhanDataAdapter(settings)._preflight()

        self.assertIsNotNone(result)
        self.assertEqual(result["status"], "NEEDS_REAUTH")
        self.assertIn("/api/dhan-auth/login", result["message"])

    def test_6_routes_return_status_shape(self):
        app = FastAPI()
        app.include_router(dhan_auth_router)
        client = TestClient(app)

        response = client.get("/api/dhan-auth/status")

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["provider"], "DHAN")
        self.assertEqual(data["usage"], "MARKET_DATA_AUTH_ONLY")
        self.assertEqual(data["order_placement"], "DISABLED")
        self.assertFalse(data["token_exposed"])

    def test_7_login_route_redirects_to_dhan_login(self):
        app = FastAPI()
        app.include_router(dhan_auth_router)
        client = TestClient(app)

        with patch(
            "app.services.dhan_auth_service.DhanAuthService.generate_consent",
            new=AsyncMock(return_value={
                "ok": True,
                "login_url": "https://auth.test/login/consentApp-login?consentAppId=abc",
            }),
        ):
            response = client.get("/api/dhan-auth/login", follow_redirects=False)

        self.assertEqual(response.status_code, 307)
        self.assertEqual(response.headers["location"], "https://auth.test/login/consentApp-login?consentAppId=abc")


if __name__ == "__main__":
    unittest.main()
