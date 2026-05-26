from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.brokers.dhan_data import DhanDataAdapter
from app.engine.dhan_instrument_importer import DhanInstrumentImporter
from app.models.candle import Candle
from app.models.instrument import InstrumentMaster


VALID_INTRADAY_INTERVALS = {"1", "5", "15", "25", "60"}
DAILY_INTERVAL = "1day"


@dataclass(frozen=True)
class MappedSymbol:
    symbol: str
    security_id: str
    exchange_segment: str
    instrument: str


class HistoricalDataService:
    def __init__(self) -> None:
        self.dhan = DhanDataAdapter()
        self.mapper = DhanInstrumentImporter()

    async def download_intraday(
        self,
        db: Session,
        symbol: str,
        interval: str,
        from_date: str,
        to_date: str,
    ) -> dict[str, Any]:
        cleaned_interval = str(interval).strip()
        if cleaned_interval not in VALID_INTRADAY_INTERVALS:
            return _error(
                "INVALID_INTERVAL",
                "Invalid interval. Allowed intraday intervals are: 1, 5, 15, 25, 60.",
            )

        parsed = _parse_range(from_date, to_date, include_time=True)
        if not parsed["ok"]:
            return parsed

        mapped = self._map_symbol(db, symbol)
        if mapped is None:
            return _symbol_missing(symbol)

        chunks = self.split_date_range_for_intraday(parsed["from_date"], parsed["to_date"])
        chunk_results: list[dict[str, Any]] = []
        total_saved = 0
        successful_chunks = 0
        failed_chunks = 0

        for index, (chunk_from, chunk_to) in enumerate(chunks, start=1):
            payload = {
                "securityId": mapped.security_id,
                "exchangeSegment": mapped.exchange_segment,
                "instrument": mapped.instrument,
                "interval": cleaned_interval,
                "fromDate": _format_dhan_datetime(chunk_from),
                "toDate": _format_dhan_datetime(chunk_to),
            }
            response = await self.dhan._post("/charts/intraday", payload)
            if not response.get("ok"):
                failed_chunks += 1
                chunk_results.append(
                    {
                        "chunk": index,
                        "from_date": payload["fromDate"],
                        "to_date": payload["toDate"],
                        "ok": False,
                        "status": response.get("status"),
                        "message": response.get("message", "Dhan intraday request failed."),
                    }
                )
                continue

            candles = self._normalize_dhan_candles(
                response.get("data"),
                mapped=mapped,
                interval=cleaned_interval,
            )
            save_result = self.save_candles(db, candles)
            if not save_result["ok"]:
                failed_chunks += 1
                chunk_results.append(
                    {
                        "chunk": index,
                        "from_date": payload["fromDate"],
                        "to_date": payload["toDate"],
                        **save_result,
                    }
                )
                continue
            successful_chunks += 1
            total_saved += save_result["saved_count"]
            chunk_results.append(
                {
                    "chunk": index,
                    "from_date": payload["fromDate"],
                    "to_date": payload["toDate"],
                    "ok": True,
                    "candles_received": len(candles),
                    **save_result,
                }
            )

            if index < len(chunks):
                await asyncio.sleep(1.0)

        return {
            "ok": failed_chunks == 0,
            "status": "COMPLETED" if failed_chunks == 0 else "PARTIAL_FAILURE",
            "symbol": mapped.symbol,
            "security_id": mapped.security_id,
            "exchange_segment": mapped.exchange_segment,
            "instrument": mapped.instrument,
            "interval": cleaned_interval,
            "total_chunks": len(chunks),
            "successful_chunks": successful_chunks,
            "failed_chunks": failed_chunks,
            "total_candles_saved": total_saved,
            "chunks": chunk_results,
            "message": (
                "Intraday candles downloaded and stored."
                if total_saved
                else "No intraday candles were returned for this request."
            ),
        }

    async def download_daily(
        self,
        db: Session,
        symbol: str,
        from_date: str,
        to_date: str,
    ) -> dict[str, Any]:
        parsed = _parse_range(from_date, to_date, include_time=False)
        if not parsed["ok"]:
            return parsed

        mapped = self._map_symbol(db, symbol)
        if mapped is None:
            return _symbol_missing(symbol)

        payload = {
            "securityId": mapped.security_id,
            "exchangeSegment": mapped.exchange_segment,
            "instrument": mapped.instrument,
            "fromDate": parsed["from_date"].date().isoformat(),
            "toDate": parsed["to_date"].date().isoformat(),
        }
        response = await self.dhan._post("/charts/historical", payload)
        if not response.get("ok"):
            return {
                "ok": False,
                "status": response.get("status", "DHAN_ERROR"),
                "message": response.get("message", "Dhan historical request failed."),
                "symbol": mapped.symbol,
                "data": None,
            }

        candles = self._normalize_dhan_candles(response.get("data"), mapped=mapped, interval=DAILY_INTERVAL)
        save_result = self.save_candles(db, candles)
        if not save_result["ok"]:
            return {
                "ok": False,
                "status": save_result["status"],
                "message": save_result["message"],
                "symbol": mapped.symbol,
            }
        return {
            "ok": True,
            "symbol": mapped.symbol,
            "security_id": mapped.security_id,
            "exchange_segment": mapped.exchange_segment,
            "instrument": mapped.instrument,
            "interval": DAILY_INTERVAL,
            "candles_received": len(candles),
            **save_result,
            "status": "COMPLETED",
            "message": (
                "Daily candles downloaded and stored."
                if candles
                else "No daily candles were returned for this request."
            ),
        }

    def save_candles(self, db: Session, candles: list[dict[str, Any]]) -> dict[str, Any]:
        inserted_count = 0
        updated_count = 0
        skipped_count = 0

        try:
            for row in candles:
                existing = db.scalar(
                    select(Candle).where(
                        Candle.source == row["source"],
                        Candle.security_id == row["security_id"],
                        Candle.exchange_segment == row["exchange_segment"],
                        Candle.instrument == row["instrument"],
                        Candle.interval == row["interval"],
                        Candle.timestamp == row["timestamp"],
                    )
                )
                if existing is None:
                    db.add(Candle(**row))
                    inserted_count += 1
                else:
                    existing.symbol = row["symbol"]
                    existing.open = row["open"]
                    existing.high = row["high"]
                    existing.low = row["low"]
                    existing.close = row["close"]
                    existing.volume = row.get("volume")
                    existing.open_interest = row.get("open_interest")
                    updated_count += 1

            db.commit()
        except SQLAlchemyError:
            db.rollback()
            return {
                "ok": False,
                "status": "DATABASE_ERROR",
                "message": "Could not save candles to the local database.",
                "inserted_count": 0,
                "updated_count": 0,
                "skipped_count": len(candles),
                "saved_count": 0,
            }

        return {
            "ok": True,
            "status": "SAVED",
            "message": "Candles saved to local database.",
            "inserted_count": inserted_count,
            "updated_count": updated_count,
            "skipped_count": skipped_count,
            "saved_count": inserted_count + updated_count,
        }

    def get_candles(
        self,
        db: Session,
        symbol: str,
        interval: str,
        from_date: str,
        to_date: str,
        limit: int = 5000,
    ) -> dict[str, Any]:
        parsed = _parse_range(from_date, to_date, include_time=True)
        if not parsed["ok"]:
            return parsed

        cleaned_symbol = symbol.strip().upper()
        cleaned_interval = _normalize_query_interval(interval)
        candles = list(
            db.scalars(
                select(Candle)
                .where(
                    Candle.symbol == cleaned_symbol,
                    Candle.interval == cleaned_interval,
                    Candle.timestamp >= parsed["from_date"],
                    Candle.timestamp <= parsed["to_date"],
                )
                .order_by(Candle.timestamp)
                .limit(limit)
            )
        )
        return {
            "ok": True,
            "symbol": cleaned_symbol,
            "interval": cleaned_interval,
            "count": len(candles),
            "limit": limit,
            "candles": [_candle_to_dict(item) for item in candles],
            "message": None if candles else "No stored candles found for this query.",
        }

    def get_summary(self, db: Session, symbol: str, interval: str) -> dict[str, Any]:
        cleaned_symbol = symbol.strip().upper()
        cleaned_interval = _normalize_query_interval(interval)
        count = db.scalar(
            select(func.count()).select_from(Candle).where(
                Candle.symbol == cleaned_symbol,
                Candle.interval == cleaned_interval,
            )
        )
        if not count:
            return {
                "ok": True,
                "symbol": cleaned_symbol,
                "interval": cleaned_interval,
                "total_candles": 0,
                "message": "No stored candles found for this symbol and interval.",
            }

        row = db.execute(
            select(
                func.min(Candle.timestamp),
                func.max(Candle.timestamp),
                func.sum(Candle.volume),
            ).where(
                Candle.symbol == cleaned_symbol,
                Candle.interval == cleaned_interval,
            )
        ).one()
        latest = db.scalar(
            select(Candle)
            .where(
                Candle.symbol == cleaned_symbol,
                Candle.interval == cleaned_interval,
            )
            .order_by(Candle.timestamp.desc())
            .limit(1)
        )
        return {
            "ok": True,
            "symbol": cleaned_symbol,
            "interval": cleaned_interval,
            "total_candles": int(count),
            "first_timestamp": row[0],
            "last_timestamp": row[1],
            "latest_close": latest.close if latest else None,
            "total_volume": float(row[2]) if row[2] is not None else None,
            "message": "Stored candle summary.",
        }

    def split_date_range_for_intraday(
        self,
        from_date: datetime,
        to_date: datetime,
        max_days: int = 90,
    ) -> list[tuple[datetime, datetime]]:
        chunks: list[tuple[datetime, datetime]] = []
        cursor = from_date
        while cursor <= to_date:
            chunk_to = min(cursor + timedelta(days=max_days) - timedelta(seconds=1), to_date)
            chunks.append((cursor, chunk_to))
            cursor = chunk_to + timedelta(seconds=1)
        return chunks

    def _map_symbol(self, db: Session, symbol: str) -> MappedSymbol | None:
        instrument = self.mapper.lookup_symbol(db, symbol)
        if instrument is None:
            return None
        return MappedSymbol(
            symbol=symbol.strip().upper(),
            security_id=instrument.security_id,
            exchange_segment=instrument.segment,
            instrument=_historical_instrument_type(instrument),
        )

    def _normalize_dhan_candles(
        self,
        response_data: Any,
        mapped: MappedSymbol,
        interval: str,
    ) -> list[dict[str, Any]]:
        payload = _extract_historical_payload(response_data)
        if not isinstance(payload, dict):
            return []

        opens = _array(payload, ["open", "Open", "o"])
        highs = _array(payload, ["high", "High", "h"])
        lows = _array(payload, ["low", "Low", "l"])
        closes = _array(payload, ["close", "Close", "c"])
        volumes = _array(payload, ["volume", "Volume", "v"])
        timestamps = _array(payload, ["timestamp", "time", "datetime", "start_Time", "startTime", "t"])
        open_interests = _array(payload, ["open_interest", "oi", "openInterest", "OpenInterest"])

        row_count = min(len(opens), len(highs), len(lows), len(closes), len(timestamps))
        candles: list[dict[str, Any]] = []
        for index in range(row_count):
            timestamp = _parse_dhan_timestamp(timestamps[index])
            if timestamp is None:
                continue
            try:
                candles.append(
                    {
                        "source": "DHAN",
                        "symbol": mapped.symbol,
                        "security_id": mapped.security_id,
                        "exchange_segment": mapped.exchange_segment,
                        "instrument": mapped.instrument,
                        "interval": interval,
                        "timestamp": timestamp,
                        "open": float(opens[index]),
                        "high": float(highs[index]),
                        "low": float(lows[index]),
                        "close": float(closes[index]),
                        "volume": _optional_float(_at(volumes, index)),
                        "open_interest": _optional_float(_at(open_interests, index)),
                    }
                )
            except (TypeError, ValueError):
                continue
        return candles

    def scan_gaps(
        self,
        db: Session,
        symbol: str,
        interval: str,
        from_date: str,
        to_date: str,
    ) -> dict[str, Any]:
        """
        Scans stored candles for gaps (entire missing days or partially missing bars on weekdays Mon-Fri).
        Standard NSE Market Hours: 09:15 to 15:30 IST.
        """
        cleaned_symbol = symbol.strip().upper()
        cleaned_interval = _normalize_query_interval(interval)
        
        parsed = _parse_range(from_date, to_date, include_time=False)
        if not parsed["ok"]:
            return parsed
            
        start_date = parsed["from_date"].date()
        end_date = parsed["to_date"].date()
        
        # 1. Fetch all weekday dates in this range
        weekdays = []
        curr = start_date
        while curr <= end_date:
            if curr.weekday() < 5:  # Monday = 0, Friday = 4, Saturday = 5, Sunday = 6
                weekdays.append(curr)
            curr += timedelta(days=1)
            
        if not weekdays:
            return {
                "ok": True,
                "symbol": cleaned_symbol,
                "interval": cleaned_interval,
                "gaps": [],
                "message": "No weekdays in the specified date range."
            }
            
        # 2. Fetch all candle timestamps for this range to analyze counts
        # Set start/end boundaries at times
        start_dt = datetime.combine(start_date, time.min).replace(tzinfo=timezone.utc)
        end_dt = datetime.combine(end_date, time.max).replace(tzinfo=timezone.utc)
        
        candles_timestamps = db.scalars(
            select(Candle.timestamp)
            .where(
                Candle.symbol == cleaned_symbol,
                Candle.interval == cleaned_interval,
                Candle.timestamp >= start_dt,
                Candle.timestamp <= end_dt
            )
        ).all()
        
        # Convert candle timestamps to local IST date for counting.
        # Dhan timezone is Asia/Kolkata (IST), i.e., UTC + 5:30.
        # Let's adjust UTC timestamp to IST date.
        from datetime import timezone as py_timezone
        ist_offset = py_timezone(timedelta(hours=5, minutes=30))
        
        from collections import defaultdict
        date_counts = defaultdict(int)
        for ts in candles_timestamps:
            # Shift UTC timestamp to IST
            ist_dt = ts.astimezone(ist_offset)
            date_counts[ist_dt.date()] += 1
            
        # 3. Analyze gaps
        # Expected candles per day based on interval
        if cleaned_interval == "1":
            expected = 375
        elif cleaned_interval == "5":
            expected = 75
        elif cleaned_interval == "15":
            expected = 25
        elif cleaned_interval == "25":
            expected = 15
        elif cleaned_interval == "60" or cleaned_interval == "60m":
            expected = 6
        elif cleaned_interval == "1day" or cleaned_interval == "daily":
            expected = 1
        else:
            expected = 75  # default fallback to 5m
            
        gaps = []
        for day in weekdays:
            count = date_counts[day]
            if count == 0:
                gaps.append({
                    "date": day.isoformat(),
                    "severity": "HIGH",
                    "reason": f"Missing entire day (0 / {expected} candles)",
                    "count": 0,
                    "expected": expected
                })
            elif count < expected:
                gaps.append({
                    "date": day.isoformat(),
                    "severity": "MEDIUM",
                    "reason": f"Partial day gap ({count} / {expected} candles)",
                    "count": count,
                    "expected": expected
                })
                
        return {
            "ok": True,
            "symbol": cleaned_symbol,
            "interval": cleaned_interval,
            "total_days_scanned": len(weekdays),
            "total_gaps_found": len(gaps),
            "gaps": gaps
        }

    async def patch_gaps(
        self,
        db: Session,
        symbol: str,
        interval: str,
        gaps_list: list[str]
    ) -> dict[str, Any]:
        """
        Targetedly downloads missing days one by one, adding rate limits to be safe.
        """
        cleaned_symbol = symbol.strip().upper()
        cleaned_interval = _normalize_query_interval(interval)
        
        if not gaps_list:
            return {
                "ok": True,
                "message": "No gaps specified to patch.",
                "patched_count": 0
            }
            
        results = []
        total_saved = 0
        success_count = 0
        fail_count = 0
        
        for index, date_str in enumerate(gaps_list, start=1):
            try:
                # For intraday, download from 09:15:00 to 15:30:00 local time
                from_date_str = f"{date_str} 09:15:00"
                to_date_str = f"{date_str} 15:30:00"
                
                if cleaned_interval == DAILY_INTERVAL:
                    res = await self.download_daily(
                        db=db,
                        symbol=cleaned_symbol,
                        from_date=date_str,
                        to_date=date_str
                    )
                else:
                    res = await self.download_intraday(
                        db=db,
                        symbol=cleaned_symbol,
                        interval=cleaned_interval,
                        from_date=from_date_str,
                        to_date=to_date_str
                    )
                    
                if res.get("ok"):
                    success_count += 1
                    saved = res.get("total_candles_saved", res.get("inserted_count", 0) + res.get("updated_count", 0))
                    total_saved += saved
                    results.append({
                        "date": date_str,
                        "ok": True,
                        "candles_saved": saved,
                        "message": res.get("message", "Success")
                    })
                else:
                    fail_count += 1
                    results.append({
                        "date": date_str,
                        "ok": False,
                        "message": res.get("message", "Patch failed")
                    })
            except Exception as e:
                fail_count += 1
                results.append({
                    "date": date_str,
                    "ok": False,
                    "message": str(e)
                })
                
            # Rate limit buffer between calls
            if index < len(gaps_list):
                await asyncio.sleep(1.0)
                
        return {
            "ok": fail_count == 0,
            "patched_count": len(gaps_list),
            "success_count": success_count,
            "fail_count": fail_count,
            "total_candles_saved": total_saved,
            "results": results
        }


