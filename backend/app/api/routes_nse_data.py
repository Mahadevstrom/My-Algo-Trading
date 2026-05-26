from typing import Literal

from fastapi import APIRouter, Query

from app.brokers.nse_data import NseDataAdapter, normalize_nse_index_name


router = APIRouter(prefix="/api/nse-data", tags=["nse-data"])


@router.get("/status")
def nse_data_status() -> dict:
    return {
        "ok": True,
        "status": "AVAILABLE",
        "source": "NSE_PUBLIC_WEBSITE",
        "read_only": True,
        "message": "NSE public market-data endpoints are available as a read-only data source.",
        "supported": {
            "indices": "/api/nse-data/indices",
            "index_names": "/api/nse-data/index-names",
            "equity_master": "/api/nse-data/equity-master",
            "equity_stock_indices": "/api/nse-data/equity-stock-indices?index=NIFTY%2050",
            "bank_nifty_indices": "/api/nse-data/equity-stock-indices?index=NIFTY%20BANK",
            "pre_open_market": "/api/nse-data/pre-open?key=NIFTY",
            "gainers_losers": "/api/nse-data/gainers-losers?side=gainers",
            "most_active_equities": "/api/nse-data/most-active-equities?by=value",
            "option_contract_info": "/api/nse-data/option-chain/contract-info/NIFTY",
            "bank_nifty_option_contract_info": "/api/nse-data/option-chain/contract-info/BANKNIFTY",
            "option_chain": "/api/nse-data/option-chain/NIFTY?segment=indices",
            "bank_nifty_option_chain": "/api/nse-data/option-chain/BANKNIFTY?segment=indices",
            "historical_equity": "/api/nse-data/historical/security/RELIANCE?from=01-05-2026&to=22-05-2026",
            "historical_index": "/api/nse-data/historical/index?index=NIFTY%2050&from=01-05-2026&to=22-05-2026",
            "daily_reports": "/api/nse-data/reports/daily?key=CM",
            "monthly_reports": "/api/nse-data/reports/monthly?key=CM",
        },
    }


@router.get("/indices")
async def all_indices() -> dict:
    return await NseDataAdapter().get_all_indices()


@router.get("/index-names")
async def index_names() -> dict:
    return await NseDataAdapter().get_index_names()


@router.get("/equity-master")
async def equity_master() -> dict:
    return await NseDataAdapter().get_equity_master()


@router.get("/equity-stock-indices")
async def equity_stock_indices(index: str = Query(default="NIFTY 50")) -> dict:
    adapter = NseDataAdapter()
    resolved_index = normalize_nse_index_name(index)
    response = await adapter.get_equity_stock_indices(resolved_index)
    if response.get("ok"):
        response["index"] = resolved_index
        response["normalized"] = adapter.normalize_equity_index_response(response.get("data") or {}, resolved_index)
    return response


@router.get("/pre-open")
async def pre_open_market(key: str = Query(default="NIFTY")) -> dict:
    return await NseDataAdapter().get_pre_open_market(key)


@router.get("/gainers-losers")
async def gainers_losers(
    side: Literal["gainers", "losers"] = Query(default="gainers"),
) -> dict:
    return await NseDataAdapter().get_live_analysis_variations(side)


@router.get("/most-active-equities")
async def most_active_equities(
    by: Literal["value", "volume"] = Query(default="value"),
) -> dict:
    return await NseDataAdapter().get_most_active_equities(by)


@router.get("/option-chain/contract-info/{symbol}")
async def option_contract_info(symbol: str) -> dict:
    return await NseDataAdapter().get_option_contract_info(symbol)


@router.get("/option-chain/{symbol}")
async def option_chain(
    symbol: str,
    segment: Literal["indices", "equity"] = Query(default="indices"),
    expiry: str | None = Query(default=None),
) -> dict:
    return await NseDataAdapter().get_option_chain(symbol, segment=segment, expiry=expiry)


@router.get("/historical/security/{symbol}")
async def historical_security(
    symbol: str,
    from_date: str = Query(alias="from"),
    to_date: str = Query(alias="to"),
    series: str = Query(default="EQ"),
    data_type: str = Query(default="priceVolumeDeliverable"),
) -> dict:
    return await NseDataAdapter().get_historical_security(
        symbol,
        from_date=from_date,
        to_date=to_date,
        series=series,
        data_type=data_type,
    )


@router.get("/historical/equity/{symbol}")
async def historical_equity_price_volume(
    symbol: str,
    from_date: str = Query(alias="from"),
    to_date: str = Query(alias="to"),
) -> dict:
    return await NseDataAdapter().get_historical_price_volume(
        symbol,
        from_date=from_date,
        to_date=to_date,
    )


@router.get("/historical/index")
async def historical_index(
    index: str = Query(default="NIFTY 50"),
    from_date: str = Query(alias="from"),
    to_date: str = Query(alias="to"),
) -> dict:
    return await NseDataAdapter().get_historical_index(index, from_date=from_date, to_date=to_date)


@router.get("/historical/vix")
async def historical_vix(
    from_date: str = Query(alias="from"),
    to_date: str = Query(alias="to"),
) -> dict:
    return await NseDataAdapter().get_historical_vix(from_date=from_date, to_date=to_date)


@router.get("/reports/daily")
async def daily_reports(key: str = Query(default="CM")) -> dict:
    return await NseDataAdapter().get_daily_reports(key)


@router.get("/reports/monthly")
async def monthly_reports(key: str = Query(default="CM")) -> dict:
    return await NseDataAdapter().get_monthly_reports(key)
