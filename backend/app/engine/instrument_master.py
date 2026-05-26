import csv
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models.instrument import InstrumentMaster


BACKEND_DIR = Path(__file__).resolve().parents[2]
DATA_DIR = BACKEND_DIR / "data"
DEFAULT_IMPORT_FILE = DATA_DIR / "instruments.csv"

REQUIRED_COLUMNS = {
    "exchange",
    "segment",
    "security_id",
    "trading_symbol",
    "display_name",
    "underlying_symbol",
    "instrument_type",
    "option_type",
    "expiry",
    "strike",
    "lot_size",
    "tick_size",
    "source",
}


class InstrumentImportError(Exception):
    status_code = 400

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class InstrumentFileMissingError(InstrumentImportError):
    status_code = 404


class InstrumentDuplicateError(InstrumentImportError):
    status_code = 409


class InstrumentMasterService:
    def search(self, db: Session, query: str, limit: int = 50) -> list[InstrumentMaster]:
        cleaned = query.strip().upper()
        if not cleaned:
            return []

        pattern = f"%{cleaned}%"
        statement = (
            select(InstrumentMaster)
            .where(
                or_(
                    InstrumentMaster.trading_symbol.ilike(pattern),
                    InstrumentMaster.display_name.ilike(pattern),
                    InstrumentMaster.underlying_symbol.ilike(pattern),
                    InstrumentMaster.security_id.ilike(pattern),
                )
            )
            .order_by(
                InstrumentMaster.underlying_symbol,
                InstrumentMaster.expiry,
                InstrumentMaster.strike,
                InstrumentMaster.option_type,
            )
            .limit(limit)
        )
        return list(db.scalars(statement))

    def underlyings(self, db: Session) -> list[str]:
        statement = (
            select(InstrumentMaster.underlying_symbol)
            .distinct()
            .order_by(InstrumentMaster.underlying_symbol)
        )
        return [value for value in db.scalars(statement) if value]

    def expiries(self, db: Session, underlying: str) -> list[date]:
        statement = (
            select(InstrumentMaster.expiry)
            .where(
                InstrumentMaster.underlying_symbol == underlying.strip().upper(),
                InstrumentMaster.expiry.is_not(None),
            )
            .distinct()
            .order_by(InstrumentMaster.expiry)
        )
        return [value for value in db.scalars(statement) if value is not None]

    def option_chain_symbols(
        self, db: Session, underlying: str, expiry: date
    ) -> list[InstrumentMaster]:
        statement = (
            select(InstrumentMaster)
            .where(
                InstrumentMaster.underlying_symbol == underlying.strip().upper(),
                InstrumentMaster.expiry == expiry,
                InstrumentMaster.option_type.in_(["CE", "PE"]),
            )
            .order_by(InstrumentMaster.strike, InstrumentMaster.option_type)
        )
        return list(db.scalars(statement))

    def import_from_csv(
        self, db: Session, file_name: str = "instruments.csv"
    ) -> tuple[int, int, Path]:
        csv_path = self._resolve_csv_path(file_name)
        if not csv_path.exists():
            raise InstrumentFileMissingError(
                f"Instrument CSV file missing: {csv_path}. Place instruments.csv in backend/data."
            )

        rows = self._read_rows(csv_path)
        if not rows:
            raise InstrumentImportError("Instrument CSV is empty.")

        duplicate_security_ids = self._find_duplicate_security_ids(rows)
        if duplicate_security_ids:
            raise InstrumentDuplicateError(
                "Duplicate security_id values found in CSV: "
                + ", ".join(sorted(duplicate_security_ids))
            )

        existing_ids = set(
            db.scalars(
                select(InstrumentMaster.security_id).where(
                    InstrumentMaster.security_id.in_([row.security_id for row in rows])
                )
            )
        )
        if existing_ids:
            raise InstrumentDuplicateError(
                "security_id already exists in database: " + ", ".join(sorted(existing_ids))
            )

        instruments = [self._row_to_model(row) for row in rows]
        db.add_all(instruments)
        db.commit()
        return len(instruments), 0, csv_path

    def _resolve_csv_path(self, file_name: str) -> Path:
        return DATA_DIR / file_name

    def _read_rows(self, csv_path: Path) -> list["_InstrumentCsvRow"]:
        try:
            with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
                reader = csv.DictReader(handle)
                if reader.fieldnames is None:
                    raise InstrumentImportError("Instrument CSV has no header row.")
                missing = REQUIRED_COLUMNS - set(reader.fieldnames)
                if missing:
                    raise InstrumentImportError(
                        "Instrument CSV is missing required columns: "
                        + ", ".join(sorted(missing))
                    )

                rows: list[_InstrumentCsvRow] = []
                for line_number, raw_row in enumerate(reader, start=2):
                    if self._is_blank_row(raw_row):
                        continue
                    rows.append(self._parse_row(raw_row, line_number))
                return rows
        except UnicodeDecodeError as exc:
            raise InstrumentImportError("Instrument CSV must be UTF-8 encoded.") from exc
        except csv.Error as exc:
            raise InstrumentImportError(f"Invalid CSV format: {exc}.") from exc

    def _parse_row(self, raw_row: dict[str, Any], line_number: int) -> "_InstrumentCsvRow":
        try:
            return _InstrumentCsvRow(
                exchange=_required_text(raw_row, "exchange", line_number).upper(),
                segment=_required_text(raw_row, "segment", line_number).upper(),
                security_id=_required_text(raw_row, "security_id", line_number),
                trading_symbol=_required_text(raw_row, "trading_symbol", line_number).upper(),
                display_name=_optional_text(raw_row, "display_name"),
                underlying_symbol=_required_text(raw_row, "underlying_symbol", line_number).upper(),
                instrument_type=_required_text(raw_row, "instrument_type", line_number).upper(),
                option_type=_optional_text(raw_row, "option_type", uppercase=True),
                expiry=_optional_date(raw_row, "expiry", line_number),
                strike=_optional_float(raw_row, "strike", line_number),
                lot_size=_optional_int(raw_row, "lot_size", line_number),
                tick_size=_optional_float(raw_row, "tick_size", line_number),
                source=_optional_text(raw_row, "source", uppercase=True) or "LOCAL_CSV",
            )
        except ValueError as exc:
            raise InstrumentImportError(str(exc)) from exc

    def _row_to_model(self, row: "_InstrumentCsvRow") -> InstrumentMaster:
        return InstrumentMaster(
            exchange=row.exchange,
            segment=row.segment,
            security_id=row.security_id,
            trading_symbol=row.trading_symbol,
            display_name=row.display_name,
            underlying_symbol=row.underlying_symbol,
            instrument_type=row.instrument_type,
            option_type=row.option_type,
            expiry=row.expiry,
            strike=row.strike,
            lot_size=row.lot_size,
            tick_size=row.tick_size,
            source=row.source,
        )

    def _find_duplicate_security_ids(self, rows: list["_InstrumentCsvRow"]) -> set[str]:
        seen: set[str] = set()
        duplicates: set[str] = set()
        for row in rows:
            if row.security_id in seen:
                duplicates.add(row.security_id)
            seen.add(row.security_id)
        return duplicates

    def _is_blank_row(self, raw_row: dict[str, Any]) -> bool:
        return all(str(value or "").strip() == "" for value in raw_row.values())


