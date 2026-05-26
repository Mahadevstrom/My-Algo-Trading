from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.brokers.dhan_data import DhanDataAdapter
from app.engine.dhan_instrument_importer import DhanInstrumentImporter
from app.engine.paper_engine import PaperEngine
from app.models.trade import PaperTrade, TradeResult, TradeStatus


CLOSED_RESULTS = {TradeResult.WIN.value, TradeResult.LOSS.value, TradeResult.BREAKEVEN.value}
OPEN_STATUSES = {TradeStatus.OPEN.value, TradeStatus.TARGET_1_HIT.value}


class PaperAccuracyEngine:
    def trades(self, db: Session) -> list[PaperTrade]:
        return list(db.scalars(select(PaperTrade).order_by(PaperTrade.entry_time)))

    def summary(self, db: Session) -> dict[str, Any]:
        trades = self.trades(db)
        closed = [trade for trade in trades if trade.result in CLOSED_RESULTS]
        open_trades = [trade for trade in trades if trade.result == TradeResult.OPEN.value]
        wins = [trade for trade in closed if trade.result == TradeResult.WIN.value]
        losses = [trade for trade in closed if trade.result == TradeResult.LOSS.value]
        breakeven = [trade for trade in closed if trade.result == TradeResult.BREAKEVEN.value]
        pnl_values = [trade.pnl or 0 for trade in closed]
        win_pnl = [trade.pnl or 0 for trade in wins]
        loss_pnl = [trade.pnl or 0 for trade in losses]
        gross_profit = sum(value for value in pnl_values if value > 0)
        gross_loss = abs(sum(value for value in pnl_values if value < 0))

        return {
            "message": None if closed else "No closed paper trades yet.",
            "total_trades": len(trades),
            "open_trades": len(open_trades),
            "closed_trades": len(closed),
            "wins": len(wins),
            "losses": len(losses),
            "breakeven": len(breakeven),
            "win_rate": _pct(len(wins), len(closed)),
            "loss_rate": _pct(len(losses), len(closed)),
            "total_pnl": round(sum(pnl_values), 2),
            "average_pnl": _avg(pnl_values),
            "average_win": _avg(win_pnl),
            "average_loss": _avg(loss_pnl),
            "profit_factor": round(gross_profit / gross_loss, 2) if gross_loss > 0 else (round(gross_profit, 2) if gross_profit > 0 else 0),
            "max_drawdown": self.drawdown(db)["max_drawdown"],
            "best_trade": _trade_brief(max(closed, key=lambda trade: trade.pnl or 0)) if closed else None,
            "worst_trade": _trade_brief(min(closed, key=lambda trade: trade.pnl or 0)) if closed else None,
            "max_consecutive_losses": self._max_streak(closed, TradeResult.LOSS.value),
            "max_consecutive_wins": self._max_streak(closed, TradeResult.WIN.value),
            "average_holding_minutes": _avg([trade.holding_minutes for trade in closed if trade.holding_minutes is not None]),
            "risk_reward_realized": self._realized_risk_reward(closed),
        }

    def by_underlying(self, db: Session) -> dict[str, Any]:
        return self._grouped(db, lambda trade: trade.underlying or trade.symbol or "UNKNOWN")

    def by_signal_type(self, db: Session) -> dict[str, Any]:
        return self._grouped(db, lambda trade: trade.signal_type or "UNKNOWN")

    def by_confidence(self, db: Session) -> dict[str, Any]:
        return self._grouped(db, lambda trade: _confidence_bucket(trade.final_confidence or trade.signal_confidence))

    def by_chain_bias(self, db: Session) -> dict[str, Any]:
        return self._grouped(db, lambda trade: trade.chain_bias or "UNKNOWN")

    def by_hour(self, db: Session) -> dict[str, Any]:
        return self._grouped(db, lambda trade: str((trade.exit_time or trade.entry_time).hour).zfill(2))

    def by_day(self, db: Session) -> dict[str, Any]:
        return self._grouped(db, lambda trade: (trade.exit_time or trade.entry_time).date().isoformat())

    def equity_curve(self, db: Session) -> list[dict[str, Any]]:
        closed = [trade for trade in self.trades(db) if trade.result in CLOSED_RESULTS and trade.exit_time is not None]
        closed.sort(key=lambda trade: trade.exit_time)
        cumulative = 0.0
        curve = []
        for trade in closed:
            cumulative += trade.pnl or 0
            curve.append(
                {
                    "trade_id": trade.id,
                    "closed_at": trade.exit_time.isoformat() if trade.exit_time else None,
                    "pnl": round(trade.pnl or 0, 2),
                    "cumulative_pnl": round(cumulative, 2),
                }
            )
        return curve

    def drawdown(self, db: Session) -> dict[str, Any]:
        curve = self.equity_curve(db)
        peak = 0.0
        max_drawdown = 0.0
        drawdown_curve = []
        for point in curve:
            equity = point["cumulative_pnl"]
            peak = max(peak, equity)
            drawdown = round(equity - peak, 2)
            max_drawdown = min(max_drawdown, drawdown)
            drawdown_curve.append({**point, "peak": round(peak, 2), "drawdown": drawdown})
        return {"max_drawdown": round(max_drawdown, 2), "drawdown_curve": drawdown_curve}

    def open_risk(self, db: Session) -> dict[str, Any]:
        open_trades = [trade for trade in self.trades(db) if trade.result == TradeResult.OPEN.value]
        total_open_risk = 0.0
        worst_case_loss = 0.0
        exposure: dict[str, float] = defaultdict(float)
        for trade in open_trades:
            risk = 0.0
            if trade.stop_loss is not None:
                risk = max((trade.entry_price - trade.stop_loss) * trade.quantity, 0)
            total_open_risk += risk
            worst_case_loss -= risk
            exposure[trade.underlying or trade.symbol] += trade.entry_price * trade.quantity
        return {
            "open_trades_count": len(open_trades),
            "total_open_risk": round(total_open_risk, 2),
            "worst_case_loss_if_all_sl_hit": round(worst_case_loss, 2),
            "exposure_by_underlying": {key: round(value, 2) for key, value in exposure.items()},
        }

    async def mark_to_market(self, db: Session, target_1_exit: bool = False) -> dict[str, Any]:
        open_trades = [
            trade
            for trade in self.trades(db)
            if trade.result == TradeResult.OPEN.value and trade.status in OPEN_STATUSES
        ]
        updates = []
        adapter = DhanDataAdapter()
        importer = DhanInstrumentImporter()
        paper_engine = PaperEngine()

        for trade in open_trades:
            instrument = _resolve_trade_instrument(db, importer, trade)
            if instrument is None:
                updates.append({"trade_id": trade.id, "status": "SKIPPED", "message": "Symbol mapping not found."})
                continue
            response = await adapter.get_ltp({instrument.segment: [instrument.security_id]})
            normalized = response.get("normalized") if isinstance(response, dict) else None
            if not response.get("ok") or not normalized:
                updates.append({"trade_id": trade.id, "status": response.get("status", "LTP_UNAVAILABLE"), "message": response.get("message")})
                continue
            current_ltp = _safe_float(normalized[0].get("ltp"))
            if current_ltp is None:
                updates.append({"trade_id": trade.id, "status": "LTP_UNAVAILABLE", "message": "LTP missing in Dhan response."})
                continue

            action = "UPDATED"
            if trade.stop_loss is not None and current_ltp <= trade.stop_loss:
                paper_engine.close_trade(trade, current_ltp, TradeStatus.STOP_LOSS_HIT.value)
                action = TradeStatus.STOP_LOSS_HIT.value
            elif trade.target_2 is not None and current_ltp >= trade.target_2:
                paper_engine.close_trade(trade, current_ltp, TradeStatus.TARGET_2_HIT.value)
                action = TradeStatus.TARGET_2_HIT.value
            elif trade.target_1 is not None and current_ltp >= trade.target_1:
                if target_1_exit:
                    paper_engine.close_trade(trade, current_ltp, TradeStatus.TARGET_1_HIT.value)
                else:
                    paper_engine.mark_target_1(trade, current_ltp)
                action = TradeStatus.TARGET_1_HIT.value
            else:
                paper_engine.update_unrealized(trade, current_ltp)

            updates.append(
                {
                    "trade_id": trade.id,
                    "symbol": trade.symbol,
                    "current_ltp": current_ltp,
                    "action": action,
                    "status": trade.status,
                    "result": trade.result,
                    "unrealized_pnl": trade.unrealized_pnl,
                    "pnl": trade.pnl,
                }
            )

        db.commit()
        return {"checked": len(open_trades), "updated": len(updates), "items": updates}

    def _grouped(self, db: Session, key_fn) -> dict[str, Any]:
        groups: dict[str, list[PaperTrade]] = defaultdict(list)
        for trade in self.trades(db):
            groups[str(key_fn(trade))].append(trade)
        return {
            "count": len(groups),
            "items": {key: self._metrics(value) for key, value in sorted(groups.items())},
        }

    def _metrics(self, trades: list[PaperTrade]) -> dict[str, Any]:
        closed = [trade for trade in trades if trade.result in CLOSED_RESULTS]
        wins = [trade for trade in closed if trade.result == TradeResult.WIN.value]
        losses = [trade for trade in closed if trade.result == TradeResult.LOSS.value]
        pnl_values = [trade.pnl or 0 for trade in closed]
        return {
            "total_trades": len(trades),
            "open_trades": len([trade for trade in trades if trade.result == TradeResult.OPEN.value]),
            "closed_trades": len(closed),
            "wins": len(wins),
            "losses": len(losses),
            "win_rate": _pct(len(wins), len(closed)),
            "total_pnl": round(sum(pnl_values), 2),
            "average_pnl": _avg(pnl_values),
        }

    def _max_streak(self, closed: list[PaperTrade], result: str) -> int:
        best = 0
        current = 0
        for trade in sorted(closed, key=lambda item: item.exit_time or item.entry_time):
            if trade.result == result:
                current += 1
                best = max(best, current)
            else:
                current = 0
        return best

    def _realized_risk_reward(self, closed: list[PaperTrade]) -> float:
        values = []
        for trade in closed:
            initial_risk = None
            if trade.stop_loss is not None:
                initial_risk = abs(trade.entry_price - trade.stop_loss) * trade.quantity
            if initial_risk and initial_risk > 0:
                values.append((trade.pnl or 0) / initial_risk)
        return _avg(values)


