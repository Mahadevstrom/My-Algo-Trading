import asyncio
from collections import Counter, deque
from datetime import datetime, time, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.audit.audit_logger import AuditLogger
from app.config import settings
from app.db.database import SessionLocal
from app.engine.paper_engine import PaperEngine, PaperTradeBlockedError
from app.engine.signal_engine_v2 import get_signal_engine_v2
from app.models.trade import Direction, InstrumentType, OptionType, PaperTrade, PaperTradeCreate, TradeResult
from app.risk.kill_switch import KillSwitch
from app.schemas.live_paper import LivePaperEvaluateRequest, LivePaperStartRequest, LivePaperStopRequest
from app.schemas.signal_v2 import SignalV2GenerateRequest
from app.services.live_feed_service import get_live_feed_service
from app.services.live_paper_mtm_service import SIMULATOR_SOURCE, get_live_paper_mtm_service
from app.services.session_gate_service import get_session_gate_service
from app.utils.market_session import india_market_session


class LivePaperSimulatorService:
    def __init__(self) -> None:
        self.running = False
        self.underlying = settings.live_paper_underlying
        self.started_at: datetime | None = None
        self.stopped_at: datetime | None = None
        self.last_signal_check_at: datetime | None = None
        self.last_mtm_at: datetime | None = None
        self.last_error: str | None = None
        self.simulator_cycle_count = 0
        self.rejected_signal_count = 0
        self.rejections: deque[dict[str, Any]] = deque(maxlen=500)
        self._task: asyncio.Task | None = None
        self._last_entry_at: datetime | None = None
        self._last_stop_loss_at: datetime | None = None
        self._tracked_candidate_security_ids: set[str] = set()
        self._tracked_candidate_symbols: dict[str, str] = {}

    async def status(self, db: Session) -> dict[str, Any]:
        open_trades = self._open_trades(db)
        closed_today = self._closed_today(db)
        realized = self._realized_today(db)
        unrealized = sum((trade.unrealized_pnl or 0.0) for trade in open_trades)
        capital = self._capital_snapshot(db)
        session_gate = get_session_gate_service().decision()
        return {
            "enabled": settings.enable_live_paper_simulator,
            "running": self.running,
            "mode": settings.trading_mode,
            "underlying": self.underlying,
            "active_symbols": sorted({trade.underlying or trade.symbol for trade in open_trades}),
            "active_option_symbols": sorted({trade.symbol for trade in open_trades}),
            "tracked_candidate_option_symbols": sorted(self._tracked_candidate_symbols.values()),
            "started_at": self.started_at,
            "stopped_at": self.stopped_at,
            "last_signal_check_at": self.last_signal_check_at,
            "last_mtm_at": self.last_mtm_at,
            "last_error": self.last_error,
            "open_paper_trade_count": len(open_trades),
            "closed_today_count": len(closed_today),
            "total_pnl_today": round(realized + unrealized, 2),
            "realized_pnl_today": round(realized, 2),
            "unrealized_pnl": round(unrealized, 2),
            "virtual_capital": capital["virtual_capital"],
            "deployed_capital": capital["deployed_capital"],
            "available_capital": capital["available_capital"],
            "equity_value": capital["equity_value"],
            "simulator_cycle_count": self.simulator_cycle_count,
            "rejected_signal_count": self.rejected_signal_count,
            "reconciliation_status": self._reconciliation_status(open_trades),
            "live_order_status": settings.safety_status["live_order_status"],
            "session_gate_enabled": settings.enable_live_paper_session_gate,
            "session_status": session_gate.session_status,
            "session_allows_paper_entry": session_gate.allow_paper_entry,
            "session_allows_paper_exit": session_gate.allow_paper_exit,
            "session_allows_square_off_review": session_gate.allow_square_off_review,
            "session_block_reason": session_gate.block_reason,
            "session_next_change": session_gate.next_session_change,
        }

    def settings_response(self) -> dict[str, Any]:
        return {
            "enabled": settings.enable_live_paper_simulator,
            "auto_start": settings.live_paper_auto_start,
            "underlying": settings.live_paper_underlying,
            "virtual_capital": settings.live_paper_virtual_capital,
            "max_open_trades": settings.live_paper_max_open_trades,
            "max_trades_per_day": settings.live_paper_max_trades_per_day,
            "max_daily_loss": settings.live_paper_max_daily_loss,
            "max_loss_per_trade": settings.live_paper_max_loss_per_trade,
            "default_qty": settings.live_paper_default_qty,
            "max_qty_per_trade": settings.max_qty_per_trade,
            "cooldown_seconds": settings.live_paper_cooldown_seconds,
            "signal_check_interval_seconds": settings.live_paper_signal_check_interval_seconds,
            "mtm_interval_seconds": settings.live_paper_mtm_interval_seconds,
            "require_data_quality_ok": settings.live_paper_require_data_quality_ok,
            "allow_warning_data_quality": settings.live_paper_allow_warning_data_quality,
            "min_signal_score": settings.live_paper_min_signal_score,
            "market_session_only": settings.live_paper_market_session_only,
            "auto_exit_on_stale_data": settings.live_paper_auto_exit_on_stale_data,
            "stale_exit_seconds": settings.live_paper_stale_exit_seconds,
            "stop_loss_percent": settings.live_paper_stop_loss_percent,
            "target_percent": settings.live_paper_target_percent,
            "trailing_enabled": settings.live_paper_trailing_enabled,
            "trailing_activate_percent": settings.live_paper_trailing_activate_percent,
            "trailing_gap_percent": settings.live_paper_trailing_gap_percent,
            "time_exit_minutes": settings.live_paper_time_exit_minutes,
            "exit_before_market_close_minutes": settings.live_paper_exit_before_market_close_minutes,
            "use_indstocks_cross_check": settings.live_paper_use_indstocks_cross_check,
            "require_indstocks_confirmation": settings.live_paper_require_indstocks_confirmation,
            "session_gate_enabled": settings.enable_live_paper_session_gate,
            "block_entries_outside_session": settings.live_paper_block_entries_outside_session,
            "allow_exits_outside_entry_session": settings.live_paper_allow_exits_outside_entry_session,
            "allow_square_off_review": settings.live_paper_allow_square_off_review,
            "live_order_status": settings.safety_status["live_order_status"],
        }

    async def start(self, db: Session, payload: LivePaperStartRequest) -> dict[str, Any]:
        if not settings.enable_live_paper_simulator:
            return {"ok": False, "status": "SIMULATOR_DISABLED", "message": "Live paper simulator is disabled by config."}
        safety = self._safety_gate(db)
        if not safety["approved"]:
            return {"ok": False, "status": "SAFETY_REJECTED", "message": "Live paper simulator start rejected.", **safety}
        if self.running:
            return {"ok": True, "status": "ALREADY_RUNNING", "message": "Live paper simulator is already running.", "state": await self.status(db)}
        self.running = True
        self.underlying = payload.underlying
        self.started_at = datetime.now(timezone.utc)
        self.stopped_at = None
        self.last_error = None
        AuditLogger().log(
            db,
            "LIVE_PAPER_SIMULATOR_STARTED",
            "Live paper simulator started.",
            source="LIVE_PAPER",
            payload={"underlying": self.underlying, "dry_run": payload.dry_run},
        )
        if not payload.dry_run:
            self._task = asyncio.create_task(self._run_loop())
        return {"ok": True, "status": "STARTED", "message": "Live paper simulator started.", "state": await self.status(db)}

    async def stop(self, db: Session, payload: LivePaperStopRequest | None = None) -> dict[str, Any]:
        payload = payload or LivePaperStopRequest()
        self.running = False
        self.stopped_at = datetime.now(timezone.utc)
        if self._task:
            self._task.cancel()
            self._task = None
        exits = []
        if payload.close_open_paper_trades:
            for trade in self._open_trades(db):
                exit_price = payload.exit_price or trade.current_price or trade.entry_price
                PaperEngine().close_trade(trade, exit_price, "MANUAL_EXIT")
                exits.append({"trade_id": trade.id, "exit_price": exit_price})
            db.commit()
        AuditLogger().log(
            db,
            "LIVE_PAPER_SIMULATOR_STOPPED",
            "Live paper simulator stopped.",
            source="LIVE_PAPER",
            payload={"closed_open_paper_trades": payload.close_open_paper_trades, "exits": exits},
        )
        return {"ok": True, "status": "STOPPED", "message": "Live paper simulator stopped.", "exits": exits}

    async def evaluate_once(self, db: Session, payload: LivePaperEvaluateRequest) -> dict[str, Any]:
        self.simulator_cycle_count += 1
        self.last_signal_check_at = datetime.now(timezone.utc)
        signal = await get_signal_engine_v2().generate(
            db,
            SignalV2GenerateRequest(
                underlying=payload.underlying,
                use_indstocks_cross_check=settings.live_paper_use_indstocks_cross_check,
            ),
        )
        shadow_option_chain_engine = None
        shadow_context_classifier = None
        shadow_market_structure_engine = None
        shadow_nifty_momentum_engine = None
        shadow_decision_engine_v2 = None
        try:
            from app.engine.specialist.option_chain_engine import run_option_chain_shadow

            shadow_record = await run_option_chain_shadow(
                db=db,
                underlying=payload.underlying,
                signal_id=str(getattr(signal, "id", "")) if getattr(signal, "id", None) is not None else None,
                signal_v2_decision=getattr(signal, "decision", None),
            )
            if shadow_record is not None:
                shadow_option_chain_engine = {
                    "evaluation_id": shadow_record.evaluation_id,
                    "engine_name": shadow_record.engine_name,
                    "verdict": shadow_record.verdict,
                    "score": shadow_record.score,
                }
        except Exception as _e:
            import logging as _logging

            _logging.getLogger(__name__).warning(f"Shadow OC engine logging failed (non-fatal): {_e}")
        try:
            from app.engine.context.context_classifier import run_context_shadow

            context_record = run_context_shadow(
                db=db,
                underlying=payload.underlying,
                signal_result=signal,
                signal_id=str(getattr(signal, "id", "")) if getattr(signal, "id", None) is not None else None,
                signal_v2_decision=getattr(signal, "decision", None),
            )
            if context_record is not None:
                shadow_context_classifier = {
                    "evaluation_id": context_record.evaluation_id,
                    "context_type": context_record.context_type,
                    "context_confidence": context_record.context_confidence,
                    "confidence_modifier": context_record.confidence_modifier,
                }
        except Exception as _ctx_e:
            import logging as _logging2

            _logging2.getLogger(__name__).warning(f"Context classification shadow logging failed (non-fatal): {_ctx_e}")
        try:
            from app.engine.specialist.market_structure_engine import run_market_structure_shadow

            ms_record = await run_market_structure_shadow(
                db=db,
                underlying=payload.underlying,
                signal_id=str(getattr(signal, "id", "")) if getattr(signal, "id", None) is not None else None,
                signal_v2_decision=getattr(signal, "decision", None),
            )
            if ms_record is not None:
                shadow_market_structure_engine = {
                    "evaluation_id": ms_record.evaluation_id,
                    "engine_name": ms_record.engine_name,
                    "verdict": ms_record.verdict,
                    "score": ms_record.score,
                }
        except Exception as _ms_e:
            import logging as _logging3

            _logging3.getLogger(__name__).warning(f"MS engine shadow logging failed (non-fatal): {_ms_e}")
        try:
            from app.engine.specialist.nifty_momentum_engine import run_nifty_momentum_shadow

            momentum_record = await run_nifty_momentum_shadow(
                db=db,
                underlying=payload.underlying,
                signal_id=str(getattr(signal, "id", "")) if getattr(signal, "id", None) is not None else None,
                signal_v2_decision=getattr(signal, "decision", None),
            )
            if momentum_record is not None:
                shadow_nifty_momentum_engine = {
                    "evaluation_id": momentum_record.evaluation_id,
                    "engine_name": momentum_record.engine_name,
                    "verdict": momentum_record.verdict,
                    "score": momentum_record.score,
                }
        except Exception as _mom_e:
            import logging as _logging4

            _logging4.getLogger(__name__).warning(f"NIFTY momentum shadow logging failed (non-fatal): {_mom_e}")
        try:
            from app.engine.setup.setup_shadow_runner import run_setup_matcher_shadow

            run_setup_matcher_shadow(
                db=db,
                signal_id=str(getattr(signal, "id", "")) if getattr(signal, "id", None) is not None else None,
                signal_v2_decision=getattr(signal, "decision", None),
            )
        except Exception as _setup_e:
            import logging as _logging5

            _logging5.getLogger(__name__).warning(f"Setup matcher shadow logging failed (non-fatal): {_setup_e}")
        try:
            from app.engine.decision.decision_engine_v2 import run_decision_engine_v2_shadow

            decision_record = run_decision_engine_v2_shadow(
                db=db,
                signal_id=str(getattr(signal, "id", "")) if getattr(signal, "id", None) is not None else None,
                signal_v2_decision=getattr(signal, "decision", None),
            )
            if decision_record is not None:
                shadow_decision_engine_v2 = {
                    "evaluation_id": decision_record.evaluation_id,
                    "decision": decision_record.decision,
                    "confidence": decision_record.confidence,
                    "agrees_with_signal_v2": decision_record.agrees_with_signal_v2,
                    "advisory_mode": decision_record.advisory_mode,
                }
        except Exception as _de_e:
            import logging as _logging6

            _logging6.getLogger(__name__).warning(f"Decision Engine v2 shadow logging failed (non-fatal): {_de_e}")
        candidate_tracking = await self._ensure_selected_option_tracked(db, signal)
        decision = self._entry_decision(db, signal, payload)
        AuditLogger().log(
            db,
            "LIVE_PAPER_EVALUATION_RUN",
            "Live paper simulator evaluation cycle completed.",
            source="LIVE_PAPER",
            payload={
                "signal_decision": signal.decision,
                "entry_allowed": decision["entry_allowed"],
                "reason": decision.get("rejection_reason"),
                "candidate_tracking": candidate_tracking,
                "shadow_option_chain_engine": shadow_option_chain_engine,
                "shadow_context_classifier": shadow_context_classifier,
                "shadow_market_structure_engine": shadow_market_structure_engine,
                "shadow_nifty_momentum_engine": shadow_nifty_momentum_engine,
                "shadow_decision_engine_v2": shadow_decision_engine_v2,
            },
        )
        if not decision["entry_allowed"]:
            self._reject(db, payload.underlying, decision["rejection_reason"], decision)
            return {"ok": True, "signal": signal.model_dump(mode="json"), "entry": decision}
        if payload.dry_run:
            return {"ok": True, "signal": signal.model_dump(mode="json"), "entry": {**decision, "paper_trade_created": False, "dry_run": True}}
        if not self.running:
            decision = {**decision, "entry_allowed": False, "rejection_reason": "SIMULATOR_NOT_RUNNING", "message": "Simulator must be running to create paper trades."}
            self._reject(db, payload.underlying, "SIMULATOR_NOT_RUNNING", decision)
            return {"ok": True, "signal": signal.model_dump(mode="json"), "entry": decision}
        try:
            birth_cert = getattr(signal, "birth_certificate", None)
            if birth_cert is None and isinstance(signal, dict):
                birth_cert = signal.get("birth_certificate")
            trade = self._create_paper_trade(db, signal, birth_certificate=birth_cert, context_record=shadow_context_classifier)
        except PaperTradeBlockedError as exc:
            decision = {**decision, "entry_allowed": False, "rejection_reason": "PAPER_ENGINE_BLOCKED", "reasons": exc.reasons}
            self._reject(db, payload.underlying, "PAPER_ENGINE_BLOCKED", decision)
            return {"ok": True, "signal": signal.model_dump(mode="json"), "entry": decision}
        get_live_paper_mtm_service().register_entry(trade)
        await get_live_paper_mtm_service().ensure_trade_symbol_subscribed(db, trade)
        self._last_entry_at = datetime.now(timezone.utc)
        AuditLogger().log(
            db,
            "LIVE_PAPER_ENTRY_CREATED",
            f"Live paper simulator created paper trade {trade.id}.",
            source="LIVE_PAPER",
            entity_type="PaperTrade",
            entity_id=trade.id,
            payload={"symbol": trade.symbol, "entry_price": trade.entry_price, "signal_score": signal.score},
        )
        return {
            "ok": True,
            "signal": signal.model_dump(mode="json"),
            "entry": {**decision, "paper_trade_created": True, "paper_trade_id": trade.id},
        }

    async def mtm(self, db: Session) -> dict[str, Any]:
        result = await get_live_paper_mtm_service().mark_to_market(db)
        self.last_mtm_at = datetime.now(timezone.utc)
        for item in result.get("items", []):
            if item.get("action") == "STOP_LOSS_HIT":
                self._last_stop_loss_at = datetime.now(timezone.utc)
        return result

    async def open_trades(self, db: Session) -> dict[str, Any]:
        await self.mtm(db)
        items = [
            get_live_paper_mtm_service().snapshot(trade)
            for trade in self._open_trades(db)
        ]
        return {"ok": True, "count": len(items), "items": items}

    def closed_trades(self, db: Session) -> dict[str, Any]:
        trades = list(
            db.scalars(
                select(PaperTrade)
                .where(PaperTrade.data_source == SIMULATOR_SOURCE, PaperTrade.result != TradeResult.OPEN.value)
                .order_by(PaperTrade.exit_time.desc().nullslast(), PaperTrade.entry_time.desc())
            )
        )
        return {"ok": True, "count": len(trades), "items": [_trade_json(trade) for trade in trades]}

    def performance(self, db: Session) -> dict[str, Any]:
        trades = list(db.scalars(select(PaperTrade).where(PaperTrade.data_source == SIMULATOR_SOURCE).order_by(PaperTrade.entry_time)))
        closed = [trade for trade in trades if trade.result != TradeResult.OPEN.value]
        wins = [trade for trade in closed if trade.result == "WIN"]
        losses = [trade for trade in closed if trade.result == "LOSS"]
        realized = sum(trade.pnl or 0.0 for trade in closed)
        unrealized = sum(trade.unrealized_pnl or 0.0 for trade in trades if trade.result == TradeResult.OPEN.value)
        capital = self._capital_snapshot(db)
        exit_reason_counts = dict(Counter((trade.exit_reason or "UNKNOWN") for trade in closed))
        result_counts = dict(Counter((trade.result or "UNKNOWN") for trade in trades))
        return {
            "total_trades": len(trades),
            "open_trades": len([trade for trade in trades if trade.result == TradeResult.OPEN.value]),
            "closed_trades": len(closed),
            "wins": len(wins),
            "losses": len(losses),
            "result_counts": result_counts,
            "exit_reason_counts": exit_reason_counts,
            "win_rate": round(len(wins) / len(closed) * 100, 2) if closed else 0.0,
            "realized_pnl": round(realized, 2),
            "unrealized_pnl": round(unrealized, 2),
            "total_pnl": round(realized + unrealized, 2),
            "virtual_capital": capital["virtual_capital"],
            "deployed_capital": capital["deployed_capital"],
            "available_capital": capital["available_capital"],
            "equity_value": capital["equity_value"],
            "average_holding_minutes": _avg([trade.holding_minutes for trade in closed if trade.holding_minutes is not None]),
            "rejection_counts": dict(Counter(item["reason"] for item in self.rejections)),
        }

    def recent_rejections(self) -> dict[str, Any]:
        items = list(self.rejections)
        return {"ok": True, "count": len(items), "items": list(reversed(items))}

    def lifecycle(self, db: Session) -> dict[str, Any]:
        trades = list(
            db.scalars(
                select(PaperTrade)
                .where(PaperTrade.data_source == SIMULATOR_SOURCE)
                .order_by(PaperTrade.entry_time.desc())
                .limit(100)
            )
        )
        open_trades = [trade for trade in trades if trade.result == TradeResult.OPEN.value]
        closed_trades = [trade for trade in trades if trade.result != TradeResult.OPEN.value]
        events: list[dict[str, Any]] = []
        for trade in trades:
            events.append(
                {
                    "trade_id": trade.id,
                    "event": "ENTRY",
                    "symbol": trade.symbol,
                    "time": trade.entry_time.isoformat() if trade.entry_time else None,
                    "price": trade.entry_price,
                    "pnl": trade.pnl or trade.unrealized_pnl or 0,
                    "status": trade.status,
                    "reason": trade.signal_type or "PAPER_ENTRY",
                }
            )
            if trade.exit_time:
                events.append(
                    {
                        "trade_id": trade.id,
                        "event": "EXIT",
                        "symbol": trade.symbol,
                        "time": trade.exit_time.isoformat(),
                        "price": trade.exit_price,
                        "pnl": trade.pnl or 0,
                        "status": trade.result,
                        "reason": trade.exit_reason or "EXIT",
                    }
                )
        events.sort(key=lambda item: item.get("time") or "", reverse=True)
        option_health = [get_live_paper_mtm_service().snapshot(trade) for trade in open_trades]
        return {
            "ok": True,
            "status": "OK",
            "reconciliation_status": self._reconciliation_status(open_trades),
            "open_count": len(open_trades),
            "closed_count": len(closed_trades),
            "exit_reason_counts": dict(Counter((trade.exit_reason or "UNKNOWN") for trade in closed_trades)),
            "result_counts": dict(Counter((trade.result or "UNKNOWN") for trade in trades)),
            "option_health": option_health,
            "events": events[:60],
            "warnings": self._lifecycle_warnings(open_trades),
            "paper_only": True,
            "live_order_status": settings.safety_status["live_order_status"],
        }

    async def manual_exit(self, db: Session, trade_id: int, exit_price: float | None, exit_reason: str) -> dict[str, Any]:
        trade = db.get(PaperTrade, trade_id)
        if trade is None or trade.data_source != SIMULATOR_SOURCE:
            return {"ok": False, "status": "PAPER_TRADE_NOT_FOUND", "message": "Simulator paper trade not found."}
        if trade.result != TradeResult.OPEN.value:
            return {"ok": False, "status": "PAPER_TRADE_ALREADY_CLOSED", "message": "Simulator paper trade is already closed."}
        final_price = exit_price or trade.current_price or trade.entry_price
        PaperEngine().close_trade(trade, final_price, exit_reason)
        AuditLogger().log(
            db,
            "LIVE_PAPER_EXIT_CREATED",
            f"Simulator paper trade {trade.id} manually exited.",
            source="LIVE_PAPER",
            entity_type="PaperTrade",
            entity_id=trade.id,
            payload={"exit_price": final_price, "exit_reason": exit_reason, "pnl": trade.pnl},
            commit=False,
        )
        db.commit()
        db.refresh(trade)
        return {"ok": True, "trade": _trade_json(trade)}

    async def reset_session(self, db: Session) -> dict[str, Any]:
        self.rejections.clear()
        self.rejected_signal_count = 0
        self.simulator_cycle_count = 0
        self._last_entry_at = None
        self._last_stop_loss_at = None
        AuditLogger().log(db, "LIVE_PAPER_SIMULATOR_STOPPED", "Live paper simulator in-memory session counters reset.", source="LIVE_PAPER")
        return {"ok": True, "status": "RESET", "message": "Live paper simulator in-memory session state reset. DB records were not deleted."}

    async def auto_start_if_configured(self) -> None:
        if not (settings.enable_live_paper_simulator and settings.live_paper_auto_start):
            return
        with SessionLocal() as db:
            await self.start(db, LivePaperStartRequest(underlying=settings.live_paper_underlying))

    async def shutdown(self) -> None:
        self.running = False
        if self._task:
            self._task.cancel()
            self._task = None

    async def _run_loop(self) -> None:
        last_signal = datetime.min.replace(tzinfo=timezone.utc)
        last_mtm = datetime.min.replace(tzinfo=timezone.utc)
        while self.running:
            try:
                now = datetime.now(timezone.utc)
                with SessionLocal() as db:
                    if (now - last_signal).total_seconds() >= settings.live_paper_signal_check_interval_seconds:
                        await self.evaluate_once(db, LivePaperEvaluateRequest(underlying=self.underlying, dry_run=False))
                        last_signal = now
                    if (now - last_mtm).total_seconds() >= settings.live_paper_mtm_interval_seconds:
                        await self.mtm(db)
                        last_mtm = now
                await asyncio.sleep(1)
            except asyncio.CancelledError:
                break
            except Exception as exc:
                self.last_error = f"{type(exc).__name__}: {exc}"
                with SessionLocal() as db:
                    AuditLogger().log(db, "LIVE_PAPER_ERROR", "Live paper simulator loop error.", severity="ERROR", source="LIVE_PAPER", payload={"error": self.last_error})
                await asyncio.sleep(5)

    def _entry_decision(self, db: Session, signal, payload: LivePaperEvaluateRequest) -> dict[str, Any]:
        safety = self._safety_gate(db)
        if not safety["approved"]:
            return {"entry_allowed": False, "rejection_reason": safety["reasons"][0], "risk_status": safety}
        session_decision = get_session_gate_service().decision()
        if (
            settings.enable_live_paper_session_gate
            and settings.live_paper_block_entries_outside_session
            and not session_decision.allow_paper_entry
        ):
            return {
                "entry_allowed": False,
                "rejection_reason": "SESSION_GATE_BLOCKED",
                "session_gate": session_decision.model_dump(mode="json"),
                "session_status": session_decision.session_status,
                "block_reason": session_decision.block_reason,
                "caution_reason": session_decision.caution_reason,
                "next_session_change": session_decision.next_session_change,
                "message": f"Session gate blocked live-paper entry: {session_decision.block_reason or session_decision.session_status}.",
            }
        if not payload.dry_run and not settings.enable_live_paper_simulator:
            return {"entry_allowed": False, "rejection_reason": "SIMULATOR_DISABLED"}
        if signal.decision not in {"BUY_CALL", "BUY_PUT"}:
            return {**self._signal_rejection_context(signal), "entry_allowed": False, "rejection_reason": "SIGNAL_V2_NO_TRADE"}
        if signal.score < settings.live_paper_min_signal_score:
            return {**self._signal_rejection_context(signal), "entry_allowed": False, "rejection_reason": "SIGNAL_SCORE_TOO_LOW"}
        if settings.live_paper_require_data_quality_ok and not signal.data_quality_gate_passed:
            return {**self._signal_rejection_context(signal), "entry_allowed": False, "rejection_reason": "DATA_QUALITY_FAILED"}
        if (
            not settings.enable_live_paper_session_gate
            and settings.live_paper_market_session_only
            and not india_market_session()["is_market_open"]
        ):
            return {"entry_allowed": False, "rejection_reason": "MARKET_CLOSED"}
        if signal.selected_option is None:
            return {**self._signal_rejection_context(signal), "entry_allowed": False, "rejection_reason": "NO_VALID_OPTION"}
        if signal.selected_option.ltp is None or signal.selected_option.ltp <= 0:
            return {**self._signal_rejection_context(signal), "entry_allowed": False, "rejection_reason": "NO_LTP_FOR_OPTION"}
        qty = max(1, min(settings.live_paper_default_qty, settings.max_qty_per_trade))
        required_capital = round(float(signal.selected_option.ltp) * qty, 2)
        capital = self._capital_snapshot(db)
        if required_capital > capital["available_capital"]:
            return {
                "entry_allowed": False,
                "rejection_reason": "INSUFFICIENT_PAPER_CAPITAL",
                "required_capital": required_capital,
                "available_capital": capital["available_capital"],
                "virtual_capital": capital["virtual_capital"],
            }
        duplicate = self._duplicate_open_trade(db, signal.selected_option.trading_symbol)
        if duplicate:
            return {"entry_allowed": False, "rejection_reason": "DUPLICATE_TRADE", "paper_trade_id": duplicate.id}
        if len(self._open_trades(db)) >= settings.live_paper_max_open_trades:
            return {"entry_allowed": False, "rejection_reason": "MAX_OPEN_TRADES_REACHED"}
        if self._today_trade_count(db) >= settings.live_paper_max_trades_per_day:
            return {"entry_allowed": False, "rejection_reason": "MAX_DAILY_TRADES_REACHED"}
        if self._realized_today(db) <= -abs(settings.live_paper_max_daily_loss):
            return {"entry_allowed": False, "rejection_reason": "DAILY_LOSS_LIMIT_REACHED"}
        if self._cooldown_active():
            return {"entry_allowed": False, "rejection_reason": "COOLDOWN_ACTIVE"}
        return {
            "entry_allowed": True,
            "rejection_reason": None,
            "signal_score": signal.score,
            "selected_option": signal.selected_option.model_dump(mode="json"),
            "paper_trade_created": False,
        }

    async def _ensure_selected_option_tracked(self, db: Session, signal) -> dict[str, Any]:
        option = getattr(signal, "selected_option", None)
        if option is None:
            return {"ok": True, "status": "NO_SELECTED_OPTION"}
        security_id = str(getattr(option, "security_id", "") or "").strip()
        if not security_id:
            return {"ok": False, "status": "NO_SELECTED_OPTION_SECURITY_ID"}
        if security_id in self._tracked_candidate_security_ids:
            return {
                "ok": True,
                "status": "ALREADY_TRACKING",
                "security_id": security_id,
                "symbol": self._tracked_candidate_symbols.get(security_id),
            }
        if not settings.enable_dhan_websocket:
            return {"ok": False, "status": "WEBSOCKET_DISABLED", "security_id": security_id}

        symbol = getattr(option, "trading_symbol", None) or f"{getattr(option, 'underlying', 'OPTION')}-{security_id}"
        item = {
            "exchange_segment": getattr(option, "exchange_segment", None) or "NSE_FNO",
            "security_id": security_id,
            "symbol": symbol,
        }
        result = await get_live_feed_service().client.subscribe([item])
        self._tracked_candidate_security_ids.add(security_id)
        self._tracked_candidate_symbols[security_id] = symbol
        AuditLogger().log(
            db,
            "LIVE_PAPER_CANDIDATE_OPTION_TRACKED",
            "Selected option candidate subscribed for Signal v2 premium-candle warmup.",
            source="LIVE_PAPER",
            payload={"item": item, "result": result, "signal_id": getattr(signal, "id", None), "signal_decision": getattr(signal, "decision", None)},
        )
        return {"ok": True, "status": result.get("status", "SUBSCRIBE_REQUESTED"), "item": item}

    def _create_paper_trade(self, db: Session, signal, birth_certificate: dict = None, context_record: dict | None = None) -> PaperTrade:
        option = signal.selected_option
        entry = float(option.ltp)
        stop_loss = round(entry * (1 - settings.live_paper_stop_loss_percent / 100), 2)
        target_1, target_2 = self._target_plan_prices(signal, entry)
        qty = max(1, min(settings.live_paper_default_qty, settings.max_qty_per_trade))
        max_loss = (entry - stop_loss) * qty
        if max_loss > settings.live_paper_max_loss_per_trade:
            raise PaperTradeBlockedError([f"Live paper max loss per trade exceeded: {max_loss:.2f}."])
        payload = PaperTradeCreate(
            symbol=option.trading_symbol or signal.underlying,
            instrument_type=InstrumentType.INDEX_OPTION,
            exchange="NSE",
            expiry=option.expiry,
            strike=option.strike,
            option_type=OptionType.CE if option.option_type == "CE" else OptionType.PE,
            direction=Direction.BUY,
            entry_price=entry,
            stop_loss=stop_loss,
            target_1=target_1,
            target_2=target_2,
            quantity=qty,
            signal_confidence=signal.score,
            underlying=signal.underlying,
            selected_strike=option.strike,
            strategy_score=signal.score,
            data_confidence=None,
            final_confidence=signal.score,
            chain_bias=signal.market_state.get("chain_bias"),
            signal_type=signal.decision,
            signal_reason=self._paper_signal_reason(signal),
            data_source=SIMULATOR_SOURCE,
            context_type_at_entry=(context_record or {}).get("context_type"),
            context_confidence_at_entry=(context_record or {}).get("context_confidence"),
            confidence_modifier_at_entry=(context_record or {}).get("confidence_modifier"),
        )
        trade = PaperEngine().create_trade(db, payload)

        import json
        if context_record is not None and isinstance(context_record, dict):
            trade.context_type_at_entry = context_record.get("context_type")
            trade.context_confidence_at_entry = context_record.get("context_confidence")
            trade.confidence_modifier_at_entry = context_record.get("confidence_modifier")
        if birth_certificate is not None and isinstance(birth_certificate, dict):
            trade.filter_states_json = json.dumps(birth_certificate.get("filter_states", {}))
            trade.confidence_score_at_entry = birth_certificate.get("confidence_score")
            sig_id = birth_certificate.get("signal_id")
            if sig_id is not None:
                try:
                    trade.signal_id = int(sig_id)
                except (ValueError, TypeError):
                    pass
            trade.regime_at_entry = birth_certificate.get("regime", "UNKNOWN") or "UNKNOWN"
            trade.session_window_at_entry = birth_certificate.get("session_window", "UNKNOWN") or "UNKNOWN"
            trade.oi_direction_at_entry = birth_certificate.get("oi_direction", "UNKNOWN") or "UNKNOWN"
            trade.market_flow_score_at_entry = birth_certificate.get("market_flow_score")
            trade.pcr_at_entry = birth_certificate.get("pcr")
            trade.spread_pct_at_entry = birth_certificate.get("spread_pct")
            trade.filters_passed_count = birth_certificate.get("filters_passed_count")
            trade.birth_cert_version = "1.0"
            db.commit()
            db.refresh(trade)
        elif context_record:
            db.commit()
            db.refresh(trade)

        return trade

    def _target_plan_prices(self, signal, entry: float) -> tuple[float, float]:
        target_plan = ((signal.market_state or {}).get("target_plan") or {})
        target_1 = _positive_target(target_plan.get("option_target_1"), entry)
        target_2 = _positive_target(target_plan.get("option_target_2"), entry)
        if target_1 is None:
            target_1 = round(entry * (1 + (settings.live_paper_target_percent * 0.50) / 100), 2)
        if target_2 is None or target_2 <= target_1:
            target_2 = round(max(entry * (1 + settings.live_paper_target_percent / 100), target_1 * 1.12), 2)
        return round(target_1, 2), round(target_2, 2)

    def _paper_signal_reason(self, signal) -> str:
        market_state = signal.market_state or {}
        context_parts = [
            "LIVE_PAPER_SIMULATOR",
            "signal_version=v2",
            "execution_type=SIMULATED",
            "no_broker_order=true",
            f"regime={(market_state.get('regime') or {}).get('regime', 'UNKNOWN')}",
            f"required_score={getattr(signal, 'required_score', None) or settings.live_paper_min_signal_score}",
            f"support={market_state.get('support_strike')}",
            f"resistance={market_state.get('resistance_strike')}",
            f"vwap_above={market_state.get('vwap_above')}",
            f"rsi={market_state.get('rsi')}",
            f"adx={market_state.get('adx')}",
            f"structure={(market_state.get('market_structure') or {}).get('status', 'UNKNOWN')}",
            f"retest={(market_state.get('retest_entry') or {}).get('status', 'UNKNOWN')}",
            f"entry_candle={(market_state.get('entry_candle') or {}).get('status', 'UNKNOWN')}",
            f"option_confirm={(market_state.get('option_confirmation') or {}).get('status', 'UNKNOWN')}",
            f"option_quality={(market_state.get('option_quality') or {}).get('status', 'UNKNOWN')}",
            f"trap={(market_state.get('false_breakout_trap') or {}).get('status', 'UNKNOWN')}",
            f"t1={(market_state.get('target_plan') or {}).get('option_target_1', 'UNKNOWN')}",
            f"t2={(market_state.get('target_plan') or {}).get('option_target_2', 'UNKNOWN')}",
            f"chase={(market_state.get('chase_filter') or {}).get('status', 'UNKNOWN')}",
            f"location={(market_state.get('trade_location') or {}).get('status', 'UNKNOWN')}",
        ]
        return "; ".join(str(item) for item in context_parts)[:500]

    def _signal_rejection_context(self, signal) -> dict[str, Any]:
        diagnostics = signal.missed_trade_diagnostics or {}
        return {
            "signal_decision": signal.decision,
            "signal_score": signal.score,
            "required_score": getattr(signal, "required_score", None) or settings.live_paper_min_signal_score,
            "failed_checks": signal.failed_checks,
            "session_status": signal.session_status,
            "data_quality_status": signal.data_quality_status,
            "candle_warmup_status": getattr(signal, "candle_warmup_status", None),
            "candle_counts_by_timeframe": getattr(signal, "candle_counts_by_timeframe", {}),
            "required_candles_by_timeframe": getattr(signal, "required_candles_by_timeframe", {}),
            "missing_timeframes": getattr(signal, "missing_timeframes", []),
            "selected_option_present": bool(signal.selected_option),
            "selected_option_reason": getattr(signal, "selected_option_reason", None),
            "missed_trade_diagnostics": diagnostics,
        }

    def _safety_gate(self, db: Session) -> dict[str, Any]:
        reasons = []
        if not settings.is_paper_mode:
            reasons.append("TRADING_MODE_NOT_PAPER")
        if settings.allow_live_orders:
            reasons.append("ALLOW_LIVE_ORDERS_TRUE")
        if settings.enable_dhan_order_placement:
            reasons.append("ENABLE_DHAN_ORDER_PLACEMENT_TRUE")
        if settings.indstocks_enable_order_placement:
            reasons.append("INDSTOCKS_ENABLE_ORDER_PLACEMENT_TRUE")
        if KillSwitch().get_state(db).kill_switch_enabled:
            reasons.append("KILL_SWITCH_ENABLED")
        return {"approved": not reasons, "reasons": reasons, "live_order_status": settings.safety_status["live_order_status"]}

    def _reject(self, db: Session, underlying: str, reason: str, details: dict[str, Any]) -> None:
        self.rejected_signal_count += 1
        event = {"timestamp": datetime.now(timezone.utc), "underlying": underlying, "reason": reason, "details": details}
        self.rejections.append(event)
        event_type = "LIVE_PAPER_SESSION_GATE_BLOCKED" if reason == "SESSION_GATE_BLOCKED" else "LIVE_PAPER_ENTRY_REJECTED"
        if details.get("missed_trade_diagnostics"):
            AuditLogger().log(
                db,
                "LIVE_PAPER_ENTRY_REJECTED_DIAGNOSTIC",
                f"Live paper entry rejected with Signal v2 diagnostic: {reason}.",
                severity="INFO",
                source="LIVE_PAPER",
                payload=details,
            )
        AuditLogger().log(
            db,
            event_type,
            f"Live paper entry rejected: {reason}.",
            severity="INFO",
            source="LIVE_PAPER",
            payload=event,
        )

    def _open_trades(self, db: Session) -> list[PaperTrade]:
        return list(
            db.scalars(select(PaperTrade).where(PaperTrade.data_source == SIMULATOR_SOURCE, PaperTrade.result == TradeResult.OPEN.value))
        )

    def _reconciliation_status(self, open_trades: list[PaperTrade]) -> str:
        if not open_trades:
            return "NO_OPEN_TRADES"
        states = [get_live_paper_mtm_service().trade_state.get(trade.id, {}) for trade in open_trades]
        if any(state.get("data_status") == "NO_LTP" for state in states):
            return "OPTION_LTP_MISSING"
        if any(state.get("data_status") == "STALE" for state in states):
            return "STALE_LTP"
        if any(not state.get("last_mtm_at") for state in states):
            return "WAITING_FOR_MTM"
        return "OK"

    def _lifecycle_warnings(self, open_trades: list[PaperTrade]) -> list[str]:
        warnings: list[str] = []
        for trade in open_trades:
            state = get_live_paper_mtm_service().trade_state.get(trade.id, {})
            data_status = state.get("data_status", "UNKNOWN")
            if data_status in {"NO_LTP", "STALE", "UNKNOWN"}:
                warnings.append(f"Trade {trade.id} {trade.symbol}: option LTP state is {data_status}.")
            if state.get("subscription_status") in {"OPTION_INSTRUMENT_NOT_FOUND", "LIVE_FEED_DISCONNECTED"}:
                warnings.append(f"Trade {trade.id} {trade.symbol}: subscription status {state.get('subscription_status')}.")
        return warnings[:12]

    def _closed_today(self, db: Session) -> list[PaperTrade]:
        start = datetime.combine(datetime.now(timezone.utc).date(), time.min, tzinfo=timezone.utc)
        return list(
            db.scalars(
                select(PaperTrade).where(
                    PaperTrade.data_source == SIMULATOR_SOURCE,
                    PaperTrade.result != TradeResult.OPEN.value,
                    PaperTrade.entry_time >= start,
                )
            )
        )

    def _today_trade_count(self, db: Session) -> int:
        start = datetime.combine(datetime.now(timezone.utc).date(), time.min, tzinfo=timezone.utc)
        return db.scalar(select(func.count()).select_from(PaperTrade).where(PaperTrade.data_source == SIMULATOR_SOURCE, PaperTrade.entry_time >= start)) or 0

    def _realized_today(self, db: Session) -> float:
        start = datetime.combine(datetime.now(timezone.utc).date(), time.min, tzinfo=timezone.utc)
        return float(db.scalar(select(func.coalesce(func.sum(PaperTrade.pnl), 0.0)).where(PaperTrade.data_source == SIMULATOR_SOURCE, PaperTrade.entry_time >= start, PaperTrade.result != TradeResult.OPEN.value)) or 0.0)

    def _capital_snapshot(self, db: Session) -> dict[str, float]:
        open_trades = self._open_trades(db)
        deployed = sum((trade.entry_price or 0.0) * (trade.quantity or 0) for trade in open_trades)
        realized = float(
            db.scalar(
                select(func.coalesce(func.sum(PaperTrade.pnl), 0.0)).where(
                    PaperTrade.data_source == SIMULATOR_SOURCE,
                    PaperTrade.result != TradeResult.OPEN.value,
                )
            )
            or 0.0
        )
        unrealized = sum((trade.unrealized_pnl or 0.0) for trade in open_trades)
        virtual_capital = float(settings.live_paper_virtual_capital)
        equity_value = virtual_capital + realized + unrealized
        available = max(0.0, equity_value - deployed)
        return {
            "virtual_capital": round(virtual_capital, 2),
            "deployed_capital": round(deployed, 2),
            "available_capital": round(available, 2),
            "equity_value": round(equity_value, 2),
        }

    def _duplicate_open_trade(self, db: Session, symbol: str | None) -> PaperTrade | None:
        if not symbol:
            return None
        return db.scalar(select(PaperTrade).where(PaperTrade.data_source == SIMULATOR_SOURCE, PaperTrade.symbol == symbol, PaperTrade.result == TradeResult.OPEN.value).limit(1))

    def _cooldown_active(self) -> bool:
        reference = self._last_stop_loss_at or self._last_entry_at
        if reference is None:
            return False
        return (datetime.now(timezone.utc) - reference).total_seconds() < settings.live_paper_cooldown_seconds

    async def create_combo(self, db: Session, payload: Any) -> dict[str, Any]:
        # Perform safety gate checks
        safety = self._safety_gate(db)
        if not safety["approved"]:
            return {"ok": False, "status": "SAFETY_REJECTED", "message": "Manual live-paper combo entries blocked in live mode.", **safety}
            
        # Get spot price for margin estimation
        spot = 22000.0
        try:
            from app.models.candle import Candle
            latest_candle = db.scalar(
                select(Candle)
                .where(Candle.symbol == "NIFTY")
                .order_by(Candle.timestamp.desc())
                .limit(1)
            )
            if latest_candle:
                spot = float(latest_candle.close)
        except Exception:
            pass

        # Calculate Margin Requirement & Net Premium
        # Long margin = entry * qty * lot_size
        # Short margin = (spot * 0.12) * qty * lot_size
        # We apply 50% short leg margin reduction benefit if hedging legs are present!
        lot_size = 50
        has_buy = any(leg.direction == "BUY" for leg in payload.legs)
        has_sell = any(leg.direction == "SELL" for leg in payload.legs)
        is_hedged = has_buy and has_sell

        total_margin = 0.0
        net_premium = 0.0

        for leg in payload.legs:
            leg_premium = leg.entry_price * leg.quantity * lot_size
            if leg.direction == "BUY":
                total_margin += leg_premium
                net_premium += leg_premium
            else:
                short_margin = (spot * 0.12) * leg.quantity * lot_size
                if is_hedged:
                    short_margin *= 0.50 # Apply 50% margin benefit for hedged spreads
                total_margin += short_margin
                net_premium -= leg_premium

        # Capital snapshot check
        capital = self._capital_snapshot(db)
        if total_margin > capital["available_capital"]:
            return {
                "ok": False,
                "status": "INSUFFICIENT_PAPER_CAPITAL",
                "message": f"Insufficient available capital for margin requirement: {total_margin:.2f} INR.",
                "required_margin": total_margin,
                "available_capital": capital["available_capital"]
            }

        # Create PaperOptionCombo
        from app.models.trade import PaperOptionCombo
        combo = PaperOptionCombo(
            name=payload.name,
            status="OPEN",
            margin_required=round(total_margin, 2),
            net_premium=round(net_premium, 2),
            pnl=0.0,
            unrealized_pnl=0.0
        )
        db.add(combo)
        db.flush() # Populate combo.id

        created_legs = []
        for leg in payload.legs:
            # Create a PaperTrade for each leg
            payload_leg = PaperTrade(
                symbol=leg.symbol,
                instrument_type=InstrumentType.INDEX_OPTION.value,
                exchange="NSE",
                expiry=leg.expiry,
                strike=leg.strike,
                option_type=leg.option_type.value if leg.option_type else None,
                direction=leg.direction.value,
                entry_price=leg.entry_price,
                stop_loss=None,
                target_1=None,
                target_2=None,
                quantity=leg.quantity,
                status="OPEN",
                entry_time=datetime.now(timezone.utc),
                data_source=SIMULATOR_SOURCE,
                underlying="NIFTY",
                combo_id=combo.id,
                current_price=leg.entry_price
            )
            db.add(payload_leg)
            created_legs.append(payload_leg)
            
            # Register leg for websocket MTM tracking
            get_live_paper_mtm_service().register_entry(payload_leg)
            await get_live_paper_mtm_service().ensure_trade_symbol_subscribed(db, payload_leg)

        db.commit()
        db.refresh(combo)

        return {
            "ok": True,
            "status": "COMBO_CREATED",
            "message": f"Option spread combination '{combo.name}' executed successfully.",
            "combo_id": combo.id,
            "margin_required": combo.margin_required,
            "net_premium": combo.net_premium
        }

    def open_combos(self, db: Session) -> dict[str, Any]:
        from app.models.trade import PaperOptionCombo
        combos = list(db.scalars(select(PaperOptionCombo).where(PaperOptionCombo.status == "OPEN").order_by(PaperOptionCombo.created_at.desc())))
        results = []
        for combo in combos:
            legs = list(db.scalars(select(PaperTrade).where(PaperTrade.combo_id == combo.id)))
            greeks = self._calculate_combo_greeks(db, combo, legs)
            results.append({
                "id": combo.id,
                "name": combo.name,
                "status": combo.status,
                "created_at": combo.created_at.isoformat() if combo.created_at else None,
                "margin_required": combo.margin_required,
                "net_premium": combo.net_premium,
                "pnl": combo.pnl,
                "unrealized_pnl": sum((leg.unrealized_pnl or 0.0) for leg in legs),
                "unified_theta": greeks["unified_theta"],
                "unified_gamma": greeks["unified_gamma"],
                "unified_delta": greeks["unified_delta"],
                "legs": [_trade_json(leg) for leg in legs]
            })
        return {"ok": True, "count": len(results), "items": results}

    def closed_combos(self, db: Session) -> dict[str, Any]:
        from app.models.trade import PaperOptionCombo
        combos = list(db.scalars(select(PaperOptionCombo).where(PaperOptionCombo.status == "CLOSED").order_by(PaperOptionCombo.closed_at.desc())))
        results = []
        for combo in combos:
            legs = list(db.scalars(select(PaperTrade).where(PaperTrade.combo_id == combo.id)))
            results.append({
                "id": combo.id,
                "name": combo.name,
                "status": combo.status,
                "created_at": combo.created_at.isoformat() if combo.created_at else None,
                "closed_at": combo.closed_at.isoformat() if combo.closed_at else None,
                "margin_required": combo.margin_required,
                "net_premium": combo.net_premium,
                "pnl": combo.pnl,
                "unrealized_pnl": 0.0,
                "legs": [_trade_json(leg) for leg in legs]
            })
        return {"ok": True, "count": len(results), "items": results}

    async def exit_combo(self, db: Session, combo_id: int) -> dict[str, Any]:
        from app.models.trade import PaperOptionCombo
        combo = db.get(PaperOptionCombo, combo_id)
        if combo is None:
            return {"ok": False, "status": "COMBO_NOT_FOUND", "message": "Multi-leg option combo not found."}
        if combo.status != "OPEN":
            return {"ok": False, "status": "COMBO_ALREADY_CLOSED", "message": "Multi-leg option combo is already closed."}
            
        legs = list(db.scalars(select(PaperTrade).where(PaperTrade.combo_id == combo_id, PaperTrade.status == "OPEN")))
        total_pnl = 0.0
        
        for leg in legs:
            current_price = leg.current_price or leg.entry_price
            PaperEngine().close_trade(leg, current_price, "MANUAL_EXIT")
            total_pnl += leg.pnl
            
        combo.status = "CLOSED"
        combo.closed_at = datetime.now(timezone.utc)
        combo.pnl = round(total_pnl, 2)
        combo.unrealized_pnl = 0.0
        db.commit()
        db.refresh(combo)
        
        return {
            "ok": True,
            "status": "COMBO_CLOSED",
            "message": f"Option combination '{combo.name}' exited successfully. Realized PnL: {combo.pnl} INR.",
            "combo_id": combo.id,
            "pnl": combo.pnl
        }

    def _calculate_combo_greeks(self, db: Session, combo: Any, legs: list[PaperTrade]) -> dict[str, float]:
        def norm_cdf(x: float) -> float:
            import math
            return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))

        def norm_pdf(x: float) -> float:
            import math
            return math.exp(-0.5 * x * x) / math.sqrt(2.0 * math.pi)

        spot = 22000.0
        try:
            from app.models.candle import Candle
            latest_candle = db.scalar(
                select(Candle)
                .where(Candle.symbol == "NIFTY")
                .order_by(Candle.timestamp.desc())
                .limit(1)
            )
            if latest_candle:
                spot = float(latest_candle.close)
        except Exception:
            pass

        total_theta = 0.0
        total_gamma = 0.0
        total_delta = 0.0

        for leg in legs:
            strike = leg.strike or spot
            qty = leg.quantity or 50
            mult = 1.0 if leg.direction == "BUY" else -1.0
            
            days = 5.0
            if leg.expiry:
                from datetime import date
                try:
                    exp = date.fromisoformat(leg.expiry)
                    days = max((exp - date.today()).days, 0.5)
                except Exception:
                    pass
            
            iv = 15.0
            import math
            t = max(days / 365.0, 1e-5)
            sigma = max(iv / 100.0, 1e-4)
            r = 0.05
            
            try:
                d1 = (math.log(spot / strike) + (r + 0.5 * sigma * sigma) * t) / (sigma * math.sqrt(t))
                d2 = d1 - sigma * math.sqrt(t)
                
                cdf_d1 = norm_cdf(d1)
                cdf_d2 = norm_cdf(d2)
                pdf_d1 = norm_pdf(d1)
                
                if leg.option_type == "CE":
                    delta = cdf_d1
                    theta = - (spot * pdf_d1 * sigma) / (2 * math.sqrt(t)) - r * strike * math.exp(-r * t) * cdf_d2
                else:
                    delta = cdf_d1 - 1.0
                    theta = - (spot * pdf_d1 * sigma) / (2 * math.sqrt(t)) + r * strike * math.exp(-r * t) * norm_cdf(-d2)
                    
                gamma = pdf_d1 / (spot * sigma * math.sqrt(t))
                theta_day = theta / 365.0
                
                total_theta += theta_day * mult * qty * 50 # Apply NSE option lot multiplier (e.g. 50 NIFTY) to get absolute portfolio Greeks
                total_gamma += gamma * mult * qty * 50
                total_delta += delta * mult * qty * 50
            except Exception:
                pass
                
        return {
            "unified_theta": round(total_theta, 2),
            "unified_gamma": round(total_gamma, 5),
            "unified_delta": round(total_delta, 2),
        }


