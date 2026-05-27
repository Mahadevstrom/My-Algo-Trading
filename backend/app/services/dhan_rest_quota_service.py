import asyncio
import copy
import hashlib
import json
from collections import deque
from time import monotonic
from typing import Any

from app.config import settings


class DhanRestQuotaService:
    """Shared read-only REST quota guard for all Dhan market-data calls."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._request_times: deque[float] = deque()
        self._last_request_at = 0.0
        self._cooldown_until = 0.0
        self._cache: dict[str, tuple[float, dict[str, Any]]] = {}
        self._total_allowed = 0
        self._total_blocked = 0
        self._total_cache_hits = 0
        self._last_endpoint: str | None = None
        self._last_block_reason: str | None = None
        self._last_rate_limited_at: float | None = None

    async def cached_response(self, endpoint: str, payload: dict[str, Any]) -> dict[str, Any] | None:
        if settings.dhan_rest_response_cache_seconds <= 0:
            return None
        key = self._cache_key(endpoint, payload)
        cached = self._cache.get(key)
        if not cached:
            return None
        cached_at, response = cached
        if monotonic() - cached_at > settings.dhan_rest_response_cache_seconds:
            self._cache.pop(key, None)
            return None
        self._total_cache_hits += 1
        copied = copy.deepcopy(response)
        copied["cache_hit"] = True
        copied["quota_status"] = self.status()
        return copied

    async def acquire(self, endpoint: str, payload: dict[str, Any]) -> dict[str, Any]:
        async with self._lock:
            now = monotonic()
            self._purge_old_requests(now)
            self._purge_old_cache(now)

            if not settings.enable_dhan_rest_quota_guard:
                self._record_allowed(endpoint, now)
                return {"allowed": True, "status": "DISABLED", "waited_seconds": 0.0}

            if now < self._cooldown_until:
                retry_after = round(self._cooldown_until - now, 2)
                return self._blocked("COOLDOWN_ACTIVE", retry_after)

            limit = max(1, settings.dhan_rest_quota_per_minute)
            if len(self._request_times) >= limit:
                retry_after = round(max(1.0, 60.0 - (now - self._request_times[0])), 2)
                return self._blocked("LOCAL_QUOTA_EXHAUSTED", retry_after)

            min_gap = max(0.0, settings.dhan_rest_min_gap_seconds)
            waited = 0.0
            if self._last_request_at and min_gap > 0:
                wait_seconds = min_gap - (now - self._last_request_at)
                if wait_seconds > 0:
                    await asyncio.sleep(wait_seconds)
                    waited = wait_seconds
                    now = monotonic()
                    self._purge_old_requests(now)

            self._record_allowed(endpoint, now)
            return {"allowed": True, "status": "ALLOWED", "waited_seconds": round(waited, 2)}

    def record_response(self, endpoint: str, payload: dict[str, Any], response: dict[str, Any]) -> None:
        status = str(response.get("status") or "").upper()
        now = monotonic()
        if status == "RATE_LIMITED" or response.get("http_status") == 429:
            self._last_rate_limited_at = now
            self._cooldown_until = max(
                self._cooldown_until,
                now + max(1.0, settings.dhan_rest_rate_limit_cooldown_seconds),
            )
            return
        if response.get("ok") and settings.dhan_rest_response_cache_seconds > 0:
            self._cache[self._cache_key(endpoint, payload)] = (now, copy.deepcopy(response))

    def status(self) -> dict[str, Any]:
        now = monotonic()
        self._purge_old_requests(now)
        return {
            "enabled": settings.enable_dhan_rest_quota_guard,
            "limit_per_minute": settings.dhan_rest_quota_per_minute,
            "min_gap_seconds": settings.dhan_rest_min_gap_seconds,
            "response_cache_seconds": settings.dhan_rest_response_cache_seconds,
            "cooldown_seconds": settings.dhan_rest_rate_limit_cooldown_seconds,
            "requests_in_window": len(self._request_times),
            "remaining_in_window": max(0, settings.dhan_rest_quota_per_minute - len(self._request_times)),
            "cooldown_active": now < self._cooldown_until,
            "cooldown_remaining_seconds": round(max(0.0, self._cooldown_until - now), 2),
            "total_allowed": self._total_allowed,
            "total_blocked": self._total_blocked,
            "total_cache_hits": self._total_cache_hits,
            "last_endpoint": self._last_endpoint,
            "last_block_reason": self._last_block_reason,
            "last_rate_limited_at_monotonic": self._last_rate_limited_at,
        }

    def reset_for_tests(self) -> None:
        self._request_times.clear()
        self._last_request_at = 0.0
        self._cooldown_until = 0.0
        self._cache.clear()
        self._total_allowed = 0
        self._total_blocked = 0
        self._total_cache_hits = 0
        self._last_endpoint = None
        self._last_block_reason = None
        self._last_rate_limited_at = None

    def _record_allowed(self, endpoint: str, now: float) -> None:
        self._request_times.append(now)
        self._last_request_at = now
        self._last_endpoint = endpoint
        self._last_block_reason = None
        self._total_allowed += 1

    def _blocked(self, reason: str, retry_after: float) -> dict[str, Any]:
        self._total_blocked += 1
        self._last_block_reason = reason
        return {
            "allowed": False,
            "status": reason,
            "retry_after_seconds": retry_after,
        }

    def _purge_old_requests(self, now: float) -> None:
        while self._request_times and now - self._request_times[0] >= 60:
            self._request_times.popleft()

    def _purge_old_cache(self, now: float) -> None:
        ttl = settings.dhan_rest_response_cache_seconds
        if ttl <= 0:
            self._cache.clear()
            return
        stale_keys = [key for key, (cached_at, _) in self._cache.items() if now - cached_at > ttl]
        for key in stale_keys:
            self._cache.pop(key, None)

    def _cache_key(self, endpoint: str, payload: dict[str, Any]) -> str:
        body = json.dumps(payload or {}, sort_keys=True, default=str, separators=(",", ":"))
        digest = hashlib.sha256(body.encode("utf-8")).hexdigest()
        return f"{endpoint}:{digest}"


dhan_rest_quota_service = DhanRestQuotaService()


def get_dhan_rest_quota_service() -> DhanRestQuotaService:
    return dhan_rest_quota_service
