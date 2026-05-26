import logging
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app.api.routes_option_chain import _build_chain_analysis
from app.config import settings
from app.engine.dhan_instrument_importer import DhanInstrumentImporter
from app.engine.specialist.base import AbstractSpecialistEngine, EngineEvidence
from app.engine.specialist.shadow_logger import log_engine_evidence
from app.services.option_chain_snapshot_service import get_option_chain_snapshot_service

logger = logging.getLogger(__name__)


def _num(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


class OptionChainEngine(AbstractSpecialistEngine):
    @property
    def engine_name(self) -> str:
        return "option_chain_engine"

    def evaluate(self, market_data: dict) -> EngineEvidence:
        option_chain = market_data.get("option_chain")
        oi_snapshot = market_data.get("oi_snapshot")
        oi_change = market_data.get("oi_change")
        spot_price = _num(market_data.get("spot_price"))

        if not option_chain or len(option_chain) == 0:
            return EngineEvidence(
                engine=self.engine_name,
                score=0.0,
                direction="UNKNOWN",
                verdict="DATA_MISSING",
                confidence=0.0,
                evidence={},
                warnings=["Option chain data unavailable"],
                blocking=True,
                blocking_reason="Option chain data unavailable",
                evaluated_at=datetime.utcnow(),
                evaluation_id=None,
            )

        total_pe_oi = sum(_num(row.get("pe_oi")) or 0 for row in option_chain)
        total_ce_oi = sum(_num(row.get("ce_oi")) or 0 for row in option_chain)
        pcr = round(total_pe_oi / total_ce_oi, 3) if total_ce_oi > 0 else None

        pe_oi_change = 0.0
        ce_oi_change = 0.0
        if oi_change and isinstance(oi_change, dict):
            pe_oi_change = _num(oi_change.get("pe_change")) or 0.0
            ce_oi_change = _num(oi_change.get("ce_change")) or 0.0
        elif oi_change and isinstance(oi_change, list):
            pe_oi_change = sum(_num(row.get("pe_change")) or 0 for row in oi_change)
            ce_oi_change = sum(_num(row.get("ce_change")) or 0 for row in oi_change)

        if pe_oi_change > 0 and ce_oi_change < 0:
            oi_direction = "BEARISH"
        elif ce_oi_change > 0 and pe_oi_change < 0:
            oi_direction = "BULLISH"
        else:
            oi_direction = "NEUTRAL"

        atm_strike = None
        atm_ce_premium = None
        atm_pe_premium = None
        if spot_price is not None:
            strikes = [_num(row.get("strike")) for row in option_chain if _num(row.get("strike")) is not None]
            if strikes:
                atm_strike = min(strikes, key=lambda strike: abs(strike - spot_price))
                atm_row = next((row for row in option_chain if _num(row.get("strike")) == atm_strike), None)
                if atm_row:
                    atm_ce_premium = _num(atm_row.get("ce_ltp") or atm_row.get("ce_last_price"))
                    atm_pe_premium = _num(atm_row.get("pe_ltp") or atm_row.get("pe_last_price"))

        ref_premium = atm_ce_premium if atm_ce_premium is not None else atm_pe_premium
        if ref_premium is None:
            premium_strength = "UNAVAILABLE"
        elif ref_premium >= settings.oc_engine_premium_strong_threshold:
            premium_strength = "STRONG"
        elif ref_premium >= settings.oc_engine_premium_weak_threshold:
            premium_strength = "MODERATE"
        else:
            premium_strength = "WEAK"

        put_writing_strike = None
        call_writing_strike = None
        if oi_change and isinstance(oi_change, list):
            try:
                put_writing_strike = max(oi_change, key=lambda row: _num(row.get("pe_change")) or 0).get("strike")
                call_writing_strike = max(oi_change, key=lambda row: _num(row.get("ce_change")) or 0).get("strike")
            except Exception:
                pass

        if pcr is not None:
            if pcr > 1.5:
                pcr_contribution = 20.0
            elif pcr > settings.oc_engine_pcr_bearish_threshold:
                pcr_contribution = 12.0
            elif pcr > settings.oc_engine_pcr_bullish_threshold:
                pcr_contribution = 0.0
            elif pcr > 0.6:
                pcr_contribution = -12.0
            else:
                pcr_contribution = -20.0
        else:
            pcr_contribution = 0.0

        oi_contribution = {"BEARISH": 15.0, "BULLISH": -15.0, "NEUTRAL": 0.0}.get(oi_direction, 0.0)
        premium_contribution = {"STRONG": 5.0, "MODERATE": 0.0, "WEAK": -10.0, "UNAVAILABLE": 0.0}.get(
            premium_strength, 0.0
        )
        final_score = max(0.0, min(100.0, 50.0 + pcr_contribution + oi_contribution + premium_contribution))

        blocking = False
        blocking_reason = None
        if premium_strength == "UNAVAILABLE":
            verdict = "DATA_MISSING"
            blocking = True
            blocking_reason = "ATM option premium unavailable"
        elif final_score >= 70 and oi_direction == "BEARISH":
            verdict = "PE_STRONG"
        elif final_score <= 30 and oi_direction == "BULLISH":
            verdict = "CE_STRONG"
        elif final_score >= 65:
            verdict = "PE_STRONG"
        elif final_score <= 35:
            verdict = "CE_STRONG"
        elif pe_oi_change > 0 and ce_oi_change > 0 and abs(pe_oi_change) > abs(ce_oi_change) * 1.5:
            verdict = "TRAP_RISK_HIGH"
        elif premium_strength == "WEAK":
            verdict = "PREMIUM_WEAK"
        else:
            verdict = "NEUTRAL"

        if verdict == "PE_STRONG":
            direction = "BEARISH"
        elif verdict == "CE_STRONG":
            direction = "BULLISH"
        else:
            direction = "NEUTRAL"

        confidence = 1.0
        if oi_snapshot is None:
            confidence -= 0.3
        if premium_strength == "WEAK":
            confidence -= 0.2
        if verdict == "TRAP_RISK_HIGH":
            confidence -= 0.2
        confidence = round(max(0.0, confidence), 3)

        warnings = []
        if oi_snapshot is None:
            warnings.append("OI snapshot unavailable; direction may be less reliable")
        if premium_strength == "WEAK":
            warnings.append("ATM option premium is thin; slippage risk high")
            if verdict == "PREMIUM_WEAK":
                warnings.append("Consider waiting for premium to build before entering.")
        if verdict == "TRAP_RISK_HIGH":
            warnings.append("Both CE and PE OI building; potential reversal trap")
        if pcr is None:
            warnings.append("PCR could not be calculated; CE OI is zero")

        return EngineEvidence(
            engine=self.engine_name,
            score=round(final_score, 2),
            direction=direction,
            verdict=verdict,
            confidence=confidence,
            evidence={
                "pcr": pcr,
                "oi_direction": oi_direction,
                "ce_oi_change": round(ce_oi_change, 2),
                "pe_oi_change": round(pe_oi_change, 2),
                "premium_strength": premium_strength,
                "atm_strike": atm_strike,
                "atm_ce_premium": atm_ce_premium,
                "atm_pe_premium": atm_pe_premium,
                "put_writing_support_strike": put_writing_strike,
                "call_writing_resistance_strike": call_writing_strike,
                "total_pe_oi": total_pe_oi,
                "total_ce_oi": total_ce_oi,
            },
            warnings=warnings,
            blocking=blocking,
            blocking_reason=blocking_reason,
            evaluated_at=datetime.utcnow(),
            evaluation_id=None,
        )


def _resolve_expiry(db: Session, underlying: str):
    today = datetime.utcnow().date()
    expiries = DhanInstrumentImporter().expiries(db, underlying)
    future = [item for item in expiries if item >= today]
    return future[0] if future else expiries[0] if expiries else None


def _normalize_change_rows(changes: dict[str, Any]) -> list[dict[str, Any]]:
    items = changes.get("items") or changes.get("strikes") or []
    rows: dict[float, dict[str, Any]] = {}
    for item in items:
        strike = _num(item.get("strike"))
        if strike is None:
            continue
        row = rows.setdefault(strike, {"strike": strike, "pe_change": 0.0, "ce_change": 0.0})
        option_type = str(item.get("option_type") or item.get("type") or "").upper()
        oi_change = _num(item.get("oi_change") or item.get("change_in_oi") or item.get("oi_delta")) or 0.0
        if option_type == "PE":
            row["pe_change"] += oi_change
        elif option_type == "CE":
            row["ce_change"] += oi_change
    return list(rows.values())


async def build_option_chain_market_data(db: Session, underlying: str = "NIFTY") -> dict[str, Any]:
    underlying = (underlying or "NIFTY").strip().upper()
    expiry = _resolve_expiry(db, underlying)
    if expiry is None:
        return {"option_chain": [], "oi_snapshot": None, "oi_change": None, "spot_price": None, "expiry": None}
    chain = await _build_chain_analysis(db, underlying, expiry)
    if not chain.get("ok"):
        return {"option_chain": [], "oi_snapshot": None, "oi_change": None, "spot_price": None, "expiry": str(expiry)}
    changes = {}
    try:
        changes = get_option_chain_snapshot_service().changes(db, underlying, expiry)
    except Exception as e:
        logger.warning(f"Option-chain OI change lookup failed (non-fatal): {e}")
    rows = _normalize_change_rows(changes) if changes else []
    summary = changes.get("summary") if isinstance(changes, dict) else None
    oi_change = rows or {
        "pe_change": (summary or {}).get("pe_oi_change", 0),
        "ce_change": (summary or {}).get("ce_oi_change", 0),
    }
    chain_summary = chain.get("summary") or {}
    return {
        "option_chain": chain.get("strikes") or [],
        "oi_snapshot": chain_summary,
        "oi_change": oi_change,
        "spot_price": chain_summary.get("spot_price"),
        "expiry": str(expiry),
    }


async def run_option_chain_shadow(
    db: Session,
    underlying: str = "NIFTY",
    signal_id: str | None = None,
    signal_v2_decision: str | None = None,
):
    try:
        market_data = await build_option_chain_market_data(db, underlying)
        evidence = OptionChainEngine().safe_evaluate(market_data)
        evidence.evaluation_id = str(uuid.uuid4())
        return log_engine_evidence(
            db=db,
            evidence=evidence,
            signal_id=signal_id,
            signal_v2_decision=signal_v2_decision,
        )
    except Exception as e:
        logger.warning(f"Shadow OC engine logging failed (non-fatal): {e}")
        return None
