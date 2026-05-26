from datetime import datetime, time, timedelta, timezone


IST = timezone(timedelta(hours=5, minutes=30))


def evaluate_time_gate(signal_time: datetime | None = None) -> dict:
    """Classify NIFTY intraday timing quality.

    Time windows:
    - 09:15-09:30 OPENING_AUCTION: blocked because spreads and first candles can be unstable.
    - 09:30-11:00 PRIME_MORNING: high-quality window when participation and trend discovery are strong.
    - 11:00-12:30 MID_MORNING: tradable but slightly lower-quality as early momentum settles.
    - 12:30-13:30 LUNCH_LULL: allowed with caution because volume often drops.
    - 13:30-14:30 AFTERNOON_PRIME: high-quality window when afternoon continuation/reversal setups appear.
    - 14:30-15:15 LATE_SESSION: tradable with moderate quality as volatility can rise.
    - 15:15-15:30 CLOSING_AUCTION: blocked because closing/expiry pressure can distort option prices.
    - Outside 09:15-15:30 MARKET_CLOSED: blocked because regular intraday trading is unavailable.
    """
    if signal_time is None:
        ist_dt = datetime.now(timezone.utc).astimezone(IST)
    elif signal_time.tzinfo is None:
        ist_dt = signal_time.replace(tzinfo=timezone.utc).astimezone(IST)
    else:
        ist_dt = signal_time.astimezone(IST)

    current = ist_dt.time()
    result = {
        "allowed": False,
        "window_name": "MARKET_CLOSED",
        "quality": "CLOSED",
        "bonus_score": 0,
        "ist_time_str": ist_dt.strftime("%Y-%m-%d %H:%M:%S IST"),
    }

    if _in_window(current, time(9, 15), time(9, 30)):
        result.update(
            {
                "window_name": "OPENING_AUCTION",
                "quality": "LOW",
                "warning": "Avoid opening 15 min - wide spreads",
            }
        )
    elif _in_window(current, time(9, 30), time(11, 0)):
        result.update({"allowed": True, "window_name": "PRIME_MORNING", "quality": "HIGH", "bonus_score": 5})
    elif _in_window(current, time(11, 0), time(12, 30)):
        result.update({"allowed": True, "window_name": "MID_MORNING", "quality": "MEDIUM", "bonus_score": 2})
    elif _in_window(current, time(12, 30), time(13, 30)):
        result.update(
            {
                "allowed": True,
                "window_name": "LUNCH_LULL",
                "quality": "LOW",
                "warning": "Low volume lunch period",
            }
        )
    elif _in_window(current, time(13, 30), time(14, 30)):
        result.update({"allowed": True, "window_name": "AFTERNOON_PRIME", "quality": "HIGH", "bonus_score": 3})
    elif _in_window(current, time(14, 30), time(15, 15)):
        result.update({"allowed": True, "window_name": "LATE_SESSION", "quality": "MEDIUM", "bonus_score": 0})
    elif _in_window(current, time(15, 15), time(15, 30)):
        result.update(
            {
                "window_name": "CLOSING_AUCTION",
                "quality": "LOW",
                "warning": "Avoid last 15 min - expiry pressure",
            }
        )

    return result


def _in_window(current: time, start: time, end: time) -> bool:
    return start <= current < end
