from datetime import date
import asyncio
from time import monotonic
from typing import Any

import httpx

from app.config import Settings, settings
from app.market.base import MarketDataProvider
from app.market.schemas import clean_response, utc_timestamp


class DhanDataAdapter(MarketDataProvider):
    """Read-only Dhan Data API adapter. No order placement methods belong here."""

    _last_calls: list[float] = []
    _rate_limit: int = 10
    _rate_window: int = 60
    _last_request_at = 0.0
    _min_request_gap_seconds = 3.0

    def __init__(self, app_settings: Settings = settings) -> None:
        self.settings = app_settings
        self.timeout = httpx.Timeout(10.0)

    def has_credentials(self) -> bool:
        return bool(self.settings.dhan_client_id and self.settings.dhan_access_token)

    def status(self) -> dict[str, Any]:
        has_client_id = bool(self.settings.dhan_client_id)
        has_access_token = bool(self.settings.dhan_access_token)

        if not self.settings.dhan_data_enabled:
            message = "Dhan Data API is disabled. Set DHAN_DATA_ENABLED=true in backend/.env."
        elif not self.has_credentials():
            message = "Dhan Data credentials missing. Add DHAN_CLIENT_ID and DHAN_ACCESS_TOKEN in backend/.env."
        else:
            message = "Dhan Data API is configured for read-only market data."

        return {
            "provider": "DHAN_DATA",
            "enabled": self.settings.dhan_data_enabled,
            "connected": self.settings.dhan_data_enabled and self.has_credentials(),
            "has_client_id": has_client_id,
            "has_access_token": has_access_token,
            "mode": "DHAN",
            "base_url": self.settings.dhan_base_url,
            "message": message,
            "token_exposed": False,
            "usage": "MARKET_DATA_ONLY",
        }

    async def get_ltp(self, instruments_by_segment: dict[str, list[int | str]]) -> dict[str, Any]:
        # Backup: public Dhan LTP request previously relied on _post-level throttling only.
        if not self._check_rate_limit():
            return self._rate_limited_response()
        response = await self._post("/marketfeed/ltp", _normalize_instruments_payload(instruments_by_segment))
        if response.get("ok"):
            response["normalized"] = self.normalize_ltp_response(response.get("data"))
        return response

    async def get_ohlc(self, instruments_by_segment: dict[str, list[int | str]]) -> dict[str, Any]:
        # Backup: public Dhan OHLC request previously relied on _post-level throttling only.
        if not self._check_rate_limit():
            return self._rate_limited_response()
        return await self._post("/marketfeed/ohlc", _normalize_instruments_payload(instruments_by_segment))

    async def get_quote(self, instruments_by_segment: dict[str, list[int | str]]) -> dict[str, Any]:
        # Backup: public Dhan quote request previously relied on _post-level throttling only.
        if not self._check_rate_limit():
            return self._rate_limited_response()
        response = await self._post("/marketfeed/quote", _normalize_instruments_payload(instruments_by_segment))
        if response.get("ok"):
            response["normalized"] = self.normalize_quote_response(response.get("data"))
        return response

    async def get_historical_daily(
        self,
        security_id: str,
        exchange_segment: str,
        instrument: str,
        from_date: date,
        to_date: date,
    ) -> dict[str, Any]:
        # Backup: public Dhan historical daily request previously relied on _post-level throttling only.
        if not self._check_rate_limit():
            return self._rate_limited_response()
        payload = {
            "securityId": str(security_id),
            "exchangeSegment": exchange_segment,
            "instrument": instrument,
            "fromDate": from_date.isoformat(),
            "toDate": to_date.isoformat(),
        }
        return await self._post("/charts/historical", payload)

    async def get_intraday(
        self,
        security_id: str,
        exchange_segment: str,
        instrument: str,
        interval: str,
        from_date: date,
        to_date: date,
    ) -> dict[str, Any]:
        # Backup: public Dhan intraday request previously relied on _post-level throttling only.
        if not self._check_rate_limit():
            return self._rate_limited_response()
        payload = {
            "securityId": str(security_id),
            "exchangeSegment": exchange_segment,
            "instrument": instrument,
            "interval": str(interval),
            "fromDate": from_date.isoformat(),
            "toDate": to_date.isoformat(),
        }
        return await self._post("/charts/intraday", payload)

    async def get_option_expiry_list(
        self,
        under_security_id: str,
        under_exchange_segment: str,
    ) -> dict[str, Any]:
        # Backup: public Dhan option-expiry request previously relied on _post-level throttling only.
        if not self._check_rate_limit():
            return self._rate_limited_response()
        payload = {
            "UnderlyingScrip": _number_if_possible(under_security_id),
            "UnderlyingSeg": under_exchange_segment,
        }
        return await self._post("/optionchain/expirylist", payload)

    async def get_option_chain(
        self,
        under_security_id: str,
        under_exchange_segment: str,
        expiry: date,
    ) -> dict[str, Any]:
        # Backup: public Dhan option-chain request previously relied on _post-level throttling only.
        if not self._check_rate_limit():
            return self._rate_limited_response()
        payload = {
            "UnderlyingScrip": _number_if_possible(under_security_id),
            "UnderlyingSeg": under_exchange_segment,
            "Expiry": expiry.isoformat(),
        }
        return await self._post("/optionchain", payload)

    def normalize_ltp_response(self, response_data: Any) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        payload = _extract_payload(response_data)
        if not isinstance(payload, dict):
            return items

        for exchange_segment, segment_data in payload.items():
            if not isinstance(segment_data, dict):
                continue
            for security_id, quote in segment_data.items():
                if not isinstance(quote, dict):
                    continue
                items.append(
                    {
                        "security_id": str(security_id),
                        "exchange_segment": str(exchange_segment),
                        "ltp": _first_present(quote, ["last_price", "lastPrice", "ltp", "LTP"]),
                        "source": "DHAN",
                        "timestamp": utc_timestamp(),
                    }
                )
        return items

    def normalize_quote_response(self, response_data: Any) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        payload = _extract_payload(response_data)
        if not isinstance(payload, dict):
            return items

        for exchange_segment, segment_data in payload.items():
            if not isinstance(segment_data, dict):
                continue
            for security_id, quote in segment_data.items():
                if not isinstance(quote, dict):
                    continue
                depth = quote.get("depth") if isinstance(quote.get("depth"), dict) else {}
                buy_depth = depth.get("buy") if isinstance(depth.get("buy"), list) else []
                sell_depth = depth.get("sell") if isinstance(depth.get("sell"), list) else []
                best_bid = buy_depth[0] if buy_depth and isinstance(buy_depth[0], dict) else {}
                best_ask = sell_depth[0] if sell_depth and isinstance(sell_depth[0], dict) else {}

                ohlc = quote.get("ohlc") if isinstance(quote.get("ohlc"), dict) else {}
                items.append(
                    {
                        "security_id": str(security_id),
                        "exchange_segment": str(exchange_segment),
                        "ltp": _first_present(quote, ["last_price", "lastPrice", "ltp", "LTP"]),
                        "open": _first_present(quote, ["open"], fallback=ohlc.get("open")),
                        "high": _first_present(quote, ["high"], fallback=ohlc.get("high")),
                        "low": _first_present(quote, ["low"], fallback=ohlc.get("low")),
                        "close": _first_present(
                            quote,
                            ["close", "previousClose", "prev_close", "prevClose"],
                            fallback=ohlc.get("close"),
                        ),
                        "volume": _first_present(quote, ["volume", "volume_traded", "volumeTraded"]),
                        "oi": _first_present(quote, ["oi", "open_interest", "openInterest"]),
                        "bid": _first_present(best_bid, ["price", "bid_price", "bidPrice"]),
                        "ask": _first_present(best_ask, ["price", "ask_price", "askPrice"]),
                        "source": "DHAN",
                        "timestamp": utc_timestamp(),
                    }
                )
        return items

    # Backup: async def _post(self, endpoint: str, payload: dict[str, Any]) -> dict[str, Any]
    async def _post(self, endpoint: str, payload: dict[str, Any]) -> dict[str, Any]:
        preflight = self._preflight()
        if preflight is not None:
            return preflight

        url = f"{self.settings.dhan_base_url.rstrip('/')}/{endpoint.lstrip('/')}"
        headers = {
            "access-token": self.settings.dhan_access_token or "",
            "client-id": self.settings.dhan_client_id or "",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

        try:
            await self._apply_rate_limit()
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(url, headers=headers, json=payload)
        except httpx.TimeoutException:
            return clean_response(
                ok=False,
                connected=False,
                status="TIMEOUT",
                message="Dhan Data API request timed out.",
            )
        except httpx.HTTPError as exc:
            return clean_response(
                ok=False,
                connected=False,
                status="API_ERROR",
                message=f"Dhan Data API request could not be completed: {type(exc).__name__}.",
            )

        if response.status_code in {401, 403}:
            return clean_response(
                ok=False,
                connected=False,
                status="UNAUTHORIZED",
                message="Dhan token expired or unauthorized. Update backend/.env with a fresh access token.",
                http_status=response.status_code,
            )

        if response.status_code == 429:
            return clean_response(
                ok=False,
                connected=False,
                status="RATE_LIMITED",
                message="Dhan Data API rate limit reached. Wait before sending more market-data requests.",
                http_status=response.status_code,
            )

        if response.status_code >= 400:
            return clean_response(
                ok=False,
                connected=False,
                status="API_ERROR",
                message=f"Dhan Data API request failed with HTTP {response.status_code}. Check subscription, security id, exchange segment, and request body.",
                http_status=response.status_code,
            )

        return clean_response(
            ok=True,
            connected=True,
            status="CONNECTED",
            message="Dhan Data API read-only request completed.",
            data=_sanitize_response(_safe_json(response)),
        )

    def _preflight(self) -> dict[str, Any] | None:
        if not self.settings.dhan_data_enabled:
            return clean_response(
                ok=False,
                connected=False,
                status="DISABLED",
                message="Dhan Data API is disabled. Set DHAN_DATA_ENABLED=true in backend/.env.",
            )
        if not self.has_credentials():
            return clean_response(
                ok=False,
                connected=False,
                status="CREDENTIALS_MISSING",
                message="Dhan Data credentials missing. Add DHAN_CLIENT_ID and DHAN_ACCESS_TOKEN in backend/.env.",
            )
        return None

    # Backup: def _check_rate_limit(self) -> bool
    def _check_rate_limit(self) -> bool:
        now = monotonic()
        cls = self.__class__
        cls._last_calls = [called_at for called_at in cls._last_calls if now - called_at < cls._rate_window]
        if len(cls._last_calls) >= cls._rate_limit:
            return False
        cls._last_calls.append(now)
        return True

    def _rate_limited_response(self) -> dict[str, Any]:
        return clean_response(
            ok=False,
            connected=False,
            status="RATE_LIMITED",
            message="Dhan API rate limit protection active",
        )

    async def _apply_rate_limit(self) -> None:
        elapsed = monotonic() - self.__class__._last_request_at
        wait_seconds = self._min_request_gap_seconds - elapsed
        if wait_seconds > 0:
            await asyncio.sleep(wait_seconds)
        self.__class__._last_request_at = monotonic()


DhanDataClient = DhanDataAdapter


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


def _extract_payload(response_data: Any) -> Any:
    if isinstance(response_data, dict):
        for key in ("data", "Data"):
            if key in response_data:
                return response_data[key]
    return response_data


def _first_present(source: dict[str, Any], keys: list[str], fallback: Any = None) -> Any:
    for key in keys:
        if key in source and source[key] is not None:
            return source[key]
    return fallback


def _number_if_possible(value: str) -> int | str:
    cleaned = str(value).strip()
    try:
        return int(cleaned)
    except ValueError:
        return cleaned


def _normalize_instruments_payload(
    instruments_by_segment: dict[str, list[int | str]]
) -> dict[str, list[int | str]]:
    return {
        str(segment).strip().upper(): [_number_if_possible(str(security_id)) for security_id in security_ids]
        for segment, security_ids in instruments_by_segment.items()
    }
