from datetime import datetime
from typing import Any

from app.backtest.brokerage_model import BrokerageModel
from app.backtest.slippage_model import SlippageModel


def get_closest_strike_snapshot(
    db,
    symbol: str,
    expiry: Any,
    strike: float,
    option_type: str,
    target_time: datetime,
) -> Any | None:
    if db is None:
        return None
    try:
        from app.models.option_chain_snapshot import OptionChainStrikeSnapshot
        from sqlalchemy import select
        from datetime import date, timezone
        
        symbol = symbol.strip().upper()
        resolved_expiry = expiry
        if isinstance(resolved_expiry, str):
            try:
                resolved_expiry = datetime.strptime(resolved_expiry.split("T")[0], "%Y-%m-%d").date()
            except Exception:
                pass
        elif isinstance(resolved_expiry, datetime):
            resolved_expiry = resolved_expiry.date()
        elif isinstance(resolved_expiry, date):
            pass
        else:
            return None

        # Fetch closest snapshot before or at target_time
        query_before = (
            select(OptionChainStrikeSnapshot)
            .where(
                OptionChainStrikeSnapshot.symbol == symbol,
                OptionChainStrikeSnapshot.expiry == resolved_expiry,
                OptionChainStrikeSnapshot.strike == float(strike),
                OptionChainStrikeSnapshot.option_type == option_type,
                OptionChainStrikeSnapshot.snapshot_at <= target_time
            )
            .order_by(OptionChainStrikeSnapshot.snapshot_at.desc())
            .limit(1)
        )
        snap_before = db.scalar(query_before)
        
        # Fetch closest snapshot after target_time
        query_after = (
            select(OptionChainStrikeSnapshot)
            .where(
                OptionChainStrikeSnapshot.symbol == symbol,
                OptionChainStrikeSnapshot.expiry == resolved_expiry,
                OptionChainStrikeSnapshot.strike == float(strike),
                OptionChainStrikeSnapshot.option_type == option_type,
                OptionChainStrikeSnapshot.snapshot_at >= target_time
            )
            .order_by(OptionChainStrikeSnapshot.snapshot_at.asc())
            .limit(1)
        )
        snap_after = db.scalar(query_after)
        
        if snap_before and snap_after:
            t_target = target_time.astimezone(timezone.utc).replace(tzinfo=None) if target_time.tzinfo else target_time
            t_before = snap_before.snapshot_at.astimezone(timezone.utc).replace(tzinfo=None) if snap_before.snapshot_at.tzinfo else snap_before.snapshot_at
            t_after = snap_after.snapshot_at.astimezone(timezone.utc).replace(tzinfo=None) if snap_after.snapshot_at.tzinfo else snap_after.snapshot_at
            
            diff_before = abs((t_target - t_before).total_seconds())
            diff_after = abs((t_after - t_target).total_seconds())
            
            chosen = snap_before if diff_before <= diff_after else snap_after
            chosen_diff = diff_before if diff_before <= diff_after else diff_after
            if chosen_diff <= 7200:
                return chosen
            return None
            
        chosen = snap_before or snap_after
        if chosen:
            t_target = target_time.astimezone(timezone.utc).replace(tzinfo=None) if target_time.tzinfo else target_time
            t_chosen = chosen.snapshot_at.astimezone(timezone.utc).replace(tzinfo=None) if chosen.snapshot_at.tzinfo else chosen.snapshot_at
            if abs((t_target - t_chosen).total_seconds()) <= 7200:
                return chosen
        return None
    except Exception as e:
        print(f"Error querying closest strike snapshot: {e}")
        return None


