import logging
import uuid
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.config import settings
from app.engine.context.context_evidence import ContextEvidence
from app.engine.context.context_logger import log_context_classification
from app.engine.context.context_types import ContextType
from app.engine.context.event_calendar import is_event_day
from app.engine.context.expiry_calendar import (
    days_to_next_expiry,
    get_expiry_session,
    is_expiry_today,
    is_monthly_expiry_today,
)
from app.engine.dhan_instrument_importer import DhanInstrumentImporter
from app.models.live_candle import LiveCandleRecord

logger = logging.getLogger(__name__)
IST = ZoneInfo("Asia/Kolkata")


class ContextClassifier:
    def classify(self, db: Session, market_data: dict = None, underlying: str = "NIFTY") -> ContextEvidence:
        market_data = market_data or {}
        now_ist = _now_ist(market_data)
        ist_hour = now_ist.hour
        ist_minute = now_ist.minute
        ist_time_str = now_ist.strftime("%H:%M")
        ist_date_str = now_ist.strftime("%Y-%m-%d")
        day_of_week = now_ist.strftime("%A").upper()

        is_expiry = bool(is_expiry_today(db, underlying))
        is_monthly = bool(is_monthly_expiry_today(db, underlying))
        dte = int(days_to_next_expiry(db, underlying))
        expiry_session = get_expiry_session(ist_hour, ist_minute)
        opening_gap_pct = _opening_gap_pct(market_data)
        vix_value = _num(market_data.get("vix"))
        vix_20day_avg = _num(market_data.get("vix_20day_avg"))
        vix_vs_avg = None
        if vix_value is not None and vix_20day_avg and vix_20day_avg > 0:
            vix_vs_avg = round((vix_value - vix_20day_avg) / vix_20day_avg * 100, 2)
        data_quality = _normalize_data_quality(market_data.get("data_quality_status"))
        is_event, event_name = is_event_day(ist_date_str)
        cross_context, cross_modifier, cross_summary = _cross_index_context(
            db=db,
            primary_underlying=underlying,
            market_data=market_data,
            today_ist=now_ist.date(),
        )

        context_type = ContextType.NORMAL_TRADING_DAY
        secondary_context = None
        confidence = 0.70
        modifier = 0.0

        if is_monthly and dte <= 5:
            secondary_context = ContextType.MONTHLY_EXPIRY_WEEK

        if data_quality == "STALE":
            context_type = ContextType.STALE_DATA_DAY
            confidence = 0.95
            modifier = 0.20
        elif is_expiry:
            if expiry_session == "AFTERNOON":
                context_type = ContextType.EXPIRY_DAY_AFTERNOON
                confidence = 0.95
                modifier = 0.15
            elif expiry_session == "MORNING":
                context_type = ContextType.EXPIRY_DAY_MORNING
                confidence = 0.90
                modifier = 0.05
            else:
                context_type = ContextType.EXPIRY_DAY_MORNING
                confidence = 0.85
                modifier = 0.08
        elif dte == 1:
            context_type = ContextType.PRE_EXPIRY_DAY
            confidence = 0.85
            modifier = 0.05
        elif vix_value is not None and vix_value > settings.context_vix_high_threshold:
            context_type = ContextType.HIGH_VIX_DAY
            confidence = 0.85
            modifier = 0.10
        elif vix_vs_avg is not None and vix_vs_avg > 25:
            context_type = ContextType.HIGH_VIX_DAY
            confidence = 0.75
            modifier = 0.08
        elif is_event:
            context_type = ContextType.NEWS_EVENT_DAY
            confidence = 0.90
            modifier = 0.12
        else:
            gap_context = _gap_context(opening_gap_pct, ist_hour, ist_minute, market_data)
            if gap_context is not None:
                context_type, confidence, modifier = gap_context
            elif vix_value is not None and vix_value < settings.context_vix_low_threshold:
                context_type = ContextType.LOW_VIX_TRENDING
                confidence = 0.75
                modifier = -0.05

        if secondary_context is None and cross_context is not None:
            secondary_context = cross_context
        if context_type not in {ContextType.STALE_DATA_DAY, ContextType.EXPIRY_DAY_AFTERNOON}:
            modifier = max(-0.20, min(0.20, modifier + cross_modifier))

        summary = _context_summary(context_type, opening_gap_pct, vix_value, vix_vs_avg, event_name)
        if cross_summary:
            summary = f"{summary} {cross_summary}"
        return ContextEvidence(
            context_type=context_type,
            context_confidence=round(confidence, 3),
            secondary_context=secondary_context,
            ist_time_str=ist_time_str,
            ist_date_str=ist_date_str,
            day_of_week=day_of_week,
            is_expiry_day=is_expiry,
            is_monthly_expiry=is_monthly,
            days_to_expiry=dte,
            opening_gap_pct=opening_gap_pct,
            vix_value=vix_value,
            vix_vs_20day_avg_pct=vix_vs_avg,
            previous_day_range_pct=_num(market_data.get("prev_day_range_pct") or market_data.get("previous_day_range_pct")),
            is_known_event_day=is_event,
            known_event_name=event_name,
            data_quality_status=data_quality,
            confidence_modifier=round(modifier, 3),
            context_summary=summary,
            evaluated_at=datetime.utcnow(),
            evaluation_id=None,
        )

    def safe_classify(self, db: Session, market_data: dict = None, underlying: str = "NIFTY") -> ContextEvidence:
        try:
            return self.classify(db=db, market_data=market_data, underlying=underlying)
        except Exception as exc:
            now_ist = datetime.now(IST)
            return ContextEvidence(
                context_type=ContextType.UNKNOWN,
                context_confidence=0.0,
                secondary_context=None,
                ist_time_str=now_ist.strftime("%H:%M"),
                ist_date_str=now_ist.strftime("%Y-%m-%d"),
                day_of_week=now_ist.strftime("%A").upper(),
                is_expiry_day=False,
                is_monthly_expiry=False,
                days_to_expiry=-1,
                opening_gap_pct=None,
                vix_value=None,
                vix_vs_20day_avg_pct=None,
                previous_day_range_pct=None,
                is_known_event_day=False,
                known_event_name=None,
                data_quality_status="UNKNOWN",
                confidence_modifier=0.0,
                context_summary=f"Context classification failed: {exc}",
                evaluated_at=datetime.utcnow(),
                evaluation_id=None,
            )


