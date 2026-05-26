from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.schemas.live_feed import LiveFeedSubscriptionRequest
from app.services.live_feed_service import get_live_feed_service


router = APIRouter(prefix="/api/live-feed", tags=["live-feed"])


@router.get("/status")
def live_feed_status(db: Session = Depends(get_db)) -> dict:
    service = get_live_feed_service()
    service.audit_stale_if_needed(db)
    return {"ok": True, **service.status()}


@router.get("/health")
def live_feed_health(db: Session = Depends(get_db)) -> dict:
    service = get_live_feed_service()
    service.audit_stale_if_needed(db)
    return service.health()


@router.post("/start")
async def start_live_feed(
    payload: LiveFeedSubscriptionRequest | None = None,
    db: Session = Depends(get_db),
) -> dict:
    payload = payload or LiveFeedSubscriptionRequest()
    return await get_live_feed_service().start(
        db,
        symbols=payload.symbols,
        security_ids=payload.security_ids,
    )


@router.post("/stop")
async def stop_live_feed(db: Session = Depends(get_db)) -> dict:
    return await get_live_feed_service().stop(db)


@router.post("/subscribe")
async def subscribe_live_feed(
    payload: LiveFeedSubscriptionRequest,
    db: Session = Depends(get_db),
) -> dict:
    return await get_live_feed_service().subscribe(
        db,
        symbols=payload.symbols,
        security_ids=payload.security_ids,
    )


@router.post("/unsubscribe")
async def unsubscribe_live_feed(
    payload: LiveFeedSubscriptionRequest,
    db: Session = Depends(get_db),
) -> dict:
    return await get_live_feed_service().unsubscribe(
        db,
        symbols=payload.symbols,
        security_ids=payload.security_ids,
    )


@router.get("/tick/security/{security_id}")
async def latest_tick_by_security_id(security_id: str) -> dict:
    return await get_live_feed_service().tick_by_security_id(security_id)


@router.get("/tick/{symbol}")
async def latest_tick_by_symbol(symbol: str) -> dict:
    return await get_live_feed_service().tick_by_symbol(symbol)


@router.get("/ticks")
async def latest_ticks() -> dict:
    return await get_live_feed_service().ticks()
