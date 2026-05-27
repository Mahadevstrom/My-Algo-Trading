import json
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo


KNOWN_EVENTS_PATH = Path(__file__).with_name("known_events.json")


def is_event_day(date_str: str = None) -> tuple[bool, str | None]:
    target = date_str or _today_ist().isoformat()
    for event in _load_events():
        if event.get("date") == target:
            return True, event.get("name")
    return False, None


def add_event(date_str: str, name: str, impact: str) -> None:
    events = _load_events()
    events.append({"date": date_str, "name": name, "impact": impact})
    _save_events(events)


def get_upcoming_events(days_ahead: int = 7) -> list[dict]:
    today = _today_ist()
    end = today + timedelta(days=max(days_ahead, 0))
    results = []
    for event in _load_events():
        try:
            event_date = date.fromisoformat(str(event.get("date")))
        except ValueError:
            continue
        if today <= event_date <= end:
            results.append(event)
    return sorted(results, key=lambda item: item.get("date") or "")


def _load_events() -> list[dict]:
    try:
        if not KNOWN_EVENTS_PATH.exists():
            return []
        data = json.loads(KNOWN_EVENTS_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _save_events(events: list[dict]) -> None:
    KNOWN_EVENTS_PATH.write_text(json.dumps(events, indent=2), encoding="utf-8")


def _today_ist() -> date:
    return datetime.now(ZoneInfo("Asia/Kolkata")).date()
