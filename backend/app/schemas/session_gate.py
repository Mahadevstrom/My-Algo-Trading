from pydantic import BaseModel


class SessionGateSafetySummary(BaseModel):
    trading_mode: str
    live_order_status: str
    paper_only_safety_confirmed: bool
    broker_execution_disabled: bool


class SessionGateScheduleResponse(BaseModel):
    enabled: bool
    timezone: str
    schedule: dict[str, str]
    filters: dict[str, bool]
    holiday_calendar_enabled: bool = False
    holiday_calendar_note: str
    safety_summary: SessionGateSafetySummary


class SessionGateDecisionResponse(BaseModel):
    enabled: bool
    session_status: str
    allow_new_signal: bool
    allow_paper_entry: bool
    allow_paper_exit: bool
    allow_square_off_review: bool
    block_reason: str | None = None
    caution_reason: str | None = None
    next_session_change: str | None = None
    safety_summary: SessionGateSafetySummary


class SessionGateStatusResponse(SessionGateDecisionResponse):
    timezone: str
    now_ist: str
    trading_date: str
    weekday: str
    is_market_day: bool
    is_market_open: bool
    schedule: dict[str, str]
    filters: dict[str, bool]
    holiday_calendar_enabled: bool = False
    holiday_calendar_note: str


class SessionGateExplainResponse(BaseModel):
    ok: bool
    session_status: str
    explanation: str
    entry_policy: str
    exit_policy: str
    next_session_change: str | None = None
    safety_note: str
