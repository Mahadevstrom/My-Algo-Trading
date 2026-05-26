from datetime import datetime, timezone
from typing import Any

from app.config import settings
from app.data.candle_gap_detector import CandleGapDetector
from app.data.live_data_validator import LiveDataValidator
from app.schemas.data_quality import DataQualityCheckResult, SymbolQualitySummary
from app.schemas.live_candle import LiveCandle, LiveInstrumentMetadata
from app.schemas.live_feed import NormalizedTick
from app.utils.market_session import india_market_session


class DataQualityEngine:
    def __init__(self) -> None:
        self.validator = LiveDataValidator()
        self.gap_detector = CandleGapDetector()

    def build_summary(
        self,
        symbol: str | None,
        security_id: str | None,
        tick: NormalizedTick | None,
        latest_candle: LiveCandle | None,
        recent_candles: list[LiveCandle],
        metadata: LiveInstrumentMetadata | None,
        live_feed_connected: bool,
        rest_checks: list[DataQualityCheckResult] | None = None,
    ) -> SymbolQualitySummary:
        checks: list[DataQualityCheckResult] = []
        checks.append(
            _check(
                "LIVE_FEED_CONNECTED",
                "OK" if live_feed_connected else "DISCONNECTED",
                "INFO" if live_feed_connected else "WARNING",
                live_feed_connected,
                "Live feed is connected." if live_feed_connected else "Live feed is disconnected or disabled.",
                symbol,
                security_id,
            )
        )
        checks.extend(self.validator.validate_tick(tick, symbol, security_id))
        checks.extend(self.validator.validate_candle(latest_candle, symbol, security_id))
        checks.extend(self.validator.validate_option_metadata(metadata, symbol, security_id))
        checks.append(self._price_spike_check(recent_candles, tick, symbol, security_id))
        checks.append(
            self.gap_detector.check_gaps(
                recent_candles,
                "1m",
                settings.data_quality_min_candles_for_gap_check,
                symbol,
                security_id,
            )
        )
        checks.append(self._market_session_check(symbol, security_id))
        if rest_checks:
            checks.extend(rest_checks)

        score = self._score(checks, live_feed_connected)
        data_status = self._status_from_score(score, checks)
        warnings = [check.message for check in checks if check.severity == "WARNING"]
        errors = [check.message for check in checks if check.severity in {"ERROR", "CRITICAL"}]
        last_tick_at = tick.received_at if tick else None
        last_candle_at = latest_candle.updated_at if latest_candle else None
        last_rest_check_at = _last_rest_timestamp(checks)
        stale = data_status in {"STALE", "NO_DATA", "DISCONNECTED"} or any(
            check.status in {"STALE", "NO_DATA", "DISCONNECTED"} for check in checks
        )
        return SymbolQualitySummary(
            symbol=(symbol or (metadata.symbol if metadata else None) or (tick.symbol if tick else None)),
            security_id=str(security_id or (metadata.security_id if metadata else None) or (tick.security_id if tick else "")) or None,
            underlying=metadata.underlying if metadata else None,
            option_type=metadata.option_type if metadata else None,
            strike=metadata.strike if metadata else None,
            expiry=metadata.expiry if metadata else None,
            data_status=data_status,
            overall_score=score,
            is_tradeable_for_paper_analysis=score >= 80 and not errors,
            live_feed_status=_first_check_status(checks, "LIVE_FEED_CONNECTED"),
            live_tick_status=_worst_status(checks, ["LATEST_TICK_PRESENT", "LATEST_TICK_FRESH", "LTP_POSITIVE", "PRICE_SPIKE_CHECK"]),
            live_candle_status=_worst_status(checks, ["CANDLE_PRESENT", "CANDLE_FRESH", "CANDLE_OHLC_VALID", "CANDLE_GAP_CHECK"]),
            rest_cross_check_status=_worst_status(checks, ["REST_LTP_AVAILABLE", "WS_REST_LTP_MATCH", "WS_REST_QUOTE_MATCH"]),
            stale=stale,
            warnings=warnings,
            errors=errors,
            checks=checks,
            last_tick_at=last_tick_at,
            last_candle_at=last_candle_at,
            last_rest_check_at=last_rest_check_at,
            market_session=india_market_session(),
        )

    def _price_spike_check(
        self,
        recent_candles: list[LiveCandle],
        tick: NormalizedTick | None,
        symbol: str | None,
        security_id: str | None,
    ) -> DataQualityCheckResult:
        if tick is None or tick.ltp is None or not recent_candles:
            return _check(
                "PRICE_SPIKE_CHECK",
                "UNKNOWN",
                "INFO",
                True,
                "Not enough data for price spike check.",
                symbol,
                security_id,
            )
        previous_close = recent_candles[-1].close
        if previous_close <= 0:
            return _check("PRICE_SPIKE_CHECK", "UNKNOWN", "INFO", True, "Previous close unavailable.", symbol, security_id)
        change_percent = abs((float(tick.ltp) - previous_close) / previous_close * 100)
        passed = change_percent <= settings.data_quality_price_spike_percent
        return _check(
            "PRICE_SPIKE_CHECK",
            "OK" if passed else "BAD_TICK",
            "INFO" if passed else "WARNING",
            passed,
            "No abnormal price spike detected." if passed else "Potential price spike detected.",
            symbol,
            security_id,
            measured_value=round(change_percent, 4),
            threshold=settings.data_quality_price_spike_percent,
        )

    def _market_session_check(self, symbol: str | None, security_id: str | None) -> DataQualityCheckResult:
        session = india_market_session()
        is_open = bool(session["is_market_open"])
        return _check(
            "MARKET_SESSION_AWARENESS",
            "OK" if is_open else "WARNING",
            "INFO" if is_open else "WARNING",
            True,
            "Market session is open." if is_open else f"Market session is {session['session_status']}; live no-data may be normal.",
            symbol,
            security_id,
            details=session,
        )

    def _score(self, checks: list[DataQualityCheckResult], live_feed_connected: bool) -> int:
        score = 100
        if not live_feed_connected:
            score -= 40
        if _failed(checks, "LATEST_TICK_PRESENT"):
            score -= 30
        if _status(checks, "LATEST_TICK_FRESH") == "STALE":
            score -= 25
        if _failed(checks, "CANDLE_OHLC_VALID"):
            score -= 20
        if any(check.status == "MISMATCH" for check in checks):
            score -= 20
        if _failed(checks, "OPTION_METADATA_PRESENT"):
            score -= 10
        if _failed(checks, "CANDLE_GAP_CHECK"):
            score -= 10
        if _failed(checks, "LTP_POSITIVE"):
            score -= 30
        return max(0, min(100, int(score)))

    def _status_from_score(self, score: int, checks: list[DataQualityCheckResult]) -> str:
        if any(check.severity == "CRITICAL" for check in checks):
            return "NO_DATA"
        if any(check.status == "MISMATCH" for check in checks):
            return "MISMATCH"
        if any(check.status == "BAD_TICK" for check in checks):
            return "BAD_TICK"
        if score >= 80:
            return "OK"
        if score >= 60:
            return "WARNING"
        if score >= 30:
            return "STALE"
        return "NO_DATA"


