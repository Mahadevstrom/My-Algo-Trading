from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit.audit_logger import AuditLogger
from app.models.risk_state import RiskState


class KillSwitch:
    def get_state(self, db: Session) -> RiskState:
        state = db.scalar(select(RiskState).order_by(RiskState.id).limit(1))
        if state is None:
            state = RiskState(kill_switch_enabled=False, reason=None)
            db.add(state)
            db.commit()
            db.refresh(state)
        return state

    def enable(self, db: Session, reason: str = "Manual kill switch enabled.") -> RiskState:
        state = self.get_state(db)
        state.kill_switch_enabled = True
        state.reason = reason
        state.updated_at = datetime.now(timezone.utc)
        AuditLogger().log(
            db,
            event_type="KILL_SWITCH_ENABLED",
            severity="WARNING",
            source="RISK",
            message=reason,
            entity_type="RiskState",
            entity_id=state.id,
            commit=False,
        )
        db.commit()
        db.refresh(state)
        return state

    def disable(self, db: Session, reason: str = "Manual kill switch disabled.") -> RiskState:
        state = self.get_state(db)
        state.kill_switch_enabled = False
        state.reason = reason
        state.updated_at = datetime.now(timezone.utc)
        AuditLogger().log(
            db,
            event_type="KILL_SWITCH_DISABLED",
            severity="INFO",
            source="RISK",
            message=reason,
            entity_type="RiskState",
            entity_id=state.id,
            commit=False,
        )
        db.commit()
        db.refresh(state)
        return state
