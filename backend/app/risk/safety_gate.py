from sqlalchemy.orm import Session

from app.config import settings
from app.risk.cooldown_manager import CooldownManager
from app.risk.duplicate_guard import DuplicateGuard
from app.risk.exposure_manager import ExposureManager
from app.risk.kill_switch import KillSwitch
from app.risk.risk_limits import RiskLimits, get_risk_limits


class SafetyGate:
    def __init__(
        self,
        limits: RiskLimits | None = None,
        duplicate_guard: DuplicateGuard | None = None,
        cooldown_manager: CooldownManager | None = None,
    ) -> None:
        self.limits = limits or get_risk_limits()
        self.duplicate_guard = duplicate_guard or DuplicateGuard()
        self.cooldown_manager = cooldown_manager or CooldownManager()
        self.exposure_manager = ExposureManager()

    def evaluate_trade_request(self, db: Session, context: dict) -> dict:
        reasons: list[str] = []
        flags: list[str] = []
        mode = str(context.get("mode", "PAPER")).upper()

        if settings.allow_live_orders or settings.enable_dhan_order_placement:
            reasons.append("Live-order flags are not disabled.")
            flags.append("LIVE_ORDER_FLAGS")
        if mode != "PAPER" or not settings.is_paper_mode:
            reasons.append("Only PAPER mode is allowed.")
            flags.append("MODE")
        if KillSwitch().get_state(db).kill_switch_enabled:
            reasons.append("Kill switch is enabled.")
            flags.append("KILL_SWITCH")

        if float(context.get("daily_pnl", 0.0)) <= -abs(self.limits.max_daily_loss):
            reasons.append("Max daily loss limit hit.")
            flags.append("MAX_DAILY_LOSS")
        if int(context.get("trades_today", 0)) >= self.limits.max_trades_per_day:
            reasons.append("Max trades per day limit hit.")
            flags.append("MAX_TRADES_PER_DAY")
        if int(context.get("quantity", 0)) > self.limits.max_quantity:
            reasons.append("Quantity exceeds max quantity.")
            flags.append("MAX_QUANTITY")
        if int(context.get("open_positions_count", 0)) >= self.limits.max_open_positions:
            reasons.append("Max open positions limit hit.")
            flags.append("MAX_OPEN_POSITIONS")
        if self.exposure_manager.would_exceed(
            context,
            context.get("open_positions", []),
            self.limits.max_position_exposure,
        ):
            reasons.append("Max position exposure would be exceeded.")
            flags.append("MAX_EXPOSURE")
        if int(context.get("consecutive_losses", 0)) >= self.limits.max_consecutive_losses:
            reasons.append("Max consecutive losses hit.")
            flags.append("LOSS_STREAK")
        if self.duplicate_guard.is_duplicate(context):
            reasons.append("Duplicate signal/trade in the same time bucket.")
            flags.append("DUPLICATE")

        blocked, cooldown_reason = self.cooldown_manager.is_blocked(context.get("signal_time"))
        if blocked:
            reasons.append(cooldown_reason or "Cooldown is active.")
            flags.append("COOLDOWN")
        if context.get("stale_data"):
            reasons.append("Stale data flag is set.")
            flags.append("STALE_DATA")
        if float(context.get("confidence") or 0) < self.limits.min_confidence:
            reasons.append("Confidence is below minimum threshold.")
            flags.append("LOW_CONFIDENCE")
        if context.get("liquidity_score") is not None and float(context["liquidity_score"]) < self.limits.min_liquidity_score:
            reasons.append("Liquidity score is below minimum threshold.")
            flags.append("LOW_LIQUIDITY")
        if context.get("spread_pct") is not None and float(context["spread_pct"]) > self.limits.max_spread_pct:
            reasons.append("Spread is too wide.")
            flags.append("WIDE_SPREAD")

        return {
            "approved": not reasons,
            "reasons": reasons,
            "risk_flags": flags,
            "limits_snapshot": self.limits.snapshot(),
        }
