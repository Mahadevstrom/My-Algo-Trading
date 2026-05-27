from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.engine.dhan_instrument_importer import DhanInstrumentImporter


def is_expiry_today(db: Session, underlying: str = "NIFTY") -> bool:
    return days_to_next_expiry(db, underlying) == 0


def is_monthly_expiry_today(db: Session, underlying: str = "NIFTY") -> bool:
    today = date.today()
    if not is_expiry_today(db, underlying):
        return False
    return _last_thursday(today.year, today.month) == today


def days_to_next_expiry(db: Session, underlying: str = "NIFTY") -> int:
    today = _today_ist()
    expiries = _db_expiries(db, underlying)
    future = [item for item in expiries if item >= today]
    if future:
        return max((future[0] - today).days, 0)
    fallback = _next_weekly_expiry(today)
    return max((fallback - today).days, 0)


def get_expiry_session(ist_hour: int, ist_minute: int) -> str:
    minute_of_day = ist_hour * 60 + ist_minute
    if minute_of_day < 11 * 60 + 30:
        return "MORNING"
    if minute_of_day <= 13 * 60 + 30:
        return "MIDDAY"
    return "AFTERNOON"


def _db_expiries(db: Session, underlying: str) -> list[date]:
    try:
        today = _today_ist()
        expiries = DhanInstrumentImporter().expiries(db, underlying)
        return sorted(item for item in expiries if item >= today)
    except Exception:
        return []


def _next_weekly_expiry(from_date: date) -> date:
    days_until_thursday = (3 - from_date.weekday()) % 7
    return from_date + timedelta(days=days_until_thursday)


def _last_thursday(year: int, month: int) -> date:
    if month == 12:
        cursor = date(year + 1, 1, 1) - timedelta(days=1)
    else:
        cursor = date(year, month + 1, 1) - timedelta(days=1)
    while cursor.weekday() != 3:
        cursor -= timedelta(days=1)
    return cursor


def _today_ist() -> date:
    return datetime.now(ZoneInfo("Asia/Kolkata")).date()
