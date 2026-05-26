import csv
from dataclasses import dataclass
from datetime import date, datetime, timezone
from io import StringIO
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy import func, inspect, or_, select
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from app.models.instrument import InstrumentMaster


BACKEND_DIR = Path(__file__).resolve().parents[2]
DHAN_DATA_DIR = BACKEND_DIR / "data" / "dhan"

DHAN_MASTER_TYPES = {
    "compact": {
        "url": "https://images.dhan.co/api-data/api-scrip-master.csv",
        "file_name": "dhan_scrip_master.csv",
        "source": "DHAN_COMPACT",
    },
    "detailed": {
        "url": "https://images.dhan.co/api-data/api-scrip-master-detailed.csv",
        "file_name": "dhan_scrip_master_detailed.csv",
        "source": "DHAN_DETAILED",
    },
}

INDEX_SYMBOL_ALIASES = {
    "NIFTY": {"NIFTY", "NIFTY 50"},
    "BANKNIFTY": {"BANKNIFTY", "NIFTY BANK"},
    "FINNIFTY": {"FINNIFTY"},
    "MIDCPNIFTY": {"MIDCPNIFTY", "NIFTY MIDCAP SELECT"},
    "SENSEX": {"SENSEX", "BSE SENSEX"},
    "BANKEX": {"BANKEX", "BSE BANKEX"},
}


class DhanInstrumentImporterError(Exception):
    status_code = 400

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class DhanInstrumentFileMissingError(DhanInstrumentImporterError):
    status_code = 404


class DhanInstrumentNetworkError(DhanInstrumentImporterError):
    status_code = 502


@dataclass(frozen=True)
class DhanDownloadResult:
    master_type: str
    url: str
    file_path: Path
    byte_count: int
    line_count: int
    message: str


@dataclass(frozen=True)
class DhanImportResult:
    master_type: str
    file_path: Path
    inserted_count: int
    updated_count: int
    skipped_count: int
    message: str


