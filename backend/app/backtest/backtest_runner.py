import json
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.audit.audit_logger import AuditLogger
from app.backtest.performance_metrics import PerformanceMetrics
from app.backtest.replay_engine import ReplayEngine
from app.models.backtest_run import BacktestRun
from app.models.backtest_trade import BacktestTrade
from app.models.candle import Candle


VALID_INTERVALS = {"1", "5", "15", "25", "60", "1day"}


class BacktestRunner:
    def run(self, db: Session, payload: Any) -> dict[str, Any]:
        parsed = self._validate(payload)
        if not parsed["ok"]:
            return parsed

        candles = self._candles(db, parsed)
        if not candles:
            return {
                "ok": False,
                "status": "NO_HISTORICAL_CANDLES",
                "message": "No historical candles found. Download candles before running a backtest.",
            }

        run = BacktestRun(
            name=payload.name,
            underlying=parsed["underlying"],
            expiry=payload.expiry,
            interval=parsed["interval"],
            from_date=parsed["from_date"],
            to_date=parsed["to_date"],
            initial_capital=payload.initial_capital,
            max_risk_per_trade=payload.max_risk_per_trade,
            lot_size=payload.lot_size,
            status="RUNNING",
            config_json=json.dumps(payload.model_dump(mode="json"), default=str),
        )
        db.add(run)
        db.commit()
        db.refresh(run)
        AuditLogger().log(
            db,
            "BACKTEST_STARTED",
            f"Backtest {run.id} started for {run.underlying}.",
            source="BACKTEST",
            entity_type="BacktestRun",
            entity_id=run.id,
            payload={"candles": len(candles)},
        )

        config = {
            "underlying": parsed["underlying"],
            "expiry": payload.expiry,
            "interval": parsed["interval"],
            "initial_capital": payload.initial_capital,
            "max_risk_per_trade": payload.max_risk_per_trade,
            "lot_size": payload.lot_size,
            "entry_model": payload.entry_model,
            "same_candle_priority": payload.same_candle_priority,
            "strategy_config": getattr(payload, "strategy_config", None),
        }
        replay = ReplayEngine().run(db, run.id, candles, config)
        try:
            for row in replay["trades"]:
                db.add(BacktestTrade(**{key: value for key, value in row.items() if key != "holding_minutes"}))
            self._update_run(run, replay["metrics"])
            db.commit()
            db.refresh(run)
        except SQLAlchemyError:
            db.rollback()
            return {
                "ok": False,
                "status": "DATABASE_ERROR",
                "message": "Could not save backtest results to the database.",
            }

        AuditLogger().log(
            db,
            "BACKTEST_COMPLETED",
            f"Backtest {run.id} completed.",
            source="BACKTEST",
            entity_type="BacktestRun",
            entity_id=run.id,
            payload=replay["metrics"],
        )
        if replay["metrics"].get("rejected_signals", 0):
            AuditLogger().log(
                db,
                "SIGNAL_REJECTED",
                f"{replay['metrics']['rejected_signals']} replay signals were rejected.",
                severity="INFO",
                source="BACKTEST",
                entity_type="BacktestRun",
                entity_id=run.id,
                payload=replay["metrics"].get("rejection_reason_breakdown", {}),
            )
        if replay["metrics"].get("accepted_signals", 0):
            AuditLogger().log(
                db,
                "PAPER_TRADE_CREATED",
                f"{replay['metrics']['accepted_signals']} simulated paper trades were created in backtest.",
                severity="INFO",
                source="BACKTEST",
                entity_type="BacktestRun",
                entity_id=run.id,
            )
        return {
            "ok": True,
            "status": "COMPLETED",
            "run_id": run.id,
            "summary": replay["metrics"],
            "message": "Backtest completed. This is paper/backtest only; no broker orders were placed.",
        }

    # Original run signature: def run(self, db: Session, payload: Any) -> dict[str, Any]:
    def walk_forward(self, db: Session, payload: Any) -> dict[str, Any]:
        parsed = self._validate(payload)
        if not parsed["ok"]:
            return parsed

        in_sample_days = int(getattr(payload, "in_sample_days", 60) or 60)
        out_of_sample_days = int(getattr(payload, "out_of_sample_days", 20) or 20)
        if in_sample_days <= 0 or out_of_sample_days <= 0:
            return {
                "ok": False,
                "status": "INVALID_WALK_FORWARD_WINDOW",
                "message": "in_sample_days and out_of_sample_days must be positive integers.",
            }

        candles = self._candles(db, parsed)
        if not candles:
            return {
                "ok": False,
                "status": "NO_HISTORICAL_CANDLES",
                "message": "No historical candles found. Download candles before running walk-forward validation.",
            }

        config = {
            "underlying": parsed["underlying"],
            "expiry": payload.expiry,
            "interval": parsed["interval"],
            "initial_capital": payload.initial_capital,
            "max_risk_per_trade": payload.max_risk_per_trade,
            "lot_size": payload.lot_size,
            "entry_model": payload.entry_model,
            "same_candle_priority": payload.same_candle_priority,
            "strategy_config": getattr(payload, "strategy_config", None),
        }
        windows: list[dict[str, Any]] = []
        skipped_windows: list[dict[str, Any]] = []
        window_start = parsed["from_date"]
        window_index = 1

        while True:
            in_sample_start = window_start
            in_sample_end = in_sample_start + timedelta(days=in_sample_days)
            out_sample_start = in_sample_end
            out_sample_end = out_sample_start + timedelta(days=out_of_sample_days)
            if out_sample_start > parsed["to_date"]:
                break
            if out_sample_end > parsed["to_date"]:
                out_sample_end = parsed["to_date"]

            in_sample_candles = self._filter_candles(candles, in_sample_start, in_sample_end)
            out_sample_candles = self._filter_candles(candles, out_sample_start, out_sample_end)
            if len(in_sample_candles) < 5 or len(out_sample_candles) < 5:
                skipped_windows.append(
                    {
                        "window": window_index,
                        "in_sample_start": in_sample_start.isoformat(),
                        "in_sample_end": in_sample_end.isoformat(),
                        "out_of_sample_start": out_sample_start.isoformat(),
                        "out_of_sample_end": out_sample_end.isoformat(),
                        "reason": "INSUFFICIENT_CANDLES",
                        "in_sample_candles": len(in_sample_candles),
                        "out_of_sample_candles": len(out_sample_candles),
                    }
                )
                window_start = window_start + timedelta(days=out_of_sample_days)
                window_index += 1
                continue

            in_sample = ReplayEngine().run(db, 0, in_sample_candles, config)
            out_sample = ReplayEngine().run(db, 0, out_sample_candles, config)
            out_metrics = out_sample["metrics"]
            windows.append(
                {
                    "window": window_index,
                    "in_sample_start": in_sample_start.isoformat(),
                    "in_sample_end": in_sample_end.isoformat(),
                    "out_of_sample_start": out_sample_start.isoformat(),
                    "out_of_sample_end": out_sample_end.isoformat(),
                    "in_sample_candles": len(in_sample_candles),
                    "out_of_sample_candles": len(out_sample_candles),
                    "in_sample_total_trades": in_sample["metrics"].get("total_trades", 0),
                    "out_of_sample_total_trades": out_metrics.get("total_trades", 0),
                    "out_of_sample_win_rate": out_metrics.get("win_rate", 0.0),
                    "out_of_sample_profit_factor": out_metrics.get("profit_factor", 0.0),
                    "out_of_sample_net_pnl": out_metrics.get("net_pnl", 0.0),
                    "out_of_sample_max_drawdown": out_metrics.get("max_drawdown", 0.0),
                }
            )
            window_start = window_start + timedelta(days=out_of_sample_days)
            window_index += 1

        profitable_windows = [window for window in windows if float(window["out_of_sample_win_rate"]) > 50]
        consistency_ratio = len(profitable_windows) / len(windows) if windows else 0.0
        return {
            "ok": True,
            "status": "COMPLETED" if windows else "NO_VALID_WINDOWS",
            "mode": "WALK_FORWARD",
            "paper_only": True,
            "message": "Walk-forward validation completed. This is paper/backtest only; no broker orders were placed.",
            "config": {
                "underlying": parsed["underlying"],
                "interval": parsed["interval"],
                "from_date": parsed["from_date"].isoformat(),
                "to_date": parsed["to_date"].isoformat(),
                "in_sample_days": in_sample_days,
                "out_of_sample_days": out_of_sample_days,
            },
            "summary": {
                "windows": len(windows),
                "skipped_windows": len(skipped_windows),
                "avg_out_of_sample_win_rate": self._average(windows, "out_of_sample_win_rate"),
                "avg_profit_factor": self._average(windows, "out_of_sample_profit_factor"),
                "consistency_score": round(consistency_ratio * 100, 2),
                "walk_forward_robustness": "ROBUST" if consistency_ratio > 0.60 else "NOT_ROBUST",
            },
            "windows": windows,
            "skipped": skipped_windows,
        }

    def optimize(self, db: Session, payload: Any) -> dict[str, Any]:
        parsed = self._validate(payload)
        if not parsed["ok"]:
            return parsed

        candles = self._candles(db, parsed)
        if not candles:
            return {
                "ok": False,
                "status": "NO_HISTORICAL_CANDLES",
                "message": "No historical candles found. Download candles before running optimization.",
            }

        sl_range = getattr(payload, "stop_loss_pct_range", [10.0, 25.0, 5.0])
        tgt_range = getattr(payload, "target_1_pct_range", [15.0, 35.0, 5.0])

        def build_range(r):
            if len(r) < 3 or float(r[2]) <= 0:
                return [float(r[0])] if r else [10.0]
            vals = []
            curr = float(r[0])
            limit = float(r[1])
            step = float(r[2])
            while curr <= limit + 1e-9:
                vals.append(round(curr, 2))
                curr += step
            return vals

        sl_vals = build_range(sl_range)
        tgt_vals = build_range(tgt_range)

        combinations = []
        max_combos = 100
        total_combos = len(sl_vals) * len(tgt_vals)
        if total_combos > max_combos:
            return {
                "ok": False,
                "status": "TOO_MANY_COMBINATIONS",
                "message": f"Total combinations ({total_combos}) exceeds maximum limit of {max_combos}. Please narrow ranges or increase steps.",
            }

        base_strategy_config = getattr(payload, "strategy_config", None) or {}

        for sl in sl_vals:
            for tgt in tgt_vals:
                config_copy = dict(base_strategy_config)
                config_copy["stop_loss_pct"] = sl
                config_copy["target_1_pct"] = tgt
                config_copy["target_2_pct"] = tgt + 10.0

                config = {
                    "underlying": parsed["underlying"],
                    "expiry": payload.expiry,
                    "interval": parsed["interval"],
                    "initial_capital": payload.initial_capital,
                    "max_risk_per_trade": payload.max_risk_per_trade,
                    "lot_size": payload.lot_size,
                    "entry_model": payload.entry_model,
                    "same_candle_priority": payload.same_candle_priority,
                    "strategy_config": config_copy,
                    "signal_every_n_candles": 1,
                }

                replay = ReplayEngine().run(db, 0, candles, config)
                metrics = replay["metrics"]

                combinations.append({
                    "stop_loss_pct": sl,
                    "target_1_pct": tgt,
                    "total_trades": metrics.get("total_trades", 0),
                    "win_rate": metrics.get("win_rate", 0.0),
                    "net_pnl": metrics.get("net_pnl", 0.0),
                    "profit_factor": metrics.get("profit_factor", 0.0),
                    "max_drawdown": metrics.get("max_drawdown", 0.0),
                    "sharpe_ratio": metrics.get("sharpe_ratio", 0.0),
                })

        optimal = None
        if combinations:
            optimal = max(combinations, key=lambda x: x["net_pnl"])

        return {
            "ok": True,
            "status": "COMPLETED",
            "mode": "OPTIMIZATION",
            "paper_only": True,
            "message": "Parameter optimization completed. This is paper/backtest only; no broker orders were placed.",
            "config": {
                "underlying": parsed["underlying"],
                "interval": parsed["interval"],
                "from_date": parsed["from_date"].isoformat(),
                "to_date": parsed["to_date"].isoformat(),
            },
            "combinations": combinations,
            "optimal": optimal,
        }

    def list_runs(self, db: Session) -> list[BacktestRun]:
        return list(db.scalars(select(BacktestRun).order_by(BacktestRun.created_at.desc()).limit(100)))

    def get_run(self, db: Session, run_id: int) -> BacktestRun | None:
        return db.get(BacktestRun, run_id)

    def trades(self, db: Session, run_id: int) -> list[BacktestTrade]:
        return list(
            db.scalars(
                select(BacktestTrade)
                .where(BacktestTrade.backtest_run_id == run_id)
                .order_by(BacktestTrade.signal_time, BacktestTrade.id)
            )
        )

    def equity_curve(self, db: Session, run_id: int) -> dict[str, Any]:
        run = self.get_run(db, run_id)
        if run is None:
            return {"ok": False, "status": "NOT_FOUND", "message": "Backtest run not found."}
        closed = [self._trade_dict(trade) for trade in self.trades(db, run_id) if trade.status == "CLOSED"]
        return {
            "ok": True,
            "run_id": run_id,
            "equity_curve": PerformanceMetrics().equity_curve(closed, run.initial_capital),
        }

    def metrics(self, db: Session, run_id: int) -> dict[str, Any]:
        run = self.get_run(db, run_id)
        if run is None:
            return {"ok": False, "status": "NOT_FOUND", "message": "Backtest run not found."}
        return {"ok": True, "run_id": run_id, "metrics": json.loads(run.summary_json or "{}")}

    def rejections(self, db: Session, run_id: int) -> dict[str, Any]:
        trades = [trade for trade in self.trades(db, run_id) if trade.status == "REJECTED"]
        return {
            "ok": True,
            "run_id": run_id,
            "count": len(trades),
            "items": trades,
            "breakdown": PerformanceMetrics().group_rejections(trades),
        }

    def _validate(self, payload: Any) -> dict[str, Any]:
        if not payload.expiry:
            return {"ok": False, "status": "EXPIRY_REQUIRED", "message": "Expiry is required."}
        interval = str(payload.interval).strip().lower()
        if interval not in VALID_INTERVALS:
            return {"ok": False, "status": "INVALID_INTERVAL", "message": "Invalid interval."}
        from_date = _parse_datetime(payload.from_date)
        to_date = _parse_datetime(payload.to_date)
        if from_date is None or to_date is None:
            return {"ok": False, "status": "INVALID_DATE", "message": "Invalid date format."}
        if from_date > to_date:
            return {"ok": False, "status": "INVALID_DATE_RANGE", "message": "from_date must be before to_date."}
        return {
            "ok": True,
            "underlying": payload.underlying.strip().upper(),
            "interval": interval,
            "from_date": from_date,
            "to_date": to_date,
        }

    def _candles(self, db: Session, parsed: dict[str, Any]) -> list[Candle]:
        return list(
            db.scalars(
                select(Candle)
                .where(
                    Candle.symbol == parsed["underlying"],
                    Candle.interval == parsed["interval"],
                    Candle.timestamp >= parsed["from_date"],
                    Candle.timestamp <= parsed["to_date"],
                )
                .order_by(Candle.timestamp)
            )
        )

    def _update_run(self, run: BacktestRun, metrics: dict[str, Any]) -> None:
        run.status = "COMPLETED"
        run.total_signals = metrics["total_signals"]
        run.accepted_signals = metrics["accepted_signals"]
        run.rejected_signals = metrics["rejected_signals"]
        run.total_trades = metrics["total_trades"]
        run.wins = metrics["wins"]
        run.losses = metrics["losses"]
        run.breakeven = metrics["breakeven"]
        run.win_rate = metrics["win_rate"]
        run.gross_pnl = metrics["gross_pnl"]
        run.net_pnl = metrics["net_pnl"]
        run.total_charges = metrics["total_charges"]
        run.total_slippage = metrics["total_slippage"]
        run.profit_factor = metrics["profit_factor"]
        run.max_drawdown = metrics["max_drawdown"]
        run.sharpe_ratio = metrics["sharpe_ratio"]
        run.max_losing_streak = metrics["max_losing_streak"]
        run.completed_at = datetime.now(timezone.utc)
        run.summary_json = json.dumps(metrics, default=str)

    def _trade_dict(self, trade: BacktestTrade) -> dict[str, Any]:
        return {
            "id": trade.id,
            "exit_time": trade.exit_time,
            "net_pnl": trade.net_pnl,
        }

    def _filter_candles(self, candles: list[Candle], start: datetime, end: datetime) -> list[Candle]:
        return [
            candle for candle in candles
            if (timestamp := self._normalized_timestamp(candle.timestamp)) is not None and start <= timestamp <= end
        ]

    def _average(self, rows: list[dict[str, Any]], key: str) -> float:
        values = [float(row.get(key) or 0.0) for row in rows]
        return round(sum(values) / len(values), 2) if values else 0.0

    def _normalized_timestamp(self, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)


def _parse_datetime(value: str) -> datetime | None:
    cleaned = str(value).strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            parsed = datetime.strptime(cleaned, fmt)
            return parsed.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    try:
        parsed = datetime.fromisoformat(cleaned.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed
    except ValueError:
        return None
