from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import date, datetime, time, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.config import settings
from app.models.audit_log import AuditLog
from app.models.trade import PaperTrade, TradeResult
from app.services.live_paper_mtm_service import SIMULATOR_SOURCE


try:
    IST = ZoneInfo("Asia/Kolkata")
except ZoneInfoNotFoundError:
    IST = timezone(timedelta(hours=5, minutes=30), name="Asia/Kolkata")


PASS_STATUSES = {
    "CONFIRMED",
    "BULLISH_CONFIRMED",
    "BEARISH_CONFIRMED",
    "RETEST_CONFIRMED",
    "STRONG",
    "ACCEPTABLE",
    "CLEAR",
    "CLEAN",
    "FAVORABLE",
    "OK",
}

CAUTION_STATUSES = {
    "UNKNOWN",
    "UNAVAILABLE",
    "INSUFFICIENT_DATA",
    "INVALID_DATA",
    "NO_CANDLES",
    "NO_OPTION_CANDLES",
    "WEAK",
    "BELOW_VWAP",
    "SLIPPAGE_RISK",
    "LOW_VOLUME",
    "NOT_CONFIRMED",
    "RETEST_MISSING",
    "IMPULSE_NO_RETEST",
    "CHASE_RISK",
    "TRAP_RISK",
    "NO_REFERENCE_LEVEL",
    "NO_CANDIDATE",
}

ENTRY_FILTER_LABELS = {
    "regime": "Market regime",
    "structure": "Market structure",
    "retest": "Retest entry gate",
    "entry_candle": "Entry candle",
    "option_confirm": "Selected option confirmation",
    "option_quality": "Selected option quality",
    "trap": "Trap detection",
    "chase": "Chase filter",
    "location": "Trade location",
}

EXIT_REASON_TEXT = {
    "TARGET_2_HIT": "Target 2 hit; planned profit exit completed.",
    "TARGET_HIT": "Target hit; planned profit exit completed.",
    "TARGET_1_HIT": "Target 1 hit; trade should be managed by trailing logic after the partial milestone.",
    "STOP_LOSS_HIT": "Stop loss hit; risk exit triggered.",
    "TRAILING_STOP_HIT": "Trailing stop hit after profit protection was armed.",
    "BREAKEVEN_STOP_HIT": "Breakeven stop protected capital after the trade moved in favor.",
    "OPTION_MOMENTUM_FADE_EXIT": "Option momentum faded after target 1; early exit protected profit.",
    "NO_PROGRESS_EXIT": "Trade did not make enough progress within the allowed time window.",
    "TIME_EXIT": "Time-based exit triggered.",
    "MARKET_CLOSE_EXIT": "Market close/session rule triggered exit.",
    "DATA_STALE_EXIT": "Market-data stream became stale; trade was closed for data safety.",
    "KILL_SWITCH_EXIT": "Risk kill-switch exit triggered.",
    "MANUAL_EXIT": "Manual paper exit was recorded.",
    "EXPIRED": "Contract expiry exit was recorded.",
}


