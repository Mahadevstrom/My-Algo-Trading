from fastapi import APIRouter

from app.schemas.session_gate import (
    SessionGateDecisionResponse,
    SessionGateExplainResponse,
    SessionGateScheduleResponse,
    SessionGateStatusResponse,
)
from app.services.session_gate_service import get_session_gate_service


router = APIRouter(prefix="/api/session-gate", tags=["session-gate"])


@router.get("/status", response_model=SessionGateStatusResponse)
def session_gate_status() -> SessionGateStatusResponse:
    return get_session_gate_service().status()


@router.get("/schedule", response_model=SessionGateScheduleResponse)
def session_gate_schedule() -> SessionGateScheduleResponse:
    return get_session_gate_service().schedule()


@router.get("/decision", response_model=SessionGateDecisionResponse)
def session_gate_decision() -> SessionGateDecisionResponse:
    return get_session_gate_service().decision()


@router.get("/explain", response_model=SessionGateExplainResponse)
def session_gate_explain() -> SessionGateExplainResponse:
    return get_session_gate_service().explain()
