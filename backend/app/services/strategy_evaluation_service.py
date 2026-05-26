import json
from collections import Counter, defaultdict
from datetime import datetime, time, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.engine.paper_accuracy_engine import PaperAccuracyEngine
from app.models.audit_log import AuditLog
from app.models.backtest_run import BacktestRun
from app.models.backtest_trade import BacktestTrade
from app.models.signal import SignalRecord
from app.models.trade import PaperTrade, TradeResult
from app.schemas.strategy_evaluation import StrategyMetrics
from app.services.live_paper_simulator_service import get_live_paper_simulator_service


LIVE_PAPER_SOURCE = "LIVE_PAPER_SIMULATOR"
REJECTION_EVENTS = {
    "SIGNAL_V2_NO_TRADE",
    "SIGNAL_V2_DATA_QUALITY_REJECTED",
    "SIGNAL_V2_RISK_REJECTED",
    "LIVE_PAPER_ENTRY_REJECTED",
    "SAFETY_GATE_REJECTED",
    "SIGNAL_REJECTED",
}


class StrategyEvaluationService:
    def status(self) -> dict[str, Any]:
        return {
            "enabled": settings.enable_strategy_evaluation,
            "mode": settings.trading_mode,
            "live_order_status": settings.safety_status["live_order_status"],
            "lookback_days": settings.strategy_eval_lookback_days,
            "min_sample_size": settings.strategy_eval_min_sample_size,
            "source": "READ_ONLY_ANALYTICS",
        }

    async def summary(self, db: Session) -> dict[str, Any]:
        paper = self.paper_metrics(db)
        live_paper = self.live_paper_metrics(db)
        backtest = self.backtest_metrics(db)
        health = self.health_score(db)
        live_status = await get_live_paper_simulator_service().status(db)
        return {
            "ok": True,
            "status": "OK",
            "paper": paper.model_dump(),
            "live_paper": live_paper.model_dump(),
            "backtest": backtest.model_dump(),
            "health_score": health,
            "live_paper_status": live_status,
            "message": "Strategy evaluation is read-only and paper/backtest analytics only.",
        }

    def backtest_vs_paper(self, db: Session) -> dict[str, Any]:
        backtest = self.backtest_metrics(db)
        paper = self.live_paper_metrics(db)
        if paper.closed_trades < settings.strategy_eval_min_sample_size or backtest.closed_trades < settings.strategy_eval_min_sample_size:
            status = "INSUFFICIENT_DATA"
            message = "Backtest or live paper sample size is too small to compare responsibly."
        else:
            win_delta = abs(backtest.win_rate - paper.win_rate)
            pf_delta = abs(backtest.profit_factor - paper.profit_factor)
            dd_delta = abs(backtest.max_drawdown - paper.max_drawdown)
            if win_delta <= 10 and pf_delta <= 0.4 and dd_delta <= 5:
                status = "ALIGNED"
                message = "Backtest and live paper metrics are broadly aligned."
            elif win_delta <= 20 and pf_delta <= 0.8:
                status = "WARNING"
                message = "Backtest and live paper metrics show moderate drift."
            else:
                status = "DIVERGING"
                message = "Backtest and live paper metrics are diverging."
        return {
            "ok": True,
            "status": status,
            "message": message,
            "backtest": backtest.model_dump(),
            "live_paper": paper.model_dump(),
            "deltas": {
                "total_trades": backtest.total_trades - paper.total_trades,
                "win_rate": round(backtest.win_rate - paper.win_rate, 2),
                "profit_factor": round(backtest.profit_factor - paper.profit_factor, 2),
                "max_drawdown": round(backtest.max_drawdown - paper.max_drawdown, 2),
                "average_trade": round(_avg_trade(backtest) - _avg_trade(paper), 2),
            },
        }

    def signal_v1_vs_v2(self, db: Session) -> dict[str, Any]:
        latest_v1 = db.scalar(select(SignalRecord).order_by(SignalRecord.created_at.desc()).limit(1))
        latest_v2_items = get_signal_v2_latest()
        latest_v2 = latest_v2_items[0] if latest_v2_items else None
        if latest_v1 is None and latest_v2 is None:
            return {
                "ok": True,
                "status": "NO_DATA",
                "latest_v1": None,
                "latest_v2": None,
                "v2_is_stricter": True,
                "v2_rejected_weak_signal": False,
                "v2_has_better_context": True,
                "recommendation": "NEED_MORE_DATA",
                "message": "No Signal v1 or v2 results are available yet.",
            }
        v1_payload = _signal_record_json(latest_v1) if latest_v1 else None
        v2_payload = latest_v2
        v2_decision = (latest_v2 or {}).get("decision")
        v1_status = latest_v1.status if latest_v1 else None
        v2_rejected = v2_decision == "NO_TRADE" and v1_status in {"SIGNAL", "WATCHLIST"}
        return {
            "ok": True,
            "status": "OK",
            "latest_v1": v1_payload,
            "latest_v2": v2_payload,
            "v2_is_stricter": True,
            "v2_rejected_weak_signal": bool(v2_rejected),
            "v2_has_better_context": True,
            "recommendation": "TRUST_V2_FILTERS_FOR_PAPER_TESTING"
            if v2_rejected
            else "CONTINUE_COMPARING_SIGNALS",
            "reason": "Signal v2 includes data-quality, live-candle, option-chain, risk, and session context.",
        }

    def health_score(self, db: Session) -> dict[str, Any]:
        metrics = self.live_paper_metrics(db)
        if metrics.closed_trades < settings.strategy_eval_min_sample_size:
            return {
                "status": "INSUFFICIENT_DATA",
                "score": 0,
                "label": "INSUFFICIENT_DATA",
                "reasons": [f"Need at least {settings.strategy_eval_min_sample_size} closed live paper trades."],
                "metrics": metrics.model_dump(),
            }
        score = 0.0
        reasons = []
        score += min(metrics.win_rate / 60 * 20, 20)
        score += min(metrics.profit_factor / settings.strategy_eval_healthy_profit_factor * 20, 20) if settings.strategy_eval_healthy_profit_factor else 0
        drawdown_abs = abs(metrics.max_drawdown)
        if drawdown_abs <= settings.strategy_eval_max_acceptable_drawdown:
            score += 20
        else:
            score += max(0, 20 - (drawdown_abs - settings.strategy_eval_max_acceptable_drawdown))
            reasons.append("Drawdown is above the configured comfort threshold.")
        if metrics.expectancy > settings.strategy_eval_min_expectancy:
            score += 15
        else:
            reasons.append("Expectancy is not positive yet.")
        dq = self.data_quality_impact(db)
        dq_ok = dq.get("quality_counts", {}).get("OK", 0)
        dq_total = sum(dq.get("quality_counts", {}).values())
        score += 10 if dq_total == 0 else min(dq_ok / dq_total * 10, 10)
        rejection = self.rejections(db)
        score += 10 if rejection.get("discipline_status") in {"HEALTHY", "STRICT"} else 4
        score += 5
        label = "HEALTHY" if score >= 80 else "WATCH" if score >= 60 else "WEAK" if score >= 40 else "UNSAFE"
        return {"status": "OK", "score": round(score, 2), "label": label, "reasons": reasons, "metrics": metrics.model_dump()}

    def rejections(self, db: Session) -> dict[str, Any]:
        events = self._recent_rejection_events(db)
        counts = Counter()
        for event in events:
            reason = _reason_from_audit(event)
            counts[reason] += 1
        most_common = counts.most_common(1)[0][0] if counts else None
        total = sum(counts.values())
        if total == 0:
            discipline = "NO_DATA"
            message = "No rejection events found in the lookback window."
        elif counts.get("DATA_QUALITY_FAILED", 0) + counts.get("SIGNAL_V2_NO_TRADE", 0) >= total * 0.5:
            discipline = "STRICT"
            message = "Rejections are mostly from quality/no-trade discipline."
        elif counts.get("MAX_OPEN_TRADES_REACHED", 0) or counts.get("DAILY_LOSS_LIMIT_REACHED", 0):
            discipline = "RISK_CONSTRAINED"
            message = "Risk limits are actively constraining entries."
        else:
            discipline = "HEALTHY"
            message = "Rejection mix looks reasonable for paper testing."
        return {
            "ok": True,
            "status": "OK" if total else "NO_DATA",
            "total_rejections": total,
            "counts": dict(counts),
            "most_common_rejection_reason": most_common,
            "discipline_status": discipline,
            "message": message,
        }

    def data_quality_impact(self, db: Session) -> dict[str, Any]:
        events = list(
            db.scalars(
                select(AuditLog)
                .where(AuditLog.created_at >= _lookback_start(), AuditLog.source.in_(["DATA_QUALITY", "SIGNAL_V2", "LIVE_PAPER"]))
                .order_by(AuditLog.created_at.desc())
            )
        )
        quality_counts = Counter()
        signal_rejections = 0
        for event in events:
            payload = _payload(event)
            status = payload.get("data_status") or payload.get("data_quality_status")
            if not status and isinstance(payload.get("check"), dict):
                status = payload["check"].get("status")
            if status:
                quality_counts[str(status)] += 1
            if event.event_type == "SIGNAL_V2_DATA_QUALITY_REJECTED":
                signal_rejections += 1
        if not events:
            return {"ok": True, "status": "NO_DATA", "message": "No data quality history found.", "quality_counts": {}, "signal_rejections_due_to_quality": 0}
        return {
            "ok": True,
            "status": "OK" if quality_counts else "NO_DATA",
            "quality_counts": dict(quality_counts),
            "signal_rejections_due_to_quality": signal_rejections,
            "paper_trades_during_ok_data": 0,
            "paper_trades_during_stale_data": 0,
            "message": "Data-quality impact is based on audit events; per-trade quality attribution can be expanded later.",
        }

    def performance_by(self, db: Session, field: str) -> dict[str, Any]:
        trades = self._paper_trades(db, include_live=True)
        groups: dict[str, list[PaperTrade]] = defaultdict(list)
        for trade in trades:
            if field == "signal_type":
                key = trade.signal_type or "UNKNOWN"
            elif field == "confidence":
                key = _confidence_bucket(trade.final_confidence or trade.signal_confidence)
            elif field == "chain_bias":
                key = trade.chain_bias or "UNKNOWN"
            elif field == "data_quality":
                key = "UNKNOWN"
            elif field == "strategy_version":
                key = "v2" if trade.signal_reason and "signal_version=v2" in trade.signal_reason else "v1_or_manual"
            else:
                key = "UNKNOWN"
            groups[key].append(trade)
        return {"ok": True, "group_by": field, "count": len(groups), "items": {key: self._metrics_from_paper(value).model_dump() for key, value in sorted(groups.items())}}

    async def daily_review(self, db: Session) -> dict[str, Any]:
        start = datetime.combine(datetime.now(timezone.utc).date(), time.min, tzinfo=timezone.utc)
        trades = list(db.scalars(select(PaperTrade).where(PaperTrade.entry_time >= start).order_by(PaperTrade.entry_time)))
        open_trades = [trade for trade in trades if trade.result == TradeResult.OPEN.value]
        closed = [trade for trade in trades if trade.result != TradeResult.OPEN.value]
        pnl = sum(trade.pnl or 0.0 for trade in closed)
        unrealized = sum(trade.unrealized_pnl or 0.0 for trade in open_trades)
        rejections = self.rejections(db)
        dq = self.data_quality_impact(db)
        live_status = await get_live_paper_simulator_service().status(db)
        recommendation = self._daily_recommendation(closed, pnl, rejections)
        return {
            "ok": True,
            "date": start.date().isoformat(),
            "today_paper_trades": len(trades),
            "open_paper_trades": len(open_trades),
            "closed_paper_trades": len(closed),
            "realized_pnl": round(pnl, 2),
            "unrealized_pnl": round(unrealized, 2),
            "wins": len([trade for trade in closed if trade.result == "WIN"]),
            "losses": len([trade for trade in closed if trade.result == "LOSS"]),
            "rejected_signals": rejections,
            "data_quality_issues": dq,
            "live_paper_simulator_status": live_status,
            "best_trade": _trade_brief(max(closed, key=lambda trade: trade.pnl or 0)) if closed else None,
            "worst_trade": _trade_brief(min(closed, key=lambda trade: trade.pnl or 0)) if closed else None,
            "recommendation": recommendation,
        }

    def recommendation(self, db: Session) -> dict[str, Any]:
        health = self.health_score(db)
        if health["status"] == "INSUFFICIENT_DATA":
            recommendation = "NEED_MORE_DATA"
        elif health["label"] in {"HEALTHY", "WATCH"}:
            recommendation = "CONTINUE_PAPER_TESTING"
        elif health["label"] == "WEAK":
            recommendation = "REDUCE_RISK"
        else:
            recommendation = "PAUSE_STRATEGY"
        return {"ok": True, "recommendation": recommendation, "health": health, "note": "Paper/backtest evaluation only; this is not live-trading approval."}

    def paper_metrics(self, db: Session) -> StrategyMetrics:
        return self._metrics_from_paper(self._paper_trades(db, include_live=True))

    def live_paper_metrics(self, db: Session) -> StrategyMetrics:
        return self._metrics_from_paper(self._paper_trades(db, include_live=False))

    def backtest_metrics(self, db: Session) -> StrategyMetrics:
        runs = list(db.scalars(select(BacktestRun).where(BacktestRun.created_at >= _lookback_start()).order_by(BacktestRun.created_at)))
        trades = list(db.scalars(select(BacktestTrade).where(BacktestTrade.signal_time >= _lookback_start()).order_by(BacktestTrade.signal_time)))
        closed = [trade for trade in trades if trade.result in {"WIN", "LOSS", "BREAKEVEN"}]
        pnl_values = [trade.net_pnl or 0.0 for trade in closed]
        wins = [trade for trade in closed if trade.result == "WIN"]
        losses = [trade for trade in closed if trade.result == "LOSS"]
        rejected = [trade for trade in trades if trade.status == "REJECTED" or trade.rejection_reason]
        rejection_counts = Counter(trade.rejection_reason or "UNKNOWN" for trade in rejected)
        return StrategyMetrics(
            total_trades=sum(run.total_trades for run in runs) if runs else len(trades),
            open_trades=len([trade for trade in trades if trade.result == "OPEN"]),
            closed_trades=len(closed),
            wins=len(wins),
            losses=len(losses),
            breakeven=len([trade for trade in closed if trade.result == "BREAKEVEN"]),
            win_rate=_pct(len(wins), len(closed)),
            gross_pnl=round(sum(trade.gross_pnl or 0.0 for trade in closed), 2),
            net_pnl=round(sum(pnl_values), 2),
            average_win=_avg([trade.net_pnl for trade in wins]),
            average_loss=_avg([trade.net_pnl for trade in losses]),
            expectancy=_avg(pnl_values),
            profit_factor=_profit_factor(pnl_values),
            max_drawdown=min([run.max_drawdown for run in runs], default=0.0),
            average_holding_time=_avg([_holding_minutes(trade.entry_time, trade.exit_time) for trade in closed if trade.entry_time and trade.exit_time]),
            max_losing_streak=max([run.max_losing_streak for run in runs], default=0),
            average_signal_score=_avg([trade.strategy_score or trade.confidence for trade in trades if trade.strategy_score or trade.confidence]),
            rejected_signal_count=len(rejected),
            rejection_reason_breakdown=dict(rejection_counts),
        )

    def _metrics_from_paper(self, trades: list[PaperTrade]) -> StrategyMetrics:
        closed = [trade for trade in trades if trade.result in {"WIN", "LOSS", "BREAKEVEN"}]
        wins = [trade for trade in closed if trade.result == "WIN"]
        losses = [trade for trade in closed if trade.result == "LOSS"]
        pnl_values = [trade.pnl or 0.0 for trade in closed]
        return StrategyMetrics(
            total_trades=len(trades),
            open_trades=len([trade for trade in trades if trade.result == TradeResult.OPEN.value]),
            closed_trades=len(closed),
            wins=len(wins),
            losses=len(losses),
            breakeven=len([trade for trade in closed if trade.result == "BREAKEVEN"]),
            win_rate=_pct(len(wins), len(closed)),
            gross_pnl=round(sum(value for value in pnl_values if value > 0), 2),
            net_pnl=round(sum(pnl_values), 2),
            average_win=_avg([trade.pnl for trade in wins]),
            average_loss=_avg([trade.pnl for trade in losses]),
            expectancy=_avg(pnl_values),
            profit_factor=_profit_factor(pnl_values),
            max_drawdown=PaperAccuracyEngine().drawdown_from_trades(trades)["max_drawdown"] if hasattr(PaperAccuracyEngine(), "drawdown_from_trades") else _drawdown(pnl_values),
            average_holding_time=_avg([trade.holding_minutes for trade in closed if trade.holding_minutes is not None]),
            max_losing_streak=_max_streak(closed, "LOSS"),
            average_signal_score=_avg([trade.final_confidence or trade.signal_confidence for trade in trades if trade.final_confidence or trade.signal_confidence]),
        )

    def _paper_trades(self, db: Session, include_live: bool) -> list[PaperTrade]:
        query = select(PaperTrade).where(PaperTrade.entry_time >= _lookback_start()).order_by(PaperTrade.entry_time)
        if not include_live:
            query = query.where(PaperTrade.data_source == "LIVE_PAPER_SIMULATOR")
        return list(db.scalars(query))

    def _recent_rejection_events(self, db: Session) -> list[AuditLog]:
        return list(
            db.scalars(
                select(AuditLog)
                .where(AuditLog.created_at >= _lookback_start(), AuditLog.event_type.in_(REJECTION_EVENTS))
                .order_by(AuditLog.created_at.desc())
            )
        )

    def _daily_recommendation(self, closed: list[PaperTrade], pnl: float, rejections: dict[str, Any]) -> str:
        if len(closed) < 3:
            return "NEED_MORE_DATA"
        if pnl < -abs(settings.live_paper_max_daily_loss) * 0.5:
            return "PAUSE_STRATEGY"
        if rejections.get("discipline_status") == "RISK_CONSTRAINED":
            return "REDUCE_RISK"
        return "CONTINUE_PAPER_TESTING"


