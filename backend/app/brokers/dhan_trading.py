from typing import Any

import httpx

from app.brokers.base import ReadOnlyBrokerClient
from app.config import Settings, settings


class DhanTradingClient(ReadOnlyBrokerClient):
    """Read-only Dhan Trading API wrapper. It intentionally has no order placement method."""

    def __init__(self, app_settings: Settings = settings) -> None:
        self.settings = app_settings
        self.timeout = httpx.Timeout(10.0)

    def status(self) -> dict[str, Any]:
        connected = self.settings.has_dhan_credentials

        import os
        import time
        from pathlib import Path

        env_path = Path(__file__).resolve().parents[2] / ".env"
        token_created_at = None
        seconds_remaining = None

        if env_path.exists():
            token_created_at = os.path.getmtime(env_path)
        else:
            config_path = Path(__file__).resolve().parents[1] / "config.py"
            if config_path.exists():
                token_created_at = os.path.getmtime(config_path)
            else:
                token_created_at = time.time() - 3600

        if connected and token_created_at:
            expires_at = token_created_at + 86400
            seconds_remaining = max(0.0, expires_at - time.time())

        return {
            "broker": "DHAN",
            "configured": connected,
            "connected": connected,
            "status": "CONFIGURED" if connected else "DISCONNECTED",
            "message": "Dhan credentials found in .env."
            if connected
            else "Dhan credentials missing",
            "token_exposed": False,
            "token_note": "Dhan access tokens are temporary and commonly expire after around 24 hours.",
            "order_placement": "DISABLED",
            "token_seconds_remaining": seconds_remaining,
            "token_created_at": token_created_at,
        }

    async def _get(self, endpoint: str) -> dict[str, Any]:
        if not self.settings.has_dhan_credentials:
            return {
                "ok": False,
                "connected": False,
                "status": "DISCONNECTED",
                "message": "Dhan credentials missing",
                "data": None,
            }

        url = f"{self.settings.dhan_trading_base_url.rstrip('/')}/{endpoint.lstrip('/')}"
        headers = {
            "client-id": self.settings.dhan_client_id or "",
            "access-token": self.settings.dhan_access_token or "",
            "Accept": "application/json",
        }

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(url, headers=headers)
            if response.status_code in {401, 403}:
                return {
                    "ok": False,
                    "connected": False,
                    "status": "UNAUTHORIZED",
                    "message": "Dhan token expired or unauthorized. Update .env with new 24-hour access token.",
                    "http_status": response.status_code,
                    "data": None,
                }
            if response.status_code >= 400:
                return {
                    "ok": False,
                    "connected": False,
                    "status": "API_ERROR",
                    "message": f"Dhan API request failed with HTTP {response.status_code}.",
                    "http_status": response.status_code,
                    "data": None,
                }
            return {
                "ok": True,
                "connected": True,
                "status": "CONNECTED",
                "message": "Dhan read-only request completed.",
                "data": _sanitize_response(_safe_json(response)),
            }
        except httpx.HTTPError as exc:
            return {
                "ok": False,
                "connected": False,
                "status": "API_ERROR",
                "message": f"Dhan API request could not be completed: {type(exc).__name__}.",
                "data": None,
            }

    async def funds(self) -> dict[str, Any]:
        return await self._get("fundlimit")

    async def positions(self) -> dict[str, Any]:
        return await self._get("positions")

    async def orderbook(self) -> dict[str, Any]:
        return await self._get("orders")

    async def tradebook(self) -> dict[str, Any]:
        return await self._get("trades")

    async def summary(self) -> dict[str, Any]:
        status_payload = self.status()
        live_orders_enabled = False

        if not self.settings.has_dhan_credentials:
            return {
                "dhan_status": status_payload,
                "funds_status": "DISCONNECTED",
                "positions_count": None,
                "orderbook_count": None,
                "tradebook_count": None,
                "token_message": "Dhan credentials missing",
                "live_orders_enabled": live_orders_enabled,
            }

        funds_payload = await self.funds()
        positions_payload = await self.positions()
        orderbook_payload = await self.orderbook()
        tradebook_payload = await self.tradebook()

        token_message = _token_message(
            funds_payload,
            positions_payload,
            orderbook_payload,
            tradebook_payload,
        )

        return {
            "dhan_status": {
                **status_payload,
                "connected": all(
                    payload.get("connected") is True
                    for payload in [
                        funds_payload,
                        positions_payload,
                        orderbook_payload,
                        tradebook_payload,
                    ]
                ),
            },
            "funds_status": funds_payload.get("status", "UNKNOWN"),
            "positions_count": _count_items(positions_payload.get("data")),
            "orderbook_count": _count_items(orderbook_payload.get("data")),
            "tradebook_count": _count_items(tradebook_payload.get("data")),
            "token_message": token_message,
            "live_orders_enabled": live_orders_enabled,
        }


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
            if "token" in lower_key or "access" in lower_key:
                sanitized[key] = "[REDACTED]"
            else:
                sanitized[key] = _sanitize_response(item)
        return sanitized
    if isinstance(value, list):
        return [_sanitize_response(item) for item in value]
    return value


def _count_items(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, list):
        return len(value)
    if isinstance(value, dict):
        for key in ("data", "positions", "orders", "trades", "orderBook", "tradeBook"):
            nested = value.get(key)
            if isinstance(nested, list):
                return len(nested)
        return 1
    return None


def _token_message(*payloads: dict[str, Any]) -> str:
    if any(payload.get("status") == "UNAUTHORIZED" for payload in payloads):
        return "Dhan token expired or unauthorized. Update .env with new 24-hour access token."
    if all(payload.get("connected") is True for payload in payloads):
        return "Dhan read-only connection is working."
    return "Dhan API returned an error. Check credentials, token freshness, and network connectivity."