@dataclass(frozen=True)
class _InstrumentCsvRow:
    exchange: str
    segment: str
    security_id: str
    trading_symbol: str
    display_name: str | None
    underlying_symbol: str
    instrument_type: str
    option_type: str | None
    expiry: date | None
    strike: float | None
    lot_size: int | None
    tick_size: float | None
    source: str


def _required_text(raw_row: dict[str, Any], column: str, line_number: int) -> str:
    value = str(raw_row.get(column) or "").strip()
    if value == "":
        raise ValueError(f"Line {line_number}: {column} is required.")
    return value


def _optional_text(
    raw_row: dict[str, Any], column: str, uppercase: bool = False
) -> str | None:
    value = str(raw_row.get(column) or "").strip()
    if value == "":
        return None
    return value.upper() if uppercase else value


def _optional_date(raw_row: dict[str, Any], column: str, line_number: int) -> date | None:
    value = str(raw_row.get(column) or "").strip()
    if value == "":
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError as exc:
        raise ValueError(f"Line {line_number}: {column} must use YYYY-MM-DD format.") from exc


def _optional_float(raw_row: dict[str, Any], column: str, line_number: int) -> float | None:
    value = str(raw_row.get(column) or "").strip()
    if value == "":
        return None
    try:
        return float(value)
    except ValueError as exc:
        raise ValueError(f"Line {line_number}: {column} must be a number.") from exc


def _optional_int(raw_row: dict[str, Any], column: str, line_number: int) -> int | None:
    value = str(raw_row.get(column) or "").strip()
    if value == "":
        return None
    try:
        return int(value)
    except ValueError as exc:
        raise ValueError(f"Line {line_number}: {column} must be an integer.") from exc