def signal_context_market_data(signal_result: Any) -> dict[str, Any]:
    market_state = getattr(signal_result, "market_state", None) or {}
    if isinstance(signal_result, dict):
        market_state = signal_result.get("market_state") or {}
    return {
        "vix": _get(signal_result, "vix") or market_state.get("vix"),
        "vix_20day_avg": _get(signal_result, "vix_20day_avg") or market_state.get("vix_20day_avg"),
        "previous_close": _get(signal_result, "previous_close") or market_state.get("previous_close"),
        "open_price": _get(signal_result, "open_price") or market_state.get("open_price"),
        "current_price": _get(signal_result, "current_price") or market_state.get("spot_price"),
        "opening_gap_pct": _get(signal_result, "opening_gap_pct") or market_state.get("opening_gap_pct"),
        "prev_day_range_pct": _get(signal_result, "prev_day_range_pct") or market_state.get("prev_day_range_pct"),
        "data_quality_status": _get(signal_result, "data_quality_status"),
    }


def run_context_shadow(
    db: Session,
    underlying: str = "NIFTY",
    signal_result: Any = None,
    signal_id: str | None = None,
    signal_v2_decision: str | None = None,
    evaluation_id: str | None = None,
):
    try:
        market_data = signal_context_market_data(signal_result) if signal_result is not None else {}
        context = ContextClassifier().safe_classify(db=db, market_data=market_data, underlying=underlying)
        context.evaluation_id = evaluation_id or str(uuid.uuid4())
        return log_context_classification(
            db=db,
            context=context,
            signal_id=signal_id,
            signal_v2_decision=signal_v2_decision,
        )
    except Exception as exc:
        logger.warning(f"Context classification shadow logging failed (non-fatal): {exc}")
        return None


def _now_ist(market_data: dict[str, Any]) -> datetime:
    raw = market_data.get("_now_ist")
    if isinstance(raw, datetime):
        return raw.astimezone(IST) if raw.tzinfo else raw.replace(tzinfo=IST)
    if isinstance(raw, str):
        try:
            parsed = datetime.fromisoformat(raw)
            return parsed.astimezone(IST) if parsed.tzinfo else parsed.replace(tzinfo=IST)
        except ValueError:
            pass
    return datetime.now(IST)


def _opening_gap_pct(market_data: dict[str, Any]) -> float | None:
    direct = _num(market_data.get("opening_gap_pct"))
    if direct is not None:
        return round(direct, 3)
    previous_close = _num(market_data.get("previous_close"))
    open_price = _num(market_data.get("open_price") or market_data.get("current_price"))
    if previous_close and open_price is not None:
        return round((open_price - previous_close) / previous_close * 100, 3)
    return None


