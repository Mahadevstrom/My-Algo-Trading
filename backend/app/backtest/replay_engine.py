import json
from datetime import datetime
from typing import Any

from app.backtest.fill_simulator import FillSimulator
from app.backtest.performance_metrics import PerformanceMetrics
from app.risk.cooldown_manager import CooldownManager
from app.risk.duplicate_guard import DuplicateGuard
from app.risk.safety_gate import SafetyGate


class ReplayEngine:
    def __init__(self) -> None:
        self.cooldown = CooldownManager()
        self.duplicate_guard = DuplicateGuard()
        self.safety_gate = SafetyGate(
            duplicate_guard=self.duplicate_guard,
            cooldown_manager=self.cooldown,
        )
        self.fill_simulator = FillSimulator()
        self.metrics = PerformanceMetrics()

    def run(self, db, run_id: int, candles: list, config: dict[str, Any]) -> dict[str, Any]:
        self.db = db
        trades: list[dict[str, Any]] = []
        rejected_reasons: list[str] = []
        open_positions: list[dict[str, Any]] = []
        trades_by_day: dict[str, int] = {}
        pnl_by_day: dict[str, float] = {}
        consecutive_losses = 0
        total_signals = 0
        accepted = 0
        rejected = 0
        total_snapshots_used = 0

        for index in range(3, max(len(candles) - 1, 0)):
            if index % int(config.get("signal_every_n_candles", 3)) != 0:
                continue

            signal = self._spot_signal(candles, index, config)
            if signal is None:
                total_signals += 1
                rejected += 1
                rejected_reasons.append("NO_SIGNAL")
                trades.append(self._rejection(run_id, candles[index].timestamp, config, "NO_TRADE", "NO_SIGNAL"))
                continue

            total_signals += 1
            day_key = _day_key(candles[index].timestamp)
            context = {
                **signal,
                "mode": "PAPER",
                "signal_time": candles[index].timestamp,
                "trades_today": trades_by_day.get(day_key, 0),
                "daily_pnl": pnl_by_day.get(day_key, 0.0),
                "open_positions_count": len(open_positions),
                "open_positions": open_positions,
                "consecutive_losses": consecutive_losses,
                "stale_data": False,
            }
            gate = self.safety_gate.evaluate_trade_request(db, context)
            if not gate["approved"]:
                rejected += 1
                reason = "; ".join(gate["reasons"]) or "SAFETY_GATE_REJECTED"
                rejected_reasons.append(reason)
                self.cooldown.record_rejection(candles[index].timestamp)
                trades.append(self._rejection(run_id, candles[index].timestamp, config, signal["signal_type"], reason, signal))
                continue

            fill = self.fill_simulator.simulate_trade(
                candles,
                index,
                signal,
                entry_model=config.get("entry_model", "NEXT_CANDLE_OPEN"),
                same_candle_priority=config.get("same_candle_priority", "SL_FIRST"),
                db=db,
            )
            if fill is None:
                rejected += 1
                rejected_reasons.append("NO_FILL")
                trades.append(self._rejection(run_id, candles[index].timestamp, config, signal["signal_type"], "NO_FILL", signal))
                continue

            accepted += 1
            total_snapshots_used += fill.get("option_chain_snapshots_used", 0)
            trades_by_day[day_key] = trades_by_day.get(day_key, 0) + 1
            pnl_by_day[day_key] = round(pnl_by_day.get(day_key, 0.0) + fill["net_pnl"], 2)
            if fill["result"] == "LOSS":
                consecutive_losses += 1
                self.cooldown.record_loss(fill["exit_time"], self.safety_gate.limits.cooldown_after_loss_minutes)
            else:
                consecutive_losses = 0

            trades.append(
                {
                    "backtest_run_id": run_id,
                    "signal_time": candles[index].timestamp,
                    "underlying": config["underlying"],
                    "expiry": config["expiry"],
                    "signal_type": signal["signal_type"],
                    "status": "CLOSED",
                    "rejection_reason": None,
                    "spot_price": signal["spot_price"],
                    "selected_strike": signal["selected_strike"],
                    "option_type": signal["option_type"],
                    "entry_time": fill["entry_time"],
                    "entry_price": fill["entry_price"],
                    "exit_time": fill["exit_time"],
                    "exit_price": fill["exit_price"],
                    "stop_loss": signal["stop_loss"],
                    "target_1": signal["target_1"],
                    "target_2": signal["target_2"],
                    "quantity": signal["quantity"],
                    "gross_pnl": fill["gross_pnl"],
                    "charges": fill["charges"],
                    "slippage": fill["slippage"],
                    "net_pnl": fill["net_pnl"],
                    "result": fill["result"],
                    "exit_reason": fill["exit_reason"],
                    "confidence": signal["confidence"],
                    "strategy_score": signal["strategy_score"],
                    "chain_bias": signal["chain_bias"],
                    "reason_json": json.dumps(signal["reasons"]),
                    "holding_minutes": _holding_minutes(fill["entry_time"], fill["exit_time"]),
                }
            )

        metrics = self.metrics.calculate(trades, rejected_reasons, config["initial_capital"])
        metrics["total_signals"] = total_signals
        metrics["accepted_signals"] = accepted
        metrics["rejected_signals"] = rejected
        if total_snapshots_used > 0:
            metrics["option_chain_replay_mode"] = "ENABLED"
            metrics["replay_note"] = (
                f"Historical option-chain snapshots were used to simulate real option premium movements "
                f"({total_snapshots_used} snapshot lookups succeeded)."
            )
        else:
            metrics["option_chain_replay_mode"] = "DISABLED"
            metrics["replay_note"] = (
                "Historical option-chain snapshots are not stored or not found for these strikes. "
                "This replay used stored spot candles and an option-premium proxy approximation."
            )
        return {"trades": trades, "metrics": metrics}

    def _spot_signal(self, candles: list, index: int, config: dict[str, Any]) -> dict[str, Any] | None:
        strat = config.get("strategy_config")
        if strat:
            return self._custom_spot_signal(candles, index, config, strat)

        current = candles[index]
        previous = candles[index - 1]
        lookback = candles[index - 3 : index]
        previous_high = max(float(item.high) for item in lookback)
        previous_low = min(float(item.low) for item in lookback)
        close = float(current.close)
        momentum = close - float(candles[index - 3].close)
        if close > previous_high and momentum > 0:
            signal_type = "BUY_CE"
            option_type = "CE"
            chain_bias = "BULLISH"
            reason = "Spot broke above recent candle highs with positive momentum."
        elif close < previous_low and momentum < 0:
            signal_type = "BUY_PE"
            option_type = "PE"
            chain_bias = "BEARISH"
            reason = "Spot broke below recent candle lows with negative momentum."
        else:
            return None

        strike_step = 100 if config["underlying"] in {"BANKNIFTY", "BANKEX"} else 50
        selected_strike = round(close / strike_step) * strike_step
        entry = round(max(10.0, close * 0.005), 2)
        risk = max(entry * 0.20, 1.0)
        strategy_score = 90.0
        confidence = round(strategy_score * 0.85, 2)
        return {
            "underlying": config["underlying"],
            "expiry": config["expiry"],
            "signal_type": signal_type,
            "spot_price": close,
            "selected_strike": float(selected_strike),
            "option_type": option_type,
            "entry_price": entry,
            "stop_loss": round(max(entry - risk, 0.05), 2),
            "target_1": round(entry + risk * 1.5, 2),
            "target_2": round(entry + risk * 2.0, 2),
            "quantity": int(config["lot_size"]),
            "confidence": confidence,
            "strategy_score": strategy_score,
            "chain_bias": chain_bias,
            "liquidity_score": 65.0,
            "spread_pct": 6.0,
            "reasons": [reason, "Option-chain replay is disabled; this is a spot-candle proxy signal."],
        }

    def _rejection(
        self,
        run_id: int,
        signal_time: datetime,
        config: dict[str, Any],
        signal_type: str,
        reason: str,
        signal: dict | None = None,
    ) -> dict[str, Any]:
        signal = signal or {}
        return {
            "backtest_run_id": run_id,
            "signal_time": signal_time,
            "underlying": config["underlying"],
            "expiry": config["expiry"],
            "signal_type": signal_type,
            "status": "REJECTED",
            "rejection_reason": reason,
            "spot_price": signal.get("spot_price"),
            "selected_strike": signal.get("selected_strike"),
            "option_type": signal.get("option_type"),
            "entry_time": None,
            "entry_price": None,
            "exit_time": None,
            "exit_price": None,
            "stop_loss": signal.get("stop_loss"),
            "target_1": signal.get("target_1"),
            "target_2": signal.get("target_2"),
            "quantity": signal.get("quantity", 0),
            "gross_pnl": 0.0,
            "charges": 0.0,
            "slippage": 0.0,
            "net_pnl": 0.0,
            "result": "REJECTED",
            "exit_reason": None,
            "confidence": signal.get("confidence"),
            "strategy_score": signal.get("strategy_score"),
            "chain_bias": signal.get("chain_bias"),
            "reason_json": json.dumps(signal.get("reasons", [])),
        }

    def _custom_spot_signal(self, candles: list, index: int, config: dict[str, Any], strat: dict[str, Any]) -> dict[str, Any] | None:
        current = candles[index]
        close = float(current.close)
        
        lookback_len = int(strat.get("momentum_lookback_candles", 3))
        momentum_threshold = float(strat.get("momentum_threshold", 0.0))
        
        if index < lookback_len:
            return None
            
        lookback = candles[index - lookback_len : index]
        previous_high = max(float(item.high) for item in lookback)
        previous_low = min(float(item.low) for item in lookback)
        momentum = close - float(candles[index - lookback_len].close)
        
        is_bullish = close > previous_high and momentum > momentum_threshold
        is_bearish = close < previous_low and momentum < -momentum_threshold
        
        if not is_bullish and not is_bearish:
            return None
            
        if strat.get("use_volume_threshold", False):
            vol_lookback = int(strat.get("volume_sma_lookback", 10))
            vol_multiplier = float(strat.get("volume_multiplier", 1.2))
            
            if index >= vol_lookback:
                past_candles = candles[index - vol_lookback : index]
                avg_volume = sum(float(item.volume or 0) for item in past_candles) / vol_lookback
                current_vol = float(current.volume or 0)
                if current_vol < avg_volume * vol_multiplier:
                    return None
            else:
                return None
                
        if strat.get("use_pcr_bias", False) and hasattr(self, "db") and self.db is not None:
            pcr_val = self._get_historical_pcr(self.db, config["underlying"], current.timestamp)
            if pcr_val is not None:
                pcr_bullish = float(strat.get("pcr_bullish_threshold", 0.9))
                pcr_bearish = float(strat.get("pcr_bearish_threshold", 0.7))
                if is_bullish and pcr_val < pcr_bullish:
                    return None
                if is_bearish and pcr_val > pcr_bearish:
                    return None

        signal_type = "BUY_CE" if is_bullish else "BUY_PE"
        option_type = "CE" if is_bullish else "PE"
        chain_bias = "BULLISH" if is_bullish else "BEARISH"
        reason = f"Custom Builder: spot broke {'above' if is_bullish else 'below'} lookback breakout limits."

        strike_step = 100 if config["underlying"] in {"BANKNIFTY", "BANKEX"} else 50
        selected_strike = round(close / strike_step) * strike_step
        
        entry = round(max(10.0, close * 0.005), 2)
        
        sl_pct = float(strat.get("stop_loss_pct", 20.0)) / 100.0
        t1_pct = float(strat.get("target_1_pct", 30.0)) / 100.0
        t2_pct = float(strat.get("target_2_pct", 40.0)) / 100.0
        
        stop_loss = round(max(entry * (1 - sl_pct), 0.05), 2)
        target_1 = round(entry * (1 + t1_pct), 2)
        target_2 = round(entry * (1 + t2_pct), 2)
        
        strategy_score = 95.0
        confidence = round(strategy_score * 0.85, 2)
        
        return {
            "underlying": config["underlying"],
            "expiry": config["expiry"],
            "signal_type": signal_type,
            "spot_price": close,
            "selected_strike": float(selected_strike),
            "option_type": option_type,
            "entry_price": entry,
            "stop_loss": stop_loss,
            "target_1": target_1,
            "target_2": target_2,
            "quantity": int(config["lot_size"]),
            "confidence": confidence,
            "strategy_score": strategy_score,
            "chain_bias": chain_bias,
            "liquidity_score": 75.0,
            "spread_pct": 5.0,
            "reasons": [reason, "Custom Algo Strategy Builder Execution."],
        }

    def _get_historical_pcr(self, db, symbol: str, target_time: datetime) -> float | None:
        if db is None:
            return None
        try:
            from app.models.option_chain_snapshot import OptionChainSnapshot
            from sqlalchemy import select
            from datetime import timezone
            
            symbol = symbol.strip().upper()
            
            query_before = (
                select(OptionChainSnapshot)
                .where(
                    OptionChainSnapshot.symbol == symbol,
                    OptionChainSnapshot.snapshot_at <= target_time
                )
                .order_by(OptionChainSnapshot.snapshot_at.desc())
                .limit(1)
            )
            snap_before = db.scalar(query_before)
            
            query_after = (
                select(OptionChainSnapshot)
                .where(
                    OptionChainSnapshot.symbol == symbol,
                    OptionChainSnapshot.snapshot_at >= target_time
                )
                .order_by(OptionChainSnapshot.snapshot_at.asc())
                .limit(1)
            )
            snap_after = db.scalar(query_after)
            
            chosen = None
            if snap_before and snap_after:
                t_target = target_time.astimezone(timezone.utc).replace(tzinfo=None) if target_time.tzinfo else target_time
                t_before = snap_before.snapshot_at.astimezone(timezone.utc).replace(tzinfo=None) if snap_before.snapshot_at.tzinfo else snap_before.snapshot_at
                t_after = snap_after.snapshot_at.astimezone(timezone.utc).replace(tzinfo=None) if snap_after.snapshot_at.tzinfo else snap_after.snapshot_at
                
                diff_before = abs((t_target - t_before).total_seconds())
                diff_after = abs((t_after - t_target).total_seconds())
                chosen = snap_before if diff_before <= diff_after else snap_after
            else:
                chosen = snap_before or snap_after
                
            if chosen and chosen.pcr_oi is not None:
                return float(chosen.pcr_oi)
            return None
        except Exception as e:
            print(f"Error querying historical PCR: {e}")
            return None


def _day_key(value: datetime) -> str:
    return value.date().isoformat()


def _holding_minutes(start: datetime, end: datetime) -> float:
    return round((end - start).total_seconds() / 60, 2)