class FillSimulator:
    def __init__(
        self,
        slippage_model: SlippageModel | None = None,
        brokerage_model: BrokerageModel | None = None,
    ) -> None:
        self.slippage_model = slippage_model or SlippageModel()
        self.brokerage_model = brokerage_model or BrokerageModel()

    def simulate_trade(
        self,
        candles: list,
        signal_index: int,
        signal: dict,
        entry_model: str = "NEXT_CANDLE_OPEN",
        same_candle_priority: str = "SL_FIRST",
        db = None,
    ) -> dict | None:
        entry_index = signal_index + 1 if entry_model == "NEXT_CANDLE_OPEN" else signal_index
        if entry_index >= len(candles):
            return None

        entry_candle = candles[entry_index]
        base_entry = float(entry_candle.open if entry_model == "NEXT_CANDLE_OPEN" else entry_candle.close)
        option_entry = signal["entry_price"]
        
        # Resolve bid-ask quote at entry time
        entry_bid = None
        entry_ask = None
        symbol = signal.get("underlying")
        expiry = signal.get("expiry")
        strike = signal.get("selected_strike")
        option_type = signal.get("option_type")
        if db is not None and symbol and expiry and strike and option_type:
            snap = get_closest_strike_snapshot(db, symbol, expiry, strike, option_type, entry_candle.timestamp)
            if snap:
                entry_bid = snap.bid_price
                entry_ask = snap.ask_price

        entry_slippage = self.slippage_model.option_slippage(option_entry, entry_bid, entry_ask)
        entry_price = round(option_entry + entry_slippage, 2)

        stop_loss = signal["stop_loss"]
        target_1 = signal["target_1"]
        target_2 = signal["target_2"]
        quantity = signal["quantity"]
        direction = 1 if signal["signal_type"] == "BUY_CE" else -1
        exit_price = None
        exit_time: datetime | None = None
        exit_reason = "EOD_EXIT"
        snapshots_used = 0
        total_candles = 0

        for candle in candles[entry_index:]:
            total_candles += 1
            opt_snap = None
            if db is not None and symbol and expiry and strike and option_type:
                opt_snap = get_closest_strike_snapshot(db, symbol, expiry, strike, option_type, candle.timestamp)

            if opt_snap is not None and opt_snap.ltp is not None and opt_snap.ltp > 0:
                option_high = opt_snap.ltp
                option_low = opt_snap.ltp
                snapshots_used += 1
            else:
                move_pct_high = ((float(candle.high) - base_entry) / base_entry) * direction if base_entry else 0.0
                move_pct_low = ((float(candle.low) - base_entry) / base_entry) * direction if base_entry else 0.0
                option_high = max(0.05, entry_price * (1 + move_pct_high * 6))
                option_low = max(0.05, entry_price * (1 + move_pct_low * 6))

            sl_hit = option_low <= stop_loss
            t2_hit = option_high >= target_2
            t1_hit = option_high >= target_1
            if sl_hit and (t1_hit or t2_hit):
                if same_candle_priority == "SL_FIRST":
                    exit_price = stop_loss
                    exit_reason = "STOP_LOSS_HIT"
                else:
                    exit_price = target_2 if t2_hit else target_1
                    exit_reason = "TARGET_2_HIT" if t2_hit else "TARGET_1_HIT"
                exit_time = candle.timestamp
                break
            if sl_hit:
                exit_price = stop_loss
                exit_reason = "STOP_LOSS_HIT"
                exit_time = candle.timestamp
                break
            if t2_hit:
                exit_price = target_2
                exit_reason = "TARGET_2_HIT"
                exit_time = candle.timestamp
                break
            if t1_hit:
                exit_price = target_1
                exit_reason = "TARGET_1_HIT"
                exit_time = candle.timestamp
                break

        if exit_price is None:
            last = candles[-1]
            opt_snap = None
            if db is not None and symbol and expiry and strike and option_type:
                opt_snap = get_closest_strike_snapshot(db, symbol, expiry, strike, option_type, last.timestamp)

            if opt_snap is not None and opt_snap.ltp is not None and opt_snap.ltp > 0:
                exit_price = opt_snap.ltp
                snapshots_used += 1
            else:
                move_pct = ((float(last.close) - base_entry) / base_entry) * direction if base_entry else 0.0
                exit_price = round(max(0.05, entry_price * (1 + move_pct * 6)), 2)
            exit_time = last.timestamp

        # Resolve bid-ask quote at exit time
        exit_bid = None
        exit_ask = None
        if db is not None and symbol and expiry and strike and option_type and exit_time:
            snap = get_closest_strike_snapshot(db, symbol, expiry, strike, option_type, exit_time)
            if snap:
                exit_bid = snap.bid_price
                exit_ask = snap.ask_price

        exit_slippage = self.slippage_model.option_slippage(exit_price, exit_bid, exit_ask)
        exit_price = round(max(0.05, exit_price - exit_slippage), 2)
        gross_pnl = round((exit_price - entry_price) * quantity, 2)
        charges = self.brokerage_model.charges(entry_price, exit_price, quantity)
        total_slippage = round((entry_slippage + exit_slippage) * quantity, 2)
        net_pnl = round(gross_pnl - charges["total_charges"], 2)
        result = "WIN" if net_pnl > 0 else "LOSS" if net_pnl < 0 else "BREAKEVEN"
        return {
            "entry_time": entry_candle.timestamp,
            "entry_price": entry_price,
            "exit_time": exit_time,
            "exit_price": exit_price,
            "gross_pnl": gross_pnl,
            "charges": charges["total_charges"],
            "slippage": total_slippage,
            "net_pnl": net_pnl,
            "result": result,
            "exit_reason": exit_reason,
            "option_chain_snapshots_used": snapshots_used,
            "total_candles_simulated": total_candles,
        }

