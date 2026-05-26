from datetime import date
from time import monotonic
from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.brokers.dhan_data import DhanDataAdapter
from app.db.database import get_db
from app.engine.dhan_instrument_importer import DhanInstrumentImporter
from app.engine.option_chain_analyzer import OptionChainAnalyzer
from app.engine.option_chain_normalizer import OptionChainNormalizer
from app.models.instrument import InstrumentRead


router = APIRouter(prefix="/api/option-chain", tags=["option-chain"])

EXPIRY_REQUIRED_MESSAGE = (
    "Expiry is required. First call /api/market/option-expiries/{underlying} "
    "and use one exact expiry from the response."
)
_CHAIN_CACHE: dict[tuple[str, str], tuple[float, dict[str, Any]]] = {}
_CHAIN_CACHE_TTL_SECONDS = 90.0


@router.get("/analyze/{underlying}")
async def analyze_option_chain(
    underlying: str,
    expiry: date | None = Query(default=None),
    include_raw: bool = Query(default=False),
    db: Session = Depends(get_db),
) -> dict:
    result = await _build_chain_analysis(db, underlying, expiry)
    if not result.get("ok"):
        return result
    response = {
        "ok": True,
        "summary": result["summary"],
        "strikes": result["strikes"],
        "raw_available": True,
    }
    if include_raw:
        response["raw"] = result["raw"]
    return response


@router.get("/summary/{underlying}")
async def option_chain_summary(
    underlying: str,
    expiry: date | None = Query(default=None),
    db: Session = Depends(get_db),
) -> dict:
    result = await _build_chain_analysis(db, underlying, expiry)
    if not result.get("ok"):
        return result
    return {
        "ok": True,
        "summary": result["summary"],
        "raw_available": True,
    }


@router.get("/atm/{underlying}")
async def option_chain_atm(
    underlying: str,
    expiry: date | None = Query(default=None),
    db: Session = Depends(get_db),
) -> dict:
    result = await _build_chain_analysis(db, underlying, expiry)
    if not result.get("ok"):
        return result

    strikes = result["strikes"]
    atm_strike = result["summary"].get("atm_strike")
    if atm_strike is None:
        atm_window = []
    else:
        sorted_strikes = sorted(strikes, key=lambda row: row["strike"])
        atm_index = next(
            (index for index, row in enumerate(sorted_strikes) if row["strike"] == atm_strike),
            None,
        )
        if atm_index is None:
            atm_window = []
        else:
            start = max(atm_index - 5, 0)
            end = min(atm_index + 6, len(sorted_strikes))
            atm_window = sorted_strikes[start:end]

    return {
        "ok": True,
        "spot_price": result["summary"].get("spot_price"),
        "atm_strike": atm_strike,
        "strikes": atm_window,
        "summary": result["summary"],
    }


@router.get("/nearby")
async def option_chain_nearby(
    db: Session = Depends(get_db),
) -> dict:
    underlying = "NIFTY"
    importer = DhanInstrumentImporter()
    underlying_instrument = importer.lookup_option_underlying(db, underlying)
    if underlying_instrument is None:
        return {
            "ok": False,
            "status": "UNDERLYING_NOT_FOUND",
            "message": "NIFTY not found in Dhan instrument master.",
            "underlying": underlying,
            "strikes": [],
        }

    adapter = DhanDataAdapter()
    expiry_resp = await adapter.get_option_expiry_list(
        under_security_id=underlying_instrument.security_id,
        under_exchange_segment=underlying_instrument.segment,
    )
    expiries = expiry_resp.get("data")
    if not expiries or not isinstance(expiries, list):
        return {
            "ok": False,
            "status": "EXPIRY_NOT_FOUND",
            "message": "Could not retrieve options expiry dates from Dhan.",
            "underlying": underlying,
            "strikes": [],
        }

    first_expiry_str = expiries[0]
    try:
        first_expiry = date.fromisoformat(first_expiry_str)
    except Exception:
        return {
            "ok": False,
            "status": "INVALID_EXPIRY_DATE",
            "message": f"Invalid expiry date format: {first_expiry_str}",
            "underlying": underlying,
            "strikes": [],
        }

    atm_res = await option_chain_atm(underlying=underlying, expiry=first_expiry, db=db)
    return atm_res


