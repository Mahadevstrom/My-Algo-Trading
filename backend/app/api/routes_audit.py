from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.audit.audit_logger import AuditLogger
from app.db.database import get_db
from app.models.audit_log import AuditLogRead


router = APIRouter(prefix="/api/audit", tags=["audit"])


@router.get("/events")
def audit_events(
    limit: int = Query(default=100, ge=1, le=500),
    event_type: str | None = Query(default=None),
    db: Session = Depends(get_db),
) -> dict:
    items = AuditLogger().list_events(db, limit=limit, event_type=event_type)
    return {
        "ok": True,
        "count": len(items),
        "items": [AuditLogRead.model_validate(item) for item in items],
    }


@router.get("/events/{event_id}")
def audit_event(event_id: int, db: Session = Depends(get_db)) -> AuditLogRead:
    event = AuditLogger().get_event(db, event_id)
    if event is None:
        raise HTTPException(status_code=404, detail="Audit event not found.")
    return AuditLogRead.model_validate(event)
