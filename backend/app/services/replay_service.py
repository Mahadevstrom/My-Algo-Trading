from __future__ import annotations

from collections import Counter
from datetime import date, datetime, time, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo
from zoneinfo._common import ZoneInfoNotFoundError

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from app.config import settings
from app.engine.dhan_instrument_importer import DhanInstrumentImporter
from app.engine.filters.chop_filter import evaluate_chop
from app.engine.filters.momentum_filter import evaluate_momentum
from app.engine.filters.regime_filter import classify_regime
from app.engine.filters.trend_filter import evaluate_trend
from app.engine.filters.volatility_filter import evaluate_volatility
from app.engine.signal_engine_v2 import SignalEngineV2
from app.models.live_candle import LiveCandleRecord
from app.models.live_tick import LiveTick
from app.models.trade import PaperTrade, TradeResult
from app.services.live_paper_simulator_service import SIMULATOR_SOURCE


try:
    IST = ZoneInfo("Asia/Kolkata")
except ZoneInfoNotFoundError:
    IST = timezone(timedelta(hours=5, minutes=30), name="Asia/Kolkata")


class ReplayService:
    """Read-only replay of stored live candles, option ticks, and paper trades."""

    def run_live_day_replay(
        self,
        db: Session,
        trading_date: date | None = None,
        underlying: str = "NIFTY",
        max_signal_events: int = 80,
    ) -> dict[str, Any]:
        day = trading_date or datetime.now(IST).date()
        symbol = underlying.strip().upper() or "NIFTY"
        start_utc, end_utc = _day_bounds_utc(day)

        candles = self._candles_by_timeframe(db, symbol, start_utc, end_utc)
        trades = self._paper_trades(db, symbol, start_utc, end_utc)
        signal_events = self._replay_signal_proxy(candles, max_signal_events)
        trade_replays = [self._replay_trade_exit(db, trade, end_utc) for trade in trades]
        summary = self._summary(candles, signal_events, trade_replays, trades)

        return {
            "ok": True,
            "mode": "READ_ONLY_REPLAY",
            "trading_date": day.isoformat(),
            "underlying": symbol,
            "time_window": {
                "start_ist": datetime.combine(day, time.min, tzinfo=IST).isoformat(),
                "end_ist": datetime.combine(day, time.max, tzinfo=IST).isoformat(),
                "start_utc": start_utc.isoformat(),
                "end_utc": end_utc.isoformat(),
            },
            "summary": summary,
            "signal_replay": {
                "mode": "SIGNAL_V2_CANDLE_PROXY",
                "note": (
                    "Uses stored live candles and Signal v2 filters. Historical option-chain snapshots, "
                    "data-quality snapshots, session-gate state, and market-flow state are not time-travelled in this first pass."
                ),
                "events": signal_events,
            },
            "trade_exit_replay": {
                "mode": "OPTION_TICK_EXIT_REPLAY",
                "note": "Replays actual live-paper entries against stored option LTP ticks without creating or modifying trades.",
                "trades": trade_replays,
            },
            "safety": {
                "creates_trades": False,
                "modifies_trades": False,
                "broker_execution": False,
                "live_orders": settings.safety_status["live_order_status"],
            },
        }

    def _candles_by_timeframe(
        self,
        db: Session,
        underlying: str,
        start_utc: datetime,
        end_utc: datetime,
    ) -> dict[str, list[LiveCandleRecord]]:
        output: dict[str, list[LiveCandleRecord]] = {}
        for timeframe in ("1m", "3m", "5m", "15m"):
            output[timeframe] = list(
                db.scalars(
                    select(LiveCandleRecord)
                    .where(
                        LiveCandleRecord.timeframe == timeframe,
                        LiveCandleRecord.start_time >= start_utc,
                        LiveCandleRecord.start_time <= end_utc,
                        or_(
                            LiveCandleRecord.symbol == underlying,
                            LiveCandleRecord.underlying == underlying,
                            and_(
                                LiveCandleRecord.underlying == underlying,
                                LiveCandleRecord.option_type.is_(None),
                            ),
                        ),
                    )
                    .order_by(LiveCandleRecord.start_time)
                )
            )
        return output

    def _paper_trades(
        self,
        db: Session,
        underlying: str,
        start_utc: datetime,
        end_utc: datetime,
    ) -> list[PaperTrade]:
        return list(
            db.scalars(
                select(PaperTrade)
                .where(
                    PaperTrade.data_source == SIMULATOR_SOURCE,
                    PaperTrade.entry_time >= start_utc,
                    PaperTrade.entry_time <= end_utc,
                    or_(PaperTrade.underlying == underlying, PaperTrade.symbol.ilike(f"{underlying}%")),
                )
                .order_by(PaperTrade.entry_time)
            )
        )

    def _replay_signal_proxy(self, candles: dict[str, list[LiveCandleRecord]], max_events: int) -> list[dict[str, Any]]:
        five_minute = candles.get("5m") or []
        if not five_minute:
            return []

        engine = SignalEngineV2()
        events: list[dict[str, Any]] = []
        for candle in five_minute:
            now = candle.start_time
            c1 = _slice_until(candles.get("1m", []), now, 60)
            c3 = _slice_until(candles.get("3m", []), now, 60)
            c5 = _slice_until(five_minute, now, 60)
            c15 = _slice_until(candles.get("15m", []), now, 40)
            if len(c5) < 5:
                continue

            trend = evaluate_trend(c5, c15, vwap_candles=c5)
            momentum = evaluate_momentum(c1, c3, trend["direction"])
            volatility = evaluate_volatility(c5)
            chop = evaluate_chop(c5)
            regime = classify_regime(
                _float(chop.get("adx")),
                _float(volatility.get("bb_width")),
                _float(volatility.get("avg_range_percent")),
            )
            required_score = float(regime.get("recommended_min_score") or settings.signal_v2_paper_min_score)
            direction = trend.get("direction", "UNKNOWN")
            score = 22.0 + float(trend.get("score") or 0) + float(momentum.get("score") or 0) + float(volatility.get("score") or 0)
            score += float(chop.get("score_penalty") or 0)

            failed_checks: list[str] = []
            reasons = [trend.get("message"), momentum.get("message"), volatility.get("message"), chop.get("message")]
            if chop.get("choppy") and chop.get("status") != "WEAK_TREND":
                failed_checks.append("CHOP_FILTER")
            market_structure = engine._market_structure_filter(c5, direction)
            retest_entry = engine._retest_entry_filter(c5, direction, trend, None, None)
            entry_candle = engine._entry_candle_quality(c5, direction)
            chase_filter = engine._chase_filter(c5, direction, trend, volatility)
            for diagnostic in (market_structure, retest_entry, entry_candle, chase_filter):
                score += diagnostic["score_adjustment"]
                failed_checks.extend(diagnostic["failed_checks"])
                reasons.extend(diagnostic["reasons"])

            decision = self._proxy_decision(direction, score, required_score, failed_checks)
            if decision == "NO_TRADE" and not failed_checks and score < required_score:
                failed_checks.append("SCORE_BELOW_DYNAMIC_THRESHOLD")
            events.append(
                {
                    "time": now.isoformat(),
                    "time_ist": _to_ist(now),
                    "decision": decision,
                    "direction": direction,
                    "score": round(score, 2),
                    "required_score": required_score,
                    "threshold_source": f"REPLAY_REGIME_{regime.get('regime', 'NEUTRAL')}",
                    "regime": regime.get("regime", "UNKNOWN"),
                    "trend_status": trend.get("status"),
                    "momentum_status": momentum.get("status"),
                    "volatility_status": volatility.get("status"),
                    "adx": chop.get("adx"),
                    "bb_width": volatility.get("bb_width"),
                    "market_structure": market_structure["context"],
                    "retest_entry": retest_entry["context"],
                    "entry_candle": entry_candle["context"],
                    "chase_filter": chase_filter["context"],
                    "failed_checks": _dedupe(failed_checks),
                    "reasons": _dedupe([str(reason) for reason in reasons if reason]),
                }
            )

        actionable = [event for event in events if event["decision"] != "NO_TRADE"]
        blocked = [event for event in events if event["decision"] == "NO_TRADE"]
        trimmed = actionable[-max_events:]
        if len(trimmed) < max_events:
            trimmed = (blocked[-(max_events - len(trimmed)):] + trimmed)[-max_events:]
        return trimmed

    def _replay_trade_exit(self, db: Session, trade: PaperTrade, day_end_utc: datetime) -> dict[str, Any]:
        instrument = self._resolve_trade_instrument(db, trade)
        tick_pack = self._trade_ticks(db, trade, instrument, day_end_utc)
        ticks = tick_pack["ticks"]
        expected = self._simulate_exit(trade, ticks, day_end_utc)
        actual = {
            "exit_time": trade.exit_time.isoformat() if trade.exit_time else None,
            "exit_time_ist": _to_ist(trade.exit_time) if trade.exit_time else None,
            "exit_price": trade.exit_price,
            "exit_reason": trade.exit_reason,
            "result": trade.result,
            "pnl": trade.pnl,
        }
        comparison = self._compare_exit(trade, expected)
        return {
            "trade_id": trade.id,
            "symbol": trade.symbol,
            "underlying": trade.underlying,
            "option_type": trade.option_type,
            "strike": trade.strike,
            "expiry": trade.expiry,
            "entry_time": trade.entry_time.isoformat() if trade.entry_time else None,
            "entry_time_ist": _to_ist(trade.entry_time) if trade.entry_time else None,
            "entry_price": trade.entry_price,
            "stop_loss": trade.stop_loss,
            "target_1": trade.target_1,
            "target_2": trade.target_2,
            "quantity": trade.quantity,
            "resolved_security_id": instrument.security_id if instrument else None,
            "resolved_symbol": instrument.trading_symbol if instrument else None,
            "tick_count": len(ticks),
            "tick_source": tick_pack["source"],
            "alternate_security_ids": tick_pack["alternate_security_ids"],
            "expected": expected,
            "actual": actual,
            "comparison": comparison,
        }

    def _resolve_trade_instrument(self, db: Session, trade: PaperTrade):
        importer = DhanInstrumentImporter()
        expiry = _parse_date(trade.expiry)
        if trade.underlying and expiry and trade.strike is not None and trade.option_type:
            for item in importer.options(db, trade.underlying, expiry):
                if item.option_type == trade.option_type and item.strike is not None and abs(float(item.strike) - float(trade.strike)) < 0.01:
                    return item
        return importer.lookup_symbol(db, trade.symbol)

    def _trade_ticks(self, db: Session, trade: PaperTrade, instrument, day_end_utc: datetime) -> dict[str, Any]:
        start = trade.entry_time
        end = trade.exit_time or day_end_utc
        base_conditions = [LiveTick.ltp.is_not(None), LiveTick.ltp > 0, LiveTick.received_at >= start, LiveTick.received_at <= end]
        if instrument is not None:
            exact_ticks = list(
                db.scalars(
                    select(LiveTick)
                    .where(*base_conditions, LiveTick.security_id == str(instrument.security_id))
                    .order_by(LiveTick.received_at)
                )
            )
            if exact_ticks:
                return {"ticks": exact_ticks, "source": "EXACT_SECURITY_ID", "alternate_security_ids": []}
        symbol_ticks = list(
            db.scalars(
                select(LiveTick)
                .where(*base_conditions, LiveTick.symbol == trade.symbol)
                .order_by(LiveTick.received_at)
            )
        )
        alternate_ids = sorted({str(tick.security_id) for tick in symbol_ticks if tick.security_id})
        if symbol_ticks:
            source = "SYMBOL_FALLBACK_AMBIGUOUS" if instrument is not None else "SYMBOL_FALLBACK"
            return {"ticks": symbol_ticks, "source": source, "alternate_security_ids": alternate_ids}
        if instrument is not None:
            return {"ticks": [], "source": "EXACT_SECURITY_ID_ONLY_OUTSIDE_TRADE_WINDOW", "alternate_security_ids": []}
        return {"ticks": [], "source": "NO_TICKS_FOUND", "alternate_security_ids": []}

    def _simulate_exit(self, trade: PaperTrade, ticks: list[LiveTick], day_end_utc: datetime) -> dict[str, Any]:
        if not ticks:
            return {
                "status": "NO_OPTION_TICKS",
                "exit_time": None,
                "exit_time_ist": None,
                "exit_price": None,
                "exit_reason": None,
                "pnl": None,
                "max_favorable_price": trade.entry_price,
                "max_adverse_price": trade.entry_price,
            }

        max_favorable = trade.entry_price
        max_adverse = trade.entry_price
        trailing_stop = None
        breakeven_stop = None
        for tick in ticks:
            price = float(tick.ltp or 0)
            tick_time = tick.received_at
            max_favorable = max(max_favorable, price)
            max_adverse = min(max_adverse, price)
            activation_price = trade.entry_price * (1 + settings.live_paper_trailing_activate_percent / 100)
            if price >= activation_price:
                breakeven_stop = max(breakeven_stop or trade.entry_price, trade.entry_price)
                if settings.live_paper_trailing_enabled:
                    candidate = price * (1 - settings.live_paper_trailing_gap_percent / 100)
                    trailing_stop = max(trailing_stop or candidate, candidate)

            reason = None
            if trade.stop_loss is not None and price <= trade.stop_loss:
                reason = "STOP_LOSS_HIT"
            elif breakeven_stop is not None and price <= breakeven_stop:
                reason = "BREAKEVEN_STOP_HIT"
            elif trailing_stop is not None and price <= trailing_stop:
                reason = "TRAILING_STOP_HIT"
            elif trade.target_2 is not None and price >= trade.target_2:
                reason = "TARGET_2_HIT"
            elif _minutes_between(trade.entry_time, tick_time) >= 15 and max_favorable < trade.entry_price * 1.05:
                reason = "NO_PROGRESS_EXIT"
            elif _minutes_between(trade.entry_time, tick_time) >= settings.live_paper_time_exit_minutes:
                reason = "TIME_EXIT"
            if reason:
                return self._expected_exit_payload(trade, tick_time, price, reason, max_favorable, max_adverse, trailing_stop, breakeven_stop)

        last_tick = ticks[-1]
        return {
            "status": "NO_EXIT_TRIGGERED",
            "exit_time": None,
            "exit_time_ist": None,
            "exit_price": None,
            "exit_reason": None,
            "pnl": None,
            "last_tick_time": last_tick.received_at.isoformat(),
            "last_tick_time_ist": _to_ist(last_tick.received_at),
            "last_ltp": last_tick.ltp,
            "max_favorable_price": round(max_favorable, 2),
            "max_adverse_price": round(max_adverse, 2),
            "trailing_stop_price": round(trailing_stop, 2) if trailing_stop is not None else None,
            "breakeven_stop_price": round(breakeven_stop, 2) if breakeven_stop is not None else None,
        }

    def _expected_exit_payload(
        self,
        trade: PaperTrade,
        tick_time: datetime,
        price: float,
        reason: str,
        max_favorable: float,
        max_adverse: float,
        trailing_stop: float | None,
        breakeven_stop: float | None,
    ) -> dict[str, Any]:
        pnl = (price - trade.entry_price) * trade.quantity
        return {
            "status": "EXIT_TRIGGERED",
            "exit_time": tick_time.isoformat(),
            "exit_time_ist": _to_ist(tick_time),
            "exit_price": round(price, 2),
            "exit_reason": reason,
            "pnl": round(pnl, 2),
            "pnl_percent": round((price - trade.entry_price) / trade.entry_price * 100, 2) if trade.entry_price else None,
            "max_favorable_price": round(max_favorable, 2),
            "max_adverse_price": round(max_adverse, 2),
            "trailing_stop_price": round(trailing_stop, 2) if trailing_stop is not None else None,
            "breakeven_stop_price": round(breakeven_stop, 2) if breakeven_stop is not None else None,
        }

    def _compare_exit(self, trade: PaperTrade, expected: dict[str, Any]) -> dict[str, Any]:
        expected_reason = expected.get("exit_reason")
        if expected.get("status") == "NO_OPTION_TICKS":
            return {"status": "NO_TICK_DATA", "message": "Replay cannot verify exit because stored option LTP ticks are missing."}
        if expected_reason and trade.result == TradeResult.OPEN.value:
            return {"status": "MISSED_EXIT", "message": f"Replay expected {expected_reason}, but trade is still open."}
        if not expected_reason and trade.result != TradeResult.OPEN.value:
            return {"status": "UNEXPECTED_ACTUAL_EXIT", "message": f"Trade closed as {trade.exit_reason}, but replay did not find an exit trigger."}
        if not expected_reason:
            return {"status": "MATCH_OPEN", "message": "Replay found no exit trigger and trade is open/no-trigger."}

        reason_match = _normalized_reason(trade.exit_reason) == _normalized_reason(expected_reason)
        delay_minutes = _minutes_between(_parse_datetime(expected.get("exit_time")), trade.exit_time) if trade.exit_time else None
        if reason_match:
            status = "MATCH_DELAYED" if delay_minutes is not None and delay_minutes > 2 else "MATCH"
            return {
                "status": status,
                "message": f"Replay and actual exit agree on {expected_reason}.",
                "exit_delay_minutes": round(delay_minutes, 2) if delay_minutes is not None else None,
            }
        return {
            "status": "DIFFERENT_EXIT",
            "message": f"Replay expected {expected_reason}, actual exit was {trade.exit_reason}.",
            "exit_delay_minutes": round(delay_minutes, 2) if delay_minutes is not None else None,
        }

    def _proxy_decision(self, direction: str, score: float, required_score: float, failed_checks: list[str]) -> str:
        if any(check in {"CHOP_FILTER", "ENTRY_CANDLE_NOT_CONFIRMED", "CHASE_DISTANCE_FROM_VWAP", "CHASE_AFTER_BIG_MOVE"} for check in failed_checks):
            return "NO_TRADE"
        if score < required_score:
            return "NO_TRADE"
        if direction == "BULLISH":
            return "BUY_CALL"
        if direction == "BEARISH":
            return "BUY_PUT"
        return "NO_TRADE"

    def _summary(
        self,
        candles: dict[str, list[LiveCandleRecord]],
        signal_events: list[dict[str, Any]],
        trade_replays: list[dict[str, Any]],
        trades: list[PaperTrade],
    ) -> dict[str, Any]:
        comparison_counts = Counter((row.get("comparison") or {}).get("status", "UNKNOWN") for row in trade_replays)
        decision_counts = Counter(row.get("decision", "UNKNOWN") for row in signal_events)
        expected_exits = [row for row in trade_replays if (row.get("expected") or {}).get("exit_reason")]
        return {
            "candle_counts": {timeframe: len(rows) for timeframe, rows in candles.items()},
            "paper_trade_count": len(trades),
            "signal_event_count": len(signal_events),
            "signal_decision_counts": dict(decision_counts),
            "expected_exit_count": len(expected_exits),
            "comparison_counts": dict(comparison_counts),
            "mismatches": [
                row
                for row in trade_replays
                if (row.get("comparison") or {}).get("status") in {"MISSED_EXIT", "DIFFERENT_EXIT", "UNEXPECTED_ACTUAL_EXIT", "NO_TICK_DATA"}
            ],
        }


