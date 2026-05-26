from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit.audit_logger import AuditLogger
from app.engine.risk_manager import RiskManager
from app.models.trade import (
    Direction,
    ExitReason,
    PaperTrade,
    PaperTradeCreate,
    PaperTradeExit,
    PerformanceRead,
    TradeResult,
    TradeStatus,
)


class PaperTradeBlockedError(Exception):
    def __init__(self, reasons: list[str]) -> None:
        super().__init__("Paper trade blocked by risk manager.")
        self.reasons = reasons


class PaperTradeNotFoundError(Exception):
    pass


class PaperTradeAlreadyClosedError(Exception):
    pass


class PaperEngine:
    def __init__(self) -> None:
        self.risk_manager = RiskManager()

    def create_trade(self, db: Session, payload: PaperTradeCreate) -> PaperTrade:
        allowed, reasons = self.risk_manager.can_place_paper_trade(db, payload)
        if not allowed:
            raise PaperTradeBlockedError(reasons)

        trade = PaperTrade(
            symbol=payload.symbol,
            instrument_type=payload.instrument_type.value,
            exchange=payload.exchange,
            expiry=payload.expiry,
            strike=payload.strike,
            option_type=payload.option_type.value if payload.option_type else None,
            direction=payload.direction.value,
            entry_price=payload.entry_price,
            stop_loss=payload.stop_loss,
            target_1=payload.target_1,
            target_2=payload.target_2,
            quantity=payload.quantity,
            signal_confidence=payload.signal_confidence,
            signal_reason=payload.signal_reason,
            data_source=payload.data_source,
            signal_id=payload.signal_id,
            underlying=payload.underlying or payload.symbol,
            selected_strike=payload.selected_strike or payload.strike,
            strategy_score=payload.strategy_score,
            data_confidence=payload.data_confidence,
            final_confidence=payload.final_confidence,
            chain_bias=payload.chain_bias,
            signal_type=payload.signal_type,
            result=TradeResult.OPEN.value,
        )
        db.add(trade)
        db.flush()
        AuditLogger().log(
            db,
            event_type="PAPER_TRADE_CREATED",
            severity="INFO",
            source="PAPER_ENGINE",
            message=f"Paper trade {trade.id} created for {trade.symbol}.",
            entity_type="PaperTrade",
            entity_id=trade.id,
            payload={
                "symbol": trade.symbol,
                "entry_price": trade.entry_price,
                "quantity": trade.quantity,
                "data_source": trade.data_source,
            },
            commit=False,
        )
        db.commit()
        db.refresh(trade)
        return trade

    def list_trades(self, db: Session) -> list[PaperTrade]:
        return list(db.scalars(select(PaperTrade).order_by(PaperTrade.entry_time.desc())))

    def exit_trade(self, db: Session, trade_id: int, payload: PaperTradeExit) -> PaperTrade:
        trade = db.get(PaperTrade, trade_id)
        if trade is None:
            raise PaperTradeNotFoundError(f"Paper trade {trade_id} was not found.")
        if trade.status in {
            TradeStatus.CLOSED.value,
            TradeStatus.TARGET_2_HIT.value,
            TradeStatus.STOP_LOSS_HIT.value,
            TradeStatus.MANUAL_EXIT.value,
            TradeStatus.EXPIRED.value,
        }:
            raise PaperTradeAlreadyClosedError(f"Paper trade {trade_id} is already closed.")

        self.close_trade(trade, payload.exit_price, payload.exit_reason.value)
        AuditLogger().log(
            db,
            event_type="PAPER_TRADE_EXITED",
            severity="INFO",
            source="PAPER_ENGINE",
            message=f"Paper trade {trade.id} exited with result {trade.result}.",
            entity_type="PaperTrade",
            entity_id=trade.id,
            payload={
                "symbol": trade.symbol,
                "exit_price": trade.exit_price,
                "pnl": trade.pnl,
                "exit_reason": trade.exit_reason,
            },
            commit=False,
        )
        db.commit()
        db.refresh(trade)
        return trade

    def close_trade(self, trade: PaperTrade, exit_price: float, exit_reason: str) -> PaperTrade:
        multiplier = 1 if trade.direction == Direction.BUY.value else -1
        exit_time = datetime.now(timezone.utc)
        pnl = round((exit_price - trade.entry_price) * trade.quantity * multiplier, 2)
        invested = trade.entry_price * trade.quantity
        trade.exit_price = exit_price
        trade.exit_time = exit_time
        trade.pnl = pnl
        trade.pnl_percent = round((pnl / invested * 100), 2) if invested > 0 else 0.0
        trade.result = self._result_from_pnl(pnl)
        trade.exit_reason = exit_reason
        trade.holding_minutes = self._holding_minutes(trade.entry_time, exit_time)
        trade.unrealized_pnl = None
        trade.current_price = exit_price
        trade.status = exit_reason if exit_reason in {item.value for item in TradeStatus} else TradeStatus.CLOSED.value
        return trade

    def mark_target_1(self, trade: PaperTrade, current_price: float) -> PaperTrade:
        trade.status = TradeStatus.TARGET_1_HIT.value
        self.update_unrealized(trade, current_price)
        return trade

    def update_unrealized(self, trade: PaperTrade, current_price: float) -> PaperTrade:
        multiplier = 1 if trade.direction == Direction.BUY.value else -1
        unrealized = round((current_price - trade.entry_price) * trade.quantity * multiplier, 2)
        trade.current_price = current_price
        trade.unrealized_pnl = unrealized
        return trade

    def _result_from_pnl(self, pnl: float) -> str:
        if pnl > 0:
            return TradeResult.WIN.value
        if pnl < 0:
            return TradeResult.LOSS.value
        return TradeResult.BREAKEVEN.value

    def _holding_minutes(self, entry_time: datetime, exit_time: datetime) -> float:
        if entry_time.tzinfo is None:
            entry_time = entry_time.replace(tzinfo=timezone.utc)
        return round((exit_time - entry_time).total_seconds() / 60, 2)

    def performance(self, db: Session) -> PerformanceRead:
        trades = list(db.scalars(select(PaperTrade)))
        closed_trades = [trade for trade in trades if trade.result in {TradeResult.WIN.value, TradeResult.LOSS.value, TradeResult.BREAKEVEN.value}]
        wins = len([trade for trade in closed_trades if trade.result == TradeResult.WIN.value])
        losses = len([trade for trade in closed_trades if trade.result == TradeResult.LOSS.value])
        total = len(trades)
        win_rate = round((wins / len(closed_trades) * 100), 2) if closed_trades else 0.0
        total_pnl = round(sum(trade.pnl for trade in trades), 2)
        return PerformanceRead(
            total_trades=total,
            wins=wins,
            losses=losses,
            win_rate=win_rate,
            total_virtual_pnl=total_pnl,
        )
