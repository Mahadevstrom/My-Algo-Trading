from datetime import datetime, time as datetime_time, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from app.audit.audit_logger import AuditLogger
from app.config import settings
from app.db.database import SessionLocal
from app.market.live_candle_builder import LiveCandleBuilderError, normalize_timeframe
from app.market.live_candle_store import live_candle_store
from app.models.instrument import InstrumentMaster
from app.models.live_candle import LiveCandleRecord
from app.schemas.live_candle import LiveCandle, LiveInstrumentMetadata, LiveMarketSnapshot
from app.schemas.live_feed import NormalizedTick
from app.services.live_feed_service import get_live_feed_service


class LiveMarketMonitorService:
    def __init__(self) -> None:
        self.store = live_candle_store
        self.running = False
        self.source = "DHAN_WS"
        self.last_error: str | None = None
        self.last_stale_audit_at: datetime | None = None
        self.auto_start_attempts = 0
        self.last_auto_start_at: datetime | None = None
        self.last_auto_start_status: str | None = None

    async def start(self, db: Session) -> dict[str, Any]:
        live_feed = get_live_feed_service()
        feed_status = live_feed.status()
        if not settings.enable_dhan_websocket:
            return {
                "ok": False,
                "status": "WEBSOCKET_DISABLED",
                "message": "Live feed is disabled. Enable Dhan WebSocket before starting live monitor.",
                "status_snapshot": await self.status(),
            }
        if not feed_status["connected"]:
            return {
                "ok": False,
                "status": "LIVE_FEED_DISCONNECTED",
                "message": "Live feed is not connected. Start /api/live-feed/start first.",
                "status_snapshot": await self.status(),
            }
        if self.running:
            return {"ok": True, "status": "ALREADY_RUNNING", "message": "Live market monitor is already running."}
        auto_subscribe = await live_feed.ensure_default_subscriptions(db)
        live_feed.register_tick_listener(self.process_tick)
        self.running = True
        self.last_error = None
        AuditLogger().log(db, "LIVE_MONITOR_STARTED", "Live market monitor started.", source="LIVE_MONITOR")
        AuditLogger().log(
            db,
            "LIVE_CANDLE_BUILDER_STARTED",
            "Live candle builder started.",
            source="LIVE_MONITOR",
            payload={"timeframes": settings.live_candle_timeframes_list, "auto_subscribe": auto_subscribe},
        )
        return {"ok": True, "status": "STARTED", "message": "Live market monitor started.", "auto_subscribe": auto_subscribe, "snapshot": await self.status()}

    async def stop(self, db: Session) -> dict[str, Any]:
        get_live_feed_service().unregister_tick_listener(self.process_tick)
        was_running = self.running
        self.running = False
        AuditLogger().log(db, "LIVE_MONITOR_STOPPED", "Live market monitor stopped.", source="LIVE_MONITOR")
        AuditLogger().log(db, "LIVE_CANDLE_BUILDER_STOPPED", "Live candle builder stopped.", source="LIVE_MONITOR")
        return {
            "ok": True,
            "status": "STOPPED",
            "message": "Live market monitor stopped." if was_running else "Live market monitor was already stopped.",
        }

    async def status(self) -> dict[str, Any]:
        live_feed_status = get_live_feed_service().status()
        symbols = await self.store.get_all_symbols()
        stale = await self.store.get_stale_symbols(settings.live_market_stale_after_seconds)
        return {
            "enabled": True,
            "running": self.running,
            "auto_start_enabled": settings.live_monitor_auto_start,
            "auto_start_attempts": self.auto_start_attempts,
            "last_auto_start_at": self.last_auto_start_at.isoformat() if self.last_auto_start_at else None,
            "last_auto_start_status": self.last_auto_start_status,
            "source": self.source,
            "live_feed_connected": live_feed_status["connected"],
            "subscribed_count": live_feed_status["subscribed_count"],
            "candle_symbols_count": len(symbols),
            "timeframes": settings.live_candle_timeframes_list,
            "last_tick_at": live_feed_status["last_tick_at"],
            "last_candle_at": self.store.last_candle_at,
            "stale_symbols_count": len(stale),
            "mode": settings.trading_mode,
            "live_order_status": settings.safety_status["live_order_status"],
            "store_live_candles": settings.store_live_candles,
            "error": self.last_error,
        }

    async def process_tick(self, tick: NormalizedTick) -> None:
        if not self.running:
            return
        try:
            with SessionLocal() as db:
                metadata = self._metadata_for_tick(db, tick)
            result = await self.store.upsert_tick(tick, metadata)
            if settings.store_live_candles:
                for candle in result["closed"]:
                    self._persist_closed_candle(candle)
        except Exception as exc:
            self.last_error = f"{type(exc).__name__}: {exc}"
            with SessionLocal() as db:
                AuditLogger().log(
                    db,
                    "LIVE_MONITOR_ERROR",
                    "Live market monitor could not process a tick.",
                    severity="WARNING",
                    source="LIVE_MONITOR",
                    payload={"error": self.last_error, "security_id": tick.security_id, "symbol": tick.symbol},
                )

    async def ingest_test_tick(self, db: Session, tick: NormalizedTick) -> dict[str, Any]:
        if not settings.enable_test_tick_ingest:
            return {
                "ok": False,
                "status": "TEST_TICK_INGEST_DISABLED",
                "message": "Test tick ingest is disabled. Set ENABLE_TEST_TICK_INGEST=true only for local testing.",
            }
        metadata = self._metadata_for_tick(db, tick)
        result = await self.store.upsert_tick(tick, metadata)
        return {
            "ok": True,
            "status": "INGESTED",
            "updated_count": len(result["updated"]),
            "closed_count": len(result["closed"]),
        }

    async def snapshot(self, symbol: str) -> dict[str, Any]:
        normalized_symbol = symbol.strip().upper()
        tick_result = await get_live_feed_service().tick_by_symbol(normalized_symbol)
        candle_snapshot = await self.store.get_snapshot(normalized_symbol)
        if not tick_result.get("ok") and not candle_snapshot:
            return {
                "ok": False,
                "status": "NO_DATA",
                "message": "No live tick or candle data available for this symbol.",
                "symbol": normalized_symbol,
            }
        tick = tick_result.get("tick") if tick_result.get("ok") else {}
        metadata = candle_snapshot.get("metadata") or {}
        latest_candles = candle_snapshot.get("latest_candles", {})
        ltp = tick.get("ltp") or _latest_close(latest_candles)
        previous_close = tick.get("close")
        change = round(ltp - previous_close, 4) if ltp is not None and previous_close else None
        change_percent = round((change / previous_close) * 100, 4) if change is not None and previous_close else None
        payload = LiveMarketSnapshot(
            symbol=normalized_symbol,
            security_id=tick.get("security_id") or candle_snapshot.get("security_id"),
            exchange_segment=tick.get("exchange_segment") or metadata.get("exchange_segment"),
            underlying=metadata.get("underlying") or normalized_symbol,
            expiry=metadata.get("expiry"),
            strike=metadata.get("strike"),
            option_type=metadata.get("option_type"),
            ltp=ltp,
            previous_close=previous_close,
            day_open=tick.get("open"),
            day_high=tick.get("high"),
            day_low=tick.get("low"),
            change=change,
            change_percent=change_percent,
            volume=tick.get("volume"),
            open_interest=tick.get("open_interest"),
            latest_tick_at=tick.get("received_at"),
            stale=_is_snapshot_stale(tick.get("received_at")),
            active_timeframes=sorted(latest_candles.keys()),
            latest_candles=latest_candles,
        )
        return {"ok": True, "snapshot": payload.model_dump(mode="json")}

    async def candles(self, symbol: str, timeframe: str, limit: int) -> dict[str, Any]:
        try:
            timeframe = normalize_timeframe(timeframe)
        except LiveCandleBuilderError as exc:
            return {"ok": False, "status": "INVALID_TIMEFRAME", "message": str(exc)}
        if limit < 1 or limit > 1000:
            return {"ok": False, "status": "INVALID_LIMIT", "message": "limit must be between 1 and 1000."}
        memory_items = await self.store.get_candles(symbol, timeframe, limit)
        persisted_items = self._persisted_candles_for_today(symbol, timeframe, limit)
        items = self._merge_candles(persisted_items, memory_items, limit)
        if not items:
            return {
                "ok": False,
                "status": "NO_CANDLE",
                "message": "No live candles available for this symbol/timeframe today.",
                "symbol": symbol.upper(),
                "timeframe": timeframe,
                "memory_count": 0,
                "persisted_count": 0,
                "warmup_source": "NONE",
                "items": [],
            }
        return {
            "ok": True,
            "symbol": symbol.upper(),
            "timeframe": timeframe,
            "count": len(items),
            "memory_count": len(memory_items),
            "persisted_count": len(persisted_items),
            "warmup_source": self._warmup_source(memory_items, persisted_items),
            "items": [item.model_dump(mode="json") for item in items],
        }

    async def latest_candle(self, symbol: str, timeframe: str) -> dict[str, Any]:
        try:
            timeframe = normalize_timeframe(timeframe)
        except LiveCandleBuilderError as exc:
            return {"ok": False, "status": "INVALID_TIMEFRAME", "message": str(exc)}
        memory_items = await self.store.get_candles(symbol, timeframe, 1)
        persisted_items = self._persisted_candles_for_today(symbol, timeframe, 1)
        items = self._merge_candles(persisted_items, memory_items, 1)
        candle = items[-1] if items else None
        if candle is None:
            return {
                "ok": False,
                "status": "NO_CANDLE",
                "message": "No live candle available for this symbol/timeframe today.",
                "symbol": symbol.upper(),
                "timeframe": timeframe,
                "memory_count": 0,
                "persisted_count": 0,
                "warmup_source": "NONE",
            }
        return {
            "ok": True,
            "memory_count": len(memory_items),
            "persisted_count": len(persisted_items),
            "warmup_source": self._warmup_source(memory_items, persisted_items),
            "candle": candle.model_dump(mode="json"),
        }

    async def market_state(self, symbol: str) -> dict[str, Any]:
        candles = await self._combined_candles(symbol, "5m", 5)
        timeframe = "5m"
        if not candles:
            candles = await self._combined_candles(symbol, "1m", 5)
            timeframe = "1m"
        if not candles:
            return {
                "ok": False,
                "status": "NO_DATA",
                "symbol": symbol.upper(),
                "direction": "UNKNOWN",
                "short_term_trend": "UNKNOWN",
                "volatility_state": "UNKNOWN",
                "data_status": "NO_DATA",
                "reason": "No live candles are available yet.",
            }
        last = candles[-1]
        direction = "SIDEWAYS"
        if last.close > last.open:
            direction = "BULLISH"
        elif last.close < last.open:
            direction = "BEARISH"
        closes = [candle.close for candle in candles]
        if len(closes) >= 3 and closes[-1] > closes[0]:
            trend = "UP"
        elif len(closes) >= 3 and closes[-1] < closes[0]:
            trend = "DOWN"
        else:
            trend = "SIDEWAYS"
        range_percent = ((last.high - last.low) / last.close * 100) if last.close else 0
        volatility = "LOW" if range_percent < 0.15 else "HIGH" if range_percent > 0.7 else "NORMAL"
        stale = _is_snapshot_stale(last.updated_at)
        return {
            "ok": True,
            "symbol": symbol.upper(),
            "direction": direction,
            "short_term_trend": trend,
            "volatility_state": volatility,
            "data_status": "STALE" if stale else "OK",
            "reason": f"Based on {len(candles)} recent live candles from {timeframe}.",
        }

    async def stale_symbols(self, db: Session) -> dict[str, Any]:
        items = await self.store.get_stale_symbols(settings.live_market_stale_after_seconds)
        if items:
            self._audit_stale_symbols(db, items)
        return {"ok": True, "count": len(items), "items": [_json_dates(item) for item in items]}

    async def symbols(self) -> dict[str, Any]:
        symbols = await self.store.get_all_symbols()
        return {"ok": True, "count": len(symbols), "symbols": symbols}

    async def option_snapshot(self, symbol: str) -> dict[str, Any]:
        result = await self.snapshot(symbol)
        if not result.get("ok"):
            return result
        snapshot = result["snapshot"]
        if snapshot.get("option_type") not in {"CE", "PE"}:
            return {
                "ok": False,
                "status": "NOT_OPTION_CONTRACT",
                "message": "Symbol is not currently tracked as an option contract.",
                "snapshot": snapshot,
            }
        return {"ok": True, "option_snapshot": snapshot}

    async def nifty_overview(self) -> dict[str, Any]:
        metadata = await self.store.tracked_metadata()
        nifty_items = [
            item for item in metadata if (item.underlying or item.symbol or "").upper() in {"NIFTY", "NIFTY 50"}
        ]
        snapshots = []
        for item in nifty_items:
            if item.symbol:
                result = await self.snapshot(item.symbol)
                if result.get("ok"):
                    snapshots.append(result["snapshot"])
        ce_count = sum(1 for item in nifty_items if item.option_type == "CE")
        pe_count = sum(1 for item in nifty_items if item.option_type == "PE")
        stale = await self.store.get_stale_symbols(settings.live_market_stale_after_seconds)
        return {
            "ok": True,
            "status": "OK" if snapshots else "NO_DATA",
            "message": None if snapshots else "No NIFTY live ticks/candles are tracked yet.",
            "nifty_snapshot": next((item for item in snapshots if item.get("option_type") is None), None),
            "option_snapshots": [item for item in snapshots if item.get("option_type") in {"CE", "PE"}],
            "ce_tracked_count": ce_count,
            "pe_tracked_count": pe_count,
            "stale_contracts": [item for item in stale if (item.get("symbol") or "").upper().startswith("NIFTY")],
            "active_timeframes": settings.live_candle_timeframes_list,
        }

    async def rebuild_from_ticks(self, db: Session) -> dict[str, Any]:
        ticks = await get_live_feed_service().store.recent_ticks()
        if not ticks:
            return {"ok": False, "status": "NO_TICKS", "message": "No recent ticks are available to rebuild candles."}
        updated = 0
        for tick in ticks:
            metadata = self._metadata_for_tick(db, tick)
            result = await self.store.upsert_tick(tick, metadata)
            updated += len(result["updated"])
        return {"ok": True, "status": "REBUILT", "ticks_used": len(ticks), "candles_updated": updated}

    async def clear_all(self, db: Session) -> dict[str, Any]:
        await self.store.clear_all()
        AuditLogger().log(db, "LIVE_CANDLE_STORE_RESET", "Live candle store reset.", source="LIVE_MONITOR")
        return {"ok": True, "status": "RESET", "message": "Live candle store cleared."}

    async def auto_start_if_configured(self) -> None:
        await self.ensure_running_after_feed_connected("BACKEND_STARTUP")

    async def ensure_running_after_feed_connected(self, trigger: str) -> dict[str, Any]:
        if not settings.live_monitor_auto_start:
            self.last_auto_start_status = "AUTO_START_DISABLED"
            return {"ok": True, "status": "AUTO_START_DISABLED"}
        if self.running:
            self.last_auto_start_status = "ALREADY_RUNNING"
            return {"ok": True, "status": "ALREADY_RUNNING"}

        feed_status = get_live_feed_service().status()
        if not feed_status.get("connected"):
            self.last_auto_start_status = "LIVE_FEED_DISCONNECTED"
            self.last_auto_start_at = datetime.now(timezone.utc)
            return {
                "ok": False,
                "status": "LIVE_FEED_DISCONNECTED",
                "message": "Live monitor auto-start is waiting for the live feed to connect.",
            }

        self.auto_start_attempts += 1
        self.last_auto_start_at = datetime.now(timezone.utc)
        with SessionLocal() as db:
            AuditLogger().log(
                db,
                "LIVE_MONITOR_AUTO_START_RETRY",
                "Live monitor auto-start retry triggered after live feed connection.",
                source="LIVE_MONITOR",
                payload={"trigger": trigger, "attempt": self.auto_start_attempts},
            )
            result = await self.start(db)
        self.last_auto_start_status = str(result.get("status", "UNKNOWN"))
        return result

    async def shutdown(self) -> None:
        self.running = False
        get_live_feed_service().unregister_tick_listener(self.process_tick)

    def _metadata_for_tick(self, db: Session, tick: NormalizedTick) -> LiveInstrumentMetadata:
        instrument = self._lookup_instrument(db, tick)
        if instrument is None:
            return LiveInstrumentMetadata(
                exchange_segment=tick.exchange_segment,
                security_id=tick.security_id,
                symbol=tick.symbol,
                underlying=tick.symbol,
            )
        return LiveInstrumentMetadata(
            exchange_segment=instrument.segment or tick.exchange_segment,
            security_id=instrument.security_id,
            symbol=instrument.trading_symbol or tick.symbol,
            underlying=instrument.underlying_symbol,
            option_type=instrument.option_type,
            strike=instrument.strike,
            expiry=instrument.expiry.isoformat() if instrument.expiry else None,
        )

    def _lookup_instrument(self, db: Session, tick: NormalizedTick) -> InstrumentMaster | None:
        query = select(InstrumentMaster).where(
            InstrumentMaster.source.in_(["DHAN_COMPACT", "DHAN_DETAILED"]),
            InstrumentMaster.security_id == tick.security_id,
        )
        if tick.exchange_segment:
            query = query.order_by((InstrumentMaster.segment == tick.exchange_segment).desc(), InstrumentMaster.id)
        else:
            query = query.order_by(InstrumentMaster.id)
        return db.scalar(query.limit(1))

    def _persist_closed_candle(self, candle: LiveCandle) -> None:
        with SessionLocal() as db:
            existing = db.scalar(
                select(LiveCandleRecord).where(
                    LiveCandleRecord.source == candle.source,
                    LiveCandleRecord.security_id == candle.security_id,
                    LiveCandleRecord.timeframe == candle.timeframe,
                    LiveCandleRecord.start_time == candle.start_time,
                )
            )
            values = candle.model_dump(exclude={"start_volume", "last_tick_at"})
            if existing:
                for key, value in values.items():
                    setattr(existing, key, value)
            else:
                db.add(LiveCandleRecord(**values))
            db.commit()

    async def _combined_candles(self, symbol: str, timeframe: str, limit: int) -> list[LiveCandle]:
        memory_items = await self.store.get_candles(symbol, timeframe, limit)
        persisted_items = self._persisted_candles_for_today(symbol, timeframe, limit)
        return self._merge_candles(persisted_items, memory_items, limit)

    def _persisted_candles_for_today(self, symbol: str, timeframe: str, limit: int) -> list[LiveCandle]:
        if not settings.store_live_candles:
            return []
        normalized_symbol = symbol.strip().upper()
        start_utc, end_utc = self._today_bounds_utc()
        query = (
            select(LiveCandleRecord)
            .where(
                LiveCandleRecord.timeframe == timeframe,
                LiveCandleRecord.start_time >= start_utc,
                LiveCandleRecord.start_time < end_utc,
                or_(
                    LiveCandleRecord.symbol == normalized_symbol,
                    LiveCandleRecord.security_id == normalized_symbol,
                    and_(
                        LiveCandleRecord.underlying == normalized_symbol,
                        LiveCandleRecord.option_type.is_(None),
                        LiveCandleRecord.strike.is_(None),
                    ),
                ),
            )
            .order_by(LiveCandleRecord.start_time.desc())
            .limit(max(1, min(int(limit), 1000)))
        )
        with SessionLocal() as db:
            records = list(db.scalars(query))
        return [self._record_to_candle(record) for record in reversed(records)]

    def _record_to_candle(self, record: LiveCandleRecord) -> LiveCandle:
        last_tick_at = record.updated_at or record.end_time or record.start_time
        start_time = self._normalized_stored_candle_time(record.start_time, last_tick_at)
        end_time = self._normalized_stored_candle_time(record.end_time, last_tick_at)
        return LiveCandle(
            source=record.source,
            exchange_segment=record.exchange_segment,
            security_id=record.security_id,
            symbol=record.symbol,
            underlying=record.underlying,
            option_type=record.option_type,
            strike=record.strike,
            expiry=str(record.expiry) if record.expiry else None,
            timeframe=record.timeframe,
            start_time=start_time,
            end_time=end_time,
            open=record.open,
            high=record.high,
            low=record.low,
            close=record.close,
            volume=record.volume,
            open_interest=record.open_interest,
            tick_count=record.tick_count,
            is_closed=record.is_closed,
            last_tick_at=last_tick_at,
            created_at=record.created_at or start_time,
            updated_at=record.updated_at or last_tick_at,
        )

    def _normalized_stored_candle_time(self, value: datetime, reference: datetime | None) -> datetime:
        if reference is None:
            return value
        normalized_value = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        normalized_reference = reference if reference.tzinfo else reference.replace(tzinfo=timezone.utc)
        if normalized_value.astimezone(timezone.utc) - normalized_reference.astimezone(timezone.utc) > timedelta(minutes=30):
            return normalized_value - timedelta(hours=5, minutes=30)
        return value

    def _merge_candles(self, persisted_items: list[LiveCandle], memory_items: list[LiveCandle], limit: int) -> list[LiveCandle]:
        by_key: dict[tuple[str, str, datetime], LiveCandle] = {}
        for candle in persisted_items:
            by_key[(str(candle.security_id), candle.timeframe, candle.start_time)] = candle
        for candle in memory_items:
            by_key[(str(candle.security_id), candle.timeframe, candle.start_time)] = candle
        return sorted(by_key.values(), key=lambda item: item.start_time)[-max(1, min(int(limit), 1000)):]

    def _today_bounds_utc(self) -> tuple[datetime, datetime]:
        timezone_name = settings.session_gate_timezone or "Asia/Kolkata"
        try:
            market_tz = ZoneInfo(timezone_name)
        except Exception:
            market_tz = timezone(timedelta(hours=5, minutes=30))
        today = datetime.now(market_tz).date()
        start_local = datetime.combine(today, datetime_time.min, tzinfo=market_tz)
        end_local = start_local + timedelta(days=1)
        return start_local.astimezone(timezone.utc), end_local.astimezone(timezone.utc)

    def _warmup_source(self, memory_items: list[LiveCandle], persisted_items: list[LiveCandle]) -> str:
        if memory_items and persisted_items:
            return "MEMORY_DB_MERGED"
        if persisted_items:
            return "DB_FALLBACK"
        if memory_items:
            return "MEMORY"
        return "NONE"

    def _audit_stale_symbols(self, db: Session, items: list[dict[str, Any]]) -> None:
        now = datetime.now(timezone.utc)
        if self.last_stale_audit_at and (now - self.last_stale_audit_at).total_seconds() < 60:
            return
        self.last_stale_audit_at = now
        AuditLogger().log(
            db,
            "LIVE_MONITOR_STALE_SYMBOL_DETECTED",
            "Live monitor detected stale symbols.",
            severity="WARNING",
            source="LIVE_MONITOR",
            payload={"count": len(items), "items": [_json_dates(item) for item in items[:20]]},
        )


def _latest_close(latest_candles: dict[str, Any]) -> float | None:
    for timeframe in ("1m", "3m", "5m", "15m"):
        candle = latest_candles.get(timeframe)
        if candle:
            return candle.get("close")
    return None


def _is_snapshot_stale(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return True
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - value.astimezone(timezone.utc)).total_seconds() > settings.live_market_stale_after_seconds


def _json_dates(item: dict[str, Any]) -> dict[str, Any]:
    return {key: value.isoformat() if isinstance(value, datetime) else value for key, value in item.items()}


live_market_monitor_service = LiveMarketMonitorService()


def get_live_market_monitor_service() -> LiveMarketMonitorService:
    return live_market_monitor_service
