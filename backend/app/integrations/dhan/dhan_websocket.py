import asyncio
import json
import struct
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import quote

import websockets

from app.config import Settings, settings
from app.schemas.live_feed import NormalizedTick


DHAN_WS_URL = "wss://api-feed.dhan.co"
SUBSCRIBE_QUOTE = 17
UNSUBSCRIBE_QUOTE = 18
DISCONNECT_FEED = 12

EXCHANGE_SEGMENT_BY_CODE = {
    0: "IDX_I",
    1: "NSE_EQ",
    2: "NSE_FNO",
    3: "NSE_CURRENCY",
    4: "BSE_EQ",
    5: "MCX_COMM",
    7: "BSE_CURRENCY",
    8: "BSE_FNO",
}


class DhanWebSocketClient:
    """Read-only Dhan market-feed WebSocket client. It never sends order messages."""

    def __init__(self, app_settings: Settings = settings) -> None:
        self.settings = app_settings
        self.connected = False
        self.running = False
        self.last_heartbeat: datetime | None = None
        self.last_tick_at: datetime | None = None
        self.reconnect_attempts = 0
        self.error: str | None = None
        self.subscriptions: dict[str, dict[str, str | None]] = {}
        self._websocket: Any = None
        self._task: asyncio.Task | None = None
        self._on_tick = None
        self._on_event = None

    def has_credentials(self) -> bool:
        return bool(self.settings.dhan_client_id and self.settings.dhan_access_token)

    def connection_url(self) -> str:
        token = quote(self.settings.dhan_access_token or "", safe="")
        client_id = quote(self.settings.dhan_client_id or "", safe="")
        return f"{DHAN_WS_URL}?version=2&token={token}&clientId={client_id}&authType=2"

    async def start(
        self,
        instruments: list[dict[str, str | None]] | None = None,
        on_tick=None,
        on_event=None,
    ) -> dict[str, Any]:
        if not self.settings.enable_dhan_websocket:
            return self._error("WEBSOCKET_DISABLED", "Dhan WebSocket is disabled. Set ENABLE_DHAN_WEBSOCKET=true.")
        if not self.has_credentials():
            return self._error("CREDENTIALS_MISSING", "Dhan WebSocket credentials missing. Add Dhan client id and access token.")
        if self.running:
            if instruments:
                await self.subscribe(instruments)
            return {"ok": True, "status": "ALREADY_RUNNING", "message": "Dhan WebSocket is already running."}

        self._on_tick = on_tick
        self._on_event = on_event
        self.running = True
        self.error = None
        if instruments:
            self._remember(instruments)
        self._task = asyncio.create_task(self._run_forever())
        return {"ok": True, "status": "STARTING", "message": "Dhan WebSocket read-only feed is starting."}

    async def stop(self) -> dict[str, Any]:
        self.running = False
        try:
            if self._websocket is not None:
                await self._websocket.send(json.dumps({"RequestCode": DISCONNECT_FEED}))
                await self._websocket.close()
        except Exception:
            pass
        if self._task is not None:
            self._task.cancel()
        self.connected = False
        self._websocket = None
        return {"ok": True, "status": "STOPPED", "message": "Dhan WebSocket feed stopped."}

    async def subscribe(self, instruments: list[dict[str, str | None]]) -> dict[str, Any]:
        self._remember(instruments)
        if not self.connected or self._websocket is None:
            return {"ok": True, "status": "QUEUED", "message": "Subscription queued until WebSocket is connected."}
        await self._send_subscription(instruments, SUBSCRIBE_QUOTE)
        return {"ok": True, "status": "SUBSCRIBED", "message": "Subscription message sent."}

    async def unsubscribe(self, instruments: list[dict[str, str | None]]) -> dict[str, Any]:
        if self.connected and self._websocket is not None:
            await self._send_subscription(instruments, UNSUBSCRIBE_QUOTE)
        for item in instruments:
            self.subscriptions.pop(str(item["security_id"]), None)
        return {"ok": True, "status": "UNSUBSCRIBED", "message": "Unsubscribe processed."}

    def status(self) -> dict[str, Any]:
        return {
            "enabled": self.settings.enable_dhan_websocket,
            "connected": self.connected,
            "running": self.running,
            "source": "DHAN_WS",
            "subscribed_count": len(self.subscriptions),
            "last_heartbeat": self.last_heartbeat,
            "last_tick_at": self.last_tick_at,
            "reconnect_attempts": self.reconnect_attempts,
            "error": self.error,
        }

    async def _run_forever(self) -> None:
        while self.running:
            try:
                async with websockets.connect(self.connection_url(), ping_interval=None) as websocket:
                    self._websocket = websocket
                    self.connected = True
                    self.error = None
                    was_reconnect = self.reconnect_attempts > 0
                    self.reconnect_attempts = 0
                    self.last_heartbeat = datetime.now(timezone.utc)
                    if self._on_event:
                        if was_reconnect:
                            await self._on_event("LIVE_FEED_RECONNECTED", "Dhan WebSocket reconnected.")
                        else:
                            await self._on_event("LIVE_FEED_STARTED", "Dhan WebSocket connected.")
                    if self.subscriptions:
                        await self._send_subscription(list(self.subscriptions.values()), SUBSCRIBE_QUOTE)
                    stale_timeout = max(15, self.settings.dhan_ws_stale_after_seconds * 2)
                    while self.running:
                        message = await asyncio.wait_for(websocket.recv(), timeout=stale_timeout)
                        self.last_heartbeat = datetime.now(timezone.utc)
                        tick = self.normalize_message(message)
                        if tick is not None:
                            self.last_tick_at = tick.received_at
                            if self._on_tick:
                                await self._on_tick(tick)
            except asyncio.TimeoutError as exc:
                self.connected = False
                self._websocket = None
                raise RuntimeError(
                    f"Dhan WebSocket stale for {stale_timeout}s; reconnecting."
                ) from exc
            except asyncio.CancelledError:
                break
            except Exception as exc:
                self.connected = False
                if not self.running:
                    break
                self.error = f"{type(exc).__name__}: {exc}"
                if self._on_event:
                    await self._on_event("LIVE_FEED_ERROR", self.error)
                if not self.settings.dhan_ws_reconnect or not self.running:
                    break
                self.reconnect_attempts += 1
                if self.reconnect_attempts > self.settings.dhan_ws_max_reconnect_attempts:
                    self.error = "Dhan WebSocket reconnect attempts exhausted."
                    break
                if self._on_event:
                    await self._on_event("LIVE_FEED_RECONNECT_ATTEMPT", f"Reconnect attempt {self.reconnect_attempts}.")
                await asyncio.sleep(min(60.0, self.settings.dhan_ws_reconnect_base_seconds * self.reconnect_attempts))
        self.connected = False
        self.running = False

    async def _send_subscription(self, instruments: list[dict[str, str | None]], request_code: int) -> None:
        if self._websocket is None:
            return
        for chunk in _chunks(instruments, 100):
            payload = {
                "RequestCode": request_code,
                "InstrumentCount": len(chunk),
                "InstrumentList": [
                    {"ExchangeSegment": item["exchange_segment"], "SecurityId": str(item["security_id"])}
                    for item in chunk
                ],
            }
            await self._websocket.send(json.dumps(payload))

    def _remember(self, instruments: list[dict[str, str | None]]) -> None:
        for item in instruments:
            self.subscriptions[str(item["security_id"])] = {
                "exchange_segment": item.get("exchange_segment"),
                "security_id": str(item["security_id"]),
                "symbol": item.get("symbol"),
            }

    def normalize_message(self, message: Any) -> NormalizedTick | None:
        if isinstance(message, str):
            return None
        data = bytes(message)
        if len(data) < 8:
            return None
        response_code = data[0]
        exchange_code = data[3]
        security_id = str(struct.unpack_from("<I", data, 4)[0])
        exchange_segment = EXCHANGE_SEGMENT_BY_CODE.get(exchange_code)
        subscription = self.subscriptions.get(security_id, {})
        received_at = datetime.now(timezone.utc)
        raw: dict[str, Any] = {
            "response_code": response_code,
            "message_length": _safe_unpack("<H", data, 1),
            "exchange_code": exchange_code,
        }
        base = {
            "source": "DHAN_WS",
            "exchange_segment": exchange_segment or subscription.get("exchange_segment"),
            "security_id": security_id,
            "symbol": subscription.get("symbol"),
            "received_at": received_at,
            "raw_payload": raw,
        }

        try:
            if response_code in {1, 2} and len(data) >= 16:
                ltp = struct.unpack_from("<f", data, 8)[0]
                if ltp <= 0:
                    return None
                timestamp = _normalize_exchange_timestamp(_epoch_to_datetime(_safe_unpack("<I", data, 12)), received_at)
                return NormalizedTick(**base, ltp=round(float(ltp), 4), timestamp=timestamp)
            if response_code == 4 and len(data) >= 50:
                ltp = struct.unpack_from("<f", data, 8)[0]
                if ltp <= 0:
                    return None
                return NormalizedTick(
                    **base,
                    ltp=round(float(ltp), 4),
                    last_traded_quantity=int(struct.unpack_from("<H", data, 12)[0]),
                    timestamp=_normalize_exchange_timestamp(_epoch_to_datetime(_safe_unpack("<I", data, 14)), received_at),
                    average_traded_price=round(float(struct.unpack_from("<f", data, 18)[0]), 4),
                    volume=int(struct.unpack_from("<I", data, 22)[0]),
                    open=round(float(struct.unpack_from("<f", data, 34)[0]), 4),
                    close=round(float(struct.unpack_from("<f", data, 38)[0]), 4),
                    high=round(float(struct.unpack_from("<f", data, 42)[0]), 4),
                    low=round(float(struct.unpack_from("<f", data, 46)[0]), 4),
                )
            if response_code == 5 and len(data) >= 12:
                return NormalizedTick(**base, open_interest=int(struct.unpack_from("<I", data, 8)[0]))
            if response_code == 6 and len(data) >= 16:
                return NormalizedTick(
                    **base,
                    close=round(float(struct.unpack_from("<f", data, 8)[0]), 4),
                    open_interest=int(struct.unpack_from("<I", data, 12)[0]),
                )
            if response_code == 8 and len(data) >= 162:
                ltp = struct.unpack_from("<f", data, 8)[0]
                if ltp <= 0:
                    return None
                depth = _parse_depth(data, 62)
                best = depth[0] if depth else {}
                return NormalizedTick(
                    **base,
                    ltp=round(float(ltp), 4),
                    last_traded_quantity=int(struct.unpack_from("<H", data, 12)[0]),
                    timestamp=_normalize_exchange_timestamp(_epoch_to_datetime(_safe_unpack("<I", data, 14)), received_at),
                    average_traded_price=round(float(struct.unpack_from("<f", data, 18)[0]), 4),
                    volume=int(struct.unpack_from("<I", data, 22)[0]),
                    open_interest=int(struct.unpack_from("<I", data, 34)[0]),
                    open=round(float(struct.unpack_from("<f", data, 46)[0]), 4),
                    close=round(float(struct.unpack_from("<f", data, 50)[0]), 4),
                    high=round(float(struct.unpack_from("<f", data, 54)[0]), 4),
                    low=round(float(struct.unpack_from("<f", data, 58)[0]), 4),
                    bid_quantity=best.get("bid_quantity"),
                    ask_quantity=best.get("ask_quantity"),
                    bid_price=best.get("bid_price"),
                    ask_price=best.get("ask_price"),
                )
            if response_code == 50:
                self.error = f"Dhan feed disconnected with code {_safe_unpack('<H', data, 8)}."
        except (struct.error, ValueError, TypeError) as exc:
            self.error = f"Could not parse Dhan WebSocket packet: {type(exc).__name__}."
        return None

    def _error(self, status: str, message: str) -> dict[str, Any]:
        self.error = message
        return {"ok": False, "status": status, "message": message}


