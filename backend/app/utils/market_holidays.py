from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


try:
    IST = ZoneInfo("Asia/Kolkata")
except ZoneInfoNotFoundError:
    IST = timezone(timedelta(hours=5, minutes=30), name="Asia/Kolkata")


NSE_HOLIDAYS_2026 = [
    "2026-01-26",  # Republic Day
    "2026-03-02",  # Mahashivratri
    "2026-03-25",  # Holi
    "2026-04-02",  # Ram Navami
    "2026-04-03",  # Good Friday
    "2026-04-14",  # Dr Ambedkar Jayanti
    "2026-05-01",  # Maharashtra Day
    "2026-08-15",  # Independence Day
    "2026-09-02",  # Ganesh Chaturthi
    "2026-10-02",  # Gandhi Jayanti
    "2026-10-20",  # Diwali Laxmi Puja
    "2026-10-21",  # Diwali Balipratipada
    "2026-11-04",  # Guru Nanak Jayanti
    "2026-12-25",  # Christmas
]


def is_market_holiday(date_str: str | None = None) -> bool:
    check_date = _parse_date(date_str) if date_str else datetime.now(IST).date()
    return check_date.weekday() >= 5 or check_date.isoformat() in NSE_HOLIDAYS_2026


def get_next_trading_day(from_date_str: str | None = None) -> str:
    current = _parse_date(from_date_str) if from_date_str else datetime.now(IST).date()
    next_day = current + timedelta(days=1)
    while is_market_holiday(next_day.isoformat()):
        next_day += timedelta(days=1)
    return next_day.isoformat()


def _parse_date(date_str: str) -> date:
    return date.fromisoformat(date_str)
