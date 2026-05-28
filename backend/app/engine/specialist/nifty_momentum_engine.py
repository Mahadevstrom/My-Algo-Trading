import logging
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app.config import settings
from app.engine.specialist.base import AbstractSpecialistEngine, EngineEvidence
from app.engine.specialist.market_structure_engine import build_market_structure_data, calculate_vwap
from app.engine.specialist.shadow_logger import log_engine_evidence
from app.services.sector_breadth_service import get_sector_breadth_service

logger = logging.getLogger(__name__)


class NiftyMomentumVerdict:
    BULLISH_CONTINUATION = "BULLISH_CONTINUATION"
    BEARISH_CONTINUATION = "BEARISH_CONTINUATION"
    MOMENTUM_WEAKENING = "MOMENTUM_WEAKENING"
    REVERSAL_RISK = "REVERSAL_RISK"
    CHOPPY_NO_EDGE = "CHOPPY_NO_EDGE"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


class NiftyMomentumValidationEngine(AbstractSpecialistEngine):
    @property
    def engine_name(self) -> str:
        return "nifty_momentum_engine"

    def evaluate(self, market_data: dict) -> EngineEvidence:
        candles = market_data.get("nifty_candles") or market_data.get("candles") or []
        banknifty_candles = market_data.get("banknifty_candles") or []
        breadth = market_data.get("breadth") or {}

        if not candles or len(candles) < 10:
            return EngineEvidence(
                engine=self.engine_name,
                score=50.0,
                direction="NEUTRAL",
                verdict=NiftyMomentumVerdict.INSUFFICIENT_DATA,
                confidence=0.0,
                evidence={"candle_count": len(candles) if candles else 0},
                warnings=["Insufficient NIFTY candle data for momentum validation"],
                blocking=False,
                blocking_reason=None,
                evaluated_at=datetime.utcnow(),
                evaluation_id=None,
            )

        closes = [_num(_field(candle, "close")) for candle in candles]
        closes = [item for item in closes if item is not None]
        if len(closes) < 10:
            return EngineEvidence(
                engine=self.engine_name,
                score=50.0,
                direction="NEUTRAL",
                verdict=NiftyMomentumVerdict.INSUFFICIENT_DATA,
                confidence=0.0,
                evidence={"candle_count": len(closes)},
                warnings=["Insufficient valid NIFTY closes for momentum validation"],
                blocking=False,
                blocking_reason=None,
                evaluated_at=datetime.utcnow(),
                evaluation_id=None,
            )

        current_price = _num(market_data.get("spot_price")) or closes[-1]
        short_change_pct = _change_pct(closes[-4], closes[-1]) if len(closes) >= 4 else 0.0
        session_change_pct = _change_pct(closes[0], closes[-1])
        slope = _linear_slope(closes[-8:])
        vwap = calculate_vwap([_candle_dict(candle) for candle in candles if _candle_dict(candle) is not None])
        vwap_distance_pct = _change_pct(vwap, current_price) if vwap else None

        banknifty_change_pct = _series_change(banknifty_candles)
        banknifty_direction = _direction_from_change(banknifty_change_pct)
        nifty_direction = _direction_from_change(short_change_pct)
        banknifty_confirmation = (
            banknifty_direction == nifty_direction if banknifty_direction != "NEUTRAL" and nifty_direction != "NEUTRAL" else None
        )

        breadth_bias = str(breadth.get("breadth_bias") or breadth.get("nifty_confirmation") or "UNKNOWN").upper()
        risk_on_score = _num(breadth.get("risk_on_score")) or _num((breadth.get("market_breadth") or {}).get("risk_on_score")) or 0.0
        risk_off_score = _num(breadth.get("risk_off_score")) or _num((breadth.get("market_breadth") or {}).get("risk_off_score")) or 0.0
        gainer_count = _num(breadth.get("gainer_count")) or 0.0
        loser_count = _num(breadth.get("loser_count")) or 0.0
        constituent_count = _num(breadth.get("constituent_count")) or (gainer_count + loser_count)
        advance_ratio = gainer_count / constituent_count if constituent_count else None
        sector_confirmation = _sector_confirmation(breadth_bias, risk_on_score, risk_off_score, advance_ratio)

        score = 50.0
        score += _bounded(short_change_pct * 18.0, -18.0, 18.0)
        score += _bounded(session_change_pct * 8.0, -12.0, 12.0)
        score += _bounded(slope * 20.0, -10.0, 10.0)
        if vwap_distance_pct is not None:
            score += _bounded(vwap_distance_pct * 8.0, -10.0, 10.0)
        if banknifty_confirmation is True:
            score += 10.0 if nifty_direction == "BULLISH" else -10.0
        elif banknifty_confirmation is False:
            score += -8.0 if nifty_direction == "BULLISH" else 8.0
        if sector_confirmation == "BULLISH":
            score += 8.0
        elif sector_confirmation == "BEARISH":
            score -= 8.0
        score = round(max(0.0, min(100.0, score)), 2)

        reversal_risk = bool(
            banknifty_confirmation is False
            or (vwap_distance_pct is not None and abs(vwap_distance_pct) > 0.7 and nifty_direction != "NEUTRAL")
            or (sector_confirmation not in {"UNKNOWN", nifty_direction} and nifty_direction != "NEUTRAL")
        )

        if reversal_risk and 42.0 <= score <= 58.0:
            verdict = NiftyMomentumVerdict.REVERSAL_RISK
            direction = "NEUTRAL"
        elif score >= 66.0 and nifty_direction == "BULLISH":
            verdict = NiftyMomentumVerdict.BULLISH_CONTINUATION
            direction = "BULLISH"
        elif score <= 34.0 and nifty_direction == "BEARISH":
            verdict = NiftyMomentumVerdict.BEARISH_CONTINUATION
            direction = "BEARISH"
        elif reversal_risk:
            verdict = NiftyMomentumVerdict.MOMENTUM_WEAKENING
            direction = "NEUTRAL"
        else:
            verdict = NiftyMomentumVerdict.CHOPPY_NO_EDGE
            direction = "NEUTRAL"

        confidence = 0.9
        warnings = []
        if len(candles) < 21:
            confidence -= 0.15
            warnings.append("Less than 21 NIFTY candles; momentum validation is early-session only")
        if not banknifty_candles:
            confidence -= 0.2
            warnings.append("NIFTY Bank/BANKNIFTY candles unavailable; cross-index validation missing")
        if not breadth:
            confidence -= 0.2
            warnings.append("NIFTY breadth/sector data unavailable; constituent confirmation missing")
        if reversal_risk:
            confidence -= 0.1
            warnings.append("Momentum validation sees contradiction; continuation may fail")
        confidence = round(max(0.0, confidence), 3)

        return EngineEvidence(
            engine=self.engine_name,
            score=score,
            direction=direction,
            verdict=verdict,
            confidence=confidence,
            evidence={
                "current_price": current_price,
                "short_change_pct": round(short_change_pct, 3),
                "session_change_pct": round(session_change_pct, 3),
                "slope": round(slope, 4),
                "vwap": round(vwap, 2) if vwap else None,
                "vwap_distance_pct": round(vwap_distance_pct, 3) if vwap_distance_pct is not None else None,
                "banknifty_change_pct": round(banknifty_change_pct, 3) if banknifty_change_pct is not None else None,
                "banknifty_direction": banknifty_direction,
                "banknifty_confirmation": banknifty_confirmation,
                "breadth_bias": breadth_bias,
                "risk_on_score": risk_on_score,
                "risk_off_score": risk_off_score,
                "advance_ratio": round(advance_ratio, 3) if advance_ratio is not None else None,
                "sector_confirmation": sector_confirmation,
                "reversal_risk": reversal_risk,
                "candle_count": len(candles),
            },
            warnings=warnings,
            blocking=False,
            blocking_reason=None,
            evaluated_at=datetime.utcnow(),
            evaluation_id=None,
        )


