from __future__ import annotations

import json
from collections import Counter
from datetime import date, datetime, time, timedelta, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.audit.audit_logger import AuditLogger
from app.brokers.dhan_data import DhanDataAdapter
from app.brokers.dhan_trading import DhanTradingClient
from app.brokers.indstocks_data import IndstocksDataClient
from app.config import settings
from app.models.audit_log import AuditLog
from app.models.backtest_run import BacktestRun
from app.models.backtest_trade import BacktestTrade
from app.models.candle import Candle
from app.models.instrument import InstrumentMaster
from app.models.live_candle import LiveCandleRecord
from app.models.live_tick import LiveTick
from app.models.option_chain_snapshot import OptionChainSnapshot, OptionChainStrikeSnapshot
from app.models.participant_flow import ParticipantFlowRecord
from app.models.signal import SignalRecord
from app.models.trade import PaperTrade
from app.reports.export_formatters import format_report
from app.reports.report_recommendations import build_recommendations
from app.services.data_quality_service import get_data_quality_service
from app.services.live_feed_service import get_live_feed_service
from app.services.live_market_monitor_service import get_live_market_monitor_service
from app.services.live_paper_simulator_service import get_live_paper_simulator_service
from app.services.market_flow_service import get_market_flow_service
from app.services.participant_flow_service import get_participant_flow_service
from app.services.sector_breadth_service import get_sector_breadth_service
from app.services.strategy_evaluation_service import get_strategy_evaluation_service
from app.services.trade_journal_service import get_trade_journal_service