@router.get("/liquid-options/{underlying}")
async def liquid_options(
    underlying: str,
    expiry: date | None = Query(default=None),
    min_score: int = Query(default=60, ge=0, le=100),
    db: Session = Depends(get_db),
) -> dict:
    result = await _build_chain_analysis(db, underlying, expiry)
    if not result.get("ok"):
        return result

    items: list[dict[str, Any]] = []
    for row in result["strikes"]:
        if (row.get("ce_liquidity_score") or 0) >= min_score:
            items.append(_liquid_leg(row, "CE"))
        if (row.get("pe_liquidity_score") or 0) >= min_score:
            items.append(_liquid_leg(row, "PE"))

    return {
        "ok": True,
        "underlying": underlying.upper(),
        "expiry": str(expiry),
        "min_score": min_score,
        "count": len(items),
        "items": items,
        "summary": result["summary"],
    }


async def _build_chain_analysis(
    db: Session,
    underlying: str,
    expiry: date | None,
) -> dict:
    if expiry is None:
        return {
            "ok": False,
            "status": "EXPIRY_REQUIRED",
            "message": EXPIRY_REQUIRED_MESSAGE,
            "underlying": underlying.upper(),
            "data": None,
        }

    importer = DhanInstrumentImporter()
    underlying_instrument = importer.lookup_option_underlying(db, underlying)
    if underlying_instrument is None:
        return {
            "ok": False,
            "status": "UNDERLYING_NOT_FOUND",
            "message": "Underlying not found in Dhan instrument master.",
            "underlying": underlying.upper(),
            "data": None,
        }

    adapter = DhanDataAdapter()
    cache_key = (underlying.upper(), expiry.isoformat())
    cached = _CHAIN_CACHE.get(cache_key)
    if cached and monotonic() - cached[0] <= _CHAIN_CACHE_TTL_SECONDS:
        chain_response = cached[1]
    else:
        chain_response = await adapter.get_option_chain(
            under_security_id=underlying_instrument.security_id,
            under_exchange_segment=underlying_instrument.segment,
            expiry=expiry,
        )
        if chain_response.get("ok"):
            _CHAIN_CACHE[cache_key] = (monotonic(), chain_response)
    if not chain_response.get("ok"):
        return {
            "ok": False,
            "status": chain_response.get("status", "DHAN_API_ERROR"),
            "message": chain_response.get("message", "Dhan API failed while fetching option chain."),
            "underlying": underlying.upper(),
            "expiry": str(expiry),
            "data": chain_response.get("data"),
        }

    normalizer = OptionChainNormalizer()
    extraction = normalizer.extract_chain(chain_response.get("data"))
    spot_price = extraction.spot_price
    if spot_price is None:
        spot_price = await _get_spot_ltp(db, underlying)
    strikes = normalizer.normalize(
        chain_response.get("data"),
        underlying=underlying,
        expiry=expiry,
        spot_price=spot_price,
    )
    if not strikes:
        return {
            "ok": False,
            "status": "NO_OPTION_CHAIN_DATA",
            "message": "No option chain data found for this underlying and expiry.",
            "underlying": underlying.upper(),
            "expiry": str(expiry),
            "data": None,
        }

    resolved_spot = spot_price if spot_price is not None else extraction.spot_price
    summary = OptionChainAnalyzer().analyze(
        strikes,
        underlying=underlying,
        expiry=str(expiry),
        spot_price=resolved_spot,
    )

    return {
        "ok": True,
        "summary": summary,
        "strikes": strikes,
        "raw": chain_response.get("data"),
        "underlying_instrument": InstrumentRead.model_validate(underlying_instrument),
    }


async def _get_spot_ltp(db: Session, underlying: str) -> float | None:
    instrument = DhanInstrumentImporter().lookup_symbol(db, underlying)
    if instrument is None:
        return None
    response = await DhanDataAdapter().get_ltp({instrument.segment: [instrument.security_id]})
    normalized = response.get("normalized")
    if isinstance(normalized, list) and normalized:
        value = normalized[0].get("ltp")
        try:
            return float(value)
        except (TypeError, ValueError):
            return None
    return None


def _liquid_leg(row: dict[str, Any], option_type: str) -> dict[str, Any]:
    prefix = option_type.lower()
    return {
        "underlying": row["underlying"],
        "expiry": row["expiry"],
        "strike": row["strike"],
        "option_type": option_type,
        "ltp": row.get(f"{prefix}_ltp"),
        "oi": row.get(f"{prefix}_oi"),
        "volume": row.get(f"{prefix}_volume"),
        "bid": row.get(f"{prefix}_bid"),
        "ask": row.get(f"{prefix}_ask"),
        "spread": row.get(f"{prefix}_spread"),
        "liquidity_score": row.get(f"{prefix}_liquidity_score"),
        "activity": row.get(f"{prefix}_activity"),
        "buildup": row.get(f"{prefix}_buildup"),
    }