def _gap_context(opening_gap_pct: float | None, ist_hour: int, ist_minute: int, market_data: dict[str, Any]):
    if opening_gap_pct is None:
        return None
    if abs(opening_gap_pct) > 1.5 and (ist_hour > 10 or (ist_hour == 10 and ist_minute >= 0)):
        if bool(market_data.get("gap_filling")):
            return ContextType.GAP_FADE, 0.70, 0.10
    if opening_gap_pct > settings.context_gap_large_threshold:
        return ContextType.GAP_UP_CONTINUATION, 0.80, -0.03
    if opening_gap_pct < -settings.context_gap_large_threshold:
        return ContextType.GAP_DOWN_CONTINUATION, 0.80, -0.03
    if opening_gap_pct > settings.context_gap_small_threshold:
        return ContextType.GAP_UP_CONTINUATION, 0.70, -0.02
    if opening_gap_pct < -settings.context_gap_small_threshold:
        return ContextType.GAP_DOWN_CONTINUATION, 0.70, -0.02
    return None


def _context_summary(context_type: str, opening_gap_pct: float | None, vix_value: float | None, vix_vs_avg: float | None, event_name: str | None) -> str:
    if context_type == ContextType.EXPIRY_DAY_AFTERNOON:
        return "Expiry afternoon. Premium decay risk is high; avoid fresh entries unless evidence is exceptional."
    if context_type == ContextType.EXPIRY_DAY_MORNING:
        return "Expiry day morning. Directional moves remain possible, but premium decay requires higher confidence."
    if context_type == ContextType.PRE_EXPIRY_DAY:
        return "Pre-expiry day. OI rollover noise can make PCR less reliable."
    if context_type == ContextType.GAP_DOWN_CONTINUATION:
        return f"Gap down {opening_gap_pct:.2f}% from previous close. Trend day likely; PE momentum setups may have edge."
    if context_type == ContextType.GAP_UP_CONTINUATION:
        return f"Gap up {opening_gap_pct:.2f}% from previous close. Trend day likely; CE momentum setups may have edge."
    if context_type == ContextType.GAP_FADE:
        return "Large gap is fading. Counter-trend conditions are active; momentum entries need caution."
    if context_type == ContextType.HIGH_VIX_DAY:
        suffix = f" ({vix_vs_avg:.1f}% vs 20-day average)" if vix_vs_avg is not None else ""
        return f"India VIX is elevated at {vix_value}{suffix}. Premiums are expensive; raise confidence threshold."
    if context_type == ContextType.LOW_VIX_TRENDING:
        return f"India VIX is low at {vix_value}. Directional setups can work if trend evidence is clean."
    if context_type == ContextType.NEWS_EVENT_DAY:
        return f"{event_name} today. Unpredictable moves expected; all signals need higher confidence."
    if context_type == ContextType.STALE_DATA_DAY:
        return "Data quality is stale. Treat all signal evidence as unreliable."
    if context_type == ContextType.UNKNOWN:
        return "Context could not be determined. Use conservative thresholds."
    return "Normal trading day. Standard thresholds apply."


def _cross_index_context(
    db: Session,
    primary_underlying: str,
    market_data: dict[str, Any],
    today_ist,
) -> tuple[str | None, float, str]:
    primary = (primary_underlying or "NIFTY").strip().upper()
    related = [item for item in _related_underlyings(primary) if item != primary]
    expiry_hits = _cross_expiry_hits(db, related, market_data, today_ist)

    secondary_context = None
    modifier = 0.0
    summaries = []
    if expiry_hits:
        secondary_context = _expiry_secondary_context(expiry_hits)
        modifier += 0.05 if "BANKNIFTY" in expiry_hits else 0.03
        summaries.append(
            f"{', '.join(expiry_hits)} expiry today. Watch cross-index volatility and option-flow distortion."
        )

    banknifty_momentum = _banknifty_momentum(db, market_data)
    if banknifty_momentum:
        if secondary_context is None:
            secondary_context = ContextType.BANKNIFTY_MOMENTUM_VALIDATION
        summaries.append(banknifty_momentum)

    return secondary_context, round(modifier, 3), " ".join(summaries)