def _chunks(items: list[dict[str, str | None]], size: int) -> list[list[dict[str, str | None]]]:
    return [items[index : index + size] for index in range(0, len(items), size)]


def _safe_unpack(fmt: str, data: bytes, offset: int) -> int | None:
    try:
        return struct.unpack_from(fmt, data, offset)[0]
    except struct.error:
        return None


def _epoch_to_datetime(value: int | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromtimestamp(int(value), tz=timezone.utc)


def _normalize_exchange_timestamp(value: datetime | None, received_at: datetime) -> datetime | None:
    if value is None:
        return None
    # Dhan feed timestamps can arrive as IST wall-clock encoded as epoch seconds.
    # If parsed as UTC they appear 5h30m in the future and shift candle buckets.
    if value - received_at > timedelta(minutes=30):
        return value - timedelta(hours=5, minutes=30)
    return value


def _parse_depth(data: bytes, start: int) -> list[dict[str, Any]]:
    depth = []
    for index in range(5):
        offset = start + index * 20
        if len(data) < offset + 20:
            break
        depth.append(
            {
                "bid_quantity": int(struct.unpack_from("<I", data, offset)[0]),
                "ask_quantity": int(struct.unpack_from("<I", data, offset + 4)[0]),
                "bid_orders": int(struct.unpack_from("<H", data, offset + 8)[0]),
                "ask_orders": int(struct.unpack_from("<H", data, offset + 10)[0]),
                "bid_price": round(float(struct.unpack_from("<f", data, offset + 12)[0]), 4),
                "ask_price": round(float(struct.unpack_from("<f", data, offset + 16)[0]), 4),
            }
        )
    return depth
