import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.audit.audit_logger import AuditLogger
from app.config import settings
from app.db.database import SessionLocal
from app.services.dhan_rest_quota_service import get_dhan_rest_quota_service
from app.services.live_feed_service import get_live_feed_service
from app.services.live_market_monitor_service import get_live_market_monitor_service
from app.services.session_gate_service import get_session_gate_service


logger = logging.getLogger(__name__)


class FeedReliabilityService:
    """Watchdog for read-only market-data continuity."""

    def __init__(self) -> None:
        self.running = False
        self._task: asyncio.Task | None = None
        self.last_check_at: datetime | None = None
        self.last_recovery_at: datetime | None = None
        self.last_status: str = "NOT_STARTED"
        self.last_actions: list[str] = []
        self.last_error: str | None = None

    async def start(self) -> dict[str, Any]:
        if not settings.enable_feed_watchdog:
            return {"ok": False, "status": "DISABLED", "message": "Feed watchdog is disabled."}
        if self.running:
            return {"ok": True, "status": "ALREADY_RUNNING", "snapshot": await self.status()}
        self.running = True
        self._task = asyncio.create_task(self._loop(), name="feed-reliability-watchdog")
        return {"ok": True, "status": "STARTED", "snapshot": await self.status()}

    async def stop(self) -> dict[str, Any]:
        self.running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        self.last_status = "STOPPED"
        return {"ok": True, "status": "STOPPED"}

    async def auto_start_if_configured(self) -> None:
        if settings.enable_feed_watchdog:
            await self.start()

    async def shutdown(self) -> None:
        await self.stop()

    async def status(self) -> dict[str, Any]:
        feed_status = get_live_feed_service().status()
        monitor_status = await get_live_market_monitor_service().status()
        quota_status = get_dhan_rest_quota_service().status()
        health = self._derive_health(feed_status, monitor_status, quota_status)
        return {
            "enabled": settings.enable_feed_watchdog,
            "running": self.running,
            "auto_recover": settings.feed_watchdog_auto_recover,
            "restart_on_stale": settings.feed_watchdog_restart_on_stale,
            "interval_seconds": settings.feed_watchdog_interval_seconds,
            "health": health,
            "last_status": self.last_status,
            "last_check_at": self.last_check_at.isoformat() if self.last_check_at else None,
            "last_recovery_at": self.last_recovery_at.isoformat() if self.last_recovery_at else None,
            "last_actions": self.last_actions,
            "last_error": self.last_error,
            "live_feed": feed_status,
            "live_monitor": monitor_status,
            "dhan_rest_quota": quota_status,
            "mode": settings.trading_mode,
            "live_order_status": settings.safety_status["live_order_status"],
        }

    async def check_once(self, db: Session, auto_recover: bool | None = None) -> dict[str, Any]:
        auto_recover = settings.feed_watchdog_auto_recover if auto_recover is None else bool(auto_recover)
        self.last_check_at = datetime.now(timezone.utc)
        actions: list[str] = []
        errors: list[str] = []
        feed = get_live_feed_service()
        monitor = get_live_market_monitor_service()

        try:
            feed_status = feed.status()
            session_status = get_session_gate_service().status()
            market_open = bool(session_status.is_market_open)
            if settings.enable_dhan_websocket and auto_recover:
                if not feed_status.get("running") or not feed_status.get("connected"):
                    result = await feed.start(db, symbols=settings.live_feed_default_symbols_list, security_ids=[])
                    actions.append(f"live_feed_start:{result.get('status')}")
                    feed_status = feed.status()

                if feed_status.get("connected") and settings.live_feed_auto_subscribe:
                    subscribe = await feed.ensure_default_subscriptions(db)
                    if subscribe.get("status") not in {"ALREADY_SUBSCRIBED", "AUTO_SUBSCRIBE_DISABLED"}:
                        actions.append(f"default_subscribe:{subscribe.get('status')}")

                if (
                    settings.feed_watchdog_restart_on_stale
                    and market_open
                    and feed_status.get("connected")
                    and feed_status.get("stale")
                ):
                    await feed.stop(db)
                    restart = await feed.start(db, symbols=settings.live_feed_default_symbols_list, security_ids=[])
                    actions.append(f"stale_feed_restart:{restart.get('status')}")
                    feed_status = feed.status()

            monitor_status = await monitor.status()
            if auto_recover and settings.live_monitor_auto_start and feed_status.get("connected") and not monitor_status.get("running"):
                result = await monitor.start(db)
                actions.append(f"live_monitor_start:{result.get('status')}")
                monitor_status = await monitor.status()

            if auto_recover and monitor_status.get("running") and feed_status.get("connected"):
                stale_count = int(monitor_status.get("stale_symbols_count") or 0)
                if stale_count > 0:
                    rebuild = await monitor.rebuild_from_ticks(db)
                    actions.append(f"monitor_rebuild:{rebuild.get('status')}")
                    monitor_status = await monitor.status()

            quota_status = get_dhan_rest_quota_service().status()
            health = self._derive_health(feed_status, monitor_status, quota_status)
            self.last_status = health
            self.last_actions = actions
            self.last_error = None
            if actions:
                self.last_recovery_at = datetime.now(timezone.utc)
                AuditLogger().log(
                    db,
                    "FEED_WATCHDOG_RECOVERY",
                    "Feed watchdog performed market-data recovery actions.",
                    source="FEED_WATCHDOG",
                    payload={"actions": actions, "health": health},
                )
            return {
                "ok": True,
                "status": health,
                "actions": actions,
                "errors": errors,
                "market_open": market_open,
                "snapshot": await self.status(),
            }
        except Exception as exc:
            self.last_status = "ERROR"
            self.last_error = f"{type(exc).__name__}: {exc}"
            logger.warning("Feed watchdog check failed: %s", self.last_error)
            return {"ok": False, "status": "ERROR", "message": self.last_error, "actions": actions}

    async def _loop(self) -> None:
        while self.running:
            try:
                with SessionLocal() as db:
                    await self.check_once(db)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.last_status = "ERROR"
                self.last_error = f"{type(exc).__name__}: {exc}"
                logger.warning("Feed watchdog loop failed: %s", self.last_error)
            await asyncio.sleep(max(2, settings.feed_watchdog_interval_seconds))

    def _derive_health(
        self,
        feed_status: dict[str, Any],
        monitor_status: dict[str, Any],
        quota_status: dict[str, Any],
    ) -> str:
        if not settings.enable_dhan_websocket:
            return "WEBSOCKET_DISABLED"
        if not feed_status.get("connected"):
            return "FEED_DISCONNECTED"
        if feed_status.get("stale"):
            return "FEED_STALE"
        if settings.live_monitor_auto_start and not monitor_status.get("running"):
            return "MONITOR_STOPPED"
        if quota_status.get("cooldown_active"):
            return "REST_COOLDOWN"
        if int(monitor_status.get("stale_symbols_count") or 0) > 0:
            return "MONITOR_STALE_SYMBOLS"
        return "OK"


feed_reliability_service = FeedReliabilityService()


def get_feed_reliability_service() -> FeedReliabilityService:
    return feed_reliability_service
