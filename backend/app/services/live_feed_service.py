import json
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable

from sqlalchemy.orm import Session

from app.audit.audit_logger import AuditLogger
from app.config import settings
from app.db.database import SessionLocal
from app.engine.dhan_instrument_importer import DhanInstrumentImporter
from app.integrations.dhan.dhan_websocket import DhanWebSocketClient
from app.market.live_tick_store import live_tick_store
from app.models.live_tick import LiveTick
from app.schemas.live_feed import NormalizedTick


TickListener = Callable[[NormalizedTick], Awaitable[None]]


class LiveFeedService:
    def __init__(self) -> None:
        self.client = DhanWebSocketClient()
        self.store = live_tick_store
        self.last_persist_at_by_security_id: dict[str, datetime] = {}
        self.persist_interval_seconds = 5
        self.last_stale_audit_at: datetime | None = None
        self._tick_listeners: list[TickListener] = []

    async def start(
        self,
        db: Session,
        symbols: list[str] | None = None,
        security_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        symbols = self._effective_symbols(symbols)
        security_ids = security_ids or []
        AuditLogger().log(
            db,
            "LIVE_FEED_START_REQUESTED",
            "Dhan WebSocket start requested.",
            source="LIVE_FEED",
            payload={"symbols": symbols, "security_ids": security_ids},
        )
        if not settings.enable_dhan_websocket:
            return self._disabled_response()
        instruments = self._resolve_instruments(db, symbols, security_ids)
        if not instruments["ok"]:
            return instruments
        result = await self.client.start(
            instruments=instruments["items"],
            on_tick=self._on_tick,
            on_event=self._on_event,
        )
        return {**result, "status_snapshot": self.status()}

    async def stop(self, db: Session) -> dict[str, Any]:
        result = await self.client.stop()
        AuditLogger().log(
            db,
            "LIVE_FEED_STOPPED",
            "Dhan WebSocket feed stopped.",
            source="LIVE_FEED",
            payload=result,
        )
        return result

    async def subscribe(
        self,
        db: Session,
        symbols: list[str] | None = None,
        security_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        if not settings.enable_dhan_websocket:
            return self._disabled_response()
        instruments = self._resolve_instruments(db, self._effective_symbols(symbols), security_ids or [])
        if not instruments["ok"]:
            return instruments
        result = await self.client.subscribe(instruments["items"])
        AuditLogger().log(
            db,
            "LIVE_FEED_SUBSCRIBED",
            "Dhan WebSocket subscription requested.",
            source="LIVE_FEED",
            payload={"items": instruments["items"], "result": result},
        )
        return {**result, "items": instruments["items"]}

    async def unsubscribe(
        self,
        db: Session,
        symbols: list[str] | None = None,
        security_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        instruments = self._resolve_instruments(db, symbols or [], security_ids or [], allow_unmapped_security_ids=True)
        if not instruments["ok"]:
            return instruments
        result = await self.client.unsubscribe(instruments["items"])
        AuditLogger().log(
            db,
            "LIVE_FEED_UNSUBSCRIBED",
            "Dhan WebSocket unsubscribe requested.",
            source="LIVE_FEED",
            payload={"items": instruments["items"], "result": result},
        )
        return {**result, "items": instruments["items"]}

    def status(self) -> dict[str, Any]:
        client_status = self.client.status()
        return {
            **client_status,
            "stale": self.store.is_stale(settings.dhan_ws_stale_after_seconds),
            "last_tick_age_seconds": self.store.last_tick_age_seconds(),
            "mode": settings.trading_mode,
            "live_order_status": settings.safety_status["live_order_status"],
            "store_live_ticks": settings.store_live_ticks,
        }

    def health(self) -> dict[str, Any]:
        age = self.store.last_tick_age_seconds()
        if not self.client.connected:
            status = "DISCONNECTED"
        elif self.store.is_stale(settings.dhan_ws_stale_after_seconds):
            status = "STALE"
        else:
            status = "OK"
        return {
            "status": status,
            "connected": self.client.connected,
            "last_tick_age_seconds": age,
        }

    def audit_stale_if_needed(self, db: Session) -> None:
        if not self.client.connected or not self.store.is_stale(settings.dhan_ws_stale_after_seconds):
            return
        now = datetime.now(timezone.utc)
        if self.last_stale_audit_at and (now - self.last_stale_audit_at).total_seconds() < 60:
            return
        self.last_stale_audit_at = now
        AuditLogger().log(
            db,
            "LIVE_FEED_STALE",
            "Dhan WebSocket feed is stale. No recent tick has been received.",
            severity="WARNING",
            source="LIVE_FEED",
            payload={"last_tick_age_seconds": self.store.last_tick_age_seconds()},
        )

    async def tick_by_symbol(self, symbol: str) -> dict[str, Any]:
        tick = await self.store.get_by_symbol(symbol)
        if tick is None:
            return {
                "ok": False,
                "status": "NO_TICK",
                "message": "No tick received yet for this symbol.",
                "symbol": symbol.upper(),
            }
        return {"ok": True, "tick": tick.model_dump(mode="json")}

    async def tick_by_security_id(self, security_id: str) -> dict[str, Any]:
        tick = await self.store.get_by_security_id(security_id)
        if tick is None:
            return {
                "ok": False,
                "status": "NO_TICK",
                "message": "No tick received yet for this security ID.",
                "security_id": security_id,
            }
        return {"ok": True, "tick": tick.model_dump(mode="json")}

    async def ticks(self) -> dict[str, Any]:
        ticks = await self.store.all_ticks()
        return {
            "ok": True,
            "count": len(ticks),
            "items": [tick.model_dump(mode="json") for tick in ticks],
        }

    def register_tick_listener(self, listener: TickListener) -> None:
        if listener not in self._tick_listeners:
            self._tick_listeners.append(listener)

    def unregister_tick_listener(self, listener: TickListener) -> None:
        if listener in self._tick_listeners:
            self._tick_listeners.remove(listener)

    async def auto_start_if_configured(self) -> None:
        if not (settings.enable_dhan_websocket and settings.dhan_ws_auto_start):
            return
        with SessionLocal() as db:
            await self.start(db, symbols=settings.live_feed_default_symbols_list, security_ids=[])

    async def ensure_default_subscriptions(self, db: Session) -> dict[str, Any]:
        if not settings.live_feed_auto_subscribe:
            return {"ok": True, "status": "AUTO_SUBSCRIBE_DISABLED", "items": []}
        if not self.client.connected:
            return {"ok": False, "status": "LIVE_FEED_DISCONNECTED", "message": "Live feed is not connected."}
        if self.status().get("subscribed_count", 0) > 0:
            return {"ok": True, "status": "ALREADY_SUBSCRIBED", "items": []}
        return await self.subscribe(db, symbols=settings.live_feed_default_symbols_list, security_ids=[])

    async def shutdown(self) -> None:
        await self.client.stop()

    def _resolve_instruments(
        self,
        db: Session,
        symbols: list[str],
        security_ids: list[str],
        allow_unmapped_security_ids: bool = True,
    ) -> dict[str, Any]:
        importer = DhanInstrumentImporter()
        items: dict[str, dict[str, str | None]] = {}
        errors: list[str] = []

        for symbol in symbols:
            instrument = importer.lookup_symbol(db, symbol)
            if instrument is None:
                errors.append(f"Symbol {symbol.upper()} not found in Dhan instrument master.")
                continue
            items[instrument.security_id] = {
                "exchange_segment": instrument.segment,
                "security_id": instrument.security_id,
                "symbol": symbol.upper(),
            }

        for security_id in security_ids:
            security_id = str(security_id).strip()
            if not security_id.isdigit():
                errors.append(f"Invalid security ID: {security_id}.")
                continue
            if security_id in items:
                continue
            existing = self._lookup_by_security_id(db, security_id)
            if existing is not None:
                items[security_id] = {
                    "exchange_segment": existing.segment,
                    "security_id": security_id,
                    "symbol": existing.trading_symbol,
                }
            elif allow_unmapped_security_ids:
                items[security_id] = {
                    "exchange_segment": "NSE_EQ",
                    "security_id": security_id,
                    "symbol": None,
                }
            else:
                errors.append(f"Security ID {security_id} not found in Dhan instrument master.")

        if errors:
            return {"ok": False, "status": "INSTRUMENT_RESOLUTION_ERROR", "message": " ".join(errors)}
        if not items:
            return {"ok": True, "items": []}
        return {"ok": True, "items": list(items.values())}

    def _effective_symbols(self, symbols: list[str] | None) -> list[str]:
        cleaned = [item.strip().upper() for item in symbols or [] if item and item.strip()]
        if cleaned:
            return cleaned
        if settings.live_feed_auto_subscribe:
            return settings.live_feed_default_symbols_list
        return []

    def _lookup_by_security_id(self, db: Session, security_id: str):
        from sqlalchemy import case, select
        from app.models.instrument import InstrumentMaster

        segment_priority = case(
            (InstrumentMaster.segment == "NSE_EQ", 1),
            (InstrumentMaster.segment == "IDX_I", 2),
            (InstrumentMaster.segment == "NSE_FNO", 3),
            (InstrumentMaster.segment == "BSE_EQ", 4),
            (InstrumentMaster.segment == "BSE_FNO", 5),
            else_=99,
        )
        return db.scalar(
            select(InstrumentMaster)
            .where(
                InstrumentMaster.security_id == security_id,
                InstrumentMaster.source.in_(["DHAN_COMPACT", "DHAN_DETAILED"]),
            )
            .order_by(segment_priority, InstrumentMaster.source, InstrumentMaster.trading_symbol)
            .limit(1)
        )

    async def _on_tick(self, tick: NormalizedTick) -> None:
        await self.store.update(tick)
        for listener in list(self._tick_listeners):
            try:
                await listener(tick)
            except Exception as exc:
                await self._on_event("LIVE_MONITOR_ERROR", f"Tick listener failed: {type(exc).__name__}.")
        if settings.store_live_ticks:
            self._persist_tick_throttled(tick)

    async def _on_event(self, event_type: str, message: str) -> None:
        with SessionLocal() as db:
            AuditLogger().log(
                db,
                event_type,
                message,
                severity="WARNING" if "ERROR" in event_type or "STALE" in event_type else "INFO",
                source="LIVE_FEED",
            )
        if event_type in {"LIVE_FEED_STARTED", "LIVE_FEED_RECONNECTED"} and settings.live_monitor_auto_start:
            try:
                from app.services.live_market_monitor_service import get_live_market_monitor_service

                await get_live_market_monitor_service().ensure_running_after_feed_connected(event_type)
            except Exception as exc:
                with SessionLocal() as db:
                    AuditLogger().log(
                        db,
                        "LIVE_MONITOR_AUTO_START_RETRY_FAILED",
                        "Live monitor auto-start retry failed after live feed connection.",
                        severity="WARNING",
                        source="LIVE_MONITOR",
                        payload={"trigger": event_type, "error": f"{type(exc).__name__}: {exc}"},
                    )

    def _persist_tick_throttled(self, tick: NormalizedTick) -> None:
        if (
            (tick.ltp is None or tick.ltp <= 0)
            and tick.open_interest is None
            and tick.oi_change is None
        ):
            return
        last = self.last_persist_at_by_security_id.get(tick.security_id)
        if last and (tick.received_at - last).total_seconds() < self.persist_interval_seconds:
            return
        self.last_persist_at_by_security_id[tick.security_id] = tick.received_at
        with SessionLocal() as db:
            db.add(
                LiveTick(
                    source=tick.source,
                    exchange_segment=tick.exchange_segment,
                    security_id=tick.security_id,
                    symbol=tick.symbol,
                    ltp=tick.ltp,
                    volume=tick.volume,
                    open_interest=tick.open_interest,
                    timestamp=tick.timestamp,
                    received_at=tick.received_at,
                    raw_payload=json.dumps(tick.raw_payload, default=str),
                )
            )
            db.commit()

    def _disabled_response(self) -> dict[str, Any]:
        return {
            "ok": False,
            "status": "WEBSOCKET_DISABLED",
            "message": "Dhan WebSocket is disabled. Set ENABLE_DHAN_WEBSOCKET=true in backend/.env.",
            "status_snapshot": self.status(),
        }


live_feed_service = LiveFeedService()


def get_live_feed_service() -> LiveFeedService:
    return live_feed_service
