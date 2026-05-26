import json
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit.audit_logger import AuditLogger
from app.config import settings
from app.models.participant_flow import ParticipantFlowRecord
from app.schemas.participant_flow import ParticipantFlowImportRequest, ParticipantFlowRecordResponse


class ParticipantFlowImportService:
    def import_records(self, db: Session, request: ParticipantFlowImportRequest) -> dict[str, Any]:
        if not settings.enable_participant_flow_engine:
            return {
                "ok": False,
                "status": "PARTICIPANT_FLOW_DISABLED",
                "message": "Participant Flow Engine is disabled by config.",
                "inserted": 0,
                "updated": 0,
                "items": [],
            }
        if not request.records:
            return {
                "ok": False,
                "status": "NO_RECORDS",
                "message": "No participant-flow records were supplied.",
                "inserted": 0,
                "updated": 0,
                "items": [],
            }

        imported_at = datetime.now(timezone.utc)
        inserted = 0
        updated = 0
        saved: list[ParticipantFlowRecord] = []
        try:
            for record in request.records:
                existing = self._find_existing(db, record)
                values = record.model_dump()
                values["imported_at"] = imported_at
                values["raw_json"] = json.dumps(record.model_dump(mode="json"), default=str)[:10000] if settings.participant_flow_store_raw else None
                if existing is None:
                    item = ParticipantFlowRecord(**values)
                    db.add(item)
                    db.flush()
                    inserted += 1
                else:
                    item = existing
                    for key, value in values.items():
                        setattr(item, key, value)
                    updated += 1
                saved.append(item)
            db.commit()
            for item in saved:
                db.refresh(item)
        except Exception as exc:
            db.rollback()
            AuditLogger().log(
                db,
                "PARTICIPANT_FLOW_IMPORT_FAILED",
                "Participant-flow import failed.",
                severity="ERROR",
                source="PARTICIPANT_FLOW",
                payload={"error": f"{type(exc).__name__}: {exc}"},
            )
            return {
                "ok": False,
                "status": "DATABASE_ERROR",
                "message": f"Participant-flow records could not be imported: {type(exc).__name__}.",
                "inserted": 0,
                "updated": 0,
                "items": [],
            }

        if settings.participant_flow_enable_audit:
            AuditLogger().log(
                db,
                "PARTICIPANT_FLOW_IMPORTED",
                "Participant-flow records imported.",
                source="PARTICIPANT_FLOW",
                payload={"inserted": inserted, "updated": updated, "count": len(saved)},
            )
        return {
            "ok": True,
            "status": "IMPORTED",
            "message": "Participant-flow records imported.",
            "inserted": inserted,
            "updated": updated,
            "items": [ParticipantFlowRecordResponse.model_validate(item).model_dump(mode="json") for item in saved],
        }

    def _find_existing(self, db: Session, record) -> ParticipantFlowRecord | None:
        return db.scalar(
            select(ParticipantFlowRecord).where(
                ParticipantFlowRecord.source == record.source,
                ParticipantFlowRecord.market_date == record.market_date,
                ParticipantFlowRecord.segment == record.segment,
                ParticipantFlowRecord.participant_type == record.participant_type,
                ParticipantFlowRecord.category == record.category,
                ParticipantFlowRecord.symbol == record.symbol,
                ParticipantFlowRecord.underlying == record.underlying,
                ParticipantFlowRecord.expiry == record.expiry,
                ParticipantFlowRecord.instrument_type == record.instrument_type,
                ParticipantFlowRecord.data_frequency == record.data_frequency,
            )
        )


participant_flow_import_service = ParticipantFlowImportService()


def get_participant_flow_import_service() -> ParticipantFlowImportService:
    return participant_flow_import_service
