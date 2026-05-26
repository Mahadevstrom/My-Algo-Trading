import math
from collections import Counter, defaultdict
from statistics import mean, pstdev


class PerformanceMetrics:
    def calculate(self, trades: list[dict], rejected_reasons: list[str], initial_capital: float) -> dict:
        closed = [trade for trade in trades if trade.get("status") == "CLOSED"]
        wins = [trade for trade in closed if trade.get("result") == "WIN"]
        losses = [trade for trade in closed if trade.get("result") == "LOSS"]
        breakeven = [trade for trade in closed if trade.get("result") == "BREAKEVEN"]
        gross_pnl = round(sum(trade.get("gross_pnl", 0.0) for trade in closed), 2)
        net_pnl = round(sum(trade.get("net_pnl", 0.0) for trade in closed), 2)
        total_charges = round(sum(trade.get("charges", 0.0) for trade in closed), 2)
        total_slippage = round(sum(trade.get("slippage", 0.0) for trade in closed), 2)
        gross_profit = sum(trade.get("net_pnl", 0.0) for trade in wins)
        gross_loss = abs(sum(trade.get("net_pnl", 0.0) for trade in losses))
        equity_curve = self.equity_curve(closed, initial_capital)
        returns = [trade.get("net_pnl", 0.0) / initial_capital for trade in closed if initial_capital > 0]
        avg_holding = mean([trade.get("holding_minutes", 0.0) for trade in closed]) if closed else 0.0
        average_win = mean([trade.get("net_pnl", 0.0) for trade in wins]) if wins else 0.0
        average_loss = mean([trade.get("net_pnl", 0.0) for trade in losses]) if losses else 0.0
        return {
            "total_trades": len(closed),
            "wins": len(wins),
            "losses": len(losses),
            "breakeven": len(breakeven),
            "win_rate": round((len(wins) / len(closed) * 100), 2) if closed else 0.0,
            "gross_pnl": gross_pnl,
            "net_pnl": net_pnl,
            "total_charges": total_charges,
            "total_slippage": total_slippage,
            "average_win": round(average_win, 2),
            "average_loss": round(average_loss, 2),
            "profit_factor": round(gross_profit / gross_loss, 2) if gross_loss else (round(gross_profit, 2) if gross_profit else 0.0),
            "max_drawdown": self.max_drawdown(equity_curve),
            "sharpe_ratio": self.sharpe_ratio(returns),
            "max_losing_streak": self.max_streak(closed, "LOSS"),
            "max_winning_streak": self.max_streak(closed, "WIN"),
            "average_holding_minutes": round(avg_holding, 2),
            "expectancy": round(net_pnl / len(closed), 2) if closed else 0.0,
            "rejected_signals_count": len(rejected_reasons),
            "rejection_reason_breakdown": dict(Counter(rejected_reasons)),
        }

    def equity_curve(self, trades: list[dict], initial_capital: float) -> list[dict]:
        equity = initial_capital
        curve = []
        for index, trade in enumerate(trades, start=1):
            equity += trade.get("net_pnl", 0.0)
            curve.append(
                {
                    "index": index,
                    "trade_id": trade.get("id"),
                    "closed_at": trade.get("exit_time"),
                    "pnl": round(trade.get("net_pnl", 0.0), 2),
                    "equity": round(equity, 2),
                    "cumulative_pnl": round(equity - initial_capital, 2),
                }
            )
        return curve

    def max_drawdown(self, equity_curve: list[dict]) -> float:
        peak = None
        max_dd = 0.0
        for point in equity_curve:
            equity = point["equity"]
            peak = equity if peak is None else max(peak, equity)
            if peak:
                max_dd = min(max_dd, equity - peak)
        return round(max_dd, 2)

    def sharpe_ratio(self, returns: list[float]) -> float:
        if len(returns) < 2:
            return 0.0
        deviation = pstdev(returns)
        if deviation == 0:
            return 0.0
        return round((mean(returns) / deviation) * math.sqrt(len(returns)), 2)

    def max_streak(self, trades: list[dict], result: str) -> int:
        best = 0
        current = 0
        for trade in trades:
            if trade.get("result") == result:
                current += 1
                best = max(best, current)
            else:
                current = 0
        return best

    def group_rejections(self, trades) -> dict:
        counts = defaultdict(int)
        for trade in trades:
            if trade.status == "REJECTED":
                counts[trade.rejection_reason or "UNKNOWN"] += 1
        return dict(counts)
