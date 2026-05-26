import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.audit_log import AuditLog


class AuditLogger:
    def log(
        self,
        db: Session,
        event_type: str,
        message: str,
        severity: str = "INFO",
        source: str = "BACKEND",
        entity_type: str | None = None,
        entity_id: int | None = None,
        mode: str = "PAPER",
        payload: dict[str, Any] | None = None,
        commit: bool = True,
    ) -> AuditLog:
        event = AuditLog(
            event_type=event_type,
            severity=severity,
            source=source,
            message=message,
            entity_type=entity_type,
            entity_id=entity_id,
            mode=mode,
            payload_json=json.dumps(payload or {}, default=str),
        )
        db.add(event)
        if commit:
            db.commit()
            db.refresh(event)
        return event

    def list_events(
        self,
        db: Session,
        limit: int = 100,
        event_type: str | None = None,
    ) -> list[AuditLog]:
        query = select(AuditLog).order_by(AuditLog.created_at.desc()).limit(limit)
        if event_type:
            query = (
                select(AuditLog)
                .where(AuditLog.event_type == event_type)
                .order_by(AuditLog.created_at.desc())
                .limit(limit)
            )
        return list(db.scalars(query))

    def get_event(self, db: Session, event_id: int) -> AuditLog | None:
        return db.get(AuditLog, event_id)
