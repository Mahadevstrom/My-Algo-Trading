import os
import sys
import unittest
from datetime import date
from unittest.mock import patch

backend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.routes_participant_flow import router as participant_flow_router
from app.config import settings
from app.db.database import Base, get_db
from app.models.participant_flow import ParticipantFlowRecord
from app.services.participant_flow_nse_service import get_participant_flow_nse_service
from app.services.participant_flow_service import get_participant_flow_service


class TestParticipantFlow(unittest.TestCase):
    def setUp(self):
        self.original_enabled = settings.enable_participant_flow_engine
        self.original_web_fetch = settings.participant_flow_allow_web_fetch
        settings.enable_participant_flow_engine = True
        settings.participant_flow_allow_web_fetch = False
        get_participant_flow_nse_service().reset_for_tests()
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(bind=self.engine)
        self.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)
        self.db = self.SessionLocal()

        self.app = FastAPI()
        self.app.include_router(participant_flow_router)

        def override_db():
            db = self.SessionLocal()
            try:
                yield db
            finally:
                db.close()

        self.app.dependency_overrides[get_db] = override_db
        self.client = TestClient(self.app)

    def tearDown(self):
        self.db.close()
        self.app.dependency_overrides.clear()
        settings.enable_participant_flow_engine = self.original_enabled
        settings.participant_flow_allow_web_fetch = self.original_web_fetch
        get_participant_flow_nse_service().reset_for_tests()

    def test_1_no_data_response_includes_import_guidance(self):
        result = get_participant_flow_service().fii_dii_summary(self.db, lookback_days=10)
        self.assertFalse(result["ok"])
        self.assertTrue(result["import_required"])
        self.assertEqual(result["import_guidance"]["quick_import_endpoint"], "/api/participant-flow/import-fii-dii-cash")

    def test_2_quick_import_creates_fii_and_dii_cash_rows(self):
        response = self.client.post(
            "/api/participant-flow/import-fii-dii-cash",
            json={
                "market_date": date.today().isoformat(),
                "source": "MANUAL_FII_DII",
                "fii_cash_net": -1200.5,
                "dii_cash_net": 900.25,
                "is_provisional": True,
            },
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["ok"])
        self.assertTrue(payload["quick_import"])
        self.assertEqual(payload["inserted"], 2)

        count = self.db.scalar(select(func.count(ParticipantFlowRecord.id)))
        self.assertEqual(count, 2)
        summary = get_participant_flow_service().fii_dii_summary(self.db, lookback_days=10)
        self.assertTrue(summary["ok"])
        self.assertEqual(summary["fii_cash_net"], -1200.5)
        self.assertEqual(summary["dii_cash_net"], 900.25)
        self.assertEqual(summary["cash_context_bias"], "DII_SUPPORT")

    def test_3_status_reports_import_required_until_fresh_data_exists(self):
        status = get_participant_flow_service().status(self.db)
        self.assertFalse(status["data_ready"])
        self.assertEqual(status["readiness"], "IMPORT_REQUIRED")
        self.assertIn("import_guidance", status)

    def test_4_import_template_returns_full_and_quick_shapes(self):
        response = self.client.get("/api/participant-flow/import-template")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["ok"])
        self.assertIn("quick_import_endpoint", payload["guidance"])
        self.assertIn("nse_fetch_endpoint", payload["guidance"])
        self.assertEqual(len(payload["full_import_payload"]["records"]), 2)

    def test_5_nse_fetch_imports_public_fii_dii_rows(self):
        settings.participant_flow_allow_web_fetch = True

        class FakeResponse:
            def __init__(self, payload):
                self._payload = payload

            def raise_for_status(self):
                return None

            def json(self):
                return self._payload

        class FakeSession:
            def get(self, url, headers=None, timeout=None):
                if "fiidiiTradeReact" in url:
                    return FakeResponse(
                        [
                            {
                                "buyValue": "15536.74",
                                "category": "DII",
                                "date": "26-May-2026",
                                "netValue": "1361.43",
                                "sellValue": "14175.31",
                            },
                            {
                                "buyValue": "13127.02",
                                "category": "FII/FPI",
                                "date": "26-May-2026",
                                "netValue": "-2407.87",
                                "sellValue": "15534.89",
                            },
                        ]
                    )
                return FakeResponse({})

        with patch("app.services.participant_flow_nse_service.requests.Session", return_value=FakeSession()):
            result = get_participant_flow_nse_service().fetch_and_import(self.db, force=True)

        self.assertTrue(result["ok"])
        self.assertEqual(result["source"], "NSE_PUBLIC")
        self.assertEqual(result["inserted"], 2)
        rows = list(self.db.scalars(select(ParticipantFlowRecord).order_by(ParticipantFlowRecord.participant_type)))
        self.assertEqual({row.participant_type for row in rows}, {"DII", "FII"})
        self.assertEqual({row.source for row in rows}, {"NSE_PUBLIC"})

    def test_6_fetch_nse_route_uses_existing_import_pipeline(self):
        settings.participant_flow_allow_web_fetch = True

        def fake_fetch_and_import(db, force=False):
            return {
                "ok": True,
                "status": "IMPORTED",
                "inserted": 0,
                "updated": 0,
                "items": [],
            }

        with patch.object(get_participant_flow_nse_service(), "fetch_and_import", side_effect=fake_fetch_and_import):
            response = self.client.post("/api/participant-flow/fetch-nse")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["ok"])


if __name__ == "__main__":
    unittest.main()
