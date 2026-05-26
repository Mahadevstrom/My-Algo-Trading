import asyncio
import csv
from datetime import datetime, timezone
from io import StringIO
from pathlib import Path
from time import monotonic
from typing import Any

import httpx

from app.config import Settings, settings


BACKEND_DIR = Path(__file__).resolve().parents[2]
INDSTOCKS_DATA_DIR = BACKEND_DIR / "data" / "indstocks"

VALID_INSTRUMENT_SOURCES = {"equity", "fno", "index"}
VALID_HISTORICAL_INTERVALS = {
    "1second",
    "5second",
    "10second",
    "15second",
    "1minute",
    "2minute",
    "3minute",
    "4minute",
    "5minute",
    "10minute",
    "15minute",
    "30minute",
    "60minute",
    "120minute",
    "180minute",
    "240minute",
    "1day",
    "1week",
    "1month",
}

HISTORICAL_INTERVAL_ALIASES = {
    "1s": "1second",
    "5s": "5second",
    "10s": "10second",
    "15s": "15second",
    "1m": "1minute",
    "2m": "2minute",
    "3m": "3minute",
    "4m": "4minute",
    "5m": "5minute",
    "10m": "10minute",
    "15m": "15minute",
    "30m": "30minute",
    "1h": "60minute",
    "2h": "120minute",
    "3h": "180minute",
    "4h": "240minute",
    "1d": "1day",
    "1w": "1week",
}

HISTORICAL_MAX_RANGE_MS = {
    "1second": 1 * 24 * 60 * 60 * 1000,
    "5second": 1 * 24 * 60 * 60 * 1000,
    "10second": 1 * 24 * 60 * 60 * 1000,
    "15second": 1 * 24 * 60 * 60 * 1000,
    "1minute": 7 * 24 * 60 * 60 * 1000,
    "2minute": 7 * 24 * 60 * 60 * 1000,
    "3minute": 7 * 24 * 60 * 60 * 1000,
    "4minute": 7 * 24 * 60 * 60 * 1000,
    "5minute": 7 * 24 * 60 * 60 * 1000,
    "10minute": 7 * 24 * 60 * 60 * 1000,
    "15minute": 7 * 24 * 60 * 60 * 1000,
    "30minute": 7 * 24 * 60 * 60 * 1000,
    "60minute": 14 * 24 * 60 * 60 * 1000,
    "120minute": 14 * 24 * 60 * 60 * 1000,
    "180minute": 14 * 24 * 60 * 60 * 1000,
    "240minute": 14 * 24 * 60 * 60 * 1000,
    "1day": 366 * 24 * 60 * 60 * 1000,
    "1week": 366 * 24 * 60 * 60 * 1000,
    "1month": 366 * 24 * 60 * 60 * 1000,
}