class DhanInstrumentImporter:
    def __init__(self) -> None:
        self.timeout = httpx.Timeout(60.0)

    async def download(self, master_type: str) -> DhanDownloadResult:
        meta = _master_meta(master_type)
        DHAN_DATA_DIR.mkdir(parents=True, exist_ok=True)
        target_path = DHAN_DATA_DIR / meta["file_name"]

        try:
            async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=True) as client:
                response = await client.get(meta["url"])
        except httpx.HTTPError as exc:
            raise DhanInstrumentNetworkError(
                f"Could not download Dhan instrument master: {type(exc).__name__}."
            ) from exc

        if response.status_code >= 400:
            raise DhanInstrumentNetworkError(
                f"Dhan instrument master download failed with HTTP {response.status_code}."
            )

        csv_text = response.text
        if not csv_text.strip():
            raise DhanInstrumentImporterError("Downloaded Dhan instrument master CSV was empty.")

        validation_error = _validate_csv(csv_text)
        if validation_error:
            raise DhanInstrumentImporterError(validation_error)

        target_path.write_text(csv_text, encoding="utf-8", newline="")
        line_count = len([line for line in csv_text.splitlines() if line.strip()])
        return DhanDownloadResult(
            master_type=master_type.lower(),
            url=meta["url"],
            file_path=target_path,
            byte_count=len(csv_text.encode("utf-8")),
            line_count=line_count,
            message=f"Downloaded Dhan {master_type.lower()} instrument master.",
        )

    def import_from_saved_csv(self, db: Session, master_type: str, force: bool = False) -> DhanImportResult:
        meta = _master_meta(master_type)
        csv_path = DHAN_DATA_DIR / meta["file_name"]
        if not csv_path.exists():
            raise DhanInstrumentFileMissingError(
                f"Dhan {master_type.lower()} CSV not found at {csv_path}. Download it first."
            )

        inserted_count = 0
        updated_count = 0
        skipped_count = 0
        source = meta["source"]
        legacy_security_id_unique = _has_legacy_security_id_unique_constraint(db)

        try:
            existing_source_count = db.scalar(
                select(func.count()).select_from(InstrumentMaster).where(InstrumentMaster.source == source)
            )
            raw_row_count = _csv_data_line_count(csv_path)
            if not force and existing_source_count and raw_row_count and existing_source_count >= int(raw_row_count * 0.95):
                return DhanImportResult(
                    master_type=master_type.lower(),
                    file_path=csv_path,
                    inserted_count=0,
                    updated_count=0,
                    skipped_count=0,
                    message=(
                        f"Dhan {master_type.lower()} instruments are already imported "
                        f"({existing_source_count} rows). Use force=true only when you need to refresh existing rows."
                    ),
                )

            mapped_rows, skipped_count = self._read_mapped_rows(csv_path, source)
            if not mapped_rows:
                raise DhanInstrumentImporterError("Dhan CSV did not contain any importable instruments.")

            if legacy_security_id_unique:
                inserted_count, updated_count = self._import_legacy_security_id_unique(db, mapped_rows)
            else:
                inserted_count, updated_count = self._bulk_upsert(db, mapped_rows, source)

            db.commit()
        except csv.Error as exc:
            db.rollback()
            raise DhanInstrumentImporterError(f"Invalid Dhan CSV format: {exc}.") from exc
        except DhanInstrumentImporterError:
            db.rollback()
            raise
        except Exception:
            db.rollback()
            raise

        return DhanImportResult(
            master_type=master_type.lower(),
            file_path=csv_path,
            inserted_count=inserted_count,
            updated_count=updated_count,
            skipped_count=skipped_count,
            message=(
                f"Imported Dhan {master_type.lower()} instruments: "
                f"{inserted_count} inserted, {updated_count} updated, {skipped_count} skipped."
            ),
        )

    def _read_mapped_rows(self, csv_path: Path, source: str) -> tuple[list[dict[str, Any]], int]:
        skipped_count = 0
        rows_by_key: dict[tuple[str, str, str, str], dict[str, Any]] = {}
        with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            if reader.fieldnames is None:
                raise DhanInstrumentImporterError("Dhan CSV has no header row.")

            for row in reader:
                mapped = self._map_row(row, source)
                if mapped is None:
                    skipped_count += 1
                    continue
                key = (
                    mapped["security_id"],
                    mapped["exchange"],
                    mapped["segment"],
                    mapped["source"],
                )
                if key in rows_by_key:
                    skipped_count += 1
                rows_by_key[key] = mapped
        return list(rows_by_key.values()), skipped_count

    def _bulk_upsert(
        self,
        db: Session,
        mapped_rows: list[dict[str, Any]],
        source: str,
    ) -> tuple[int, int]:
        existing_keys = {
            (security_id, exchange, segment, existing_source)
            for security_id, exchange, segment, existing_source in db.execute(
                select(
                    InstrumentMaster.security_id,
                    InstrumentMaster.exchange,
                    InstrumentMaster.segment,
                    InstrumentMaster.source,
                ).where(InstrumentMaster.source == source)
            )
        }
        incoming_keys = {
            (row["security_id"], row["exchange"], row["segment"], row["source"])
            for row in mapped_rows
        }
        inserted_count = len(incoming_keys - existing_keys)
        updated_count = len(incoming_keys & existing_keys)

        dialect_name = db.bind.dialect.name if db.bind is not None else ""
        if dialect_name == "postgresql":
            insert_factory = postgresql_insert
        elif dialect_name == "sqlite":
            insert_factory = sqlite_insert
        else:
            return self._import_row_by_row(db, mapped_rows)

        for chunk in _chunks(mapped_rows, 5000):
            statement = insert_factory(InstrumentMaster).values(chunk)
            excluded = statement.excluded
            statement = statement.on_conflict_do_update(
                index_elements=["security_id", "exchange", "segment", "source"],
                set_={
                    "trading_symbol": excluded.trading_symbol,
                    "display_name": excluded.display_name,
                    "underlying_symbol": excluded.underlying_symbol,
                    "instrument_type": excluded.instrument_type,
                    "option_type": excluded.option_type,
                    "expiry": excluded.expiry,
                    "strike": excluded.strike,
                    "lot_size": excluded.lot_size,
                    "tick_size": excluded.tick_size,
                    "updated_at": datetime.now(timezone.utc),
                },
            )
            db.execute(statement)

        return inserted_count, updated_count

    def _import_legacy_security_id_unique(
        self,
        db: Session,
        mapped_rows: list[dict[str, Any]],
    ) -> tuple[int, int]:
        rows_by_security_id = {row["security_id"]: row for row in mapped_rows}
        return self._import_row_by_row(db, list(rows_by_security_id.values()), legacy_security_id_only=True)

    def _import_row_by_row(
        self,
        db: Session,
        mapped_rows: list[dict[str, Any]],
        legacy_security_id_only: bool = False,
    ) -> tuple[int, int]:
        inserted_count = 0
        updated_count = 0
        for mapped in mapped_rows:
            if legacy_security_id_only:
                existing = db.scalar(
                    select(InstrumentMaster).where(InstrumentMaster.security_id == mapped["security_id"])
                )
            else:
                existing = db.scalar(
                    select(InstrumentMaster).where(
                        InstrumentMaster.security_id == mapped["security_id"],
                        InstrumentMaster.exchange == mapped["exchange"],
                        InstrumentMaster.segment == mapped["segment"],
                        InstrumentMaster.source == mapped["source"],
                    )
                )
            if existing:
                _update_instrument(existing, mapped)
                updated_count += 1
            else:
                db.add(InstrumentMaster(**mapped))
                inserted_count += 1

            if (inserted_count + updated_count) % 5000 == 0:
                db.flush()
        return inserted_count, updated_count

    def search(self, db: Session, query: str, limit: int = 50) -> list[InstrumentMaster]:
        cleaned = query.strip().upper()
        if not cleaned:
            return []
        pattern = f"%{cleaned}%"
        return list(
            db.scalars(
                select(InstrumentMaster)
                .where(
                    InstrumentMaster.source.in_(["DHAN_COMPACT", "DHAN_DETAILED"]),
                    or_(
                        InstrumentMaster.trading_symbol.ilike(pattern),
                        InstrumentMaster.display_name.ilike(pattern),
                        InstrumentMaster.underlying_symbol.ilike(pattern),
                        InstrumentMaster.security_id.ilike(pattern),
                    ),
                )
                .order_by(
                    InstrumentMaster.instrument_type,
                    InstrumentMaster.underlying_symbol,
                    InstrumentMaster.expiry,
                    InstrumentMaster.strike,
                    InstrumentMaster.option_type,
                )
                .limit(limit)
            )
        )

    def underlyings(self, db: Session) -> list[str]:
        return [
            value
            for value in db.scalars(
                select(InstrumentMaster.underlying_symbol)
                .where(
                    InstrumentMaster.source.in_(["DHAN_COMPACT", "DHAN_DETAILED"]),
                    InstrumentMaster.underlying_symbol != "",
                )
                .distinct()
                .order_by(InstrumentMaster.underlying_symbol)
            )
            if value
        ]

    def expiries(self, db: Session, underlying: str) -> list[date]:
        symbol = underlying.strip().upper()
        return [
            value
            for value in db.scalars(
                select(InstrumentMaster.expiry)
                .where(
                    InstrumentMaster.source.in_(["DHAN_COMPACT", "DHAN_DETAILED"]),
                    InstrumentMaster.underlying_symbol == symbol,
                    InstrumentMaster.expiry.is_not(None),
                    InstrumentMaster.option_type.in_(["CE", "PE"]),
                )
                .distinct()
                .order_by(InstrumentMaster.expiry)
            )
            if value is not None
        ]

    def options(self, db: Session, underlying: str, expiry: date) -> list[InstrumentMaster]:
        symbol = underlying.strip().upper()
        return list(
            db.scalars(
                select(InstrumentMaster)
                .where(
                    InstrumentMaster.source.in_(["DHAN_COMPACT", "DHAN_DETAILED"]),
                    InstrumentMaster.underlying_symbol == symbol,
                    InstrumentMaster.expiry == expiry,
                    InstrumentMaster.option_type.in_(["CE", "PE"]),
                )
                .order_by(InstrumentMaster.strike, InstrumentMaster.option_type)
            )
        )

    def lookup_symbol(self, db: Session, symbol: str) -> InstrumentMaster | None:
        symbol = symbol.strip().upper()
        candidates = list(
            db.scalars(
                select(InstrumentMaster).where(
                    InstrumentMaster.source.in_(["DHAN_COMPACT", "DHAN_DETAILED"]),
                    or_(
                        InstrumentMaster.trading_symbol == symbol,
                        InstrumentMaster.underlying_symbol == symbol,
                        InstrumentMaster.display_name.ilike(symbol),
                    ),
                )
            )
        )
        return _best_symbol_candidate(symbol, candidates)

    def lookup_option_underlying(self, db: Session, underlying: str) -> InstrumentMaster | None:
        symbol = underlying.strip().upper()
        index_aliases = INDEX_SYMBOL_ALIASES.get(symbol, {symbol})
        candidates = list(
            db.scalars(
                select(InstrumentMaster).where(
                    InstrumentMaster.source.in_(["DHAN_COMPACT", "DHAN_DETAILED"]),
                    or_(
                        InstrumentMaster.trading_symbol.in_(index_aliases),
                        InstrumentMaster.underlying_symbol.in_(index_aliases),
                        InstrumentMaster.display_name.in_(index_aliases),
                    ),
                )
            )
        )
        best_index = _best_index_candidate(symbol, candidates)
        if best_index is not None:
            return best_index

        option_candidate = db.scalar(
            select(InstrumentMaster)
            .where(
                InstrumentMaster.source.in_(["DHAN_COMPACT", "DHAN_DETAILED"]),
                InstrumentMaster.underlying_symbol == symbol,
                InstrumentMaster.option_type.in_(["CE", "PE"]),
            )
            .order_by(InstrumentMaster.expiry, InstrumentMaster.strike)
        )
        return option_candidate

    def _map_row(self, row: dict[str, Any], source: str) -> dict[str, Any] | None:
        exchange = _first_text(row, ["EXCH_ID", "SEM_EXM_EXCH_ID", "exchange"]).upper()
        raw_segment = _first_text(row, ["SEGMENT", "SEM_SEGMENT", "segment"]).upper()
        security_id = _first_text(row, ["SECURITY_ID", "SEM_SMST_SECURITY_ID", "security_id"])
        if not exchange or not raw_segment or not security_id:
            return None

        instrument = _first_text(
            row,
            [
                "INSTRUMENT",
                "INSTRUMENT_TYPE",
                "SEM_INSTRUMENT_NAME",
                "SEM_EXCH_INSTRUMENT_TYPE",
                "instrument_type",
            ],
        ).upper()
        trading_symbol = (
            _first_text(row, ["SYMBOL_NAME", "SEM_TRADING_SYMBOL", "TRADING_SYMBOL", "trading_symbol"])
            or _first_text(row, ["DISPLAY_NAME", "SEM_CUSTOM_SYMBOL", "display_name"])
            or security_id
        ).upper()
        display_name = _first_text(row, ["DISPLAY_NAME", "SEM_CUSTOM_SYMBOL", "display_name"]) or trading_symbol
        underlying_symbol = (
            _first_text(row, ["UNDERLYING_SYMBOL", "SM_SYMBOL_NAME", "underlying_symbol"])
            or _derive_underlying(trading_symbol, display_name, instrument)
            or trading_symbol
        ).upper()

        option_type = _normalize_option_type(
            _first_text(row, ["OPTION_TYPE", "SEM_OPTION_TYPE", "option_type"])
        )
        expiry = _parse_date(_first_text(row, ["SM_EXPIRY_DATE", "SEM_EXPIRY_DATE", "expiry"]))
        strike = _parse_float(_first_text(row, ["STRIKE_PRICE", "SEM_STRIKE_PRICE", "strike"]))
        if strike is not None and strike <= 0:
            strike = None

        lot_size = _parse_int(_first_text(row, ["LOT_SIZE", "SEM_LOT_UNITS", "lot_size"]))
        tick_size = _parse_float(_first_text(row, ["TICK_SIZE", "SEM_TICK_SIZE", "tick_size"]))
        segment = _to_dhan_exchange_segment(exchange, raw_segment, instrument)

        return {
            "exchange": exchange,
            "segment": segment,
            "security_id": security_id,
            "trading_symbol": trading_symbol,
            "display_name": display_name,
            "underlying_symbol": underlying_symbol,
            "instrument_type": instrument or "UNKNOWN",
            "option_type": option_type,
            "expiry": expiry,
            "strike": strike,
            "lot_size": lot_size,
            "tick_size": tick_size,
            "source": source,
        }