def get_signal_v2_latest() -> list[dict[str, Any]]:
    try:
        from app.engine.signal_engine_v2 import get_signal_engine_v2

        return get_signal_engine_v2().latest(10).get("items", [])
    except Exception:
        return []


def _lookback_start() -> datetime:
    return datetime.now(timezone.utc) - timedelta(days=settings.strategy_eval_lookback_days)


def _pct(numerator: int, denominator: int) -> float:
    return round(numerator / denominator * 100, 2) if denominator else 0.0


def _avg(values: list[Any]) -> float:
    clean = []
    for value in values:
        try:
            if value is not None:
                clean.append(float(value))
        except (TypeError, ValueError):
            pass
    return round(sum(clean) / len(clean), 2) if clean else 0.0


def _profit_factor(pnl_values: list[float]) -> float:
    gross_profit = sum(value for value in pnl_values if value > 0)
    gross_loss = abs(sum(value for value in pnl_values if value < 0))
    if gross_loss > 0:
        return round(gross_profit / gross_loss, 2)
    return round(gross_profit, 2) if gross_profit > 0 else 0.0


def _drawdown(pnl_values: list[float]) -> float:
    cumulative = 0.0
    peak = 0.0
    max_drawdown = 0.0
    for value in pnl_values:
        cumulative += value
        peak = max(peak, cumulative)
        max_drawdown = min(max_drawdown, cumulative - peak)
    return round(max_drawdown, 2)


