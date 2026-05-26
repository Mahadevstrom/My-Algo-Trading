from datetime import datetime, time, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import settings
from app.models.trade import PaperTrade, PaperTradeCreate
from app.risk.kill_switch import KillSwitch


class RiskManager:
    def can_place_paper_trade(self, db: Session, trade: PaperTradeCreate) -> tuple[bool, list[str]]:
        reasons: list[str] = []

        if not settings.is_paper_mode:
            reasons.append("TRADING_MODE is not PAPER.")

        if KillSwitch().get_state(db).kill_switch_enabled:
            reasons.append("Kill switch is enabled. New paper trades are blocked.")

        if trade.quantity > settings.max_qty_per_trade:
            reasons.append(
                f"Quantity {trade.quantity} exceeds MAX_QTY_PER_TRADE={settings.max_qty_per_trade}."
            )

        trade_count = self._today_trade_count(db)
        if trade_count >= settings.max_trades_per_day:
            reasons.append(
                f"Daily trade limit reached: {trade_count}/{settings.max_trades_per_day}."
            )

        realized_pnl = self._today_realized_pnl(db)
        if realized_pnl <= -abs(settings.max_daily_loss):
            reasons.append(
                f"Daily loss limit reached: {realized_pnl:.2f} <= -{settings.max_daily_loss:.2f}."
            )

        return len(reasons) == 0, reasons

    def can_place_live_order(self) -> tuple[bool, list[str]]:
        reasons: list[str] = []
        if not settings.allow_live_orders:
            reasons.append("ALLOW_LIVE_ORDERS=false blocks all live orders.")
        if not settings.enable_dhan_order_placement:
            reasons.append("ENABLE_DHAN_ORDER_PLACEMENT=false blocks Dhan order placement.")
        return len(reasons) == 0, reasons

    def _today_trade_count(self, db: Session) -> int:
        start = datetime.combine(datetime.now(timezone.utc).date(), time.min, tzinfo=timezone.utc)
        return db.scalar(select(func.count()).select_from(PaperTrade).where(PaperTrade.entry_time >= start)) or 0

    def _today_realized_pnl(self, db: Session) -> float:
        start = datetime.combine(datetime.now(timezone.utc).date(), time.min, tzinfo=timezone.utc)
        return float(
            db.scalar(
                select(func.coalesce(func.sum(PaperTrade.pnl), 0.0)).where(
                    PaperTrade.entry_time >= start,
                    PaperTrade.status == "CLOSED",
                )
            )
            or 0.0
        )
