from datetime import timedelta

from app.market.live_candle_builder import parse_timeframe
from app.schemas.data_quality import DataQualityCheckResult
from app.schemas.live_candle import LiveCandle


class CandleGapDetector:
    def check_gaps(
        self,
        candles: list[LiveCandle],
        timeframe: str,
        min_candles: int,
        symbol: str | None,
        security_id: str | None,
    ) -> DataQualityCheckResult:
        if len(candles) < min_candles:
            return DataQualityCheckResult(
                check_name="CANDLE_GAP_CHECK",
                status="UNKNOWN",
                severity="INFO",
                passed=True,
                message="Not enough candles for gap check yet.",
                symbol=symbol,
                security_id=security_id,
                source="DHAN_WS",
                threshold=min_candles,
                timestamp=_now(),
                details={"candles_available": len(candles)},
            )
        minutes = parse_timeframe(timeframe)
        expected_delta = timedelta(minutes=minutes)
        missing = []
        ordered = sorted(candles, key=lambda item: item.start_time)
        for previous, current in zip(ordered, ordered[1:]):
            expected_next = previous.start_time + expected_delta
            if current.start_time > expected_next:
                cursor = expected_next
                while cursor < current.start_time:
                    missing.append(cursor.isoformat())
                    cursor += expected_delta
        passed = not missing
        return DataQualityCheckResult(
            check_name="CANDLE_GAP_CHECK",
            status="OK" if passed else "STALE",
            severity="INFO" if passed else "WARNING",
            passed=passed,
            message="No candle gaps detected." if passed else "Missing expected candle buckets detected.",
            symbol=symbol,
            security_id=security_id,
            source="DHAN_WS",
            threshold=f"{minutes}m sequence",
            timestamp=_now(),
            details={"missing_buckets": missing, "market_session_holiday_calendar": "not implemented"},
        )


def _now():
    from datetime import datetime, timezone

    return datetime.now(timezone.utc)