class ReportingService:
    def __init__(self) -> None:
        self._last_audit_at: dict[str, datetime] = {}

    def status(self) -> dict[str, Any]:
        return {
            "enabled": settings.enable_reporting_engine,
            "supported_formats": settings.reports_supported_formats_list,
            "default_lookback_days": settings.reports_default_lookback_days,
            "audit_lookback_days": settings.reports_audit_lookback_days,
            "store_snapshots": settings.reports_store_snapshots,
            "live_order_status": settings.safety_status["live_order_status"],
            "paper_only_safety_confirmed": _paper_only_confirmed(),
        }

    async def system_health(self, db: Session) -> dict[str, Any]:
        sections = {
            "backend": {"status": "OK", "generated_by": "REPORTING_ENGINE"},
            "settings": settings.public_dict(),
            "safety": settings.safety_status,
            "data_sources": {
                "dhan_data": DhanDataAdapter().status(),
                "dhan_trading": DhanTradingClient().status(),
                "indstocks": IndstocksDataClient().status(),
            },
            "live_feed": get_live_feed_service().status(),
            "live_monitor": await get_live_market_monitor_service().status(),
            "data_quality": await get_data_quality_service().status(),
            "live_paper": await get_live_paper_simulator_service().status(db),
            "strategy_evaluation": get_strategy_evaluation_service().status(),
            "market_flow": await get_market_flow_service().status(db),
            "participant_flow": get_participant_flow_service().status(db),
            "sector_breadth": get_sector_breadth_service().status(),
            "database_counts": self._database_counts(db),
        }
        warnings = self._health_warnings(sections)
        return self._report(db, "system_health", "OK" if not warnings else "WARNING", sections, warnings)

    async def daily_review(self, db: Session, report_date: date | None = None) -> dict[str, Any]:
        day = report_date or date.today()
        paper = self._paper_trade_summary(db, day)
        strategy_daily = await get_strategy_evaluation_service().daily_review(db)
        latest_v2 = get_strategy_evaluation_service().signal_v1_vs_v2(db).get("latest_v2")
        market_flow = await self.market_flow_summary(db, "NIFTY")
        sector = await self.sector_breadth_summary(db, "NIFTY")
        participant = self.participant_flow_summary(db, "NIFTY")
        dq = await self.data_quality_summary(db)
        audit = self.audit_summary(db, settings.reports_audit_lookback_days)
        trade_journal = get_trade_journal_service().daily_review(db, day, "NIFTY")
        sections = {
            "date": day.isoformat(),
            "paper_trades": paper,
            "trade_journal": trade_journal,
            "latest_signal_v2": latest_v2,
            "live_paper": await get_live_paper_simulator_service().status(db),
            "strategy_daily_review": strategy_daily,
            "market_flow": _compact_report(market_flow),
            "sector_breadth": _compact_report(sector),
            "participant_flow": _compact_report(participant),
            "data_quality": _compact_report(dq),
            "audit": _compact_report(audit),
        }
        warnings = []
        if paper["total_trades"] == 0:
            warnings.append("NO_TRADES for selected date.")
        warnings.extend(_collect_nested_warnings(sections))
        return self._report(db, "daily_review", "OK" if paper["total_trades"] else "NO_TRADES", sections, warnings, {"report_date": day.isoformat()})

    async def strategy_evaluation(self, db: Session) -> dict[str, Any]:
        service = get_strategy_evaluation_service()
        sections = {
            "status": service.status(),
            "summary": await service.summary(db),
            "health_score": service.health_score(db),
            "backtest_vs_paper": service.backtest_vs_paper(db),
            "signal_v1_vs_v2": service.signal_v1_vs_v2(db),
            "rejections": service.rejections(db),
            "data_quality_impact": service.data_quality_impact(db),
            "recommendation": service.recommendation(db),
        }
        warnings = _collect_status_warnings(sections)
        return self._report(db, "strategy_evaluation", "OK" if not warnings else "PARTIAL_DATA", sections, warnings)

    async def live_paper_summary(self, db: Session) -> dict[str, Any]:
        service = get_live_paper_simulator_service()
        sections = {
            "status": await service.status(db),
            "settings": service.settings_response(),
            "open_trades": await service.open_trades(db),
            "closed_trades": service.closed_trades(db),
            "performance": service.performance(db),
            "rejections": service.recent_rejections(),
        }
        warnings = []
        if not settings.enable_live_paper_simulator:
            warnings.append("Live paper simulator is disabled by config.")
        return self._report(db, "live_paper_summary", "OK", sections, warnings)

    async def market_flow_summary(self, db: Session, symbol: str = "NIFTY") -> dict[str, Any]:
        summary = await get_market_flow_service().summary(db, symbol)
        explanation = await get_market_flow_service().explain(db, symbol)
        sections = {
            "summary": summary,
            "explanation": explanation,
        }
        status = summary.get("status", "UNKNOWN")
        warnings = list(summary.get("warnings", []))
        return self._report(db, "market_flow_summary", status, sections, warnings)

    def participant_flow_summary(self, db: Session, symbol: str = "NIFTY") -> dict[str, Any]:
        service = get_participant_flow_service()
        context = service.context(db, symbol, settings.participant_flow_lookback_days)
        sections = {
            "status": service.status(db),
            "fii_dii": service.fii_dii_summary(db, settings.participant_flow_lookback_days),
            "derivatives": service.derivatives_summary(db, settings.participant_flow_lookback_days),
            "nifty_bias": service.nifty_bias(db, settings.participant_flow_lookback_days),
            "context": context,
            "test_data": self._participant_test_data(db),
        }
        warnings = list(context.get("warnings", []))
        test_data = sections["test_data"]
        if settings.reports_include_test_data_warnings and test_data["test_row_count"]:
            warnings.append(f"Participant-flow contains {test_data['test_row_count']} MANUAL_TEST/AUDIT_TEST rows.")
        warnings.append("Participant-flow mode is manual import; data can be delayed or provisional.")
        return self._report(db, "participant_flow_summary", context.get("status", "UNKNOWN"), sections, warnings)

    async def sector_breadth_summary(self, db: Session, index: str = "NIFTY") -> dict[str, Any]:
        summary = await get_sector_breadth_service().summary(db, index)
        sections = {
            "summary": summary,
            "heavyweights": await get_sector_breadth_service().heavyweights(db),
            "nifty_confirmation": await get_sector_breadth_service().nifty_confirmation(db),
        }
        warnings = list(summary.get("warnings", []))
        return self._report(db, "sector_breadth_summary", summary.get("status", "UNKNOWN"), sections, warnings)

    async def data_quality_summary(self, db: Session) -> dict[str, Any]:
        sections = {
            "status": await get_data_quality_service().status(),
            "stale": await get_data_quality_service().stale(),
            "mismatches": await get_data_quality_service().mismatches(),
            "recent_audit_events": self._audit_events(db, settings.reports_audit_lookback_days, source="DATA_QUALITY", limit=25),
        }
        warnings = _collect_status_warnings(sections)
        return self._report(db, "data_quality_summary", "OK" if not warnings else "WARNING", sections, warnings)

    def audit_summary(self, db: Session, lookback_days: int | None = None) -> dict[str, Any]:
        days = lookback_days or settings.reports_audit_lookback_days
        since = datetime.now(timezone.utc) - timedelta(days=days)
        events = list(db.scalars(select(AuditLog).where(AuditLog.created_at >= since).order_by(AuditLog.created_at.desc()).limit(settings.reports_max_audit_events)))
        event_counts = Counter(event.event_type for event in events)
        source_counts = Counter(event.source for event in events)
        severity_counts = Counter(event.severity for event in events)
        sections = {
            "lookback_days": days,
            "total_events": len(events),
            "event_counts": dict(event_counts),
            "source_counts": dict(source_counts),
            "severity_counts": dict(severity_counts),
            "error_events": [_audit_read(event) for event in events if event.severity in {"ERROR", "CRITICAL"}][:25],
            "latest_events": [_audit_read(event) for event in events[:25]],
        }
        return self._report(db, "audit_summary", "OK" if events else "NO_DATA", sections, [])

    async def export_report(self, db: Session, report_type: str, output_format: str) -> dict[str, Any]:
        if output_format not in settings.reports_supported_formats_list:
            return {"ok": False, "status": "INVALID_FORMAT", "message": "Use one of: " + ", ".join(settings.reports_supported_formats_list)}
        report = await self._report_by_type(db, report_type)
        formatted = format_report(report, output_format)
        now = datetime.now(timezone.utc)
        self._audit(db, "REPORT_EXPORT_GENERATED", f"Report export generated: {report_type}.{output_format}", "INFO")
        return {
            "ok": True,
            "filename": f"{report_type}_{now.strftime('%Y%m%d_%H%M%S')}.{output_format}",
            "generated_at": now.isoformat(),
            **formatted,
        }

    async def _report_by_type(self, db: Session, report_type: str) -> dict[str, Any]:
        normalized = report_type.strip().lower().replace("-", "_")
        if normalized == "daily_review":
            return await self.daily_review(db)
        if normalized == "strategy_evaluation":
            return await self.strategy_evaluation(db)
        if normalized == "system_health":
            return await self.system_health(db)
        raise ValueError("Unsupported export report type.")

    def _report(
        self,
        db: Session,
        report_type: str,
        status: str,
        sections: dict[str, Any],
        warnings: list[str],
        extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        report = {
            "ok": True,
            "report_type": report_type,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "trading_mode": settings.trading_mode,
            "live_order_status": settings.safety_status["live_order_status"],
            "report_status": status,
            "warnings": warnings,
            "errors": [],
            "paper_only_safety_confirmed": _paper_only_confirmed(),
            "sections": _sanitize(sections),
            **(extra or {}),
        }
        report["recommendations"] = build_recommendations(report)
        event_type = "REPORT_PARTIAL_DATA" if status in {"PARTIAL_DATA", "NO_DATA", "NO_TRADES"} else "REPORT_GENERATED"
        self._audit(db, event_type, f"{report_type} report generated.", "INFO")
        return report

    def _paper_trade_summary(self, db: Session, day: date) -> dict[str, Any]:
        start = datetime.combine(day, time.min, tzinfo=timezone.utc)
        end = datetime.combine(day, time.max, tzinfo=timezone.utc)
        trades = list(db.scalars(select(PaperTrade).where(PaperTrade.entry_time >= start, PaperTrade.entry_time <= end).order_by(PaperTrade.entry_time.desc())))
        open_trades = [trade for trade in trades if trade.status == "OPEN"]
        closed = [trade for trade in trades if trade.status != "OPEN"]
        wins = [trade for trade in closed if trade.result == "WIN"]
        losses = [trade for trade in closed if trade.result == "LOSS"]
        realized = round(sum((trade.pnl or 0.0) for trade in closed), 2)
        unrealized = round(sum((trade.unrealized_pnl or 0.0) for trade in open_trades), 2)
        return {
            "total_trades": len(trades),
            "open_trades": len(open_trades),
            "closed_trades": len(closed),
            "wins": len(wins),
            "losses": len(losses),
            "realized_pnl": realized,
            "unrealized_pnl": unrealized,
            "total_pnl": round(realized + unrealized, 2),
            "largest_win": max([trade.pnl for trade in wins], default=None),
            "largest_loss": min([trade.pnl for trade in losses], default=None),
        }

    def _database_counts(self, db: Session) -> dict[str, int | str]:
        models = {
            "instruments": InstrumentMaster,
            "signals": SignalRecord,
            "paper_trades": PaperTrade,
            "candles": Candle,
            "backtest_runs": BacktestRun,
            "backtest_trades": BacktestTrade,
            "audit_logs": AuditLog,
            "live_ticks": LiveTick,
            "live_candles": LiveCandleRecord,
            "option_chain_snapshots": OptionChainSnapshot,
            "option_chain_strike_snapshots": OptionChainStrikeSnapshot,
            "participant_flow_records": ParticipantFlowRecord,
        }
        counts: dict[str, int | str] = {}
        for name, model in models.items():
            try:
                counts[name] = int(db.scalar(select(func.count(model.id))) or 0)
            except Exception as exc:
                counts[name] = f"ERROR:{type(exc).__name__}"
        return counts

    def _participant_test_data(self, db: Session) -> dict[str, Any]:
        count = int(db.scalar(select(func.count(ParticipantFlowRecord.id)).where(ParticipantFlowRecord.source.in_(["MANUAL_TEST", "AUDIT_TEST"]))) or 0)
        return {"test_row_count": count, "sources": ["MANUAL_TEST", "AUDIT_TEST"] if count else []}

    def _audit_events(self, db: Session, lookback_days: int, source: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        since = datetime.now(timezone.utc) - timedelta(days=lookback_days)
        query = select(AuditLog).where(AuditLog.created_at >= since).order_by(AuditLog.created_at.desc()).limit(limit)
        if source:
            query = select(AuditLog).where(AuditLog.created_at >= since, AuditLog.source == source).order_by(AuditLog.created_at.desc()).limit(limit)
        return [_audit_read(event) for event in db.scalars(query)]

    def _health_warnings(self, sections: dict[str, Any]) -> list[str]:
        warnings = []
        if not _paper_only_confirmed():
            warnings.append("Paper-only safety flags are not fully confirmed.")
        if sections.get("data_sources", {}).get("indstocks", {}).get("status") not in {"CONFIGURED", "DISABLED"}:
            warnings.append("INDstocks is not fully available; this is non-blocking for Dhan-primary reports.")
        return warnings

    def _audit(self, db: Session, event_type: str, message: str, severity: str) -> None:
        if not settings.reports_enable_audit:
            return
        now = datetime.now(timezone.utc)
        last = self._last_audit_at.get(event_type)
        if last and (now - last).total_seconds() < settings.reports_audit_throttle_seconds:
            return
        self._last_audit_at[event_type] = now
        AuditLogger().log(db, event_type, message, severity=severity, source="REPORTING")


def _paper_only_confirmed() -> bool:
    return (
        settings.trading_mode == "PAPER"
        and not settings.allow_live_orders
        and not settings.enable_dhan_order_placement
        and not settings.indstocks_enable_order_placement
        and settings.safety_status["live_order_status"] == "BLOCKED"
    )


def _audit_read(event: AuditLog) -> dict[str, Any]:
    return {
        "id": event.id,
        "event_type": event.event_type,
        "severity": event.severity,
        "source": event.source,
        "message": event.message,
        "created_at": event.created_at.isoformat() if event.created_at else None,
    }


def _collect_status_warnings(value: Any) -> list[str]:
    warnings: list[str] = []
    if isinstance(value, dict):
        status = value.get("status") or value.get("report_status")
        if isinstance(status, str) and status in {"NO_DATA", "PARTIAL_DATA", "WARNING", "ERROR", "INSUFFICIENT_DATA"}:
            warnings.append(f"Section status is {status}.")
        for item in value.values():
            warnings.extend(_collect_status_warnings(item))
    elif isinstance(value, list):
        for item in value:
            warnings.extend(_collect_status_warnings(item))
    return warnings[:20]


def _collect_nested_warnings(value: Any) -> list[str]:
    warnings: list[str] = []
    if isinstance(value, dict):
        if isinstance(value.get("warnings"), list):
            warnings.extend(str(item) for item in value["warnings"])
        for item in value.values():
            warnings.extend(_collect_nested_warnings(item))
    elif isinstance(value, list):
        for item in value:
            warnings.extend(_collect_nested_warnings(item))
    return warnings[:20]


def _compact_report(report: dict[str, Any]) -> dict[str, Any]:
    return {
        "report_status": report.get("report_status"),
        "warnings": report.get("warnings", []),
        "recommendations": report.get("recommendations", []),
        "sections": report.get("sections", {}),
    }


def _sanitize(value: Any) -> Any:
    if isinstance(value, dict):
        output = {}
        for key, item in value.items():
            lowered = str(key).lower()
            if "token" in lowered or "access" in lowered or "authorization" in lowered:
                output[key] = "[REDACTED]"
            else:
                output[key] = _sanitize(item)
        return output
    if isinstance(value, list):
        return [_sanitize(item) for item in value]
    if isinstance(value, datetime):
        return value.isoformat()
    return value


reporting_service = ReportingService()


def get_reporting_service() -> ReportingService:
    return reporting_service
