from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.config import settings
from app.schemas.session_gate import (
    SessionGateDecisionResponse,
    SessionGateExplainResponse,
    SessionGateSafetySummary,
    SessionGateScheduleResponse,
    SessionGateStatusResponse,
)
from app.utils.market_holidays import is_market_holiday


class SessionGateService:
    """Read-only Indian market session classifier.

    TODO: Add NSE/BSE exchange holiday calendar support in a future phase.
    """

    def __init__(self) -> None:
        self.timezone_name = settings.session_gate_timezone
        try:
            self.timezone = ZoneInfo(settings.session_gate_timezone)
        except ZoneInfoNotFoundError:
            self.timezone = timezone(timedelta(hours=5, minutes=30), name="Asia/Kolkata")

    def status(self, now: datetime | None = None) -> SessionGateStatusResponse:
        now_ist = self._now_ist(now)
        current_time = now_ist.time().replace(second=0, microsecond=0)
        schedule = self._schedule_times()
        date_str = now_ist.date().isoformat()
        is_market_day = not is_market_holiday(date_str)
        session_status, block_reason, caution_reason = self._classify(
            current_time=current_time,
            is_market_day=is_market_day,
            date_str=date_str,
            schedule=schedule,
        )

        is_market_open = is_market_day and schedule["market_open"] <= current_time < schedule["market_close"]
        allow_paper_exit = settings.enable_session_gate and is_market_day and (
            schedule["market_open"] <= current_time < schedule["market_close"]
        )
        allow_square_off_review = (
            settings.enable_session_gate
            and is_market_day
            and schedule["square_off_time"] <= current_time < schedule["market_close"]
        )
        allow_entries = session_status in {"ACTIVE_MORNING", "MIDDAY_CAUTION", "ACTIVE_AFTERNOON"}
        if session_status == "MIDDAY_CAUTION" and not settings.session_allow_midday_trades:
            allow_entries = False

        allow_new_signal = settings.enable_session_gate and is_market_day and allow_entries
        allow_paper_entry = allow_new_signal

        if not settings.enable_session_gate:
            allow_paper_exit = True

        return SessionGateStatusResponse(
            enabled=settings.enable_session_gate,
            timezone=self.timezone_name,
            now_ist=now_ist.isoformat(),
            trading_date=now_ist.date().isoformat(),
            weekday=now_ist.strftime("%A").upper(),
            session_status=session_status,
            is_market_day=is_market_day,
            is_market_open=is_market_open,
            allow_new_signal=allow_new_signal,
            allow_paper_entry=allow_paper_entry,
            allow_paper_exit=allow_paper_exit,
            allow_square_off_review=allow_square_off_review,
            block_reason=block_reason,
            caution_reason=caution_reason,
            next_session_change=self._next_change(now_ist.date(), current_time, schedule, is_market_day),
            schedule=settings.session_gate_schedule,
            filters=self._filters(),
            holiday_calendar_enabled=True,
            holiday_calendar_note="Exchange static holiday calendar is active (14 national holidays for 2026 registered).",
            safety_summary=self._safety_summary(),
        )

    def schedule(self) -> SessionGateScheduleResponse:
        return SessionGateScheduleResponse(
            enabled=settings.enable_session_gate,
            timezone=self.timezone_name,
            schedule=settings.session_gate_schedule,
            filters=self._filters(),
            holiday_calendar_enabled=True,
            holiday_calendar_note="Exchange static holiday calendar is active (14 national holidays for 2026 registered).",
            safety_summary=self._safety_summary(),
        )

    def decision(self) -> SessionGateDecisionResponse:
        status = self.status()
        return SessionGateDecisionResponse(
            enabled=status.enabled,
            session_status=status.session_status,
            allow_new_signal=status.allow_new_signal,
            allow_paper_entry=status.allow_paper_entry,
            allow_paper_exit=status.allow_paper_exit,
            allow_square_off_review=status.allow_square_off_review,
            block_reason=status.block_reason,
            caution_reason=status.caution_reason,
            next_session_change=status.next_session_change,
            safety_summary=status.safety_summary,
        )

    def explain(self) -> SessionGateExplainResponse:
        status = self.status()
        if status.allow_paper_entry:
            entry_policy = "New paper entries are allowed by the time-of-day session gate."
        else:
            entry_policy = f"New paper entries are blocked: {status.block_reason or status.session_status}."

        if status.allow_square_off_review:
            exit_policy = "Square-off review window is active; exits/review are allowed, new entries remain blocked."
        elif status.allow_paper_exit:
            exit_policy = "Paper exits are allowed while the market session is open."
        else:
            exit_policy = "Paper exits are outside regular market hours unless handled manually by backend review."

        caution = f" Caution: {status.caution_reason}." if status.caution_reason else ""
        return SessionGateExplainResponse(
            ok=True,
            session_status=status.session_status,
            explanation=(
                f"Current IST session is {status.session_status}. "
                f"Market day={status.is_market_day}, market open={status.is_market_open}.{caution}"
            ),
            entry_policy=entry_policy,
            exit_policy=exit_policy,
            next_session_change=status.next_session_change,
            safety_note="PAPER mode only. Broker execution remains disabled and live orders remain BLOCKED.",
        )

    def _now_ist(self, now: datetime | None) -> datetime:
        if now is None:
            return datetime.now(self.timezone)
        if now.tzinfo is None:
            return now.replace(tzinfo=self.timezone)
        return now.astimezone(self.timezone)

    def _schedule_times(self) -> dict[str, time]:
        return {key: self._parse_time(value) for key, value in settings.session_gate_schedule.items()}

    def _parse_time(self, value: str) -> time:
        hour, minute = value.split(":", 1)
        return time(hour=int(hour), minute=int(minute))

    def _classify(
        self,
        current_time: time,
        is_market_day: bool,
        date_str: str,
        schedule: dict[str, time],
    ) -> tuple[str, str | None, str | None]:
        if not settings.enable_session_gate:
            return "DISABLED", None, "Session gate is disabled by configuration."
        if not is_market_day:
            from app.utils.market_holidays import NSE_HOLIDAYS_2026
            if date_str in NSE_HOLIDAYS_2026:
                return "HOLIDAY_CLOSED", "Exchange holiday closed.", None
            return "WEEKEND_CLOSED", "Weekend closed.", None
        if current_time < schedule["pre_market_start"]:
            return "MARKET_CLOSED", "Market has not entered pre-market window.", None
        if current_time < schedule["market_open"]:
            return "PRE_MARKET", "Pre-market window; no new signals or entries.", None
        if current_time < schedule["first_trade_time"]:
            return "OPENING_WAIT", "Opening wait window; first minutes are blocked.", "Avoid opening volatility."
        if current_time < schedule["midday_start"]:
            return "ACTIVE_MORNING", None, None
        if current_time < schedule["midday_end"]:
            if settings.session_allow_midday_trades:
                return "MIDDAY_CAUTION", None, "Midday liquidity/chop caution."
            return "MIDDAY_CAUTION", "Midday trades are disabled by configuration.", "Midday liquidity/chop caution."
        if current_time < schedule["late_session_start"]:
            return "ACTIVE_AFTERNOON", None, None
        if current_time < schedule["no_new_trade_after"]:
            if settings.session_allow_late_session_trades:
                return "ACTIVE_AFTERNOON", None, "Late-session caution."
            return "LATE_SESSION_BLOCKED", "Late-session entries are disabled by configuration.", "Late-session risk."
        if current_time < schedule["square_off_time"]:
            return "NO_NEW_TRADES", "No new trades after configured cutoff.", None
        if current_time < schedule["market_close"]:
            return "SQUARE_OFF_WINDOW", "Square-off review window; exits only.", "Review open paper positions."
        if current_time < schedule["post_market_end"]:
            return "POST_MARKET", "Post-market window; no new entries.", None
        return "MARKET_CLOSED", "Market is closed.", None

    def _next_change(
        self,
        trading_date: date,
        current_time: time,
        schedule: dict[str, time],
        is_market_day: bool,
    ) -> str:
        if not is_market_day or current_time >= schedule["post_market_end"]:
            from app.utils.market_holidays import get_next_trading_day
            next_trading_day_str = get_next_trading_day(trading_date.isoformat())
            next_day = date.fromisoformat(next_trading_day_str)
            return self._combine(next_day, schedule["pre_market_start"]).isoformat()

        for key in (
            "pre_market_start",
            "market_open",
            "first_trade_time",
            "midday_start",
            "midday_end",
            "late_session_start",
            "no_new_trade_after",
            "square_off_time",
            "market_close",
            "post_market_end",
        ):
            if current_time < schedule[key]:
                return self._combine(trading_date, schedule[key]).isoformat()
        return self._combine(trading_date + timedelta(days=1), schedule["pre_market_start"]).isoformat()

    def _combine(self, day: date, value: time) -> datetime:
        return datetime.combine(day, value).replace(tzinfo=self.timezone)

    def _filters(self) -> dict[str, bool]:
        return {
            "block_first_minutes": settings.session_block_first_minutes,
            "block_expiry_last_30_min": settings.session_block_expiry_last_30_min,
            "allow_midday_trades": settings.session_allow_midday_trades,
            "allow_late_session_trades": settings.session_allow_late_session_trades,
        }

    def _safety_summary(self) -> SessionGateSafetySummary:
        live_order_status = settings.safety_status["live_order_status"]
        return SessionGateSafetySummary(
            trading_mode=settings.trading_mode,
            live_order_status=live_order_status,
            paper_only_safety_confirmed=settings.is_paper_mode and live_order_status == "BLOCKED",
            broker_execution_disabled=not (
                settings.allow_live_orders
                or settings.enable_dhan_order_placement
                or settings.indstocks_enable_order_placement
            ),
        )


_session_gate_service = SessionGateService()


def get_session_gate_service() -> SessionGateService:
    return _session_gate_service