def _master_meta(master_type: str) -> dict[str, str]:
    cleaned = master_type.strip().lower()
    if cleaned not in DHAN_MASTER_TYPES:
        raise DhanInstrumentImporterError("type must be compact or detailed.")
    return DHAN_MASTER_TYPES[cleaned]


def _chunks(rows: list[dict[str, Any]], size: int) -> list[list[dict[str, Any]]]:
    return [rows[index : index + size] for index in range(0, len(rows), size)]


def _csv_data_line_count(csv_path: Path) -> int:
    with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
        line_count = sum(1 for line in handle if line.strip())
    return max(line_count - 1, 0)


def _has_legacy_security_id_unique_constraint(db: Session) -> bool:
    inspector = inspect(db.bind)
    unique_constraints = inspector.get_unique_constraints("instruments")
    for constraint in unique_constraints:
        if constraint.get("column_names") == ["security_id"]:
            return True
    indexes = inspector.get_indexes("instruments")
    for index in indexes:
        if index.get("unique") and index.get("column_names") == ["security_id"]:
            return True
    return False


def _validate_csv(csv_text: str) -> str | None:
    try:
        reader = csv.reader(StringIO(csv_text))
        header = next(reader, None)
    except csv.Error:
        return "Downloaded Dhan instrument master was not valid CSV."
    if not header or len(header) < 5:
        return "Downloaded Dhan instrument master did not contain expected columns."
    return None


