from datetime import datetime


class DuplicateGuard:
    def __init__(self, bucket_minutes: int = 15) -> None:
        self.bucket_minutes = bucket_minutes
        self._seen: set[tuple] = set()

    def is_duplicate(self, context: dict) -> bool:
        key = self._key(context)
        if key in self._seen:
            return True
        self._seen.add(key)
        return False

    def _key(self, context: dict) -> tuple:
        signal_time = context.get("signal_time")
        if isinstance(signal_time, datetime):
            minute_bucket = (signal_time.hour * 60 + signal_time.minute) // self.bucket_minutes
            date_value = signal_time.date().isoformat()
        else:
            minute_bucket = None
            date_value = None
        return (
            str(context.get("underlying", "")).upper(),
            str(context.get("expiry", "")),
            context.get("selected_strike"),
            context.get("option_type"),
            context.get("signal_type"),
            date_value,
            minute_bucket,
        )
