from datetime import datetime, timezone
from typing import Any

import requests
from sqlalchemy.orm import Session

from app.config import settings
from app.schemas.participant_flow import ParticipantFlowImportRequest
from app.services.participant_flow_import_service import get_participant_flow_import_service


NSE_FII_DII_PAGE = "https://www.nseindia.com/reports/fii-dii"
NSE_FII_DII_API = "https://www.nseindia.com/api/fiidiiTradeReact"


class ParticipantFlowNseService:
    def __init__(self) -> None:
        self._last_fetch_at: datetime | None = None
        self._last_payload: list[dict[str, Any]] | None = None

    def fetch_and_import(self, db: Session, force: bool = False) -> dict[str, Any]:
        if not settings.enable_participant_flow_engine:
            return {
                "ok": False,
                "status": "PARTICIPANT_FLOW_DISABLED",
                "message": "Participant Flow Engine is disabled by config.",
            }
        if not settings.participant_flow_allow_web_fetch:
            return {
                "ok": False,
                "status": "WEB_FETCH_DISABLED",
                "message": "NSE FII/DII fetch is disabled. Set PARTICIPANT_FLOW_ALLOW_WEB_FETCH=true.",
            }

        fetched = self.fetch_latest(force=force)
        if not fetched["ok"]:
            return fetched
        import_request = ParticipantFlowImportRequest(records=fetched["records"])
        imported = get_participant_flow_import_service().import_records(db, import_request)
        imported["source"] = "NSE_PUBLIC"
        imported["fetch_status"] = fetched["status"]
        imported["nse_record_count"] = len(fetched["raw"])
        imported["nse_raw"] = fetched["raw"]
        return imported

    def fetch_latest(self, force: bool = False) -> dict[str, Any]:
        now = datetime.now(timezone.utc)
        if (
            not force
            and self._last_fetch_at is not None
            and self._last_payload is not None
            and (now - self._last_fetch_at).total_seconds() < settings.participant_flow_cache_seconds
        ):
            raw = self._last_payload
            return {
                "ok": True,
                "status": "CACHE_HIT",
                "raw": raw,
                "records": self._to_records(raw),
                "fetched_at": self._last_fetch_at.isoformat(),
            }

        session = requests.Session()
        headers = self._headers()
        try:
            session.get(NSE_FII_DII_PAGE, headers=headers, timeout=10)
            response = session.get(NSE_FII_DII_API, headers=headers, timeout=10)
            response.raise_for_status()
            payload = response.json()
        except Exception as exc:
            return {
                "ok": False,
                "status": "NSE_FETCH_FAILED",
                "message": f"NSE FII/DII data could not be fetched: {type(exc).__name__}.",
                "error": str(exc),
                "source_url": NSE_FII_DII_PAGE,
            }

        if not isinstance(payload, list) or not payload:
            return {
                "ok": False,
                "status": "NSE_EMPTY_RESPONSE",
                "message": "NSE returned no FII/DII rows.",
                "raw": payload,
                "source_url": NSE_FII_DII_PAGE,
            }

        records = self._to_records(payload)
        if not records:
            return {
                "ok": False,
                "status": "NSE_PARSE_FAILED",
                "message": "NSE response did not contain recognizable FII/DII rows.",
                "raw": payload,
                "source_url": NSE_FII_DII_PAGE,
            }

        self._last_fetch_at = now
        self._last_payload = payload
        return {
            "ok": True,
            "status": "FETCHED",
            "raw": payload,
            "records": records,
            "fetched_at": now.isoformat(),
            "source_url": NSE_FII_DII_PAGE,
        }

    def _to_records(self, payload: list[dict[str, Any]]) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        for row in payload:
            try:
                participant = _participant_type(row.get("category"))
                if participant not in {"FII", "DII"}:
                    continue
                records.append(
                    {
                        "market_date": _parse_nse_date(row.get("date")),
                        "source": "NSE_PUBLIC",
                        "segment": "CASH",
                        "participant_type": participant,
                        "buy_value": _parse_float(row.get("buyValue")),
                        "sell_value": _parse_float(row.get("sellValue")),
                        "net_value": _parse_float(row.get("netValue")),
                        "is_provisional": True,
                    }
                )
            except Exception:
                continue
        return records

    def _headers(self) -> dict[str, str]:
        return {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/125.0 Safari/537.36",
            "Accept": "application/json,text/plain,*/*",
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": NSE_FII_DII_PAGE,
        }

    def reset_for_tests(self) -> None:
        self._last_fetch_at = None
        self._last_payload = None


def _participant_type(value: Any) -> str:
    text = str(value or "").strip().upper()
    if text.startswith("FII") or text.startswith("FPI"):
        return "FII"
    if text == "DII":
        return "DII"
    return "UNKNOWN"


def _parse_nse_date(value: Any):
    text = str(value or "").strip()
    return datetime.strptime(text, "%d-%b-%Y").date()


def _parse_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    return float(str(value).replace(",", "").strip())


participant_flow_nse_service = ParticipantFlowNseService()


def get_participant_flow_nse_service() -> ParticipantFlowNseService:
    return participant_flow_nse_service
