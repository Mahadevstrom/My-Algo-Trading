from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.engine.instrument_master import InstrumentImportError, InstrumentMasterService
from app.models.instrument import (
    ExpiriesResponse,
    InstrumentImportRequest,
    InstrumentImportResponse,
    InstrumentRead,
    InstrumentSearchResponse,
    OptionChainSymbolsResponse,
    UnderlyingsResponse,
)


router = APIRouter(prefix="/api/instruments", tags=["instruments"])


@router.get("/search", response_model=InstrumentSearchResponse)
def search_instruments(
    query: str = Query(..., min_length=1),
    db: Session = Depends(get_db),
) -> InstrumentSearchResponse:
    items = InstrumentMasterService().search(db, query)
    return InstrumentSearchResponse(
        query=query,
        count=len(items),
        items=[InstrumentRead.model_validate(item) for item in items],
        message=None if items else "No instruments found.",
    )


@router.get("/underlyings", response_model=UnderlyingsResponse)
def get_underlyings(db: Session = Depends(get_db)) -> UnderlyingsResponse:
    underlyings = InstrumentMasterService().underlyings(db)
    return UnderlyingsResponse(
        count=len(underlyings),
        underlyings=underlyings,
        message=None if underlyings else "No underlyings found. Import instruments first.",
    )


@router.get("/expiries", response_model=ExpiriesResponse)
def get_expiries(
    underlying: str = Query(..., min_length=1),
    db: Session = Depends(get_db),
) -> ExpiriesResponse:
    expiries = InstrumentMasterService().expiries(db, underlying)
    return ExpiriesResponse(
        underlying=underlying.upper(),
        count=len(expiries),
        expiries=expiries,
        message=None if expiries else "No expiries found for this underlying.",
    )


@router.get("/option-chain-symbols", response_model=OptionChainSymbolsResponse)
def get_option_chain_symbols(
    underlying: str = Query(..., min_length=1),
    expiry: date = Query(...),
    db: Session = Depends(get_db),
) -> OptionChainSymbolsResponse:
    items = InstrumentMasterService().option_chain_symbols(db, underlying, expiry)
    return OptionChainSymbolsResponse(
        underlying=underlying.upper(),
        expiry=expiry,
        count=len(items),
        items=[InstrumentRead.model_validate(item) for item in items],
        message=None if items else "No option chain symbols found for this underlying and expiry.",
    )


@router.post("/import", response_model=InstrumentImportResponse)
def import_instruments(
    payload: InstrumentImportRequest | None = None,
    db: Session = Depends(get_db),
) -> InstrumentImportResponse:
    request = payload or InstrumentImportRequest()
    try:
        imported_count, skipped_count, source_path = InstrumentMasterService().import_from_csv(
            db, request.file_name
        )
    except InstrumentImportError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc

    return InstrumentImportResponse(
        imported_count=imported_count,
        skipped_count=skipped_count,
        source_file=str(source_path),
        message=f"Imported {imported_count} instruments from {source_path.name}.",
    )

