from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.engine.dhan_instrument_importer import (
    DhanInstrumentImporter,
    DhanInstrumentImporterError,
)
from app.models.instrument import InstrumentRead


router = APIRouter(prefix="/api/instruments/dhan", tags=["dhan-instruments"])


class DhanInstrumentMasterRequest(BaseModel):
    type: Literal["compact", "detailed"] = "compact"
    force: bool = False


@router.post("/download")
async def download_dhan_instruments(payload: DhanInstrumentMasterRequest) -> dict:
    try:
        result = await DhanInstrumentImporter().download(payload.type)
    except DhanInstrumentImporterError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc

    return {
        "ok": True,
        "type": result.master_type,
        "url": result.url,
        "file_path": str(result.file_path),
        "byte_count": result.byte_count,
        "line_count": result.line_count,
        "message": result.message,
    }


@router.post("/import")
def import_dhan_instruments(
    payload: DhanInstrumentMasterRequest,
    db: Session = Depends(get_db),
) -> dict:
    try:
        result = DhanInstrumentImporter().import_from_saved_csv(db, payload.type, force=payload.force)
    except DhanInstrumentImporterError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc

    return {
        "ok": True,
        "type": result.master_type,
        "file_path": str(result.file_path),
        "inserted_count": result.inserted_count,
        "updated_count": result.updated_count,
        "skipped_count": result.skipped_count,
        "message": result.message,
    }


@router.get("/search")
def search_dhan_instruments(
    query: str = Query(..., min_length=1),
    db: Session = Depends(get_db),
) -> dict:
    items = DhanInstrumentImporter().search(db, query)
    return {
        "query": query,
        "count": len(items),
        "items": [InstrumentRead.model_validate(item) for item in items],
        "message": None if items else "No Dhan instruments found. Download/import Dhan instrument master first.",
    }


@router.get("/lookup")
def lookup_dhan_symbol(
    symbol: str = Query(..., min_length=1),
    db: Session = Depends(get_db),
) -> dict:
    item = DhanInstrumentImporter().lookup_symbol(db, symbol)
    if item is None:
        return {
            "ok": False,
            "symbol": symbol.upper(),
            "message": "Symbol not found in Dhan instrument master. Download/import Dhan instrument master first.",
            "instrument": None,
        }
    return {
        "ok": True,
        "symbol": symbol.upper(),
        "instrument": InstrumentRead.model_validate(item),
    }


@router.get("/options")
def dhan_options(
    underlying: str = Query(..., min_length=1),
    expiry: date = Query(...),
    db: Session = Depends(get_db),
) -> dict:
    items = DhanInstrumentImporter().options(db, underlying, expiry)
    return {
        "underlying": underlying.upper(),
        "expiry": expiry,
        "count": len(items),
        "items": [InstrumentRead.model_validate(item) for item in items],
        "message": None if items else "No Dhan option instruments found for this underlying and expiry.",
    }


@router.get("/underlyings")
def dhan_underlyings(db: Session = Depends(get_db)) -> dict:
    underlyings = DhanInstrumentImporter().underlyings(db)
    return {
        "count": len(underlyings),
        "underlyings": underlyings,
        "message": None if underlyings else "No Dhan underlyings found. Download/import Dhan instrument master first.",
    }


@router.get("/expiries")
def dhan_expiries(
    underlying: str = Query(..., min_length=1),
    db: Session = Depends(get_db),
) -> dict:
    expiries = DhanInstrumentImporter().expiries(db, underlying)
    return {
        "underlying": underlying.upper(),
        "count": len(expiries),
        "expiries": expiries,
        "message": None if expiries else "No Dhan expiries found for this underlying.",
    }
