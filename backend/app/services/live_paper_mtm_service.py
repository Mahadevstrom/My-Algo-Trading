from datetime import datetime, timedelta, timezone
from time import monotonic
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit.audit_logger import AuditLogger
from app.brokers.dhan_data import DhanDataAdapter
from app.config import settings
from app.engine.paper_engine import PaperEngine
from app.engine.dhan_instrument_importer import DhanInstrumentImporter
from app.models.instrument import InstrumentMaster
from app.models.live_candle import LiveCandleRecord
from app.models.live_tick import LiveTick
from app.models.trade import PaperTrade, TradeResult
from app.services.live_feed_service import get_live_feed_service
from app.utils.market_session import india_market_session


SIMULATOR_SOURCE = "LIVE_PAPER_SIMULATOR"


class LivePaperMtmService:
    def __init__(self) -> None:
        self.trade_state: dict[int, dict[str, Any]] = {}
        self._rest_ltp_cache: dict[str, tuple[float, float]] = {}

    async def mark_to_market(self, db: Session) -> dict[str, Any]:
        trades = self.open_simulator_trades(db)
        items = []
        for trade in trades:
            await self.ensure_trade_symbol_subscribed(db, trade)
            items.append(await self.update_trade(db, trade))
        db.commit()
        return {
            "ok": True,
            "checked": len(trades),
            "updated": len([item for item in items if item.get("status") not in {"NO_LTP"}]),
            "items": items,
        }

    def open_simulator_trades(self, db: Session) -> list[PaperTrade]:
        return list(
            db.scalars(
                select(PaperTrade)
                .where(PaperTrade.data_source == SIMULATOR_SOURCE, PaperTrade.result == TradeResult.OPEN.value)
                .order_by(PaperTrade.entry_time)
            )
        )

    async def update_trade(self, db: Session, trade: PaperTrade) -> dict[str, Any]:
        instrument = self._resolve_trade_instrument(db, trade)
        tick_result = await self._tick_for_trade(trade, instrument)
        state = self.trade_state.setdefault(trade.id, {})
        current_ltp = None
        tick_age = None
        data_status = "NO_LTP"
        mark_source = "LIVE_FEED_MEMORY"
        if tick_result.get("ok"):
            tick = tick_result["tick"]
            current_ltp = _usable_ltp(tick.get("ltp"))
            received_at = _parse_datetime(tick.get("received_at"))
            if received_at:
                tick_age = (datetime.now(timezone.utc) - received_at.astimezone(timezone.utc)).total_seconds()
            data_status = "STALE" if tick_age is not None and tick_age > settings.live_paper_stale_exit_seconds else "OK"
        else:
            tick = self._latest_persisted_tick(db, trade.symbol, instrument.security_id if instrument else None)
            if tick is not None:
                mark_source = "PERSISTED_LIVE_TICK"
                current_ltp = _usable_ltp(tick.get("ltp"))
                received_at = _parse_datetime(tick.get("received_at"))
                if received_at:
                    tick_age = (datetime.now(timezone.utc) - received_at.astimezone(timezone.utc)).total_seconds()
                data_status = "STALE" if tick_age is not None and tick_age > settings.live_paper_stale_exit_seconds else "OK"

        if current_ltp is None and instrument is not None:
            rest_ltp = await self._rest_ltp_for_trade(instrument)
            if rest_ltp is not None:
                current_ltp = rest_ltp
                tick_age = 0.0
                data_status = "OK"
                mark_source = "DHAN_REST_LTP_FALLBACK"

        if current_ltp is None:
            stale_exit = self._maybe_stale_exit(db, trade, state)
            if stale_exit:
                return stale_exit
            return {
                "trade_id": trade.id,
                "symbol": trade.symbol,
                "status": "NO_LTP",
                "message": "No live LTP available for simulator paper trade.",
                "data_status": data_status,
                "mark_source": "NO_LTP",
                "subscription_status": (await self.ensure_trade_symbol_subscribed(db, trade)).get("status"),
            }

        PaperEngine().update_unrealized(trade, current_ltp)
        self._mark_target_1_if_needed(db, trade, current_ltp, state)
        self._update_price_extremes(trade, current_ltp, state)
        state["last_mtm_at"] = datetime.now(timezone.utc)
        state["data_status"] = data_status
        state["tick_age_seconds"] = round(tick_age, 2) if tick_age is not None else None
        state["mark_source"] = mark_source

        exit_reason = self._exit_reason(db, trade, current_ltp, state, data_status, instrument)
        if exit_reason:
            PaperEngine().close_trade(trade, current_ltp, exit_reason)
            AuditLogger().log(
                db,
                self._event_for_exit(exit_reason),
                f"Live paper simulator exited paper trade {trade.id}: {exit_reason}.",
                source="LIVE_PAPER",
                entity_type="PaperTrade",
                entity_id=trade.id,
                payload={
                    "symbol": trade.symbol,
                    "exit_price": current_ltp,
                    "pnl": trade.pnl,
                    "max_favorable_price": state.get("max_favorable_price"),
                    "max_adverse_price": state.get("max_adverse_price"),
                    "trailing_stop_price": state.get("trailing_stop_price"),
                    "breakeven_stop_price": state.get("breakeven_stop_price"),
                    "target_1_hit": state.get("target_1_hit"),
                    "target_1_hit_at": state.get("target_1_hit_at"),
                    "momentum_fade_context": state.get("momentum_fade_context"),
                    "data_status": data_status,
                    "mark_source": state.get("mark_source"),
                    "tick_age_seconds": state.get("tick_age_seconds"),
                },
                commit=False,
            )
            return self.snapshot(trade, current_ltp, state, action=exit_reason)

        self._audit_mtm_throttled(db, trade, current_ltp, state)
        return self.snapshot(trade, current_ltp, state, action="UPDATED")

    def register_entry(self, trade: PaperTrade) -> None:
        self.trade_state[trade.id] = {
            "max_favorable_price": trade.entry_price,
            "max_adverse_price": trade.entry_price,
            "trailing_stop_price": None,
            "breakeven_stop_price": None,
            "last_mtm_at": datetime.now(timezone.utc),
            "data_status": "NEW",
        }

    async def ensure_trade_symbol_subscribed(self, db: Session, trade: PaperTrade) -> dict[str, Any]:
        state = self.trade_state.setdefault(trade.id, {})
        if not settings.enable_dhan_websocket:
            state["subscription_status"] = "WEBSOCKET_DISABLED"
            return {"ok": False, "status": "WEBSOCKET_DISABLED"}
        feed = get_live_feed_service()
        status = feed.status()
        if not status.get("connected"):
            state["subscription_status"] = "LIVE_FEED_DISCONNECTED"
            return {"ok": False, "status": "LIVE_FEED_DISCONNECTED"}

        instrument = self._resolve_trade_instrument(db, trade)
        if instrument is None:
            AuditLogger().log(
                db,
                "LIVE_PAPER_OPTION_SUBSCRIBE_FAILED",
                "Could not resolve option contract for live paper MTM.",
                severity="WARNING",
                source="LIVE_PAPER",
                entity_type="PaperTrade",
                entity_id=trade.id,
                payload={"symbol": trade.symbol, "underlying": trade.underlying, "expiry": trade.expiry, "strike": trade.strike, "option_type": trade.option_type},
                commit=False,
            )
            state["subscription_status"] = "OPTION_INSTRUMENT_NOT_FOUND"
            return {"ok": False, "status": "OPTION_INSTRUMENT_NOT_FOUND", "symbol": trade.symbol}

        existing_tick = await feed.store.get_by_security_id(instrument.security_id)
        if existing_tick is None:
            existing_tick = await feed.store.get_by_symbol(trade.symbol)
        if existing_tick is not None:
            existing_security_id = str(getattr(existing_tick, "security_id", ""))
            existing_ltp = _safe_float(getattr(existing_tick, "ltp", None))
            if existing_security_id == str(instrument.security_id) and existing_ltp is not None:
                state["subscription_status"] = "ALREADY_HAS_LTP"
                state["security_id"] = instrument.security_id
                return {"ok": True, "status": "ALREADY_HAS_LTP", "symbol": trade.symbol, "security_id": instrument.security_id}

        result = await feed.client.subscribe(
            [
                {
                    "exchange_segment": instrument.segment,
                    "security_id": instrument.security_id,
                    "symbol": instrument.trading_symbol,
                }
            ]
        )
        AuditLogger().log(
            db,
            "LIVE_PAPER_OPTION_SUBSCRIBED_FOR_MTM",
            "Subscribed paper option contract for MTM stop-loss/target tracking.",
            source="LIVE_PAPER",
            entity_type="PaperTrade",
            entity_id=trade.id,
            payload={
                "symbol": trade.symbol,
                "security_id": instrument.security_id,
                "exchange_segment": instrument.segment,
                "result": result.get("status"),
            },
            commit=False,
        )
        state["subscription_status"] = "SUBSCRIBE_REQUESTED"
        state["security_id"] = instrument.security_id
        return {"ok": True, "status": "SUBSCRIBE_REQUESTED", "symbol": trade.symbol, "security_id": instrument.security_id}

    def snapshot(self, trade: PaperTrade, current_ltp: float | None = None, state: dict[str, Any] | None = None, action: str = "SNAPSHOT") -> dict[str, Any]:
        state = state or self.trade_state.get(trade.id, {})
        return {
            "trade_id": trade.id,
            "symbol": trade.symbol,
            "underlying": trade.underlying,
            "action": action,
            "status": trade.status,
            "result": trade.result,
            "entry_time": trade.entry_time.isoformat() if trade.entry_time else None,
            "exit_time": trade.exit_time.isoformat() if trade.exit_time else None,
            "exit_reason": trade.exit_reason,
            "signal_type": trade.signal_type,
            "entry_price": trade.entry_price,
            "current_ltp": current_ltp if current_ltp is not None else trade.current_price,
            "quantity": trade.quantity,
            "unrealized_pnl": trade.unrealized_pnl,
            "realized_pnl": trade.pnl,
            "pnl_percent": trade.pnl_percent,
            "stop_loss": trade.stop_loss,
            "target_1": trade.target_1,
            "target_2": trade.target_2,
            "max_favorable_price": state.get("max_favorable_price"),
            "max_adverse_price": state.get("max_adverse_price"),
            "breakeven_stop_price": state.get("breakeven_stop_price"),
            "trailing_stop_price": state.get("trailing_stop_price"),
            "target_1_hit": state.get("target_1_hit") or trade.status == "TARGET_1_HIT",
            "target_1_hit_at": state.get("target_1_hit_at"),
            "momentum_fade_context": state.get("momentum_fade_context"),
            "last_mtm_at": state.get("last_mtm_at"),
            "data_status": state.get("data_status", "UNKNOWN"),
            "tick_age_seconds": state.get("tick_age_seconds"),
            "mark_source": state.get("mark_source", "UNKNOWN"),
            "subscription_status": state.get("subscription_status", "UNKNOWN"),
            "stop_distance": _distance(current_ltp if current_ltp is not None else trade.current_price, trade.stop_loss),
            "target_distance": _distance(trade.target_1, current_ltp if current_ltp is not None else trade.current_price),
        }

    def _update_price_extremes(self, trade: PaperTrade, current_ltp: float, state: dict[str, Any]) -> None:
        state["max_favorable_price"] = max(_safe_float(state.get("max_favorable_price")) or trade.entry_price, current_ltp)
        state["max_adverse_price"] = min(_safe_float(state.get("max_adverse_price")) or trade.entry_price, current_ltp)
        # Backup: before adaptive exit support, only original SL, target, and optional trailing stop were tracked.
        breakeven_activation = trade.entry_price * (1 + settings.live_paper_trailing_activate_percent / 100)
        if current_ltp >= breakeven_activation:
            previous_breakeven = _safe_float(state.get("breakeven_stop_price"))
            state["breakeven_stop_price"] = max(previous_breakeven or trade.entry_price, trade.entry_price)
        if not settings.live_paper_trailing_enabled:
            return
        if state.get("target_1_hit") or trade.status == "TARGET_1_HIT":
            candidate = current_ltp * (1 - settings.live_paper_trailing_gap_percent / 100)
            previous = _safe_float(state.get("trailing_stop_price"))
            state["trailing_stop_price"] = max(previous or candidate, candidate, trade.entry_price)

    def _mark_target_1_if_needed(self, db: Session, trade: PaperTrade, current_ltp: float, state: dict[str, Any]) -> None:
        if state.get("target_1_hit") or trade.status == "TARGET_1_HIT":
            state["target_1_hit"] = True
            return
        if trade.target_1 is None or current_ltp < trade.target_1:
            return
        state["target_1_hit"] = True
        state["target_1_hit_at"] = datetime.now(timezone.utc)
        PaperEngine().mark_target_1(trade, current_ltp)
        if settings.live_paper_trailing_enabled:
            candidate = max(trade.entry_price, current_ltp * (1 - settings.live_paper_trailing_gap_percent / 100))
            previous = _safe_float(state.get("trailing_stop_price"))
            state["trailing_stop_price"] = max(previous or candidate, candidate)
        AuditLogger().log(
            db,
            "LIVE_PAPER_TARGET_1_HIT_TRAIL_ARMED",
            f"Live paper trade {trade.id} hit target 1; trailing stop armed.",
            source="LIVE_PAPER",
            entity_type="PaperTrade",
            entity_id=trade.id,
            payload={"symbol": trade.symbol, "target_1": trade.target_1, "current_ltp": current_ltp, "trailing_stop_price": state.get("trailing_stop_price")},
            commit=False,
        )

    def _exit_reason(
        self,
        db: Session,
        trade: PaperTrade,
        current_ltp: float,
        state: dict[str, Any],
        data_status: str,
        instrument: InstrumentMaster | None,
    ) -> str | None:
        if trade.stop_loss is not None and current_ltp <= trade.stop_loss:
            return "STOP_LOSS_HIT"
        breakeven = _safe_float(state.get("breakeven_stop_price"))
        if breakeven is not None and current_ltp <= breakeven:
            return "BREAKEVEN_STOP_HIT"
        trailing = _safe_float(state.get("trailing_stop_price"))
        if trailing is not None and current_ltp <= trailing:
            return "TRAILING_STOP_HIT"
        if trade.target_2 is not None and current_ltp >= trade.target_2:
            return "TARGET_2_HIT"
        if self._option_momentum_faded(db, trade, instrument, state):
            return "OPTION_MOMENTUM_FADE_EXIT"
        if data_status == "STALE" and settings.live_paper_auto_exit_on_stale_data:
            return "DATA_STALE_EXIT"
        max_favorable = _safe_float(state.get("max_favorable_price")) or trade.entry_price
        no_progress_price = trade.entry_price * 1.05
        if self._holding_minutes(trade) >= 15 and max_favorable < no_progress_price:
            return "NO_PROGRESS_EXIT"
        if self._holding_minutes(trade) >= settings.live_paper_time_exit_minutes:
            return "TIME_EXIT"
        session = india_market_session()
        if session["session_status"] == "CLOSED" and settings.live_paper_market_session_only:
            return "MARKET_CLOSE_EXIT"
        return None

    def _option_momentum_faded(
        self,
        db: Session,
        trade: PaperTrade,
        instrument: InstrumentMaster | None,
        state: dict[str, Any],
    ) -> bool:
        if not (state.get("target_1_hit") or trade.status == "TARGET_1_HIT"):
            return False
        candles = self._latest_option_candles(db, trade, instrument, "1m", 5)
        if len(candles) < 3:
            candles = self._latest_option_candles(db, trade, instrument, "3m", 5)
        if len(candles) < 3:
            return False
        closes = [_safe_float(getattr(candle, "close", None)) for candle in candles[-3:]]
        highs = [_safe_float(getattr(candle, "high", None)) for candle in candles[-3:]]
        if any(value is None for value in closes + highs):
            return False
        lower_closes = closes[-1] < closes[-2] < closes[-3]
        lower_highs = highs[-1] < highs[-2] < highs[-3]
        if lower_closes or lower_highs:
            state["momentum_fade_context"] = {
                "timeframe": getattr(candles[-1], "timeframe", None),
                "closes": closes,
                "highs": highs,
            }
            return True
        return False

    def _latest_option_candles(
        self,
        db: Session,
        trade: PaperTrade,
        instrument: InstrumentMaster | None,
        timeframe: str,
        limit: int,
    ) -> list[LiveCandleRecord]:
        filters = [LiveCandleRecord.timeframe == timeframe, LiveCandleRecord.close > 0]
        if instrument is not None:
            filters.append(LiveCandleRecord.security_id == str(instrument.security_id))
        else:
            filters.append(LiveCandleRecord.symbol == trade.symbol)
        rows = list(
            db.scalars(
                select(LiveCandleRecord)
                .where(*filters)
                .order_by(LiveCandleRecord.start_time.desc())
                .limit(limit)
            )
        )
        return list(reversed(rows))

    def _resolve_trade_instrument(self, db: Session, trade: PaperTrade) -> InstrumentMaster | None:
        if self._has_option_contract_fields(trade):
            instrument = self._lookup_option_contract(db, trade)
            if instrument is not None:
                return instrument

        instrument = DhanInstrumentImporter().lookup_symbol(db, trade.symbol)
        if instrument is not None and self._instrument_matches_trade(instrument, trade):
            return instrument
        return instrument if not self._has_option_contract_fields(trade) else None

    async def _tick_for_trade(self, trade: PaperTrade, instrument: InstrumentMaster | None) -> dict[str, Any]:
        feed = get_live_feed_service()
        if instrument is not None:
            by_security = await feed.tick_by_security_id(instrument.security_id)
            if by_security.get("ok") and _usable_ltp((by_security.get("tick") or {}).get("ltp")) is not None:
                return by_security
        by_symbol = await feed.tick_by_symbol(trade.symbol)
        if by_symbol.get("ok") and _usable_ltp((by_symbol.get("tick") or {}).get("ltp")) is None:
            return {"ok": False, "status": "INVALID_LTP", "message": "Live tick LTP is missing or non-positive."}
        if by_symbol.get("ok") and instrument is not None:
            tick = by_symbol.get("tick") or {}
            if str(tick.get("security_id")) != str(instrument.security_id):
                return {"ok": False, "status": "STALE_SYMBOL_MAPPING", "message": "Symbol maps to an older security id without usable LTP."}
        return by_symbol

    async def _rest_ltp_for_trade(self, instrument: InstrumentMaster) -> float | None:
        cache_key = f"{instrument.segment}:{instrument.security_id}"
        now = monotonic()
        cached = self._rest_ltp_cache.get(cache_key)
        if cached and now - cached[0] <= max(3, settings.live_paper_mtm_interval_seconds):
            return cached[1]
        response = await DhanDataAdapter().get_ltp({instrument.segment: [instrument.security_id]})
        if not response.get("ok"):
            return None
        for item in response.get("normalized") or []:
            if str(item.get("security_id")) != str(instrument.security_id):
                continue
            ltp = _safe_float(item.get("ltp"))
            if ltp is not None and ltp > 0:
                self._rest_ltp_cache[cache_key] = (now, ltp)
                return ltp
        return None

    def _lookup_option_contract(self, db: Session, trade: PaperTrade) -> InstrumentMaster | None:
        from datetime import date
        from sqlalchemy import select
        from app.models.instrument import InstrumentMaster

        expiry_value = trade.expiry
        try:
            expiry_date = date.fromisoformat(str(expiry_value)) if expiry_value else None
        except ValueError:
            expiry_date = None
        if expiry_date is None:
            return None
        return db.scalar(
            select(InstrumentMaster)
            .where(
                InstrumentMaster.source.in_(["DHAN_COMPACT", "DHAN_DETAILED"]),
                InstrumentMaster.underlying_symbol == (trade.underlying or "").upper(),
                InstrumentMaster.expiry == expiry_date,
                InstrumentMaster.strike == trade.strike,
                InstrumentMaster.option_type == trade.option_type,
            )
            .order_by(InstrumentMaster.source, InstrumentMaster.trading_symbol)
            .limit(1)
        )

    def _has_option_contract_fields(self, trade: PaperTrade) -> bool:
        return bool(trade.underlying and trade.expiry and trade.strike and trade.option_type)

    def _instrument_matches_trade(self, instrument: InstrumentMaster, trade: PaperTrade) -> bool:
        if not self._has_option_contract_fields(trade):
            return True
        try:
            from datetime import date

            expiry = date.fromisoformat(str(trade.expiry))
        except ValueError:
            return False
        return (
            instrument.underlying_symbol == (trade.underlying or "").upper()
            and instrument.expiry == expiry
            and _safe_float(instrument.strike) == _safe_float(trade.strike)
            and instrument.option_type == trade.option_type
        )

    def _maybe_stale_exit(self, db: Session, trade: PaperTrade, state: dict[str, Any]) -> dict[str, Any] | None:
        last_mtm = state.get("last_mtm_at")
        if not settings.live_paper_auto_exit_on_stale_data or not last_mtm or trade.current_price is None:
            return None
        if (datetime.now(timezone.utc) - last_mtm).total_seconds() < settings.live_paper_stale_exit_seconds:
            return None
        PaperEngine().close_trade(trade, trade.current_price, "DATA_STALE_EXIT")
        AuditLogger().log(
            db,
            "LIVE_PAPER_EXIT_CREATED",
            f"Live paper simulator exited stale paper trade {trade.id}.",
            severity="WARNING",
            source="LIVE_PAPER",
            entity_type="PaperTrade",
            entity_id=trade.id,
            payload={"symbol": trade.symbol, "exit_price": trade.current_price},
            commit=False,
        )
        return self.snapshot(trade, trade.current_price, state, action="DATA_STALE_EXIT")

    def _holding_minutes(self, trade: PaperTrade) -> float:
        entry = trade.entry_time
        if entry.tzinfo is None:
            entry = entry.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - entry).total_seconds() / 60

    def _event_for_exit(self, exit_reason: str) -> str:
        return {
            "STOP_LOSS_HIT": "LIVE_PAPER_STOP_LOSS_HIT",
            "TARGET_HIT": "LIVE_PAPER_TARGET_HIT",
            "TARGET_2_HIT": "LIVE_PAPER_TARGET_HIT",
            "TRAILING_STOP_HIT": "LIVE_PAPER_TRAILING_STOP_HIT",
            "BREAKEVEN_STOP_HIT": "LIVE_PAPER_BREAKEVEN_STOP_HIT",
            "NO_PROGRESS_EXIT": "LIVE_PAPER_NO_PROGRESS_EXIT",
            "OPTION_MOMENTUM_FADE_EXIT": "LIVE_PAPER_OPTION_MOMENTUM_FADE_EXIT",
            "TIME_EXIT": "LIVE_PAPER_TIME_EXIT",
            "MARKET_CLOSE_EXIT": "LIVE_PAPER_MARKET_CLOSE_EXIT",
            "DATA_STALE_EXIT": "LIVE_PAPER_DATA_STALE_EXIT",
            "KILL_SWITCH_EXIT": "LIVE_PAPER_KILL_SWITCH_EXIT",
        }.get(exit_reason, "LIVE_PAPER_EXIT_CREATED")

    def _audit_mtm_throttled(self, db: Session, trade: PaperTrade, current_ltp: float, state: dict[str, Any]) -> None:
        now = datetime.now(timezone.utc)
        last = state.get("last_mtm_audit_at")
        if isinstance(last, datetime) and (now - last).total_seconds() < 60:
            return
        state["last_mtm_audit_at"] = now
        AuditLogger().log(
            db,
            "LIVE_PAPER_MTM_UPDATED",
            f"Live paper MTM updated for trade {trade.id}.",
            source="LIVE_PAPER",
            entity_type="PaperTrade",
            entity_id=trade.id,
            payload={"symbol": trade.symbol, "current_ltp": current_ltp, "unrealized_pnl": trade.unrealized_pnl},
            commit=False,
        )

    def _latest_persisted_tick(self, db: Session, symbol: str, security_id: str | None = None) -> dict[str, Any] | None:
        normalized = symbol.strip().upper()
        if security_id:
            tick = db.scalar(
                select(LiveTick)
                .where(LiveTick.security_id == str(security_id))
                .where(LiveTick.ltp.is_not(None))
                .where(LiveTick.ltp > 0)
                .order_by(LiveTick.received_at.desc())
                .limit(1)
            )
        else:
            tick = None
        if tick is None and not security_id:
            tick = db.scalar(
                select(LiveTick)
                .where(LiveTick.symbol == normalized)
                .where(LiveTick.ltp.is_not(None))
                .where(LiveTick.ltp > 0)
                .order_by(LiveTick.received_at.desc())
                .limit(1)
            )
        if tick is None:
            return None
        return {
            "source": tick.source,
            "exchange_segment": tick.exchange_segment,
            "security_id": tick.security_id,
            "symbol": tick.symbol,
            "ltp": tick.ltp,
            "volume": tick.volume,
            "open_interest": tick.open_interest,
            "timestamp": tick.timestamp.isoformat() if tick.timestamp else None,
            "received_at": tick.received_at.isoformat() if tick.received_at else None,
        }


def _safe_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _usable_ltp(value: Any) -> float | None:
    ltp = _safe_float(value)
    return ltp if ltp is not None and ltp > 0 else None


def _parse_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
        except ValueError:
            return None
    return None


def _distance(a: Any, b: Any) -> float | None:
    left = _safe_float(a)
    right = _safe_float(b)
    if left is None or right is None:
        return None
    return round(left - right, 2)


live_paper_mtm_service = LivePaperMtmService()


def get_live_paper_mtm_service() -> LivePaperMtmService:
    return live_paper_mtm_service