def _max_streak(trades: list[PaperTrade], result: str) -> int:
    best = 0
    current = 0
    for trade in sorted(trades, key=lambda item: item.exit_time or item.entry_time):
        if trade.result == result:
            current += 1
            best = max(best, current)
        else:
            current = 0
    return best


def _holding_minutes(start: datetime | None, end: datetime | None) -> float | None:
    if not start or not end:
        return None
    if start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)
    if end.tzinfo is None:
        end = end.replace(tzinfo=timezone.utc)
    return round((end - start).total_seconds() / 60, 2)


def _confidence_bucket(value: Any) -> str:
    try:
        confidence = float(value)
    except (TypeError, ValueError):
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


def _avg_trade(metrics: StrategyMetrics) -> float:
    return metrics.net_pnl / metrics.closed_trades if metrics.closed_trades else 0.0


def _payload(event: AuditLog) -> dict[str, Any]:
    try:
        return json.loads(event.payload_json or "{}")
    except json.JSONDecodeError:
        return {}


def _reason_from_audit(event: AuditLog) -> str:
    payload = _payload(event)
    if "reason" in payload:
        return str(payload["reason"])
    if event.event_type == "SIGNAL_V2_DATA_QUALITY_REJECTED":
        return "DATA_QUALITY_FAILED"
    if event.event_type == "SIGNAL_V2_NO_TRADE":
        return "SIGNAL_V2_NO_TRADE"
    if event.event_type == "SIGNAL_V2_RISK_REJECTED":
        return "KILL_SWITCH_OR_RISK"
    return event.event_type


def _signal_record_json(signal: SignalRecord | None) -> dict[str, Any] | None:
    if signal is None:
        return None
    return {
        "id": signal.id,
        "underlying": signal.underlying,
        "expiry": signal.expiry.isoformat() if signal.expiry else None,
        "signal_type": signal.signal_type,
        "status": signal.status,
        "final_confidence": signal.final_confidence,
        "strategy_score": signal.strategy_score,
        "chain_bias": signal.chain_bias,
        "created_at": signal.created_at.isoformat() if signal.created_at else None,
    }


def _trade_brief(trade: PaperTrade) -> dict[str, Any]:
    return {
        "trade_id": trade.id,
        "symbol": trade.symbol,
        "underlying": trade.underlying,
        "pnl": trade.pnl,
        "result": trade.result,
        "exit_reason": trade.exit_reason,
    }


strategy_evaluation_service = StrategyEvaluationService()


def get_strategy_evaluation_service() -> StrategyEvaluationService:
    return strategy_evaluation_service

