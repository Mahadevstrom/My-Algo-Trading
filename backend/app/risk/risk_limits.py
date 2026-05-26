import os
from dataclasses import asdict, dataclass


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "y", "on"}


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    return float(raw)


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    return int(raw)


@dataclass(frozen=True)
class RiskLimits:
    max_daily_loss: float = _env_float("RISK_MAX_DAILY_LOSS", 1500.0)
    max_trades_per_day: int = _env_int("RISK_MAX_TRADES_PER_DAY", 5)
    max_quantity: int = _env_int("RISK_MAX_QUANTITY", 75)
    max_position_exposure: float = _env_float("RISK_MAX_POSITION_EXPOSURE", 15000.0)
    max_open_positions: int = _env_int("RISK_MAX_OPEN_POSITIONS", 1)
    max_consecutive_losses: int = _env_int("RISK_MAX_CONSECUTIVE_LOSSES", 3)
    cooldown_after_loss_minutes: int = _env_int("RISK_COOLDOWN_AFTER_LOSS_MINUTES", 15)
    allow_live_orders: bool = _env_bool("ALLOW_LIVE_ORDERS", False)
    min_confidence: float = _env_float("RISK_MIN_CONFIDENCE", 60.0)
    min_liquidity_score: float = _env_float("RISK_MIN_LIQUIDITY_SCORE", 60.0)
    max_spread_pct: float = _env_float("RISK_MAX_SPREAD_PCT", 12.0)

    def snapshot(self) -> dict:
        return asdict(self)


def get_risk_limits() -> RiskLimits:
    return RiskLimits()
