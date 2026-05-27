from collections import deque
from datetime import datetime, timezone
from time import monotonic
from typing import Any

from sqlalchemy import case, select
from sqlalchemy.orm import Session

from app.audit.audit_logger import AuditLogger
from app.brokers.dhan_data import DhanDataAdapter
from app.config import settings
from app.data.data_quality_engine import DataQualityEngine
from app.data.data_quality_store import data_quality_store
from app.models.instrument import InstrumentMaster
from app.schemas.data_quality import DataQualityCheckResult, SymbolQualitySummary
from app.schemas.live_candle import LiveInstrumentMetadata
from app.services.live_feed_service import get_live_feed_service
from app.services.live_market_monitor_service import get_live_market_monitor_service
from app.services.dhan_rest_quota_service import get_dhan_rest_quota_service


class DataQualityService:
    def __init__(self) -> None:
        self.engine = DataQualityEngine()
        self.store = data_quality_store
        self._rest_cache: dict[str, tuple[float, dict[str, Any]]] = {}
        self._rest_request_times: deque[float] = deque()
        self._last_audit_at_by_event_key: dict[str, datetime] = {}

    async def status(self) -> dict[str, Any]:
        live_feed_status = get_live_feed_service().status()
        monitor_status = await get_live_market_monitor_service().status()
        stale = await self.store.stale()
        tracked_count = await self.store.tracked_count()
        return {
            "enabled": settings.enable_data_quality_engine,
            "running": settings.enable_data_quality_engine,
            "live_feed_connected": live_feed_status["connected"],
            "live_monitor_running": monitor_status["running"],
            "tracked_symbols_count": tracked_count,
            "stale_symbols_count": len(stale),
            "last_check_at": self.store.last_check_at,
            "overall_status": "OK" if tracked_count and not stale else "NO_DATA" if not tracked_count else "WARNING",
            "dhan_rest_quota": get_dhan_rest_quota_service().status(),
            "mode": settings.trading_mode,
            "live_order_status": settings.safety_status["live_order_status"],
        }

    def config(self) -> dict[str, Any]:
        return {
            "enabled": settings.enable_data_quality_engine,
            "rest_cross_check": settings.data_quality_rest_cross_check,
            "rest_cache_seconds": settings.data_quality_rest_cache_seconds,
            "max_rest_checks_per_minute": settings.data_quality_max_rest_checks_per_minute,
            "ltp_mismatch_percent": settings.data_quality_ltp_mismatch_percent,
            "rest_mismatch_blocks_paper": settings.data_quality_rest_mismatch_blocks_paper,
            "stale_after_seconds": settings.data_quality_stale_after_seconds,
            "price_spike_percent": settings.data_quality_price_spike_percent,
            "min_candles_for_gap_check": settings.data_quality_min_candles_for_gap_check,
            "max_history": settings.data_quality_max_history,
            "audit_throttle_seconds": settings.data_quality_audit_throttle_seconds,
            "shared_dhan_rest_quota_guard": settings.enable_dhan_rest_quota_guard,
        }

    async def get_symbol(self, db: Session, symbol: str) -> SymbolQualitySummary:
        cached = await self.store.get_by_symbol(symbol)
        if cached:
            return cached
        return await self.check_symbol(db, symbol, rest_cross_check=False, audit=False)

    async def get_security(self, db: Session, security_id: str) -> SymbolQualitySummary:
        cached = await self.store.get_by_security_id(security_id)
        if cached:
            return cached
        return await self.check_security(db, security_id, rest_cross_check=False, audit=False)

    async def check_symbol(
        self,
        db: Session,
        symbol: str,
        rest_cross_check: bool = True,
        audit: bool = True,
    ) -> SymbolQualitySummary:
        instrument = _lookup_symbol(db, symbol)
        security_id = instrument.security_id if instrument else None
        return await self._check(db, symbol.upper(), security_id, instrument, rest_cross_check, audit)

    async def check_security(
        self,
        db: Session,
        security_id: str,
        rest_cross_check: bool = True,
        audit: bool = True,
    ) -> SymbolQualitySummary:
        instrument = _lookup_security_id(db, security_id)
        symbol = instrument.trading_symbol if instrument else None
        return await self._check(db, symbol, str(security_id), instrument, rest_cross_check, audit)

    async def check_nifty(self, db: Session) -> dict[str, Any]:
        metadata_items = await get_live_market_monitor_service().store.tracked_metadata()
        nifty_items = [
            item for item in metadata_items
            if (item.underlying or item.symbol or "").upper() in {"NIFTY", "NIFTY 50"}
            or (item.symbol or "").upper().startswith("NIFTY")
        ]
        if not nifty_items:
            summary = await self.check_symbol(db, "NIFTY", rest_cross_check=False)
            return {
                "ok": True,
                "status": "NO_DATA",
                "message": "No live NIFTY ticks are tracked yet.",
                "nifty_underlying": summary.model_dump(mode="json"),
                "items": [],
                "ce_tracked_count": 0,
                "pe_tracked_count": 0,
                "stale_contracts": 0,
                "bad_tick_contracts": 0,
                "mismatch_contracts": 0,
                "paper_analysis_ready_count": 0,
                "overall_status": summary.data_status,
            }
        results = []
        for item in nifty_items:
            results.append(await self._check(db, item.symbol, item.security_id, None, True, True))
        ce_count = sum(1 for item in results if item.option_type == "CE")
        pe_count = sum(1 for item in results if item.option_type == "PE")
        return {
            "ok": True,
            "status": "OK" if any(item.is_tradeable_for_paper_analysis for item in results) else "WARNING",
            "message": None,
            "items": [item.model_dump(mode="json") for item in results],
            "ce_tracked_count": ce_count,
            "pe_tracked_count": pe_count,
            "stale_contracts": sum(1 for item in results if item.stale),
            "bad_tick_contracts": sum(1 for item in results if item.data_status == "BAD_TICK"),
            "mismatch_contracts": sum(1 for item in results if item.data_status == "MISMATCH"),
            "paper_analysis_ready_count": sum(1 for item in results if item.is_tradeable_for_paper_analysis),
            "overall_status": _overall_status(results),
        }

    async def run_all(self, db: Session) -> dict[str, Any]:
        symbols = await get_live_market_monitor_service().store.get_all_symbols()
        if not symbols:
            return {"ok": False, "status": "NO_DATA", "message": "No tracked live symbols are available.", "items": []}
        items = []
        for symbol in symbols:
            items.append(await self.check_symbol(db, symbol, rest_cross_check=True))
        return {"ok": True, "count": len(items), "items": [item.model_dump(mode="json") for item in items]}

    async def stale(self) -> dict[str, Any]:
        items = await self.store.stale()
        return {"ok": True, "count": len(items), "items": [_json_dates(item) for item in items]}

    async def mismatches(self) -> dict[str, Any]:
        items = await self.store.mismatches()
        return {"ok": True, "count": len(items), "items": items}

    async def history(self, symbol: str, limit: int) -> dict[str, Any]:
        items = await self.store.history_by_symbol(symbol, max(1, min(limit, 500)))
        return {
            "ok": True,
            "symbol": symbol.upper(),
            "count": len(items),
            "items": [item.model_dump(mode="json") for item in items],
        }

    async def _check(
        self,
        db: Session,
        symbol: str | None,
        security_id: str | None,
        instrument: InstrumentMaster | None,
        rest_cross_check: bool,
        audit: bool,
    ) -> SymbolQualitySummary:
        live_feed = get_live_feed_service()
        monitor = get_live_market_monitor_service()
        if security_id is None and symbol:
            tick = await live_feed.store.get_by_symbol(symbol)
            security_id = tick.security_id if tick else None
        tick = await live_feed.store.get_by_security_id(security_id) if security_id else None
        if tick is None and symbol:
            tick = await live_feed.store.get_by_symbol(symbol)
            security_id = tick.security_id if tick else security_id

        if instrument is None and security_id:
            instrument = _lookup_security_id(db, security_id)
        metadata = _metadata_from_instrument(instrument, tick, symbol, security_id)
        effective_symbol = symbol or (metadata.symbol if metadata else None) or (tick.symbol if tick else None)
        effective_security_id = security_id or (metadata.security_id if metadata else None) or (tick.security_id if tick else None)
        latest_candle = await monitor.store.get_latest_candle(effective_symbol, "1m") if effective_symbol else None
        if latest_candle is None and effective_security_id:
            latest_candle = await monitor.store.get_latest_candle_by_security_id(effective_security_id, "1m")
        recent_candles = await monitor.store.get_candles(effective_symbol, "1m", 20) if effective_symbol else []
        if not recent_candles and effective_security_id:
            recent_candles = await monitor.store.get_candles_by_security_id(effective_security_id, "1m", 20)

        rest_checks = []
        if settings.data_quality_rest_cross_check and rest_cross_check:
            rest_checks = await self._rest_cross_check(effective_symbol, effective_security_id, metadata, tick)

        summary = self.engine.build_summary(
            symbol=effective_symbol or symbol,
            security_id=effective_security_id,
            tick=tick,
            latest_candle=latest_candle,
            recent_candles=recent_candles,
            metadata=metadata,
            live_feed_connected=live_feed.status()["connected"],
            rest_checks=rest_checks,
        )
        await self.store.put(summary)
        if audit:
            self._audit_quality_result(db, summary)
        return summary

    async def _rest_cross_check(
        self,
        symbol: str | None,
        security_id: str | None,
        metadata: LiveInstrumentMetadata | None,
        tick,
    ) -> list[DataQualityCheckResult]:
        if not security_id or metadata is None or not metadata.exchange_segment:
            return [
                _quality_check(
                    "REST_LTP_AVAILABLE",
                    "UNKNOWN",
                    "INFO",
                    True,
                    "REST cross-check skipped because instrument mapping is unavailable.",
                    symbol,
                    security_id,
                )
            ]
        cache_key = f"{metadata.exchange_segment}:{security_id}"
        cached = self._rest_cache.get(cache_key)
        now = monotonic()
        if cached and now - cached[0] <= settings.data_quality_rest_cache_seconds:
            response = cached[1]
        else:
            if not self._allow_rest_request():
                return [
                    _quality_check(
                        "REST_LTP_AVAILABLE",
                        "SKIPPED",
                        "INFO",
                        True,
                        "Data quality REST cross-check skipped to protect Dhan rate limits; using live data only.",
                        symbol,
                        security_id,
                    )
                ]
            response = await DhanDataAdapter().get_ltp({metadata.exchange_segment: [security_id]})
            self._rest_cache[cache_key] = (now, response)
        if not response.get("ok"):
            rest_status = response.get("status")
            is_rate_or_timeout = _is_rate_or_timeout(response)
            return [
                _quality_check(
                    "REST_LTP_AVAILABLE",
                    "WARNING" if is_rate_or_timeout else "UNKNOWN",
                    "WARNING",
                    True if is_rate_or_timeout else False,
                    response.get("message", "Dhan REST LTP cross-check failed."),
                    symbol,
                    security_id,
                    details={"rest_status": rest_status, "paper_mode_live_data_fallback": is_rate_or_timeout},
                )
            ]
        rest_ltp = _extract_ltp(response, security_id)
        checks = [
            _quality_check(
                "REST_LTP_AVAILABLE",
                "OK" if rest_ltp is not None else "UNKNOWN",
                "INFO" if rest_ltp is not None else "WARNING",
                rest_ltp is not None,
                "Dhan REST LTP is available." if rest_ltp is not None else "Dhan REST LTP response did not include LTP.",
                symbol,
                security_id,
                measured_value=rest_ltp,
            )
        ]
        if tick and tick.ltp and rest_ltp:
            diff_percent = abs((float(tick.ltp) - float(rest_ltp)) / float(rest_ltp) * 100)
            passed = diff_percent <= settings.data_quality_ltp_mismatch_percent
            hard_block = bool(settings.data_quality_rest_mismatch_blocks_paper)
            checks.append(
                _quality_check(
                    "WS_REST_LTP_MATCH",
                    "OK" if passed else "MISMATCH" if hard_block else "WARNING",
                    "INFO" if passed else "ERROR" if hard_block else "WARNING",
                    passed or not hard_block,
                    "WebSocket LTP matches Dhan REST LTP."
                    if passed
                    else "WebSocket LTP differs from Dhan REST LTP beyond threshold; paper mode continues with live WebSocket data.",
                    symbol,
                    security_id,
                    measured_value=round(float(tick.ltp), 4),
                    expected_value=round(float(rest_ltp), 4),
                    threshold=f"{settings.data_quality_ltp_mismatch_percent}%",
                    details={"difference_percent": round(diff_percent, 4), "blocks_paper": hard_block},
                )
            )
        else:
            checks.append(
                _quality_check(
                    "WS_REST_LTP_MATCH",
                    "UNKNOWN",
                    "INFO",
                    True,
                    "WS vs REST LTP match skipped because live tick or REST LTP is unavailable.",
                    symbol,
                    security_id,
                )
            )
        checks.extend(await self._rest_quote_cross_check(symbol, security_id, metadata, tick))
        return checks

    async def _rest_quote_cross_check(
        self,
        symbol: str | None,
        security_id: str,
        metadata: LiveInstrumentMetadata,
        tick,
    ) -> list[DataQualityCheckResult]:
        comparable_fields = ["open", "high", "low", "close", "bid_price", "ask_price"]
        if not tick or not any(getattr(tick, field, None) is not None for field in comparable_fields):
            return [
                _quality_check(
                    "WS_REST_QUOTE_MATCH",
                    "UNKNOWN",
                    "INFO",
                    True,
                    "Quote cross-check skipped because live tick does not include OHLC/depth quote fields.",
                    symbol,
                    security_id,
                )
            ]
        cache_key = f"QUOTE:{metadata.exchange_segment}:{security_id}"
        cached = self._rest_cache.get(cache_key)
        now = monotonic()
        if cached and now - cached[0] <= settings.data_quality_rest_cache_seconds:
            response = cached[1]
        else:
            if not self._allow_rest_request():
                return [
                    _quality_check(
                        "WS_REST_QUOTE_MATCH",
                        "SKIPPED",
                        "INFO",
                        True,
                        "Data quality REST quote check skipped to protect Dhan rate limits; using live data only.",
                        symbol,
                        security_id,
                    )
                ]
            response = await DhanDataAdapter().get_quote({metadata.exchange_segment: [security_id]})
            self._rest_cache[cache_key] = (now, response)
        if not response.get("ok"):
            rest_status = response.get("status")
            is_rate_or_timeout = _is_rate_or_timeout(response)
            return [
                _quality_check(
                    "WS_REST_QUOTE_MATCH",
                    "WARNING" if is_rate_or_timeout else "UNKNOWN",
                    "WARNING",
                    True if is_rate_or_timeout else False,
                    response.get("message", "Dhan REST quote cross-check failed."),
                    symbol,
                    security_id,
                    details={"rest_status": rest_status, "paper_mode_live_data_fallback": is_rate_or_timeout},
                )
            ]
        rest_quote = _extract_quote(response, security_id)
        if not rest_quote:
            return [
                _quality_check(
                    "WS_REST_QUOTE_MATCH",
                    "UNKNOWN",
                    "WARNING",
                    False,
                    "Dhan REST quote response did not include comparable fields.",
                    symbol,
                    security_id,
                )
            ]
        mismatches = []
        for live_field, rest_field in [
            ("open", "open"),
            ("high", "high"),
            ("low", "low"),
            ("close", "close"),
            ("bid_price", "bid"),
            ("ask_price", "ask"),
        ]:
            live_value = getattr(tick, live_field, None)
            rest_value = rest_quote.get(rest_field)
            if live_value is None or rest_value in {None, 0}:
                continue
            diff_percent = abs((float(live_value) - float(rest_value)) / float(rest_value) * 100)
            if diff_percent > settings.data_quality_ltp_mismatch_percent:
                mismatches.append(
                    {
                        "field": live_field,
                        "live": live_value,
                        "rest": rest_value,
                        "difference_percent": round(diff_percent, 4),
                    }
                )
        passed = not mismatches
        hard_block = bool(settings.data_quality_rest_mismatch_blocks_paper)
        return [
            _quality_check(
                "WS_REST_QUOTE_MATCH",
                "OK" if passed else "MISMATCH" if hard_block else "WARNING",
                "INFO" if passed else "ERROR" if hard_block else "WARNING",
                passed or not hard_block,
                "Comparable live quote fields match Dhan REST quote."
                if passed
                else "One or more live quote fields differ from Dhan REST quote beyond threshold; paper mode continues with live WebSocket data.",
                symbol,
                security_id,
                threshold=f"{settings.data_quality_ltp_mismatch_percent}%",
                details={"mismatches": mismatches, "rest_quote": rest_quote, "blocks_paper": hard_block},
            )
        ]

    def _allow_rest_request(self) -> bool:
        now = monotonic()
        while self._rest_request_times and now - self._rest_request_times[0] > 60:
            self._rest_request_times.popleft()
        if len(self._rest_request_times) >= settings.data_quality_max_rest_checks_per_minute:
            return False
        self._rest_request_times.append(now)
        return True

    def _audit_quality_result(self, db: Session, summary: SymbolQualitySummary) -> None:
        AuditLogger().log(
            db,
            "DATA_QUALITY_CHECK_RUN",
            "Data quality check completed.",
            source="DATA_QUALITY",
            payload={
                "symbol": summary.symbol,
                "security_id": summary.security_id,
                "data_status": summary.data_status,
                "overall_score": summary.overall_score,
            },
        )
        for check in summary.checks:
            if check.check_name == "WS_REST_LTP_MATCH" and check.status == "MISMATCH":
                self._audit_throttled(db, "DATA_QUALITY_REST_MISMATCH", summary, check)
            if check.check_name == "LATEST_TICK_FRESH" and check.status == "STALE":
                self._audit_throttled(db, "DATA_QUALITY_STALE_DETECTED", summary, check)
            if check.status == "BAD_TICK":
                self._audit_throttled(db, "DATA_QUALITY_BAD_TICK", summary, check)
            if check.message.lower().find("rate limit") >= 0:
                self._audit_throttled(db, "DATA_QUALITY_RATE_LIMITED", summary, check)

    def _audit_throttled(
        self,
        db: Session,
        event_type: str,
        summary: SymbolQualitySummary,
        check: DataQualityCheckResult,
    ) -> None:
        key = f"{event_type}:{summary.security_id or summary.symbol}"
        now = datetime.now(timezone.utc)
        last = self._last_audit_at_by_event_key.get(key)
        if last and (now - last).total_seconds() < settings.data_quality_audit_throttle_seconds:
            return
        self._last_audit_at_by_event_key[key] = now
        AuditLogger().log(
            db,
            event_type,
            check.message,
            severity=check.severity,
            source="DATA_QUALITY",
            payload={"symbol": summary.symbol, "security_id": summary.security_id, "check": check.model_dump(mode="json")},
        )


