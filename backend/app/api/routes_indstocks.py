from fastapi import APIRouter, Query, Request

from app.brokers.indstocks_data import IndstocksDataClient


router = APIRouter(prefix="/api/indstocks", tags=["indstocks"])


@router.get("/status")
def indstocks_status() -> dict:
    return IndstocksDataClient().status()


@router.get("/profile")
async def indstocks_profile() -> dict:
    return await IndstocksDataClient().get_profile()


@router.get("/funds")
async def indstocks_funds() -> dict:
    return await IndstocksDataClient().get_funds()


@router.post("/instruments/download")
async def indstocks_download_instruments(
    source: str = Query(..., description="One of: equity, fno, index"),
) -> dict:
    return await IndstocksDataClient().download_instruments(source)


@router.get("/quotes/ltp")
async def indstocks_ltp(
    scrip_codes: str = Query(..., min_length=1, description="Example: NSE_3045,NFO_51011"),
) -> dict:
    return await IndstocksDataClient().get_ltp(scrip_codes)


@router.get("/quotes/full")
async def indstocks_full_quote(
    scrip_codes: str = Query(..., min_length=1, description="Example: NSE_3045"),
) -> dict:
    return await IndstocksDataClient().get_full_quote(scrip_codes)


@router.get("/quotes/depth")
async def indstocks_market_depth(
    scrip_codes: str = Query(..., min_length=1, description="Example: NSE_3045"),
) -> dict:
    return await IndstocksDataClient().get_market_depth(scrip_codes)


@router.get("/historical")
async def indstocks_historical(
    request: Request,
    interval: str = Query(..., description="Example: 5minute"),
    scrip_codes: str | None = Query(default=None, alias="scrip-codes", description="Example: NSE_3045"),
    legacy_scrip_codes: str | None = Query(default=None, alias="scrip_codes", description="Legacy alias: NSE_3045"),
    start_time: str = Query(..., min_length=1),
    end_time: str = Query(..., min_length=1),
) -> dict:
    resolved_scrip_codes = scrip_codes or legacy_scrip_codes
    if not resolved_scrip_codes:
        return {
            "ok": False,
            "connected": False,
            "status": "SCRIP_CODES_REQUIRED",
            "message": "Use the documented query parameter scrip-codes, for example scrip-codes=NSE_3045.",
            "debug": {
                "endpoint_path": str(request.url.path),
                "interval": interval,
                "range": {"start_time": start_time, "end_time": end_time},
                "status": "SCRIP_CODES_REQUIRED",
                "token_exposed": False,
            },
            "data": None,
        }
    return await IndstocksDataClient().get_historical(
        interval=interval,
        scrip_codes=resolved_scrip_codes,
        start_time=start_time,
        end_time=end_time,
    )
