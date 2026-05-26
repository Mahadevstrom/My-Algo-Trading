import asyncio
from collections import deque
from datetime import datetime, timezone

from app.config import settings
from app.schemas.live_feed import NormalizedTick


class LiveTickStore:
    def __init__(self, max_buffer_size: int | None = None) -> None:
        self.max_buffer_size = max_buffer_size or settings.live_tick_buffer_size
        self._ticks_by_security_id: dict[str, NormalizedTick] = {}
        self._security_id_by_symbol: dict[str, str] = {}
        self._recent_ticks: deque[NormalizedTick] = deque(maxlen=self.max_buffer_size)
        self._lock = asyncio.Lock()
        self.last_tick_at: datetime | None = None

    async def update(self, tick: NormalizedTick) -> NormalizedTick:
        async with self._lock:
            stored_tick = self._merge_with_existing_price_tick(self._ticks_by_security_id.get(tick.security_id), tick)
            self._ticks_by_security_id[tick.security_id] = stored_tick
            if stored_tick.symbol:
                self._security_id_by_symbol[stored_tick.symbol.upper()] = stored_tick.security_id
            self._recent_ticks.append(tick)
            self.last_tick_at = tick.received_at
            return stored_tick

    async def get_by_security_id(self, security_id: str) -> NormalizedTick | None:
        async with self._lock:
            return self._ticks_by_security_id.get(str(security_id))

    async def get_by_symbol(self, symbol: str) -> NormalizedTick | None:
        async with self._lock:
            security_id = self._security_id_by_symbol.get(symbol.strip().upper())
            return self._ticks_by_security_id.get(security_id) if security_id else None

    async def all_ticks(self) -> list[NormalizedTick]:
        async with self._lock:
            return list(self._ticks_by_security_id.values())

    async def recent_ticks(self) -> list[NormalizedTick]:
        async with self._lock:
            return list(self._recent_ticks)

    async def clear(self) -> None:
        async with self._lock:
            self._ticks_by_security_id.clear()
            self._security_id_by_symbol.clear()
            self._recent_ticks.clear()
            self.last_tick_at = None

    def last_tick_age_seconds(self) -> float | None:
        if self.last_tick_at is None:
            return None
        return round((datetime.now(timezone.utc) - self.last_tick_at).total_seconds(), 2)

    def is_stale(self, stale_after_seconds: int | None = None) -> bool:
        age = self.last_tick_age_seconds()
        if age is None:
            return True
        return age > (stale_after_seconds or settings.dhan_ws_stale_after_seconds)

    def _merge_with_existing_price_tick(self, existing: NormalizedTick | None, tick: NormalizedTick) -> NormalizedTick:
        incoming_has_price = tick.ltp is not None and tick.ltp > 0
        existing_has_price = existing is not None and existing.ltp is not None and existing.ltp > 0
        if existing is None or incoming_has_price or not existing_has_price:
            return tick

        data = existing.model_dump()
        incoming = tick.model_dump()
        for field in ("source", "exchange_segment", "security_id", "symbol", "open_interest", "oi_change"):
            if incoming.get(field) is not None:
                data[field] = incoming[field]
        data["raw_payload"] = {
            "merged_partial_tick": True,
            "price_received_at": existing.received_at.isoformat(),
            "partial_received_at": tick.received_at.isoformat(),
            "price_raw_payload": self._base_price_payload(existing.raw_payload),
            "partial_raw_payload": tick.raw_payload,
        }
        return NormalizedTick(**data)

    def _base_price_payload(self, raw_payload: object) -> object:
        if isinstance(raw_payload, dict) and raw_payload.get("merged_partial_tick"):
            return raw_payload.get("price_raw_payload")
        return raw_payload


live_tick_store = LiveTickStore()