def _lookup_symbol(db: Session, symbol: str) -> InstrumentMaster | None:
    from app.engine.dhan_instrument_importer import DhanInstrumentImporter

    return DhanInstrumentImporter().lookup_symbol(db, symbol)


def _lookup_security_id(db: Session, security_id: str) -> InstrumentMaster | None:
    segment_priority = case(
        (InstrumentMaster.segment == "IDX_I", 1),
        (InstrumentMaster.segment == "NSE_EQ", 2),
        (InstrumentMaster.segment == "NSE_FNO", 3),
        (InstrumentMaster.segment == "BSE_EQ", 4),
        (InstrumentMaster.segment == "BSE_FNO", 5),
        else_=99,
    )
    return db.scalar(
        select(InstrumentMaster)
        .where(
            InstrumentMaster.source.in_(["DHAN_COMPACT", "DHAN_DETAILED"]),
            InstrumentMaster.security_id == str(security_id),
        )
        .order_by(segment_priority, InstrumentMaster.id)
        .limit(1)
    )


def _metadata_from_instrument(instrument, tick, symbol: str | None, security_id: str | None) -> LiveInstrumentMetadata | None:
    if instrument is not None:
        return LiveInstrumentMetadata(
            exchange_segment=instrument.segment,
            security_id=instrument.security_id,
            symbol=instrument.trading_symbol,
            underlying=instrument.underlying_symbol,
            option_type=instrument.option_type,
            strike=instrument.strike,
            expiry=instrument.expiry.isoformat() if instrument.expiry else None,
        )
    if tick is None and security_id is None:
        return None
    return LiveInstrumentMetadata(
        exchange_segment=tick.exchange_segment if tick else None,
        security_id=str(security_id or tick.security_id),
        symbol=symbol or (tick.symbol if tick else None),
        underlying=symbol or (tick.symbol if tick else None),
    )


