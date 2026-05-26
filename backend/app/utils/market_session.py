from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


try:
    IST = ZoneInfo("Asia/Kolkata")
except ZoneInfoNotFoundError:
    IST = timezone(timedelta(hours=5, minutes=30), name="Asia/Kolkata")


MARKET_OPEN = time(9, 15)
MARKET_CLOSE = time(15, 30)


def india_market_session(now: datetime | None = None) -> dict:
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    ist_now = current.astimezone(IST)
    weekday = ist_now.weekday()
    is_weekday = weekday < 5
    current_time = ist_now.time()
    if not is_weekday:
        session_status = "CLOSED"
        is_open = False
    elif current_time < MARKET_OPEN:
        session_status = "PRE_MARKET"
        is_open = False
    elif MARKET_OPEN <= current_time <= MARKET_CLOSE:
        session_status = "OPEN"
        is_open = True
    else:
        session_status = "CLOSED"
        is_open = False
    return {
        "is_market_open": is_open,
        "session_status": session_status,
        "current_ist_time": ist_now.isoformat(),
        "holiday_calendar_applied": False,
        "note": "Weekday and time-window only; exchange holiday calendar is not implemented yet.",
    }
