import asyncio
from collections import deque
from datetime import datetime
from typing import Any

from app.config import settings
from app.schemas.data_quality import SymbolQualitySummary


class DataQualityStore:
    def __init__(self, max_history: int | None = None) -> None:
        self.max_history = max_history or settings.data_quality_max_history
        self._latest_by_security_id: dict[str, SymbolQualitySummary] = {}
        self._security_id_by_symbol: dict[str, str] = {}
        self._history_by_security_id: dict[str, deque[SymbolQualitySummary]] = {}
        self._lock = asyncio.Lock()
        self.last_check_at: datetime | None = None

    async def put(self, summary: SymbolQualitySummary) -> None:
        async with self._lock:
            key = summary.security_id or summary.symbol or "UNKNOWN"
            self._latest_by_security_id[key] = summary
            if summary.symbol:
                self._security_id_by_symbol[summary.symbol.upper()] = key
            history = self._history_by_security_id.setdefault(key, deque(maxlen=self.max_history))
            history.append(summary)
            self.last_check_at = _summary_time(summary)

    async def get_by_symbol(self, symbol: str) -> SymbolQualitySummary | None:
        async with self._lock:
            key = self._security_id_by_symbol.get(symbol.strip().upper())
            return self._latest_by_security_id.get(key) if key else None

    async def get_by_security_id(self, security_id: str) -> SymbolQualitySummary | None:
        async with self._lock:
            return self._latest_by_security_id.get(str(security_id))

    async def history_by_symbol(self, symbol: str, limit: int = 50) -> list[SymbolQualitySummary]:
        async with self._lock:
            key = self._security_id_by_symbol.get(symbol.strip().upper())
            if not key:
                return []
            return list(self._history_by_security_id.get(key, []))[-limit:]

    async def mismatches(self) -> list[dict[str, Any]]:
        async with self._lock:
            items = []
            for summary in self._latest_by_security_id.values():
                mismatch_checks = [check for check in summary.checks if check.status == "MISMATCH"]
                if mismatch_checks:
                    items.append(
                        {
                            "symbol": summary.symbol,
                            "security_id": summary.security_id,
                            "data_status": summary.data_status,
                            "checks": [check.model_dump(mode="json") for check in mismatch_checks],
                        }
                    )
            return items

    async def stale(self) -> list[dict[str, Any]]:
        async with self._lock:
            return [
                {
                    "symbol": summary.symbol,
                    "security_id": summary.security_id,
                    "data_status": summary.data_status,
                    "overall_score": summary.overall_score,
                    "last_tick_at": summary.last_tick_at,
                    "last_candle_at": summary.last_candle_at,
                }
                for summary in self._latest_by_security_id.values()
                if summary.stale or summary.data_status in {"STALE", "NO_DATA", "DISCONNECTED"}
            ]

    async def tracked_count(self) -> int:
        async with self._lock:
            return len(self._latest_by_security_id)


def _summary_time(summary: SymbolQualitySummary) -> datetime | None:
    timestamps = [check.timestamp for check in summary.checks]
    return max(timestamps) if timestamps else None


data_quality_store = DataQualityStore()