class TradeJournalService:
    def daily_review(self, db: Session, trading_date: date | None = None, underlying: str = "NIFTY") -> dict[str, Any]:
        day = trading_date or datetime.now(IST).date()
        normalized_underlying = (underlying or "NIFTY").strip().upper()
        start_utc, end_utc = _day_bounds_utc(day)
        trades = self._trades_for_day(db, start_utc, end_utc, normalized_underlying)
        audits_by_trade = self._audits_by_trade(db, [trade.id for trade in trades])
        trade_reviews = [self._review_trade(trade, audits_by_trade.get(trade.id, [])) for trade in trades]
        summary = self._summary(trade_reviews)
        return {
            "ok": True,
            "mode": "PAPER_REVIEW",
            "source": SIMULATOR_SOURCE,
            "trading_date": day.isoformat(),
            "underlying": normalized_underlying,
            "generated_at": datetime.now(IST).isoformat(),
            "summary": summary,
            "day_review": self._day_review(summary),
            "trades": trade_reviews,
            "safety": {
                "read_only": True,
                "creates_trades": False,
                "modifies_trades": False,
                "broker_execution": False,
                "live_order_status": settings.safety_status["live_order_status"],
            },
        }

    def trade_review(self, db: Session, trade_id: int) -> dict[str, Any]:
        trade = db.get(PaperTrade, trade_id)
        if trade is None or trade.data_source != SIMULATOR_SOURCE:
            return {"ok": False, "status": "NOT_FOUND", "message": "Live paper simulator trade not found."}
        audits = self._audits_by_trade(db, [trade.id]).get(trade.id, [])
        return {
            "ok": True,
            "mode": "PAPER_REVIEW",
            "source": SIMULATOR_SOURCE,
            "trade": self._review_trade(trade, audits),
            "safety": {
                "read_only": True,
                "creates_trades": False,
                "modifies_trades": False,
                "broker_execution": False,
                "live_order_status": settings.safety_status["live_order_status"],
            },
        }

    def _trades_for_day(self, db: Session, start_utc: datetime, end_utc: datetime, underlying: str) -> list[PaperTrade]:
        query = (
            select(PaperTrade)
            .where(
                PaperTrade.data_source == SIMULATOR_SOURCE,
                PaperTrade.entry_time >= start_utc,
                PaperTrade.entry_time < end_utc,
                or_(func.upper(PaperTrade.underlying) == underlying, func.upper(PaperTrade.symbol).like(f"{underlying}%")),
            )
            .order_by(PaperTrade.entry_time)
        )
        return list(db.scalars(query))

    def _audits_by_trade(self, db: Session, trade_ids: list[int]) -> dict[int, list[AuditLog]]:
        if not trade_ids:
            return {}
        rows = list(
            db.scalars(
                select(AuditLog)
                .where(AuditLog.entity_type == "PaperTrade", AuditLog.entity_id.in_(trade_ids))
                .order_by(AuditLog.created_at)
            )
        )
        grouped: dict[int, list[AuditLog]] = defaultdict(list)
        for row in rows:
            if row.entity_id is not None:
                grouped[row.entity_id].append(row)
        return dict(grouped)

    def _review_trade(self, trade: PaperTrade, audits: list[AuditLog]) -> dict[str, Any]:
        context = _parse_signal_reason(trade.signal_reason)
        parsed_audits = [_audit_to_dict(item) for item in audits]
        exit_audits = [item for item in parsed_audits if _is_exit_event(item["event_type"])]
        entry_analysis = self._entry_analysis(trade, context)
        exit_analysis = self._exit_analysis(trade, exit_audits)
        improvements = self._improvements(trade, context, entry_analysis, exit_analysis)
        return {
            "trade": {
                "id": trade.id,
                "symbol": trade.symbol,
                "underlying": trade.underlying,
                "option_type": trade.option_type,
                "strike": trade.strike,
                "expiry": trade.expiry,
                "direction": trade.direction,
                "entry_price": trade.entry_price,
                "exit_price": trade.exit_price,
                "stop_loss": trade.stop_loss,
                "target_1": trade.target_1,
                "target_2": trade.target_2,
                "entry_time": _as_ist_iso(trade.entry_time),
                "exit_time": _as_ist_iso(trade.exit_time),
                "holding_minutes": trade.holding_minutes,
                "status": trade.status,
                "result": trade.result,
                "pnl": trade.pnl,
                "pnl_percent": trade.pnl_percent,
                "exit_reason": trade.exit_reason,
            },
            "entry_analysis": entry_analysis,
            "exit_analysis": exit_analysis,
            "what_would_improve_result": improvements,
            "audit_context": {
                "event_count": len(parsed_audits),
                "exit_events": exit_audits,
                "latest_events": parsed_audits[-5:],
            },
            "raw_signal_context": context,
        }

    def _entry_analysis(self, trade: PaperTrade, context: dict[str, str]) -> dict[str, Any]:
        passed, failed = _classify_filters(context)
        required_score = _safe_float(context.get("required_score"))
        score = _safe_float(trade.strategy_score) or _safe_float(trade.signal_confidence)
        late_entry = _late_entry_status(context)
        option_confirmed = _option_confirmation_status(context)
        why = [
            f"Signal v2 selected {trade.signal_type or trade.direction} on {trade.symbol}.",
            f"Score {score if score is not None else 'N/A'} vs required {required_score if required_score is not None else 'N/A'}.",
        ]
        if trade.chain_bias:
            why.append(f"Option-chain bias was {trade.chain_bias}.")
        if context.get("regime") and context["regime"] != "UNKNOWN":
            why.append(f"Market regime was {context['regime']}.")
        if context.get("support") or context.get("resistance"):
            why.append(f"Support/resistance context: support {context.get('support', 'N/A')}, resistance {context.get('resistance', 'N/A')}.")
        return {
            "why_entered": why,
            "filters_passed": passed,
            "filters_failed_or_caution": failed,
            "was_entry_late": late_entry,
            "ce_pe_option_confirmed": option_confirmed,
        }

    def _exit_analysis(self, trade: PaperTrade, exit_audits: list[dict[str, Any]]) -> dict[str, Any]:
        reason = trade.exit_reason or ("OPEN" if trade.result == TradeResult.OPEN.value else "UNKNOWN")
        payloads = [item["payload"] for item in exit_audits if item.get("payload")]
        why = EXIT_REASON_TEXT.get(reason, f"Exit reason recorded as {reason}.")
        latest_payload = payloads[-1] if payloads else {}
        if reason == "OPEN":
            why = "Trade is still open; no exit has been recorded yet."
        return {
            "why_exited": why,
            "exit_reason": reason,
            "exit_events_found": len(exit_audits),
            "exit_data_status": latest_payload.get("data_status"),
            "mark_source": latest_payload.get("mark_source"),
            "tick_age_seconds": latest_payload.get("tick_age_seconds"),
            "target_1_hit": latest_payload.get("target_1_hit"),
            "max_favorable_price": latest_payload.get("max_favorable_price"),
            "max_adverse_price": latest_payload.get("max_adverse_price"),
            "trailing_stop_price": latest_payload.get("trailing_stop_price"),
            "breakeven_stop_price": latest_payload.get("breakeven_stop_price"),
            "momentum_fade_context": latest_payload.get("momentum_fade_context"),
        }

    def _improvements(
        self,
        trade: PaperTrade,
        context: dict[str, str],
        entry_analysis: dict[str, Any],
        exit_analysis: dict[str, Any],
    ) -> list[str]:
        improvements = []
        option_status = context.get("option_quality", "UNKNOWN")
        option_confirm = context.get("option_confirm", "UNKNOWN")
        if option_status in {"NO_CANDLES", "NO_OPTION_CANDLES", "UNKNOWN", "UNAVAILABLE"}:
            improvements.append("Do not enter until the selected CE/PE has live positive option candles and stored LTP ticks.")
        if option_status in {"WEAK", "BELOW_VWAP", "LOW_VOLUME", "SLIPPAGE_RISK"}:
            improvements.append("Raise the selected-option quality bar before allowing entry.")
        if option_confirm != "CONFIRMED":
            improvements.append("Require CE/PE premium confirmation before entry.")
        if not entry_analysis["was_entry_late"]["confirmed_clean"]:
            improvements.append("Wait for a VWAP/EMA/support-resistance retest instead of chasing an impulse candle.")
        if context.get("trap") not in {"CLEAR", "OK"}:
            improvements.append("Block trap-risk setups until option chain and option premium both confirm.")
        if trade.exit_reason == "STOP_LOSS_HIT":
            improvements.append("Review whether structure, retest, and option-quality filters were strong enough before entry.")
        if trade.exit_reason in {"DATA_STALE_EXIT", "MARKET_CLOSE_EXIT"} or exit_analysis.get("mark_source") in {"NO_LTP", None}:
            improvements.append("Keep option LTP storage/subscription healthy during every open paper trade.")
        if trade.exit_reason in {"TARGET_2_HIT", "TARGET_HIT"}:
            improvements.append("Keep this setup template, then verify the automatic target exit timing in replay.")
        if not improvements:
            improvements.append("No major rule gap detected from stored context; continue paper testing and compare with replay.")
        return _dedupe(improvements)

    def _summary(self, trade_reviews: list[dict[str, Any]]) -> dict[str, Any]:
        results = Counter((item["trade"]["result"] or "UNKNOWN") for item in trade_reviews)
        exits = Counter((item["trade"]["exit_reason"] or "OPEN") for item in trade_reviews)
        option_confirmation = Counter(item["entry_analysis"]["ce_pe_option_confirmed"]["status"] for item in trade_reviews)
        late_entries = sum(1 for item in trade_reviews if item["entry_analysis"]["was_entry_late"]["is_late"] is True)
        missing_option_stream = sum(
            1
            for item in trade_reviews
            if item["raw_signal_context"].get("option_quality", "UNKNOWN")
            in {"NO_CANDLES", "NO_OPTION_CANDLES", "UNKNOWN", "UNAVAILABLE"}
        )
        improvement_counts = Counter()
        for item in trade_reviews:
            for improvement in item["what_would_improve_result"]:
                improvement_counts[improvement] += 1
        closed = [item for item in trade_reviews if item["trade"]["result"] != TradeResult.OPEN.value]
        return {
            "total_trades": len(trade_reviews),
            "open_trades": results.get(TradeResult.OPEN.value, 0),
            "wins": results.get("WIN", 0),
            "losses": results.get("LOSS", 0),
            "breakeven": results.get("BREAKEVEN", 0),
            "closed_trades": len(closed),
            "total_pnl": round(sum(float(item["trade"]["pnl"] or 0.0) for item in trade_reviews), 2),
            "exit_reason_counts": dict(exits),
            "option_confirmation_counts": dict(option_confirmation),
            "late_entry_count": late_entries,
            "missing_option_stream_count": missing_option_stream,
            "top_improvements": dict(improvement_counts.most_common(5)),
        }

    def _day_review(self, summary: dict[str, Any]) -> dict[str, Any]:
        if summary["total_trades"] == 0:
            return {"status": "NO_TRADES", "recommendation": "No paper trades found for this date."}
        if summary["missing_option_stream_count"] > 0:
            return {
                "status": "FIX_OPTION_LTP_STORAGE",
                "recommendation": "Selected option LTP/candle storage was missing or weak for at least one trade.",
            }
        unconfirmed_options = summary.get("option_confirmation_counts", {}).get("UNKNOWN", 0) + summary.get(
            "option_confirmation_counts", {}
        ).get("NOT_CONFIRMED", 0)
        if unconfirmed_options > 0:
            return {
                "status": "REQUIRE_OPTION_CONFIRMATION",
                "recommendation": "At least one trade lacked selected CE/PE premium confirmation.",
            }
        if summary["late_entry_count"] > 0:
            return {"status": "WAIT_FOR_RETEST", "recommendation": "At least one trade looked late; enforce the retest gate."}
        if summary["losses"] > summary["wins"]:
            return {"status": "TIGHTEN_FILTERS", "recommendation": "Losses exceeded wins; tighten option confirmation and trap filters."}
        return {"status": "CONTINUE_PAPER_TESTING", "recommendation": "Stored context does not show a major rule gap today."}