def _historical_instrument_type(instrument: InstrumentMaster) -> str:

    segment = instrument.segment.upper()
    instrument_type = instrument.instrument_type.upper()
    if segment == "IDX_I" or instrument_type == "INDEX":
        return "INDEX"
    if segment.endswith("_EQ") or instrument_type in {"EQUITY", "EQ"}:
        return "EQUITY"
    if instrument_type in {"FUTIDX", "FUTSTK", "OPTIDX", "OPTSTK"}:
        return instrument_type
    return instrument_type or "EQUITY"


def _parse_range(from_date: str, to_date: str, include_time: bool) -> dict[str, Any]:
    start = _parse_datetime(from_date, end_of_day=False)
    end = _parse_datetime(to_date, end_of_day=include_time)
    if start is None or end is None:
        return _error("INVALID_DATE", "Invalid date format. Use YYYY-MM-DD or YYYY-MM-DD HH:MM:SS.")
    if start > end:
        return _error("INVALID_DATE_RANGE", "from_date must be earlier than or equal to to_date.")
    return {"ok": True, "from_date": start, "to_date": end}


def _parse_datetime(value: str, end_of_day: bool) -> datetime | None:
    cleaned = str(value).strip()
    if not cleaned:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            parsed = datetime.strptime(cleaned, fmt)
            if fmt == "%Y-%m-%d" and end_of_day:
                parsed = datetime.combine(parsed.date(), time(23, 59, 59))
            return parsed.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    try:
        parsed = datetime.fromisoformat(cleaned.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed
    except ValueError:
        return None


def _format_dhan_datetime(value: datetime) -> str:
    return value.strftime("%Y-%m-%d %H:%M:%S")


def _extract_historical_payload(response_data: Any) -> Any:
    payload = response_data
    while isinstance(payload, dict):
        for key in ("data", "Data", "result", "Result"):
            nested = payload.get(key)
            if isinstance(nested, dict):
                payload = nested
                break
        else:
            return payload
    return payload


def _array(payload: dict[str, Any], keys: list[str]) -> list[Any]:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, list):
            return value
    return []


