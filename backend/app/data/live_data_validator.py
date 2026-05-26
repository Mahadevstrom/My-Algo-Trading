from datetime import datetime, timezone
from typing import Any

from app.config import settings
from app.schemas.data_quality import DataQualityCheckResult
from app.schemas.live_candle import LiveCandle, LiveInstrumentMetadata
from app.schemas.live_feed import NormalizedTick


class LiveDataValidator:
    def validate_tick(
        self,
        tick: NormalizedTick | None,
        symbol: str | None,
        security_id: str | None,
    ) -> list[DataQualityCheckResult]:
        now = datetime.now(timezone.utc)
        if tick is None:
            return [
                _result(
                    "LATEST_TICK_PRESENT",
                    "NO_DATA",
                    "ERROR",
                    False,
                    "No live tick is available for this symbol/security ID.",
                    symbol,
                    security_id,
                )
            ]

        checks = [
            _result("LATEST_TICK_PRESENT", "OK", "INFO", True, "Latest live tick is present.", symbol, tick.security_id),
        ]
        tick_time = tick.received_at or tick.timestamp
        if tick_time is None:
            checks.append(
                _result(
                    "LATEST_TICK_FRESH",
                    "BAD_TICK",
                    "ERROR",
                    False,
                    "Tick has no timestamp.",
                    symbol,
                    tick.security_id,
                )
            )
        else:
            age = _age_seconds(tick_time, now)
            fresh = age <= settings.data_quality_stale_after_seconds
            checks.append(
                _result(
                    "LATEST_TICK_FRESH",
                    "OK" if fresh else "STALE",
                    "INFO" if fresh else "WARNING",
                    fresh,
                    "Latest tick is fresh." if fresh else "Latest tick is stale.",
                    symbol,
                    tick.security_id,
                    age_seconds=age,
                    threshold=settings.data_quality_stale_after_seconds,
                )
            )

        positive = tick.ltp is not None and tick.ltp > 0
        checks.append(
            _result(
                "LTP_POSITIVE",
                "OK" if positive else "BAD_TICK",
                "INFO" if positive else "ERROR",
                positive,
                "LTP is positive." if positive else "LTP is missing, zero, or negative.",
                symbol,
                tick.security_id,
                measured_value=tick.ltp,
                threshold="> 0",
            )
        )
        return checks

    def validate_candle(
        self,
        candle: LiveCandle | None,
        symbol: str | None,
        security_id: str | None,
    ) -> list[DataQualityCheckResult]:
        if candle is None:
            return [
                _result(
                    "CANDLE_PRESENT",
                    "NO_DATA",
                    "WARNING",
                    False,
                    "No live candle is available yet.",
                    symbol,
                    security_id,
                )
            ]
        checks = [
            _result("CANDLE_PRESENT", "OK", "INFO", True, "Live candle is present.", symbol, candle.security_id),
        ]
        age = _age_seconds(candle.updated_at, datetime.now(timezone.utc))
        fresh = age <= settings.data_quality_stale_after_seconds
        checks.append(
            _result(
                "CANDLE_FRESH",
                "OK" if fresh else "STALE",
                "INFO" if fresh else "WARNING",
                fresh,
                "Latest candle is fresh." if fresh else "Latest candle is stale.",
                symbol,
                candle.security_id,
                age_seconds=age,
                threshold=settings.data_quality_stale_after_seconds,
            )
        )
        valid_ohlc = (
            candle.open > 0
            and candle.high > 0
            and candle.low > 0
            and candle.close > 0
            and candle.high >= candle.low
            and candle.high >= candle.open
            and candle.high >= candle.close
            and candle.low <= candle.open
            and candle.low <= candle.close
        )
        checks.append(
            _result(
                "CANDLE_OHLC_VALID",
                "OK" if valid_ohlc else "BAD_TICK",
                "INFO" if valid_ohlc else "ERROR",
                valid_ohlc,
                "Candle OHLC values are valid." if valid_ohlc else "Candle OHLC values are invalid.",
                symbol,
                candle.security_id,
                details={
                    "open": candle.open,
                    "high": candle.high,
                    "low": candle.low,
                    "close": candle.close,
                    "tick_count": candle.tick_count,
                },
            )
        )
        tick_count_ok = candle.tick_count > 0
        checks.append(
            _result(
                "CANDLE_TICK_COUNT",
                "OK" if tick_count_ok else "BAD_TICK",
                "INFO" if tick_count_ok else "WARNING",
                tick_count_ok,
                "Candle has tick updates." if tick_count_ok else "Candle has zero tick count.",
                symbol,
                candle.security_id,
                measured_value=candle.tick_count,
                threshold="> 0",
            )
        )
        return checks

    def validate_option_metadata(
        self,
        metadata: LiveInstrumentMetadata | None,
        symbol: str | None,
        security_id: str | None,
    ) -> list[DataQualityCheckResult]:
        if metadata is None:
            return [
                _result(
                    "OPTION_METADATA_PRESENT",
                    "WARNING",
                    "WARNING",
                    False,
                    "Instrument metadata is not available.",
                    symbol,
                    security_id,
                )
            ]
        if metadata.option_type not in {"CE", "PE"}:
            return [
                _result(
                    "OPTION_METADATA_PRESENT",
                    "OK",
                    "INFO",
                    True,
                    "Instrument is not an option contract; option metadata is not required.",
                    symbol or metadata.symbol,
                    metadata.security_id,
                )
            ]
        checks = []
        metadata_present = bool(metadata.strike and metadata.expiry and metadata.underlying and metadata.option_type in {"CE", "PE"})
        checks.append(
            _result(
                "OPTION_METADATA_PRESENT",
                "OK" if metadata_present else "WARNING",
                "INFO" if metadata_present else "WARNING",
                metadata_present,
                "Option metadata is complete." if metadata_present else "Option metadata is incomplete.",
                symbol or metadata.symbol,
                metadata.security_id,
                details=metadata.model_dump(mode="json"),
            )
        )
        is_nifty_option = (metadata.underlying or "").upper() == "NIFTY" and metadata.option_type in {"CE", "PE"}
        if (symbol or metadata.symbol or "").upper().startswith("NIFTY") or is_nifty_option:
            checks.append(
                _result(
                    "NIFTY_OPTION_VALID",
                    "OK" if is_nifty_option and metadata.strike and metadata.expiry else "WARNING",
                    "INFO" if is_nifty_option and metadata.strike and metadata.expiry else "WARNING",
                    bool(is_nifty_option and metadata.strike and metadata.expiry),
                    "NIFTY option metadata is valid."
                    if is_nifty_option and metadata.strike and metadata.expiry
                    else "NIFTY option metadata is missing underlying, strike, expiry, or CE/PE type.",
                    symbol or metadata.symbol,
                    metadata.security_id,
                    details=metadata.model_dump(mode="json"),
                )
            )
        return checks


def _age_seconds(value: datetime, now: datetime) -> float:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return round((now - value.astimezone(timezone.utc)).total_seconds(), 2)


def _result(
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
    age_seconds: float | None = None,
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
        source="DHAN_WS",
        measured_value=measured_value,
        expected_value=expected_value,
        threshold=threshold,
        age_seconds=age_seconds,
        timestamp=datetime.now(timezone.utc),
        details=details or {},
    )