def get_trade_journal_service() -> TradeJournalService:
    return TradeJournalService()


def _day_bounds_utc(day: date) -> tuple[datetime, datetime]:
    start_ist = datetime.combine(day, time.min, tzinfo=IST)
    end_ist = start_ist + timedelta(days=1)
    return start_ist.astimezone(timezone.utc), end_ist.astimezone(timezone.utc)


def _parse_signal_reason(reason: str | None) -> dict[str, str]:
    context: dict[str, str] = {}
    if not reason:
        return context
    for part in reason.split(";"):
        item = part.strip()
        if not item:
            continue
        if "=" in item:
            key, value = item.split("=", 1)
            context[key.strip()] = value.strip()
        else:
            context[item] = "true"
    return context


def _classify_filters(context: dict[str, str]) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    passed = []
    failed = []
    for key, label in ENTRY_FILTER_LABELS.items():
        status = (context.get(key) or "UNKNOWN").strip()
        normalized = status.upper()
        item = {"filter": label, "key": key, "status": status}
        if normalized in PASS_STATUSES or any(token in normalized for token in ("CONFIRMED", "STRONG", "CLEAR", "CLEAN")):
            passed.append(item)
        elif normalized in CAUTION_STATUSES or normalized.startswith(("NO_", "NOT_", "INVALID", "INSUFFICIENT")):
            failed.append(item)
        elif normalized not in {"NONE", "FALSE"}:
            passed.append(item)
        else:
            failed.append(item)
    return passed, failed


