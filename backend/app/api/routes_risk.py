from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.models.risk_state import RiskStateRead
from app.risk.kill_switch import KillSwitch
from app.risk.risk_limits import get_risk_limits
from app.services.live_feed_service import get_live_feed_service


router = APIRouter(prefix="/api/risk", tags=["risk"])


class KillSwitchRequest(BaseModel):
    reason: str = Field(default="Manual risk action.", max_length=500)


@router.get("/status")
def risk_status(db: Session = Depends(get_db)) -> dict:
    state = KillSwitch().get_state(db)
    live_feed_status = get_live_feed_service().status()
    return {
        "ok": True,
        "mode": "PAPER",
        "kill_switch": RiskStateRead.model_validate(state),
        "limits": get_risk_limits().snapshot(),
        "live_orders_enabled": False,
        "live_feed_enabled": live_feed_status["enabled"],
        "live_feed_connected": live_feed_status["connected"],
        "live_feed_source": live_feed_status["source"],
        "live_feed_stale": live_feed_status["stale"],
        "live_order_status": live_feed_status["live_order_status"],
        "message": "Risk layer is active. Live orders are disabled.",
    }


@router.post("/kill-switch/enable")
def enable_kill_switch(payload: KillSwitchRequest, db: Session = Depends(get_db)) -> dict:
    state = KillSwitch().enable(db, payload.reason)
    return {"ok": True, "kill_switch": RiskStateRead.model_validate(state)}


@router.post("/kill-switch/disable")
def disable_kill_switch(payload: KillSwitchRequest, db: Session = Depends(get_db)) -> dict:
    state = KillSwitch().disable(db, payload.reason)
    return {"ok": True, "kill_switch": RiskStateRead.model_validate(state)}


@router.get("/limits")
def risk_limits() -> dict:
    return {"ok": True, "limits": get_risk_limits().snapshot()}