class IndstocksDataClient:
    """Read-only INDstocks REST adapter for market-data research and cross-checking."""

    _rate_limit_lock = asyncio.Lock()
    _last_request_at = 0.0
    _min_request_gap_seconds = 0.25

    def __init__(self, app_settings: Settings = settings) -> None:
        self.settings = app_settings
        self.timeout = httpx.Timeout(10.0)

    def has_credentials(self) -> bool:
        return self.settings.has_indstocks_credentials

    def status(self) -> dict[str, Any]:
        if not self.settings.indstocks_enabled:
            return {
                "provider": "INDSTOCKS",
                "enabled": False,
                "configured": self.has_credentials(),
                "connected": False,
                "status": "DISABLED",
                "message": "INDstocks is disabled. Set ENABLE_INDSTOCKS=true in backend/.env to use read-only market data.",
                "token_exposed": False,
                "usage": "MARKET_DATA_CROSS_CHECK_ONLY",
            }

        if not self.has_credentials():
            return {
                "provider": "INDSTOCKS",
                "enabled": True,
                "configured": False,
                "connected": False,
                "status": "CREDENTIALS_MISSING",
                "message": "INDstocks access token missing",
                "token_exposed": False,
                "usage": "MARKET_DATA_CROSS_CHECK_ONLY",
            }

        return {
            "provider": "INDSTOCKS",
            "enabled": True,
            "configured": True,
            "connected": True,
            "status": "CONFIGURED",
            "message": "INDstocks read-only market-data credentials are configured.",
            "token_exposed": False,
            "usage": "MARKET_DATA_CROSS_CHECK_ONLY",
        }

    async def get_profile(self) -> dict[str, Any]:
        return await self._get("/user/profile")

    async def get_funds(self) -> dict[str, Any]:
        return await self._get("/funds")

    async def download_instruments(self, source: str) -> dict[str, Any]:
        cleaned_source = source.strip().lower()
        if cleaned_source not in VALID_INSTRUMENT_SOURCES:
            return {
                "ok": False,
                "connected": False,
                "status": "INVALID_SOURCE",
                "message": "source must be one of: equity, fno, index.",
                "data": None,
            }

        response = await self._get(
            "/market/instruments",
            params={"source": cleaned_source},
            expect_csv=True,
        )
        if not response.get("ok"):
            return response

        csv_text = response.get("csv_text") or ""
        validation_error = _validate_csv_text(csv_text)
        if validation_error:
            return {
                "ok": False,
                "connected": response.get("connected", False),
                "status": "INVALID_CSV",
                "message": validation_error,
                "data": None,
            }

        INDSTOCKS_DATA_DIR.mkdir(parents=True, exist_ok=True)
        target_path = INDSTOCKS_DATA_DIR / f"indstocks_{cleaned_source}_instruments.csv"
        target_path.write_text(csv_text, encoding="utf-8", newline="")

        return {
            "ok": True,
            "connected": True,
            "status": "SAVED",
            "message": f"Downloaded INDstocks {cleaned_source} instruments CSV.",
            "source": cleaned_source,
            "file_path": str(target_path),
            "byte_count": len(csv_text.encode("utf-8")),
            "line_count": len([line for line in csv_text.splitlines() if line.strip()]),
        }

    async def get_ltp(self, scrip_codes: str) -> dict[str, Any]:
        return await self._get(
            "/market/quotes/ltp",
            params={"scrip-codes": _clean_scrip_codes(scrip_codes)},
        )

    async def get_full_quote(self, scrip_codes: str) -> dict[str, Any]:
        return await self._get(
            "/market/quotes/full",
            params={"scrip-codes": _clean_scrip_codes(scrip_codes)},
        )

    async def get_market_depth(self, scrip_codes: str) -> dict[str, Any]:
        return await self._get(
            "/market/quotes/mkt",
            params={"scrip-codes": _clean_scrip_codes(scrip_codes)},
        )

    async def get_historical(
        self,
        interval: str,
        scrip_codes: str,
        start_time: str,
        end_time: str,
    ) -> dict[str, Any]:
        cleaned_interval = _normalize_historical_interval(interval)
        endpoint = f"/market/historical/{cleaned_interval}"
        debug = _historical_debug(endpoint, cleaned_interval, start_time, end_time, "VALIDATING")
        if cleaned_interval not in VALID_HISTORICAL_INTERVALS:
            debug["status"] = "INVALID_INTERVAL"
            return {
                "ok": False,
                "connected": False,
                "status": "INVALID_INTERVAL",
                "message": "Unsupported interval. Use one of the documented INDstocks historical intervals.",
                "allowed_intervals": sorted(VALID_HISTORICAL_INTERVALS),
                "debug": debug,
                "data": None,
            }
        range_error = _validate_historical_range(cleaned_interval, start_time, end_time)
        if range_error is not None:
            debug["status"] = range_error["status"]
            return {**range_error, "debug": debug, "data": None}

        response = await self._get(
            endpoint,
            params={
                "scrip-codes": _clean_scrip_codes(scrip_codes),
                "start_time": start_time,
                "end_time": end_time,
            },
        )
        response["debug"] = _historical_debug(
            endpoint,
            cleaned_interval,
            start_time,
            end_time,
            str(response.get("status", "UNKNOWN")),
        )
        return response

    async def _get(
        self,
        endpoint: str,
        params: dict[str, Any] | None = None,
        expect_csv: bool = False,
    ) -> dict[str, Any]:
        preflight = self._preflight()
        if preflight is not None:
            return preflight

        await self._apply_rate_limit()

        url = f"{self.settings.indstocks_base_url.rstrip('/')}/{endpoint.lstrip('/')}"
        headers = {
            "Authorization": self.settings.indstocks_access_token or "",
            "Accept": "text/csv" if expect_csv else "application/json",
        }

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(url, headers=headers, params=params)
        except httpx.TimeoutException:
            return {
                "ok": False,
                "connected": False,
                "status": "TIMEOUT",
                "message": "INDstocks API request timed out.",
                "data": None,
            }
        except httpx.HTTPError as exc:
            return {
                "ok": False,
                "connected": False,
                "status": "API_ERROR",
                "message": f"INDstocks API request could not be completed: {type(exc).__name__}.",
                "data": None,
            }

        if response.status_code in {401, 403}:
            return {
                "ok": False,
                "connected": False,
                "status": "UNAUTHORIZED",
                "message": "INDstocks token expired or unauthorized. Update backend/.env with a valid access token.",
                "http_status": response.status_code,
                "data": None,
            }

        if response.status_code == 429:
            return {
                "ok": False,
                "connected": False,
                "status": "RATE_LIMITED",
                "message": "INDstocks rate limit reached. Wait before sending more market-data requests.",
                "http_status": response.status_code,
                "data": None,
            }

        if response.status_code >= 400:
            return {
                "ok": False,
                "connected": False,
                "status": "API_ERROR",
                "message": f"INDstocks API request failed with HTTP {response.status_code}.",
                "http_status": response.status_code,
                "data": None,
            }

        if expect_csv:
            return {
                "ok": True,
                "connected": True,
                "status": "CONNECTED",
                "message": "INDstocks CSV request completed.",
                "csv_text": response.text,
            }

        return {
            "ok": True,
            "connected": True,
            "status": "CONNECTED",
            "message": "INDstocks read-only request completed.",
            "data": _sanitize_response(_safe_json(response)),
        }

    def _preflight(self) -> dict[str, Any] | None:
        if not self.settings.indstocks_enabled:
            return {
                "ok": False,
                "connected": False,
                "status": "DISABLED",
                "message": "INDstocks is disabled. Set INDSTOCKS_ENABLED=true in backend/.env.",
                "data": None,
            }
        if not self.has_credentials():
            return {
                "ok": False,
                "connected": False,
                "status": "CREDENTIALS_MISSING",
                "message": "INDstocks access token missing",
                "data": None,
            }
        return None

    async def _apply_rate_limit(self) -> None:
        async with self._rate_limit_lock:
            elapsed = monotonic() - self.__class__._last_request_at
            wait_seconds = self._min_request_gap_seconds - elapsed
            if wait_seconds > 0:
                await asyncio.sleep(wait_seconds)
            self.__class__._last_request_at = monotonic()