def _trade_json(trade: PaperTrade) -> dict[str, Any]:
    return {
        "id": trade.id,
        "symbol": trade.symbol,
        "underlying": trade.underlying,
        "status": trade.status,
        "result": trade.result,
        "entry_price": trade.entry_price,
        "exit_price": trade.exit_price,
        "current_price": trade.current_price,
        "quantity": trade.quantity,
        "signal_type": trade.signal_type,
        "stop_loss": trade.stop_loss,
        "target_1": trade.target_1,
        "target_2": trade.target_2,
        "pnl": trade.pnl,
        "unrealized_pnl": trade.unrealized_pnl,
        "pnl_percent": trade.pnl_percent,
        "holding_minutes": trade.holding_minutes,
        "entry_time": trade.entry_time.isoformat() if trade.entry_time else None,
        "exit_time": trade.exit_time.isoformat() if trade.exit_time else None,
        "exit_reason": trade.exit_reason,
        "data_source": trade.data_source,
    }


def _avg(values: list[Any]) -> float:
    clean = [float(value) for value in values if value is not None]
    return round(sum(clean) / len(clean), 2) if clean else 0.0


def _positive_target(value: Any, entry: float) -> float | None:
    try:
        target = float(value)
    except (TypeError, ValueError):
        return None
    return target if target > entry else None


live_paper_simulator_service = LivePaperSimulatorService()


def get_live_paper_simulator_service() -> LivePaperSimulatorService:
    return live_paper_simulator_service