async def build_nifty_momentum_data(db: Session, underlying: str = "NIFTY") -> dict[str, Any]:
    try:
        nifty_data = await build_market_structure_data(db, underlying or "NIFTY", "5min")
    except Exception as exc:
        logger.warning("NIFTY momentum data lookup failed (non-fatal): %s", exc)
        nifty_data = {"candles": [], "spot_price": None}
    try:
        banknifty_data = await build_market_structure_data(db, "BANKNIFTY", "5min")
    except Exception as exc:
        logger.warning("NIFTY Bank/BANKNIFTY momentum data lookup failed (non-fatal): %s", exc)
        banknifty_data = {"candles": []}
    try:
        breadth = await get_sector_breadth_service().summary(db, "NIFTY")
    except Exception as exc:
        logger.warning("NIFTY breadth lookup failed for momentum engine (non-fatal): %s", exc)
        breadth = {}
    return {
        "nifty_candles": nifty_data.get("candles") or [],
        "banknifty_candles": banknifty_data.get("candles") or [],
        "spot_price": nifty_data.get("spot_price"),
        "breadth": breadth if isinstance(breadth, dict) and breadth.get("ok", True) else {},
        "data_source": {
            "nifty": nifty_data.get("data_source", "UNAVAILABLE"),
            "banknifty": banknifty_data.get("data_source", "UNAVAILABLE"),
            "breadth": breadth.get("source") if isinstance(breadth, dict) else None,
        },
    }