def _check(
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
        source="DATA_QUALITY",
        measured_value=measured_value,
        expected_value=expected_value,
        threshold=threshold,
        timestamp=datetime.now(timezone.utc),
        details=details or {},
    )


def _failed(checks: list[DataQualityCheckResult], check_name: str) -> bool:
    return any(check.check_name == check_name and not check.passed for check in checks)


def _status(checks: list[DataQualityCheckResult], check_name: str) -> str | None:
    for check in checks:
        if check.check_name == check_name:
            return check.status
    return None


def _first_check_status(checks: list[DataQualityCheckResult], check_name: str) -> str:
    return _status(checks, check_name) or "UNKNOWN"


def _worst_status(checks: list[DataQualityCheckResult], names: list[str]) -> str:
    priority = ["UNKNOWN", "OK", "WARNING", "STALE", "BAD_TICK", "MISMATCH", "NO_DATA", "DISCONNECTED"]
    found = [check.status for check in checks if check.check_name in names]
    if not found:
        return "UNKNOWN"
    return max(found, key=lambda value: priority.index(value) if value in priority else 0)


def _last_rest_timestamp(checks: list[DataQualityCheckResult]) -> datetime | None:
    rest_checks = [check.timestamp for check in checks if check.check_name.startswith("REST_") or check.check_name.startswith("WS_REST_")]
    return max(rest_checks) if rest_checks else None