def _late_entry_status(context: dict[str, str]) -> dict[str, Any]:
    chase = (context.get("chase") or "UNKNOWN").upper()
    retest = (context.get("retest") or "UNKNOWN").upper()
    candle = (context.get("entry_candle") or "UNKNOWN").upper()
    reasons = []
    if chase == "CHASE_RISK":
        reasons.append("Chase filter marked impulse/chase risk.")
    if retest not in {"RETEST_CONFIRMED", "CONFIRMED", "OK"}:
        reasons.append(f"Retest gate was {retest}.")
    if candle in {"NOT_CONFIRMED", "WEAK", "UNKNOWN"}:
        reasons.append(f"Entry candle was {candle}.")
    if chase == "UNKNOWN" and retest == "UNKNOWN" and candle == "UNKNOWN":
        return {"is_late": None, "status": "UNKNOWN", "confirmed_clean": False, "reasons": ["No stored late-entry context was available."]}
    return {
        "is_late": bool(reasons),
        "status": "LATE_OR_UNCONFIRMED" if reasons else "CLEAN",
        "confirmed_clean": not reasons,
        "reasons": reasons or ["Retest, chase, and entry-candle context were clean."],
    }


def _option_confirmation_status(context: dict[str, str]) -> dict[str, Any]:
    confirm = (context.get("option_confirm") or "UNKNOWN").upper()
    quality = (context.get("option_quality") or "UNKNOWN").upper()
    confirmed = confirm == "CONFIRMED" and quality in {"STRONG", "ACCEPTABLE", "OK"}
    if confirm == "UNKNOWN" and quality == "UNKNOWN":
        status = "UNKNOWN"
    elif confirmed:
        status = "CONFIRMED"
    else:
        status = "NOT_CONFIRMED"
    return {
        "confirmed": confirmed,
        "status": status,
        "option_confirm": confirm,
        "option_quality": quality,
        "reason": "Selected option confirmed direction and quality." if confirmed else "Selected option confirmation was missing or weak.",
    }


def _audit_to_dict(event: AuditLog) -> dict[str, Any]:
    return {
        "id": event.id,
        "event_type": event.event_type,
        "severity": event.severity,
        "source": event.source,
        "message": event.message,
        "created_at": _as_ist_iso(event.created_at),
        "payload": _parse_payload(event.payload_json),
    }


def _parse_payload(payload_json: str | None) -> dict[str, Any]:
    if not payload_json:
        return {}
    try:
        payload = json.loads(payload_json)
    except (TypeError, ValueError):
        return {"raw": payload_json}
    return payload if isinstance(payload, dict) else {"value": payload}


def _is_exit_event(event_type: str) -> bool:
    normalized = event_type.upper()
    return "EXIT" in normalized or "STOP_LOSS" in normalized or "TARGET" in normalized or "TRAILING" in normalized


def _as_ist_iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    current = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    return current.astimezone(IST).isoformat()


def _safe_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _dedupe(items: list[str]) -> list[str]:
    seen = set()
    result = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result