async def run_nifty_momentum_shadow(
    db: Session,
    underlying: str = "NIFTY",
    signal_id: str | None = None,
    signal_v2_decision: str | None = None,
    evaluation_id: str | None = None,
):
    if not settings.enable_nifty_momentum_engine:
        return None
    try:
        market_data = await build_nifty_momentum_data(db, underlying)
        evidence = NiftyMomentumValidationEngine().safe_evaluate(market_data)
        evidence.evaluation_id = evaluation_id or str(uuid.uuid4())
        return log_engine_evidence(
            db=db,
            evidence=evidence,
            signal_id=signal_id,
            signal_v2_decision=signal_v2_decision,
        )
    except Exception as exc:
        logger.warning("NIFTY momentum shadow failed (non-fatal): %s", exc)
        return None


def _field(item: Any, field: str) -> Any:
    if isinstance(item, dict):
        return item.get(field)
    return getattr(item, field, None)


def _num(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _change_pct(start: float | None, end: float | None) -> float:
    if start is None or end is None or start == 0:
        return 0.0
    return (end - start) / start * 100


def _series_change(candles: list[Any]) -> float | None:
    closes = [_num(_field(candle, "close")) for candle in candles]
    closes = [item for item in closes if item is not None]
    if len(closes) < 2:
        return None
    return _change_pct(closes[0], closes[-1])


def _direction_from_change(change_pct: float | None) -> str:
    if change_pct is None:
        return "NEUTRAL"
    if change_pct >= 0.07:
        return "BULLISH"
    if change_pct <= -0.07:
        return "BEARISH"
    return "NEUTRAL"


def _linear_slope(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    first = values[0]
    if first == 0:
        return 0.0
    return ((values[-1] - first) / first * 100) / max(len(values) - 1, 1)


def _bounded(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _sector_confirmation(
    breadth_bias: str,
    risk_on_score: float,
    risk_off_score: float,
    advance_ratio: float | None,
) -> str:
    if "BULL" in breadth_bias or "RISK_ON" in breadth_bias:
        return "BULLISH"
    if "BEAR" in breadth_bias or "RISK_OFF" in breadth_bias:
        return "BEARISH"
    if risk_on_score - risk_off_score >= 10:
        return "BULLISH"
    if risk_off_score - risk_on_score >= 10:
        return "BEARISH"
    if advance_ratio is not None:
        if advance_ratio >= 0.62:
            return "BULLISH"
        if advance_ratio <= 0.38:
            return "BEARISH"
    return "UNKNOWN"


def _candle_dict(candle: Any) -> dict[str, Any] | None:
    close = _num(_field(candle, "close"))
    high = _num(_field(candle, "high"))
    low = _num(_field(candle, "low"))
    open_price = _num(_field(candle, "open"))
    if None in {close, high, low, open_price}:
        return None
    return {
        "timestamp": _field(candle, "timestamp") or _field(candle, "start_time"),
        "open": open_price,
        "high": high,
        "low": low,
        "close": close,
        "volume": _num(_field(candle, "volume")) or 0.0,
    }