def _extract_ltp(response: dict[str, Any], security_id: str) -> float | None:
    for item in response.get("normalized") or []:
        if str(item.get("security_id")) == str(security_id):
            try:
                ltp = float(item.get("ltp"))
            except (TypeError, ValueError):
                return None
            return ltp if ltp > 0 else None
    return None


def _extract_quote(response: dict[str, Any], security_id: str) -> dict[str, Any] | None:
    for item in response.get("normalized") or []:
        if str(item.get("security_id")) == str(security_id):
            return item
    return None


def _is_rate_or_timeout(response: dict[str, Any]) -> bool:
    text = f"{response.get('status', '')} {response.get('message', '')}".lower()
    return "rate" in text or "limit" in text or "timeout" in text or "timed out" in text or "429" in text


def _quality_check(
    check_name: str,
    status: str,
    severity: str,
    passed: bool,
    message: str,
    symbol: str | None,
    security_id: str | None,
    measured_value: float | str | None = None,
    expected_value: float | str | None = None,
    threshold: float | str | None = None,
    details: dict[str, Any] | None = None,
) -> DataQualityCheckResult:
    return DataQualityCheckResult(
        check_name=check_name,
        status=status,
        severity=severity,
        passed=passed,
        message=message,
        symbol=symbol.upper() if symbol else None,
        security_id=str(security_id) if security_id else None,
        source="DHAN_REST",
        measured_value=measured_value,
        expected_value=expected_value,
        threshold=threshold,
        timestamp=datetime.now(timezone.utc),
        details=details or {},
    )


def _overall_status(items: list[SymbolQualitySummary]) -> str:
    if any(item.data_status == "MISMATCH" for item in items):
        return "MISMATCH"
    if any(item.data_status in {"BAD_TICK", "NO_DATA", "DISCONNECTED"} for item in items):
        return "WARNING"
    if any(item.data_status == "STALE" for item in items):
        return "STALE"
    return "OK"


def _json_dates(item: dict[str, Any]) -> dict[str, Any]:
    return {key: value.isoformat() if isinstance(value, datetime) else value for key, value in item.items()}


data_quality_service = DataQualityService()


def get_data_quality_service() -> DataQualityService:
    return data_quality_service
