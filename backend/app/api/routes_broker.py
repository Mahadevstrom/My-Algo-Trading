from fastapi import APIRouter

from app.brokers.dhan_trading import DhanTradingClient


router = APIRouter(prefix="/api/broker", tags=["broker"])


@router.get("/dhan/status")
def dhan_status() -> dict:
    return DhanTradingClient().status()


@router.get("/dhan/funds")
async def dhan_funds() -> dict:
    return await DhanTradingClient().funds()


@router.get("/dhan/positions")
async def dhan_positions() -> dict:
    return await DhanTradingClient().positions()


@router.get("/dhan/orderbook")
async def dhan_orderbook() -> dict:
    return await DhanTradingClient().orderbook()


@router.get("/dhan/tradebook")
async def dhan_tradebook() -> dict:
    return await DhanTradingClient().tradebook()


@router.get("/dhan/summary")
async def dhan_summary() -> dict:
    return await DhanTradingClient().summary()
