from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.brokers.dhan_data import DhanDataAdapter
from app.db.database import get_db
from app.engine.dhan_instrument_importer import DhanInstrumentImporter
from app.market.market_data_router import MarketDataRouter
from app.market.schemas import (
    HistoricalDailyRequest,
    IntradayRequest,
    MarketInstrumentsRequest,
    OptionChainRequest,
    OptionExpiryRequest,
)
from app.models.instrument import InstrumentRead


router = APIRouter(prefix="/api/market", tags=["market-data"])


@router.get("/status")
def market_status() -> dict:
    return MarketDataRouter().status()


@router.post("/dhan/ltp")
async def dhan_ltp(payload: MarketInstrumentsRequest) -> dict:
    return await DhanDataAdapter().get_ltp(payload.instruments)


@router.post("/dhan/ohlc")
async def dhan_ohlc(payload: MarketInstrumentsRequest) -> dict:
    return await DhanDataAdapter().get_ohlc(payload.instruments)


@router.post("/dhan/quote")
async def dhan_quote(payload: MarketInstrumentsRequest) -> dict:
    return await DhanDataAdapter().get_quote(payload.instruments)


@router.post("/dhan/historical")
async def dhan_historical(payload: HistoricalDailyRequest) -> dict:
    return await DhanDataAdapter().get_historical_daily(
        security_id=payload.security_id,
        exchange_segment=payload.exchange_segment,
        instrument=payload.instrument,
        from_date=payload.from_date,
        to_date=payload.to_date,
    )


@router.post("/dhan/intraday")
async def dhan_intraday(payload: IntradayRequest) -> dict:
    return await DhanDataAdapter().get_intraday(
        security_id=payload.security_id,
        exchange_segment=payload.exchange_segment,
        instrument=payload.instrument,
        interval=payload.interval,
        from_date=payload.from_date,
        to_date=payload.to_date,
    )


@router.post("/dhan/option-expiries")
async def dhan_option_expiries(payload: OptionExpiryRequest) -> dict:
    return await DhanDataAdapter().get_option_expiry_list(
        under_security_id=payload.under_security_id,
        under_exchange_segment=payload.under_exchange_segment,
    )


@router.post("/dhan/option-chain")
async def dhan_option_chain(payload: OptionChainRequest) -> dict:
    if payload.expiry is None:
        return {
            "ok": False,
            "connected": False,
            "status": "EXPIRY_REQUIRED",
            "message": "Expiry is required. First call /api/market/dhan/option-expiries and use one exact expiry from the response.",
            "data": None,
        }
    return await DhanDataAdapter().get_option_chain(
        under_security_id=payload.under_security_id,
        under_exchange_segment=payload.under_exchange_segment,
        expiry=payload.expiry,
    )


@router.get("/ltp/symbol/{symbol}")
async def ltp_by_symbol(symbol: str, db: Session = Depends(get_db)) -> dict:
    instrument = DhanInstrumentImporter().lookup_symbol(db, symbol)
    if instrument is None:
        return {
            "ok": False,
            "connected": False,
            "status": "SYMBOL_NOT_FOUND",
            "message": "Symbol not found in Dhan instrument master. Download/import Dhan instrument master first.",
            "symbol": symbol.upper(),
            "instrument": None,
            "data": None,
        }

    response = await DhanDataAdapter().get_ltp({instrument.segment: [instrument.security_id]})
    response["symbol"] = symbol.upper()
    response["instrument"] = InstrumentRead.model_validate(instrument)
    return response


@router.get("/option-expiries/{underlying}")
async def option_expiries_by_underlying(
    underlying: str,
    db: Session = Depends(get_db),
) -> dict:
    instrument = DhanInstrumentImporter().lookup_option_underlying(db, underlying)
    if instrument is None:
        return {
            "ok": False,
            "connected": False,
            "status": "UNDERLYING_MAPPING_NOT_FOUND",
            "message": "Dhan underlying mapping not found. Download/import Dhan instrument master first.",
            "underlying": underlying.upper(),
            "data": None,
        }

    response = await DhanDataAdapter().get_option_expiry_list(
        under_security_id=instrument.security_id,
        under_exchange_segment=instrument.segment,
    )
    response["underlying"] = underlying.upper()
    response["instrument"] = InstrumentRead.model_validate(instrument)
    return response


@router.get("/option-chain/{underlying}")
async def option_chain_by_underlying(
    underlying: str,
    expiry: date | None = Query(default=None),
    db: Session = Depends(get_db),
) -> dict:
    if expiry is None:
        return {
            "ok": False,
            "connected": False,
            "status": "EXPIRY_REQUIRED",
            "message": "Expiry is required. First call /api/market/option-expiries/{underlying} and use one exact expiry from the response.",
            "underlying": underlying.upper(),
            "data": None,
        }

    instrument = DhanInstrumentImporter().lookup_option_underlying(db, underlying)
    if instrument is None:
        return {
            "ok": False,
            "connected": False,
            "status": "UNDERLYING_MAPPING_NOT_FOUND",
            "message": "Dhan underlying mapping not found. Download/import Dhan instrument master first.",
            "underlying": underlying.upper(),
            "data": None,
        }

    response = await DhanDataAdapter().get_option_chain(
        under_security_id=instrument.security_id,
        under_exchange_segment=instrument.segment,
        expiry=expiry,
    )
    response["underlying"] = underlying.upper()
    response["instrument"] = InstrumentRead.model_validate(instrument)
    if response.get("ok"):
        response["normalized_option_chain"] = _normalize_option_chain(response.get("data"))
    return response


def _normalize_option_chain(response_data: Any) -> list[dict[str, Any]]:
    payload = response_data
    if isinstance(payload, dict):
        payload = payload.get("data", payload.get("Data", payload))
    if isinstance(payload, dict):
        payload = payload.get("oc", payload.get("optionChain", payload.get("option_chain", payload)))

    items: list[dict[str, Any]] = []
    if not isinstance(payload, dict):
        return items

    for strike, row in payload.items():
        if not isinstance(row, dict):
            continue
        for option_type in ("ce", "pe", "CE", "PE"):
            leg = row.get(option_type)
            if not isinstance(leg, dict):
                continue
            items.append(
                {
                    "strike": _number_or_text(strike),
                    "option_type": option_type.upper(),
                    "ltp": _first_present(leg, ["last_price", "lastPrice", "ltp", "LTP"]),
                    "oi": _first_present(leg, ["oi", "open_interest", "openInterest"]),
                    "volume": _first_present(leg, ["volume", "volume_traded", "volumeTraded"]),
                    "bid": _first_present(leg, ["best_bid_price", "bid_price", "bidPrice"]),
                    "ask": _first_present(leg, ["best_ask_price", "ask_price", "askPrice"]),
                    "source": "DHAN",
                }
            )
    return items


def _first_present(source: dict[str, Any], keys: list[str]) -> Any:
    for key in keys:
        if key in source and source[key] is not None:
            return source[key]
    return None


def _number_or_text(value: Any) -> int | float | str:
    text = str(value)
    try:
        number = float(text)
    except ValueError:
        return text
    return int(number) if number.is_integer() else number