def _at(values: list[Any], index: int) -> Any:
    if index >= len(values):
        return None
    return values[index]


def _optional_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_dhan_timestamp(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        timestamp = float(value)
        if timestamp > 10_000_000_000:
            timestamp = timestamp / 1000
        return datetime.fromtimestamp(timestamp, tz=timezone.utc)
    cleaned = str(value).strip()
    if not cleaned:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            parsed = datetime.strptime(cleaned, fmt)
            return parsed.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    try:
        parsed = datetime.fromisoformat(cleaned.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed
    except ValueError:
        return None


def _normalize_query_interval(interval: str) -> str:
    cleaned = str(interval).strip().lower()
    if cleaned in {"daily", "day", "1d", "1day"}:
        return DAILY_INTERVAL
    return cleaned


def _candle_to_dict(candle: Candle) -> dict[str, Any]:
    return {
        "id": candle.id,
        "source": candle.source,
        "symbol": candle.symbol,
        "security_id": candle.security_id,
        "exchange_segment": candle.exchange_segment,
        "instrument": candle.instrument,
        "interval": candle.interval,
        "timestamp": candle.timestamp,
        "open": candle.open,
        "high": candle.high,
        "low": candle.low,
        "close": candle.close,
        "volume": candle.volume,
        "open_interest": candle.open_interest,
        "created_at": candle.created_at,
    }


def _symbol_missing(symbol: str) -> dict[str, Any]:
    return _error(
        "SYMBOL_NOT_FOUND",
        f"Symbol {symbol.strip().upper()} not found in Dhan instrument master. Download/import Dhan instrument master first.",
    )


def _error(status: str, message: str) -> dict[str, Any]:
    return {
        "ok": False,
        "status": status,
        "message": message,
    }