def _day_bounds_utc(day: date) -> tuple[datetime, datetime]:
    start_ist = datetime.combine(day, time.min, tzinfo=IST)
    end_ist = datetime.combine(day, time.max, tzinfo=IST)
    return start_ist.astimezone(timezone.utc), end_ist.astimezone(timezone.utc)


def _slice_until(candles: list[LiveCandleRecord], current_time: datetime, limit: int) -> list[LiveCandleRecord]:
    return [candle for candle in candles if candle.start_time <= current_time][-limit:]


def _float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    for fmt in ("%Y-%m-%d", "%d %b %Y", "%d %B %Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(value).date()
    except ValueError:
        return None


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _to_ist(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(IST).isoformat()


def _minutes_between(start: datetime | None, end: datetime | None) -> float:
    if start is None or end is None:
        return 0.0
    if start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)
    if end.tzinfo is None:
        end = end.replace(tzinfo=timezone.utc)
    return max(0.0, (end - start).total_seconds() / 60)


def _normalized_reason(reason: str | None) -> str | None:
    if reason in {"TARGET_HIT", "TARGET_1_HIT", "TARGET_2_HIT"}:
        return "TARGET_HIT"
    return reason


def _dedupe(items: list[str]) -> list[str]:
    seen = set()
    output = []
    for item in items:
        if item and item not in seen:
            seen.add(item)
            output.append(item)
    return output


replay_service = ReplayService()


def get_replay_service() -> ReplayService:
    return replay_service
