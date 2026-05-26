from datetime import datetime, timedelta, timezone


class CooldownManager:
    def __init__(self) -> None:
        self.cooldown_until: datetime | None = None
        self.rejected_times: list[datetime] = []

    def record_loss(self, at_time: datetime, minutes: int) -> None:
        self.cooldown_until = _aware(at_time) + timedelta(minutes=minutes)

    def record_rejection(self, at_time: datetime) -> None:
        current = _aware(at_time)
        self.rejected_times = [item for item in self.rejected_times if current - item <= timedelta(minutes=30)]
        self.rejected_times.append(current)
        if len(self.rejected_times) >= 5:
            self.cooldown_until = current + timedelta(minutes=10)

    def is_blocked(self, at_time: datetime) -> tuple[bool, str | None]:
        if at_time is None:
            return False, None
        current = _aware(at_time)
        if self.cooldown_until and current < self.cooldown_until:
            return True, f"Cooldown active until {self.cooldown_until.isoformat()}."
        return False, None


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value
