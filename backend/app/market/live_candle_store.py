import asyncio
from collections import deque
from datetime import datetime, timezone
from typing import Any

from app.config import settings
from app.market.live_candle_builder import (
    SUPPORTED_LIVE_TIMEFRAMES,
    LiveCandleBuilder,
    floor_timestamp_to_timeframe,
    normalize_timeframe,
    tick_timestamp,
)
from app.schemas.live_candle import LiveCandle, LiveInstrumentMetadata
from app.schemas.live_feed import NormalizedTick


class LiveCandleStore:
    def __init__(self, max_history: int | None = None, timeframes: list[str] | None = None) -> None:
        self.max_history = max_history or settings.live_candle_max_history
        self.timeframes = timeframes or settings.live_candle_timeframes_list
        self.builder = LiveCandleBuilder()
        self._candles: dict[tuple[str, str], deque[LiveCandle]] = {}
        self._security_id_by_symbol: dict[str, str] = {}
        self._symbol_by_security_id: dict[str, str] = {}
        self._metadata_by_security_id: dict[str, LiveInstrumentMetadata] = {}
        self._lock = asyncio.Lock()
        self.last_candle_at: datetime | None = None

    async def upsert_tick(
        self,
        tick: NormalizedTick,
        metadata: LiveInstrumentMetadata | None = None,
    ) -> dict[str, list[LiveCandle]]:
        if tick.ltp is None:
            return {"updated": [], "closed": []}
        metadata = metadata or LiveInstrumentMetadata(
            exchange_segment=tick.exchange_segment,
            security_id=tick.security_id,
            symbol=tick.symbol,
            underlying=tick.symbol,
        )
        async with self._lock:
            self._remember_metadata(tick, metadata)
            updated: list[LiveCandle] = []
            closed: list[LiveCandle] = []
            for timeframe in self.timeframes:
                result = self._upsert_timeframe(tick, timeframe, metadata)
                if result.get("closed"):
                    closed.append(result["closed"])
                if result.get("updated"):
                    updated.append(result["updated"])
            if updated:
                self.last_candle_at = max(candle.updated_at for candle in updated)
            return {"updated": updated, "closed": closed}

    async def upsert_backfilled_candles(
        self,
        candles: list[LiveCandle],
        metadata: LiveInstrumentMetadata,
    ) -> int:
        if not candles:
            return 0
        async with self._lock:
            synthetic_tick = NormalizedTick(
                source="DHAN_BACKFILL",
                exchange_segment=metadata.exchange_segment,
                security_id=metadata.security_id,
                symbol=metadata.symbol,
                ltp=candles[-1].close,
                timestamp=candles[-1].last_tick_at,
                received_at=candles[-1].updated_at,
                raw_payload={},
            )
            self._remember_metadata(synthetic_tick, metadata)
            upserted = 0
            for candle in sorted(candles, key=lambda item: (item.timeframe, item.start_time)):
                timeframe = normalize_timeframe(candle.timeframe)
                key = (str(candle.security_id), timeframe)
                existing = self._candles.setdefault(key, deque(maxlen=self.max_history))
                replaced = False
                for index, current in enumerate(existing):
                    if current.start_time == candle.start_time:
                        existing[index] = candle
                        replaced = True
                        break
                if not replaced:
                    existing.append(candle)
                    ordered = sorted(existing, key=lambda item: item.start_time)
                    existing.clear()
                    existing.extend(ordered[-self.max_history:])
                upserted += 1
            self.last_candle_at = max(candle.updated_at for candle in candles)
            return upserted

    async def get_latest_candle(self, symbol: str, timeframe: str) -> LiveCandle | None:
        security_id = await self._security_id_for_symbol(symbol)
        if security_id is None:
            return None
        return await self.get_latest_candle_by_security_id(security_id, timeframe)

    async def get_latest_candle_by_security_id(self, security_id: str, timeframe: str) -> LiveCandle | None:
        timeframe = normalize_timeframe(timeframe)
        async with self._lock:
            candles = self._candles.get((str(security_id), timeframe))
            return candles[-1] if candles else None

    async def get_candles(self, symbol: str, timeframe: str, limit: int = 100) -> list[LiveCandle]:
        security_id = await self._security_id_for_symbol(symbol)
        if security_id is None:
            return []
        return await self.get_candles_by_security_id(security_id, timeframe, limit)

    async def get_candles_by_security_id(self, security_id: str, timeframe: str, limit: int = 100) -> list[LiveCandle]:
        timeframe = normalize_timeframe(timeframe)
        limit = max(1, min(int(limit), 1000))
        async with self._lock:
            candles = list(self._candles.get((str(security_id), timeframe), []))
            return candles[-limit:]

    async def get_snapshot(self, symbol: str) -> dict[str, Any]:
        security_id = await self._security_id_for_symbol(symbol)
        if security_id is None:
            return {}
        async with self._lock:
            metadata = self._metadata_by_security_id.get(security_id)
            latest = {
                timeframe: self._candles[(security_id, timeframe)][-1].model_dump(mode="json")
                for timeframe in self.timeframes
                if self._candles.get((security_id, timeframe))
            }
        return {
            "security_id": security_id,
            "metadata": metadata.model_dump(mode="json") if metadata else None,
            "latest_candles": latest,
        }

    async def get_all_symbols(self) -> list[str]:
        async with self._lock:
            values = set(self._security_id_by_symbol.keys())
            values.update(
                metadata.symbol
                for metadata in self._metadata_by_security_id.values()
                if metadata.symbol
            )
            return sorted(values)

    async def get_stale_symbols(self, stale_after_seconds: int | None = None) -> list[dict[str, Any]]:
        stale_after = stale_after_seconds or settings.live_market_stale_after_seconds
        now = datetime.now(timezone.utc)
        stale: list[dict[str, Any]] = []
        async with self._lock:
            for security_id, metadata in self._metadata_by_security_id.items():
                latest_times = [
                    candles[-1].updated_at
                    for timeframe in self.timeframes
                    if (candles := self._candles.get((security_id, timeframe)))
                ]
                if not latest_times:
                    continue
                last_update = max(latest_times)
                age = (now - last_update.astimezone(timezone.utc)).total_seconds()
                if age > stale_after:
                    stale.append(
                        {
                            "symbol": metadata.symbol,
                            "security_id": security_id,
                            "age_seconds": round(age, 2),
                            "last_update_at": last_update,
                        }
                    )
        return stale

    async def clear_symbol(self, symbol: str) -> bool:
        async with self._lock:
            security_id = self._security_id_by_symbol.pop(symbol.strip().upper(), None)
            if not security_id:
                return False
            self._symbol_by_security_id.pop(security_id, None)
            self._metadata_by_security_id.pop(security_id, None)
            for timeframe in self.timeframes:
                self._candles.pop((security_id, timeframe), None)
            return True

    async def clear_all(self) -> None:
        async with self._lock:
            self._candles.clear()
            self._security_id_by_symbol.clear()
            self._symbol_by_security_id.clear()
            self._metadata_by_security_id.clear()
            self.last_candle_at = None

    async def tracked_metadata(self) -> list[LiveInstrumentMetadata]:
        async with self._lock:
            return list(self._metadata_by_security_id.values())

    def _upsert_timeframe(
        self,
        tick: NormalizedTick,
        timeframe: str,
        metadata: LiveInstrumentMetadata,
    ) -> dict[str, LiveCandle | None]:
        timeframe = normalize_timeframe(timeframe)
        key = (tick.security_id, timeframe)
        candles = self._candles.setdefault(key, deque(maxlen=self.max_history))
        bucket_start = floor_timestamp_to_timeframe(tick_timestamp(tick), timeframe)
        if not candles:
            candle = self.builder.build_new_candle(tick, timeframe, metadata)
            if candle is None:
                return {"updated": None, "closed": None}
            candles.append(candle)
            return {"updated": candle, "closed": None}

        current = candles[-1]
        if bucket_start == current.start_time:
            return {"updated": self.builder.update_candle(current, tick), "closed": None}
        if bucket_start > current.start_time:
            current.is_closed = True
            closed = current
            candle = self.builder.build_new_candle(tick, timeframe, metadata)
            if candle is None:
                return {"updated": None, "closed": closed}
            candles.append(candle)
            return {"updated": candle, "closed": closed}

        for candle in reversed(candles):
            if candle.start_time == bucket_start:
                return {"updated": self.builder.update_candle(candle, tick), "closed": None}
        return {"updated": current, "closed": None}

    def _remember_metadata(self, tick: NormalizedTick, metadata: LiveInstrumentMetadata) -> None:
        self._metadata_by_security_id[tick.security_id] = metadata
        symbol = metadata.symbol or tick.symbol
        if symbol:
            self._security_id_by_symbol[symbol.upper()] = tick.security_id
            self._symbol_by_security_id[tick.security_id] = symbol.upper()

    async def _security_id_for_symbol(self, symbol: str) -> str | None:
        async with self._lock:
            return self._security_id_by_symbol.get(symbol.strip().upper())


def configured_timeframes() -> list[str]:
    values = []
    for item in settings.live_candle_timeframes_list:
        cleaned = item.strip().lower()
        if cleaned in SUPPORTED_LIVE_TIMEFRAMES and cleaned not in values:
            values.append(cleaned)
    return values or ["1m", "3m", "5m", "15m"]


live_candle_store = LiveCandleStore(timeframes=configured_timeframes())