def _cross_expiry_hits(
    db: Session,
    related: list[str],
    market_data: dict[str, Any],
    today_ist,
) -> list[str]:
    explicit = market_data.get("cross_index_expiries")
    if isinstance(explicit, str):
        return [item.strip().upper() for item in explicit.split(",") if item.strip().upper() in related]
    if isinstance(explicit, (list, tuple, set)):
        return [str(item).strip().upper() for item in explicit if str(item).strip().upper() in related]

    hits = []
    importer = DhanInstrumentImporter()
    for symbol in related:
        try:
            expiries = importer.expiries(db, symbol)
        except Exception:
            continue
        if any(item == today_ist for item in expiries):
            hits.append(symbol)
    return hits


def _related_underlyings(primary: str) -> list[str]:
    if primary == "BANKNIFTY":
        return ["NIFTY", "SENSEX", "BANKEX"]
    if primary == "SENSEX":
        return ["NIFTY", "BANKNIFTY", "BANKEX"]
    return ["BANKNIFTY", "SENSEX", "BANKEX"]


def _expiry_secondary_context(expiry_hits: list[str]) -> str:
    if "BANKNIFTY" in expiry_hits:
        return ContextType.BANKNIFTY_EXPIRY_DAY
    if "SENSEX" in expiry_hits:
        return ContextType.SENSEX_EXPIRY_DAY
    return ContextType.CROSS_INDEX_EXPIRY_DAY


def _banknifty_momentum(db: Session, market_data: dict[str, Any]) -> str:
    direction = str(
        market_data.get("banknifty_direction")
        or market_data.get("banknifty_momentum")
        or ""
    ).upper()
    change_pct = _num(
        market_data.get("banknifty_change_pct")
        or market_data.get("banknifty_opening_gap_pct")
    )

    if not direction or direction == "UNKNOWN":
        db_momentum = _latest_index_momentum(db, "BANKNIFTY")
        direction = db_momentum[0] if db_momentum else direction
        change_pct = db_momentum[1] if db_momentum and change_pct is None else change_pct

    if direction not in {"BULLISH", "BEARISH"}:
        return ""

    if change_pct is None:
        return f"NIFTY Bank/BANKNIFTY momentum is {direction}; use it only as cross-market validation, not as a trade trigger."
    return (
        f"NIFTY Bank/BANKNIFTY momentum is {direction} ({change_pct:+.2f}%); "
        "use it only as cross-market validation, not as a trade trigger."
    )


def _latest_index_momentum(db: Session, underlying: str) -> tuple[str, float | None] | None:
    try:
        aliases = _index_aliases(underlying)
        rows = list(
            db.scalars(
                select(LiveCandleRecord)
                .where(
                    LiveCandleRecord.timeframe.in_(["5m", "5min"]),
                    LiveCandleRecord.close > 0,
                    or_(
                        LiveCandleRecord.symbol.in_(aliases),
                        LiveCandleRecord.underlying.in_(aliases),
                    ),
                    LiveCandleRecord.option_type.is_(None),
                )
                .order_by(LiveCandleRecord.start_time.desc())
                .limit(6)
            )
        )
    except Exception:
        return None
    rows = list(reversed(rows))
    if len(rows) < 2:
        return None
    first = rows[0].close
    last = rows[-1].close
    if not first:
        return None
    change_pct = round((last - first) / first * 100, 3)
    if change_pct >= 0.25:
        return "BULLISH", change_pct
    if change_pct <= -0.25:
        return "BEARISH", change_pct
    return None


def _index_aliases(underlying: str) -> list[str]:
    normalized = (underlying or "NIFTY").strip().upper().replace("_", " ")
    aliases = {
        "BANKNIFTY": ["BANKNIFTY", "NIFTY BANK", "NIFTYBANK"],
        "NIFTY BANK": ["BANKNIFTY", "NIFTY BANK", "NIFTYBANK"],
        "NIFTYBANK": ["BANKNIFTY", "NIFTY BANK", "NIFTYBANK"],
        "NIFTY": ["NIFTY", "NIFTY 50"],
        "NIFTY 50": ["NIFTY", "NIFTY 50"],
    }
    return aliases.get(normalized, [normalized])


def _normalize_data_quality(value: Any) -> str:
    status = str(value or "UNKNOWN").upper()
    if status in {"OK", "CLEAN", "PASS", "PASSED"}:
        return "CLEAN"
    if status in {"WARNING", "DEGRADED"}:
        return "DEGRADED"
    if status in {"STALE", "NO_DATA", "DISCONNECTED", "BAD_TICK", "MISMATCH", "STALE_DATA"}:
        return "STALE"
    return "UNKNOWN"


def _num(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _get(source: Any, key: str):
    if source is None:
        return None
    if isinstance(source, dict):
        return source.get(key)
    return getattr(source, key, None)
