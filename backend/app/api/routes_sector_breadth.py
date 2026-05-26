from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.market_breadth.sector_universe import normalize_sector
from app.services.sector_breadth_service import get_sector_breadth_service


router = APIRouter(prefix="/api/sector-breadth", tags=["sector-breadth"])


@router.get("/status")
def sector_breadth_status() -> dict:
    return {"ok": True, **get_sector_breadth_service().status()}


@router.get("/summary")
async def sector_breadth_summary(
    index: str = Query(default="NIFTY"),
    db: Session = Depends(get_db),
) -> dict:
    return await get_sector_breadth_service().summary(db, index)


@router.get("/sectors")
async def sector_breadth_sectors(
    index: str = Query(default="NIFTY"),
    db: Session = Depends(get_db),
) -> dict:
    return await get_sector_breadth_service().sectors(db, index)


@router.get("/sector/{sector}")
async def sector_breadth_sector(sector: str, db: Session = Depends(get_db)) -> dict:
    return await get_sector_breadth_service().sector_detail(db, normalize_sector(sector))


@router.get("/nifty-confirmation")
async def sector_breadth_nifty_confirmation(db: Session = Depends(get_db)) -> dict:
    return await get_sector_breadth_service().nifty_confirmation(db)


@router.get("/heavyweights")
async def sector_breadth_heavyweights(db: Session = Depends(get_db)) -> dict:
    return await get_sector_breadth_service().heavyweights(db)


@router.get("/heatmap")
async def sector_breadth_heatmap(db: Session = Depends(get_db)) -> dict:
    return await get_sector_breadth_service().heatmap(db)


@router.get("/constituents")
async def sector_breadth_constituents(
    index: str = Query(default="NIFTY"),
    db: Session = Depends(get_db),
) -> dict:
    return await get_sector_breadth_service().constituents(db, index)


@router.get("/explain")
async def sector_breadth_explain(db: Session = Depends(get_db)) -> dict:
    return await get_sector_breadth_service().explain(db)


@router.post("/refresh")
async def sector_breadth_refresh(
    index: str = Query(default="NIFTY"),
    db: Session = Depends(get_db),
) -> dict:
    return await get_sector_breadth_service().summary(db, index, force_refresh=True)
