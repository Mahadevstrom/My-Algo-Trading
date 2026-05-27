from collections import defaultdict
from datetime import datetime, time, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.engine.dhan_instrument_importer import DhanInstrumentImporter
from app.engine.historical_data_service import HistoricalDataService
from app.market.live_candle_builder import candle_end_time, floor_timestamp_to_timeframe, normalize_timeframe
from app.models.candle import Candle
from app.schemas.live_candle import LiveCandle, LiveInstrumentMetadata
from app.services.live_market_monitor_service import get_live_market_monitor_service
from app.services.session_gate_service import get_session_gate_service


IST = ZoneInfo("Asia/Kolkata")


class StartupMarketBackfillService:
    """Backfills today's candle warmup when the backend starts late."""

    def __init__(self) -> None:
        self.last_run_at: datetime | None = None
        self.last_result: dict[str, Any] | None = None
        self.running = False

    def status(self) -> dict[str, Any]:
        return {
            "enabled": settings.enable_startup_market_backfill,
            "running": self.running,
            "symbols": settings.market_backfill_symbols_list,
            "source_interval": settings.market_backfill_source_interval,
            "target_timeframes": settings.live_candle_timeframes_list,
            "last_run_at": self.last_run_at.isoformat() if self.last_run_at else None,
            "last_result": self.last_result,
            "mode": settings.trading_mode,
            "live_order_status": settings.safety_status["live_order_status"],
        }

    async def auto_backfill_if_configured(self, db: Session) -> dict[str, Any]:
        if not settings.enable_startup_market_backfill:
            result = {"ok": True, "status": "DISABLED", "message": "Startup market backfill is disabled."}
            self.last_result = result
            return result
        return await self.backfill_today(db)

    async def backfill_today(
        self,
        db: Session,
        symbols: list[str] | None = None,
        source_interval: str | None = None,
    ) -> dict[str, Any]:
        if self.running:
            return {"ok": False, "status": "ALREADY_RUNNING", "message": "Market backfill is already running."}

        self.running = True
        self.last_run_at = datetime.now(timezone.utc)
        try:
            if not settings.dhan_data_enabled or not settings.has_dhan_credentials:
                result = {
                    "ok": True,
                    "status": "SKIPPED_DHAN_UNAVAILABLE",
                    "message": "Backfill skipped because Dhan Data API is disabled or credentials are missing.",
                    "historical_saved_count": 0,
                    "live_candles_projected": 0,
                }
                self.last_result = result
                return result

            session = get_session_gate_service().status()
            if settings.market_backfill_run_after_market_open and not _should_backfill_now(session.now_ist):
                result = {
                    "ok": True,
                    "status": "SKIPPED_BEFORE_MARKET_OPEN",
                    "message": "Backfill skipped because market has not opened yet.",
                    "now_ist": session.now_ist,
                }
                self.last_result = result
                return result

            source_interval = source_interval or settings.market_backfill_source_interval
            symbols = [item.strip().upper() for item in (symbols or settings.market_backfill_symbols_list) if item.strip()]
            window = _today_backfill_window(session.now_ist)
            results = []
            total_saved = 0
            total_projected = 0
            for symbol in symbols:
                item = await self._backfill_symbol(db, symbol, source_interval, window)
                results.append(item)
                total_saved += int(item.get("historical_saved_count") or 0)
                total_projected += int(item.get("live_candles_projected") or 0)

            result = {
                "ok": all(item.get("ok") for item in results) if results else True,
                "status": "COMPLETED" if all(item.get("ok") for item in results) else "PARTIAL_FAILURE",
                "source": "DHAN_INTRADAY_BACKFILL",
                "window": {
                    "from": window["from_str"],
                    "to": window["to_str"],
                    "trading_date": window["date_str"],
                },
                "symbols": symbols,
                "historical_saved_count": total_saved,
                "live_candles_projected": total_projected,
                "data_quality_note": (
                    "Backfilled candles recover price structure only. Missed tick-by-tick option data "
                    "and OI snapshots are not fully reconstructed."
                ),
                "results": results,
            }
            self.last_result = result
            return result
        finally:
            self.running = False

    async def _backfill_symbol(
        self,
        db: Session,
        symbol: str,
        source_interval: str,
        window: dict[str, Any],
    ) -> dict[str, Any]:
        download = await HistoricalDataService().download_intraday(
            db=db,
            symbol=symbol,
            interval=source_interval,
            from_date=window["from_str"],
            to_date=window["to_str"],
        )
        if not download.get("ok") and int(download.get("total_candles_saved") or 0) == 0:
            return {
                "ok": False,
                "symbol": symbol,
                "status": download.get("status", "DOWNLOAD_FAILED"),
                "message": download.get("message", "Backfill download failed."),
                "historical_saved_count": 0,
                "live_candles_projected": 0,
            }

        candles = _stored_candles_for_window(db, symbol, source_interval, window["from_dt"], window["to_dt"])
        metadata = _metadata_for_symbol(db, symbol, candles)
        if metadata is None:
            return {
                "ok": False,
                "symbol": symbol,
                "status": "METADATA_MISSING",
                "message": "Could not map symbol metadata for live candle projection.",
                "historical_saved_count": download.get("total_candles_saved", 0),
                "live_candles_projected": 0,
            }

        projected = _project_candles(candles, metadata, settings.live_candle_timeframes_list)
        count = await get_live_market_monitor_service().store.upsert_backfilled_candles(projected, metadata)
        return {
            "ok": True,
            "symbol": symbol,
            "status": "BACKFILLED",
            "historical_saved_count": download.get("total_candles_saved", 0),
            "stored_source_candles": len(candles),
            "live_candles_projected": count,
            "timeframes": sorted({item.timeframe for item in projected}),
            "message": "Backfilled candles were loaded into live monitor memory.",
        }