def _safe_json(response: httpx.Response) -> Any:
    try:
        return response.json()
    except ValueError:
        return response.text


def _sanitize_response(value: Any) -> Any:
    if isinstance(value, dict):
        sanitized: dict[str, Any] = {}
        for key, item in value.items():
            lower_key = str(key).lower()
            if "token" in lower_key or "access" in lower_key or "authorization" in lower_key:
                sanitized[key] = "[REDACTED]"
            else:
                sanitized[key] = _sanitize_response(item)
        return sanitized
    if isinstance(value, list):
        return [_sanitize_response(item) for item in value]
    return value


def _normalize_historical_interval(interval: str) -> str:
    cleaned = interval.strip().lower()
    return HISTORICAL_INTERVAL_ALIASES.get(cleaned, cleaned)


def _parse_epoch_ms(value: str) -> int | None:
    cleaned = str(value).strip()
    if cleaned.isdigit():
        return int(cleaned)
    try:
        parsed = datetime.fromisoformat(cleaned.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return int(parsed.timestamp() * 1000)


def _validate_historical_range(interval: str, start_time: str, end_time: str) -> dict[str, Any] | None:
    start_ms = _parse_epoch_ms(start_time)
    end_ms = _parse_epoch_ms(end_time)
    if start_ms is None or end_ms is None:
        return {
            "ok": False,
            "connected": False,
            "status": "INVALID_TIME_RANGE",
            "message": "start_time and end_time must be Unix epoch milliseconds or ISO datetime values.",
        }
    if end_ms <= start_ms:
        return {
            "ok": False,
            "connected": False,
            "status": "INVALID_TIME_RANGE",
            "message": "end_time must be greater than start_time.",
        }
    max_range_ms = HISTORICAL_MAX_RANGE_MS[interval]
    requested_range_ms = end_ms - start_ms
    if requested_range_ms > max_range_ms:
        return {
            "ok": False,
            "connected": False,
            "status": "DATE_RANGE_TOO_LARGE",
            "message": "Requested INDstocks historical range exceeds the documented maximum for this interval.",
            "max_range_ms": max_range_ms,
            "requested_range_ms": requested_range_ms,
        }
    return None


def _historical_debug(endpoint: str, interval: str, start_time: str, end_time: str, status: str) -> dict[str, Any]:
    return {
        "endpoint_path": endpoint,
        "interval": interval,
        "range": {
            "start_time": start_time,
            "end_time": end_time,
        },
        "status": status,
        "token_exposed": False,
    }


def _clean_scrip_codes(scrip_codes: str) -> str:
    return ",".join(code.strip().upper() for code in scrip_codes.split(",") if code.strip())


def _validate_csv_text(csv_text: str) -> str | None:
    if not csv_text.strip():
        return "INDstocks instruments CSV response was empty."
    try:
        reader = csv.reader(StringIO(csv_text))
        first_row = next(reader, None)
    except csv.Error:
        return "INDstocks instruments response was not valid CSV."
    if not first_row or len(first_row) < 2:
        return "INDstocks instruments CSV response did not contain enough columns."
    return None