def _update_instrument(existing: InstrumentMaster, mapped: dict[str, Any]) -> None:
    for key, value in mapped.items():
        setattr(existing, key, value)
    existing.updated_at = datetime.now(timezone.utc)


def _first_text(row: dict[str, Any], keys: list[str]) -> str:
    for key in keys:
        value = row.get(key)
        if value is not None and str(value).strip() not in {"", "NA", "NaN", "nan"}:
            return str(value).strip()
    return ""


def _normalize_option_type(value: str) -> str | None:
    cleaned = value.strip().upper()
    if cleaned in {"CE", "PE"}:
        return cleaned
    return None


def _parse_date(value: str) -> date | None:
    cleaned = value.strip()
    if not cleaned:
        return None
    for fmt in ("%Y-%m-%d", "%Y-%m-%d %H:%M:%S", "%d-%m-%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(cleaned, fmt).date()
        except ValueError:
            continue
    return None


def _parse_float(value: str) -> float | None:
    cleaned = value.strip()
    if not cleaned:
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def _parse_int(value: str) -> int | None:
    parsed = _parse_float(value)
    if parsed is None:
        return None
    return int(parsed)


def _to_dhan_exchange_segment(exchange: str, raw_segment: str, instrument: str) -> str:
    exchange = exchange.upper()
    raw_segment = raw_segment.upper()
    instrument = instrument.upper()
    if raw_segment == "I" or instrument == "INDEX":
        return "IDX_I"
    if exchange == "NSE" and raw_segment == "E":
        return "NSE_EQ"
    if exchange == "BSE" and raw_segment == "E":
        return "BSE_EQ"
    if exchange == "NSE" and raw_segment == "D":
        return "NSE_FNO"
    if exchange == "BSE" and raw_segment == "D":
        return "BSE_FNO"
    if exchange == "NSE" and raw_segment == "C":
        return "NSE_CURRENCY"
    if exchange == "BSE" and raw_segment == "C":
        return "BSE_CURRENCY"
    return f"{exchange}_{raw_segment}"


def _derive_underlying(trading_symbol: str, display_name: str, instrument: str) -> str:
    for text in (trading_symbol, display_name):
        cleaned = text.strip().upper()
        if not cleaned:
            continue
        if instrument in {"OPTIDX", "OPTSTK", "FUTIDX", "FUTSTK", "OP", "FUT"}:
            return cleaned.split("-")[0].split()[0]
        return cleaned
    return ""


def _best_symbol_candidate(symbol: str, candidates: list[InstrumentMaster]) -> InstrumentMaster | None:
    if not candidates:
        return None
    exact_option_candidates = [
        item
        for item in candidates
        if item.trading_symbol.upper() == symbol
        and item.option_type in {"CE", "PE"}
        and item.expiry is not None
    ]
    if exact_option_candidates:
        today = date.today()
        active = [item for item in exact_option_candidates if item.expiry and item.expiry >= today]
        if active:
            return sorted(active, key=lambda item: (item.expiry, item.source, item.id or 0))[0]
        return sorted(exact_option_candidates, key=lambda item: (item.expiry or date.min, item.source, item.id or 0), reverse=True)[0]

    def score(item: InstrumentMaster) -> tuple[int, str, int]:
        instrument = item.instrument_type.upper()
        segment = item.segment.upper()
        score_value = 0
        if item.trading_symbol.upper() == symbol:
            score_value += 100
        if item.underlying_symbol.upper() == symbol:
            score_value += 50
        if instrument == "INDEX":
            score_value += 40
        if instrument in {"EQUITY", "EQ"} or segment.endswith("_EQ"):
            score_value += 35
        if segment == "NSE_EQ":
            score_value += 20
        if segment == "BSE_EQ":
            score_value += 10
        if item.option_type in {"CE", "PE"}:
            score_value -= 50
        if item.expiry is not None:
            score_value -= 5
        return (-score_value, item.source, item.id or 0)

    return sorted(candidates, key=score)[0]


def _best_index_candidate(symbol: str, candidates: list[InstrumentMaster]) -> InstrumentMaster | None:
    index_candidates = [
        item
        for item in candidates
        if item.instrument_type.upper() == "INDEX" or item.segment.upper() == "IDX_I"
    ]
    if not index_candidates:
        return None

    aliases = INDEX_SYMBOL_ALIASES.get(symbol, {symbol})

    def score(item: InstrumentMaster) -> tuple[int, int]:
        score_value = 0
        if item.trading_symbol.upper() == symbol:
            score_value += 100
        if item.underlying_symbol.upper() == symbol:
            score_value += 80
        if item.display_name and item.display_name.upper() in aliases:
            score_value += 40
        if item.exchange.upper() == "NSE":
            score_value += 10
        return (-score_value, item.id or 0)

    return sorted(index_candidates, key=score)[0]