def _pct(numerator: int, denominator: int) -> float:
    return round(numerator / denominator * 100, 2) if denominator else 0.0


def _avg(values: list[Any]) -> float:
    nums = [_safe_float(value) for value in values]
    clean = [value for value in nums if value is not None]
    return round(sum(clean) / len(clean), 2) if clean else 0.0


def _safe_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _resolve_trade_instrument(db: Session, importer: DhanInstrumentImporter, trade: PaperTrade):
    if trade.underlying and trade.expiry and trade.strike and trade.option_type:
        try:
            expiry = date.fromisoformat(str(trade.expiry))
        except ValueError:
            expiry = None
        if expiry is not None:
            for instrument in importer.options(db, trade.underlying, expiry):
                if _safe_float(instrument.strike) == _safe_float(trade.strike) and instrument.option_type == trade.option_type:
                    return instrument
    return importer.lookup_symbol(db, trade.symbol)


def _trade_brief(trade: PaperTrade) -> dict[str, Any]:
    return {
        "trade_id": trade.id,
        "symbol": trade.symbol,
        "underlying": trade.underlying,
        "pnl": trade.pnl,
        "result": trade.result,
        "exit_reason": trade.exit_reason,
    }


def _confidence_bucket(value: Any) -> str:
    confidence = _safe_float(value)
    if confidence is None:
        return "UNKNOWN"
    if confidence < 50:
        return "<50"
    if confidence < 60:
        return "50-60"
    if confidence < 70:
        return "60-70"
    if confidence < 80:
        return "70-80"
    if confidence < 90:
        return "80-90"
    return "90-100"
