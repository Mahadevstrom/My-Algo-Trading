from datetime import date, datetime, timezone
from time import monotonic
from typing import Any

from sqlalchemy.orm import Session

from app.api.routes_option_chain import _build_chain_analysis
from app.audit.audit_logger import AuditLogger
from app.brokers.indstocks_data import IndstocksDataClient
from app.config import settings
from app.engine.dhan_instrument_importer import DhanInstrumentImporter
from app.market_flow.flow_explainer import decision_support, explain_market_flow
from app.market_flow.market_flow_score import score_market_flow
from app.market_flow.option_money_flow_service import analyze_option_money_flow
from app.market_flow.support_resistance_flow import analyze_support_resistance
from app.market_flow.trap_detection import detect_trap
from app.services.data_quality_service import get_data_quality_service
from app.services.live_market_monitor_service import get_live_market_monitor_service
from app.services.option_chain_snapshot_service import get_option_chain_snapshot_service


class MarketFlowService:
    """Read-only NIFTY/options market-flow intelligence coordinator."""

    def __init__(self) -> None:
        self._cache: dict[tuple[str, str | None], tuple[float, dict[str, Any]]] = {}
        self._last_generated_at: datetime | None = None
        self._last_audit_at_by_key: dict[str, datetime] = {}

    async def status(self, db: Session) -> dict[str, Any]:
        underlying = DhanInstrumentImporter().lookup_option_underlying(db, settings.market_flow_default_symbol)
        ind_status = IndstocksDataClient().status()
        return {
            "enabled": settings.enable_market_flow_engine,
            "source": "MARKET_FLOW_ENGINE",
            "mode": settings.trading_mode,
            "live_order_status": settings.safety_status["live_order_status"],
            "option_chain_available": underlying is not None,
            "data_quality_available": settings.enable_data_quality_engine,
            "indstocks_secondary_available": bool(ind_status.get("configured")),
            "last_generated_at": self._last_generated_at.isoformat() if self._last_generated_at else None,
            "supported_symbols": ["NIFTY", "BANKNIFTY", "FINNIFTY", "SENSEX", "BANKEX", "MIDCPNIFTY"],
        }

    async def summary(
        self,
        db: Session,
        symbol: str | None = None,
        expiry: date | None = None,
        refresh: bool = False,
    ) -> dict[str, Any]:
        symbol = (symbol or settings.market_flow_default_symbol).strip().upper()
        if not settings.enable_market_flow_engine:
            return _disabled(symbol, expiry)

        resolved_expiry = self._resolve_expiry(db, symbol, expiry)
        cache_key = (symbol, resolved_expiry.isoformat() if resolved_expiry else None)
        cached = self._cache.get(cache_key)
        if not refresh and cached and monotonic() - cached[0] <= settings.market_flow_cache_seconds:
            return cached[1]

        if resolved_expiry is None:
            result = self._no_data(
                symbol,
                None,
                "NO_VALID_EXPIRY",
                "No valid option expiry was found in the Dhan instrument master.",
                missing=["expiry", "option_chain"],
            )
            self._audit(db, "MARKET_FLOW_NO_DATA", "Market flow could not resolve an expiry.", "WARNING", result)
            return result

        chain_result = await _build_chain_analysis(db, symbol, resolved_expiry)
        if not chain_result.get("ok"):
            result = self._no_data(
                symbol,
                resolved_expiry,
                chain_result.get("status", "OPTION_CHAIN_UNAVAILABLE"),
                chain_result.get("message", "Option chain unavailable."),
                missing=["option_chain"],
            )
            self._audit(db, "MARKET_FLOW_NO_DATA", "Market flow option-chain data is unavailable.", "WARNING", result)
            return result

        chain_summary = chain_result.get("summary") or {}
        strikes = self._limit_strikes(chain_result.get("strikes") or [], chain_summary)
        snapshot_changes = get_option_chain_snapshot_service().changes(db, symbol, resolved_expiry)
        flow = analyze_option_money_flow(
            strikes,
            chain_summary,
            settings.market_flow_min_liquidity_score,
            snapshot_changes=snapshot_changes,
        )
        sr = analyze_support_resistance(strikes, chain_summary, snapshot_changes=snapshot_changes)
        data_quality_status, data_quality_payload = await self._data_quality(db, symbol)
        live_candle_status, live_candle_payload = await self._live_candles(symbol)
        latest_signal = self._latest_signal_v2(symbol)
        secondary_status = self._secondary_data_status()
        trap = detect_trap(flow, sr, latest_signal, data_quality_status, snapshot_changes=snapshot_changes)
        score = score_market_flow(
            chain_summary,
            flow,
            sr,
            trap,
            data_quality_status,
            live_candle_status,
            secondary_status,
        )
        market_bias = self._market_flow_bias(flow, sr, trap)
        missing_data = self._missing_data(
            data_quality_status,
            live_candle_status,
            secondary_status,
            flow.get("oi_change_available"),
        )
        warnings = self._warnings(trap, data_quality_status, live_candle_status, secondary_status)
        generated_at = datetime.now(timezone.utc)
        result: dict[str, Any] = {
            "ok": True,
            "status": "OK" if not missing_data else "PARTIAL_DATA",
            "symbol": symbol,
            "underlying": symbol,
            "expiry": resolved_expiry.isoformat(),
            "spot": chain_summary.get("spot_price"),
            "atm_strike": chain_summary.get("atm_strike"),
            "pcr_oi": chain_summary.get("pcr_oi"),
            "pcr_volume": chain_summary.get("pcr_volume"),
            "option_flow_bias": flow.get("option_flow_bias"),
            "market_flow_bias": market_bias,
            "flow_score": score["score"],
            "flow_strength": score["strength"],
            "confidence": score["confidence"],
            "chain_summary": chain_summary,
            "option_money_flow": flow,
            "support_resistance": sr,
            "trap_detection": trap,
            "data_quality_status": data_quality_status,
            "data_quality": data_quality_payload,
            "live_candle_status": live_candle_status,
            "live_candle": live_candle_payload,
            "secondary_data_status": secondary_status,
            "latest_signal_v2": latest_signal,
            "oi_change_available": bool(flow.get("oi_change_available")),
            "snapshot_count": self._snapshot_count(db, symbol, resolved_expiry),
            "latest_snapshot_at": snapshot_changes.get("latest_snapshot_at"),
            "previous_snapshot_at": snapshot_changes.get("previous_snapshot_at"),
            "snapshot_change_status": snapshot_changes.get("status"),
            "snapshot_changes": snapshot_changes.get("summary") or {},
            "ce_oi_change": flow.get("ce_oi_change"),
            "pe_oi_change": flow.get("pe_oi_change"),
            "ce_volume_change": flow.get("ce_volume_change"),
            "pe_volume_change": flow.get("pe_volume_change"),
            "pcr_oi_change": flow.get("pcr_oi_change"),
            "pcr_volume_change": flow.get("pcr_volume_change"),
            "top_ce_buildup_strikes": flow.get("ce_oi_buildup_strikes", []),
            "top_pe_buildup_strikes": flow.get("pe_oi_buildup_strikes", []),
            "top_ce_unwinding_strikes": flow.get("top_ce_unwinding_strikes", []),
            "top_pe_unwinding_strikes": flow.get("top_pe_unwinding_strikes", []),
            "support_strength_change": sr.get("support_strength_change"),
            "resistance_strength_change": sr.get("resistance_strength_change"),
            "flow_change_bias": flow.get("flow_change_bias"),
            "buildup_summary": flow.get("buildup_summary", {}),
            "unwinding_summary": flow.get("unwinding_summary", {}),
            "missing_data": missing_data,
            "reasons": flow.get("reasons") or [],
            "warnings": warnings,
            "decision_support": decision_support(market_bias, latest_signal),
            "generated_at": generated_at.isoformat(),
        }
        result["explanation"] = explain_market_flow(result)
        self._last_generated_at = generated_at
        self._cache[cache_key] = (monotonic(), result)
        self._audit(
            db,
            "MARKET_FLOW_TRAP_RISK_HIGH" if trap.get("trap_risk") == "HIGH" else "MARKET_FLOW_GENERATED",
            f"Market flow generated for {symbol}.",
            "WARNING" if trap.get("trap_risk") == "HIGH" else "INFO",
            result,
        )
        return result

    async def option_flow(self, db: Session, symbol: str, expiry: date | None = None) -> dict[str, Any]:
        result = await self.summary(db, symbol, expiry)
        if not result.get("ok"):
            return result
        return {
            "ok": True,
            "symbol": result["symbol"],
            "expiry": result["expiry"],
            "option_money_flow": result["option_money_flow"],
            "chain_summary": result.get("chain_summary"),
            "oi_change_available": result["oi_change_available"],
            "missing_data": result["missing_data"],
        }

    async def support_resistance(self, db: Session, symbol: str, expiry: date | None = None) -> dict[str, Any]:
        result = await self.summary(db, symbol, expiry)
        if not result.get("ok"):
            return result
        return {
            "ok": True,
            "symbol": result["symbol"],
            "expiry": result["expiry"],
            "spot": result["spot"],
            "support_resistance": result["support_resistance"],
            "warnings": result["warnings"],
        }

    async def trap_risk(self, db: Session, symbol: str, expiry: date | None = None) -> dict[str, Any]:
        result = await self.summary(db, symbol, expiry)
        if not result.get("ok"):
            return result
        return {
            "ok": True,
            "symbol": result["symbol"],
            "expiry": result["expiry"],
            "market_flow_bias": result["market_flow_bias"],
            "trap_detection": result["trap_detection"],
            "decision_support": result["decision_support"],
        }

    async def smart_money_bias(self, db: Session, symbol: str, expiry: date | None = None) -> dict[str, Any]:
        result = await self.summary(db, symbol, expiry)
        if not result.get("ok"):
            return {
                "ok": True,
                "symbol": symbol.upper(),
                "expiry": str(expiry) if expiry else None,
                "bias": "NO_DATA",
                "flow_score": 0,
                "confidence": 0,
                "reasons": [result.get("message", "No market-flow data available.")],
            }
        return {
            "ok": True,
            "symbol": result["symbol"],
            "expiry": result["expiry"],
            "bias": result["market_flow_bias"],
            "flow_score": result["flow_score"],
            "confidence": result["confidence"],
            "reasons": result["explanation"],
        }

    async def explain(self, db: Session, symbol: str, expiry: date | None = None) -> dict[str, Any]:
        result = await self.summary(db, symbol, expiry)
        return {
            "ok": True,
            "symbol": symbol.upper(),
            "expiry": result.get("expiry") if isinstance(result, dict) else str(expiry) if expiry else None,
            "explanation": result.get("explanation") or [result.get("message", "No explanation available.")],
            "summary": result,
        }

    def _resolve_expiry(self, db: Session, symbol: str, requested: date | None) -> date | None:
        if requested:
            return requested
        today = datetime.now(timezone.utc).date()
        expiries = DhanInstrumentImporter().expiries(db, symbol)
        future = [item for item in expiries if item >= today]
        return future[0] if future else expiries[0] if expiries else None

    def _limit_strikes(self, strikes: list[dict[str, Any]], summary: dict[str, Any]) -> list[dict[str, Any]]:
        max_count = settings.market_flow_max_chain_strikes
        if max_count <= 0 or len(strikes) <= max_count:
            return strikes
        atm = _num(summary.get("atm_strike"))
        if atm is None:
            return sorted(strikes, key=lambda row: _num(row.get("strike")) or 0)[:max_count]
        ranked = sorted(strikes, key=lambda row: abs((_num(row.get("strike")) or atm) - atm))
        return sorted(ranked[:max_count], key=lambda row: _num(row.get("strike")) or 0)

    async def _data_quality(self, db: Session, symbol: str) -> tuple[str, dict[str, Any] | None]:
        if not settings.market_flow_use_data_quality or not settings.enable_data_quality_engine:
            return "DISABLED", None
        try:
            summary = await get_data_quality_service().get_symbol(db, symbol)
            return summary.data_status, summary.model_dump(mode="json")
        except Exception as exc:
            return "UNAVAILABLE", {"error": f"{type(exc).__name__}: {exc}"}

    async def _live_candles(self, symbol: str) -> tuple[str, dict[str, Any] | None]:
        if not settings.market_flow_use_live_candles:
            return "DISABLED", None
        try:
            state = await get_live_market_monitor_service().market_state(symbol)
            return state.get("data_status", state.get("status", "UNKNOWN")), state
        except Exception as exc:
            return "UNAVAILABLE", {"error": f"{type(exc).__name__}: {exc}"}

    def _secondary_data_status(self) -> str:
        if not settings.market_flow_use_indstocks_cross_check or not settings.indstocks_use_as_secondary_data:
            return "DISABLED"
        status = IndstocksDataClient().status()
        if not status.get("enabled"):
            return "DISABLED"
        if not status.get("configured"):
            return "TOKEN_MISSING"
        return "CONFIGURED_READ_ONLY"

    def _latest_signal_v2(self, symbol: str) -> dict[str, Any] | None:
        try:
            from app.engine.signal_engine_v2 import get_signal_engine_v2

            items = get_signal_engine_v2().latest(10).get("items", [])
            return next((item for item in items if (item.get("underlying") or item.get("symbol") or "").upper() == symbol), None)
        except Exception:
            return None

    def _market_flow_bias(self, flow: dict[str, Any], sr: dict[str, Any], trap: dict[str, Any]) -> str:
        if trap.get("trap_risk") == "HIGH":
            return "TRAP_POSSIBLE"
        flow_change = flow.get("flow_change_bias")
        if flow_change in {"BULLISH_BREAKOUT_SUPPORT", "BEARISH_BREAKDOWN_SUPPORT", "RANGE_COMPRESSION"}:
            return flow_change
        if flow_change == "BULLISH_SUPPORT" and not sr.get("near_resistance"):
            return "BULLISH"
        if flow_change == "BEARISH_RESISTANCE" and not sr.get("near_support"):
            return "BEARISH"
        flow_bias = flow.get("option_flow_bias")
        if flow_bias == "BULLISH":
            return "BULLISH_BUT_OVEREXTENDED" if sr.get("near_resistance") else "BULLISH"
        if flow_bias == "BEARISH":
            return "BEARISH_BUT_OVERSOLD" if sr.get("near_support") else "BEARISH"
        if flow_bias == "RANGE":
            return "RANGE"
        return "NO_EDGE"

    def _missing_data(
        self,
        data_quality_status: str,
        live_candle_status: str,
        secondary_status: str,
        oi_change_available: bool,
    ) -> list[str]:
        missing = []
        if data_quality_status in {"NO_DATA", "DISABLED", "UNAVAILABLE", "UNKNOWN"}:
            missing.append("data_quality")
        if live_candle_status in {"NO_DATA", "DISABLED", "UNAVAILABLE", "UNKNOWN"}:
            missing.append("live_candles")
        if secondary_status in {"DISABLED", "TOKEN_MISSING"}:
            missing.append("indstocks_secondary_cross_check")
        if not oi_change_available:
            missing.append("oi_change_snapshot")
        return missing

    def _snapshot_count(self, db: Session, symbol: str, expiry: date) -> int:
        try:
            return len(get_option_chain_snapshot_service().get_snapshot_history(db, symbol, expiry, limit=200))
        except Exception:
            return 0

    def _warnings(
        self,
        trap: dict[str, Any],
        data_quality_status: str,
        live_candle_status: str,
        secondary_status: str,
    ) -> list[str]:
        warnings = []
        if trap.get("trap_risk") in {"MEDIUM", "HIGH"}:
            warnings.extend(trap.get("trap_reason") or [])
        if data_quality_status not in {"OK", "DISABLED"}:
            warnings.append(f"Data quality status is {data_quality_status}.")
        if live_candle_status not in {"OK", "DISABLED"}:
            warnings.append(f"Live candle status is {live_candle_status}.")
        if secondary_status == "TOKEN_MISSING":
            warnings.append("INDstocks secondary cross-check token is missing; Dhan-only analysis used.")
        return warnings

    def _no_data(
        self,
        symbol: str,
        expiry: date | None,
        status: str,
        message: str,
        missing: list[str],
    ) -> dict[str, Any]:
        return {
            "ok": False,
            "status": status,
            "message": message,
            "symbol": symbol,
            "underlying": symbol,
            "expiry": expiry.isoformat() if expiry else None,
            "market_flow_bias": "NO_DATA",
            "flow_score": 0,
            "flow_strength": "NO_EDGE_OR_BAD_DATA",
            "confidence": 0,
            "missing_data": missing,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }

    def _audit(
        self,
        db: Session,
        event_type: str,
        message: str,
        severity: str,
        payload: dict[str, Any],
    ) -> None:
        if not settings.market_flow_enable_audit:
            return
        now = datetime.now(timezone.utc)
        key = f"{event_type}:{payload.get('symbol')}:{payload.get('expiry')}"
        last = self._last_audit_at_by_key.get(key)
        if last and (now - last).total_seconds() < settings.market_flow_audit_throttle_seconds:
            return
        self._last_audit_at_by_key[key] = now
        AuditLogger().log(
            db,
            event_type,
            message,
            severity=severity,
            source="MARKET_FLOW",
            payload={
                "symbol": payload.get("symbol"),
                "expiry": payload.get("expiry"),
                "market_flow_bias": payload.get("market_flow_bias"),
                "flow_score": payload.get("flow_score"),
                "status": payload.get("status"),
                "warnings": payload.get("warnings", [])[:5],
            },
        )


def _disabled(symbol: str, expiry: date | None) -> dict[str, Any]:
    return {
        "ok": False,
        "status": "MARKET_FLOW_DISABLED",
        "message": "Market Flow Intelligence Engine is disabled by config.",
        "symbol": symbol,
        "expiry": expiry.isoformat() if expiry else None,
        "market_flow_bias": "NO_DATA",
        "flow_score": 0,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def _num(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


market_flow_service = MarketFlowService()


def get_market_flow_service() -> MarketFlowService:
    return market_flow_service