def _should_backfill_now(now_ist: str) -> bool:
    parsed = datetime.fromisoformat(now_ist)
    return parsed.time() >= _parse_time(settings.market_backfill_start_time)


def _today_backfill_window(now_ist: str) -> dict[str, Any]:
    now = datetime.fromisoformat(now_ist)
    if now.tzinfo is None:
        now = now.replace(tzinfo=IST)
    start_time = _parse_time(settings.market_backfill_start_time)
    end_time = _parse_time(settings.market_backfill_end_time)
    start = datetime.combine(now.date(), start_time, tzinfo=IST)
    end = min(now, datetime.combine(now.date(), end_time, tzinfo=IST))
    return {
        "date_str": now.date().isoformat(),
        "from_dt": start.astimezone(timezone.utc),
        "to_dt": end.astimezone(timezone.utc),
        "from_str": start.strftime("%Y-%m-%d %H:%M:%S"),
        "to_str": end.strftime("%Y-%m-%d %H:%M:%S"),
    }


def _stored_candles_for_window(
    db: Session,
    symbol: str,
    interval: str,
    from_dt: datetime,
    to_dt: datetime,
) -> list[Candle]:
    query_from = from_dt - timedelta(hours=6)
    query_to = to_dt + timedelta(hours=6)
    return list(
        db.scalars(
            select(Candle)
            .where(
                Candle.symbol == symbol.strip().upper(),
                Candle.interval == str(interval).strip(),
                Candle.timestamp >= query_from,
                Candle.timestamp <= query_to,
            )
            .order_by(Candle.timestamp)
        )
    )


def _metadata_for_symbol(db: Session, symbol: str, candles: list[Candle]) -> LiveInstrumentMetadata | None:
    instrument = DhanInstrumentImporter().lookup_symbol(db, symbol)
    if instrument is not None:
        return LiveInstrumentMetadata(
            exchange_segment=instrument.segment,
            security_id=instrument.security_id,
            symbol=instrument.trading_symbol or symbol.strip().upper(),
            underlying=instrument.underlying_symbol or symbol.strip().upper(),
            option_type=instrument.option_type,
            strike=instrument.strike,
            expiry=instrument.expiry.isoformat() if instrument.expiry else None,
        )
    if candles:
        first = candles[0]
        return LiveInstrumentMetadata(
            exchange_segment=first.exchange_segment,
            security_id=first.security_id,
            symbol=first.symbol,
            underlying=first.symbol,
        )
    return None


def _project_candles(
    candles: list[Candle],
    metadata: LiveInstrumentMetadata,
    target_timeframes: list[str],
) -> list[LiveCandle]:
    projected: list[LiveCandle] = []
    for timeframe in target_timeframes:
        normalized = normalize_timeframe(timeframe)
        groups: dict[datetime, list[Candle]] = defaultdict(list)
        for candle in candles:
            groups[floor_timestamp_to_timeframe(_as_aware(candle.timestamp), normalized)].append(candle)
        for start, items in sorted(groups.items()):
            ordered = sorted(items, key=lambda item: item.timestamp)
            volume_values = [item.volume for item in ordered if item.volume is not None]
            oi_values = [item.open_interest for item in ordered if item.open_interest is not None]
            projected.append(
                LiveCandle(
                    source="DHAN_BACKFILL",
                    exchange_segment=metadata.exchange_segment,
                    security_id=metadata.security_id,
                    symbol=metadata.symbol,
                    underlying=metadata.underlying,
                    option_type=metadata.option_type,
                    strike=metadata.strike,
                    expiry=metadata.expiry,
                    timeframe=normalized,
                    start_time=start,
                    end_time=candle_end_time(start, normalized),
                    open=float(ordered[0].open),
                    high=max(float(item.high) for item in ordered),
                    low=min(float(item.low) for item in ordered),
                    close=float(ordered[-1].close),
                    volume=int(sum(volume_values)) if volume_values else None,
                    open_interest=int(oi_values[-1]) if oi_values else None,
                    tick_count=len(ordered),
                    is_closed=True,
                    last_tick_at=_as_aware(ordered[-1].timestamp),
                    created_at=datetime.now(timezone.utc),
                    updated_at=datetime.now(timezone.utc),
                )
            )
    return projected


def _as_aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _parse_time(value: str) -> time:
    parts = [int(item) for item in value.split(":")]
    while len(parts) < 3:
        parts.append(0)
    return time(parts[0], parts[1], parts[2])


startup_market_backfill_service = StartupMarketBackfillService()


def get_startup_market_backfill_service() -> StartupMarketBackfillService:
    return startup_market_backfill_service
