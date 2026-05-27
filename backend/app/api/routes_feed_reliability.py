from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.services.dhan_rest_quota_service import get_dhan_rest_quota_service
from app.services.feed_reliability_service import get_feed_reliability_service


router = APIRouter(prefix="/api/feed-reliability", tags=["feed-reliability"])


@router.get("/status")
async def feed_reliability_status() -> dict:
    return {"ok": True, **await get_feed_reliability_service().status()}


@router.post("/check-once")
async def feed_reliability_check_once(db: Session = Depends(get_db)) -> dict:
    return await get_feed_reliability_service().check_once(db)


@router.post("/start")
async def feed_reliability_start() -> dict:
    return await get_feed_reliability_service().start()


@router.post("/stop")
async def feed_reliability_stop() -> dict:
    return await get_feed_reliability_service().stop()


@router.get("/rest-quota")
def feed_reliability_rest_quota() -> dict:
    return {"ok": True, "dhan_rest_quota": get_dhan_rest_quota_service().status()}
