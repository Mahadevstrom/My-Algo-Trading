from datetime import date, datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.audit.audit_logger import AuditLogger
from app.config import settings
from app.models.participant_flow import ParticipantFlowRecord
from app.schemas.participant_flow import VALID_SEGMENTS, ParticipantFlowRecordResponse


class ParticipantFlowService:
    def __init__(self) -> None:
        self._last_context_at: datetime | None = None

    def status(self, db: Session) -> dict[str, Any]:
        latest_date = db.scalar(select(func.max(ParticipantFlowRecord.market_date)))
        latest_import = db.scalar(select(func.max(ParticipantFlowRecord.imported_at)))
        count = db.scalar(select(func.count(ParticipantFlowRecord.id))) or 0
        freshness = self._freshness(latest_date)
        return {
            "enabled": settings.enable_participant_flow_engine,
            "data_mode": settings.participant_flow_data_mode,
            "web_fetch_allowed": settings.participant_flow_allow_web_fetch,
            "latest_record_date": latest_date.isoformat() if latest_date else None,
            "latest_import_at": latest_import.isoformat() if latest_import else None,
            "record_count": count,
            "data_freshness": freshness,
            "data_ready": bool(count and freshness != "STALE_DATA"),
            "readiness": "READY" if count and freshness != "STALE_DATA" else "IMPORT_REQUIRED",
            "import_guidance": self.import_guidance(),
            "live_order_status": settings.safety_status["live_order_status"],
            "supported_segments": sorted(VALID_SEGMENTS),
        }

    def fii_dii_summary(self, db: Session, lookback_days: int | None = None) -> dict[str, Any]:
        records = self._records(db, None, lookback_days)
        cash = [row for row in records if row.segment == "CASH"]
        fii = [row for row in cash if row.participant_type == "FII"]
        dii = [row for row in cash if row.participant_type == "DII"]
        if (not fii and not dii) and settings.participant_flow_allow_web_fetch:
            self._refresh_from_nse(db)
            records = self._records(db, None, lookback_days)
            cash = [row for row in records if row.segment == "CASH"]
            fii = [row for row in cash if row.participant_type == "FII"]
            dii = [row for row in cash if row.participant_type == "DII"]
        if not fii and not dii:
            return self._no_data("NO_FII_DII_DATA", "No FII/DII cash participant-flow records found.")
        latest_date = max(row.market_date for row in cash) if cash else None
        if latest_date and self._freshness(latest_date) == "STALE_DATA" and settings.participant_flow_allow_web_fetch:
            self._refresh_from_nse(db)
            records = self._records(db, None, lookback_days)
            cash = [row for row in records if row.segment == "CASH"]
            fii = [row for row in cash if row.participant_type == "FII"]
            dii = [row for row in cash if row.participant_type == "DII"]
            latest_date = max(row.market_date for row in cash) if cash else None
        fii_net = _sum(fii, "net_value")
        dii_net = _sum(dii, "net_value")
        bias = _cash_bias(fii_net, dii_net)
        freshness = self._freshness(latest_date)
        warnings = []
        if freshness == "STALE_DATA":
            warnings.append("Latest participant-flow data is older than configured freshness threshold.")
            self._audit(db, "PARTICIPANT_FLOW_STALE_DATA", "Participant-flow FII/DII data is stale.", "WARNING")
        return {
            "ok": True,
            "status": "OK" if freshness != "STALE_DATA" else "STALE_DATA",
            "lookback_days": lookback_days or settings.participant_flow_lookback_days,
            "latest_record_date": latest_date.isoformat() if latest_date else None,
            "data_freshness": freshness,
            "fii_cash_net": fii_net,
            "dii_cash_net": dii_net,
            "fii_dii_divergence": _opposite_signs(fii_net, dii_net),
            "dii_supporting_fii_selling": bool(fii_net < 0 and dii_net > 0),
            "cash_context_bias": bias,
            "trend": self._daily_cash_trend(cash),
            "warnings": warnings,
        }

    def derivatives_summary(self, db: Session, lookback_days: int | None = None) -> dict[str, Any]:
        records = [row for row in self._records(db, None, lookback_days) if row.segment != "CASH"]
        if not records:
            return {
                "ok": True,
                "status": "PARTIAL_DATA",
                "message": "No derivatives participant-flow records found.",
                "derivative_bias": "PARTIAL_DATA",
                "missing_data": ["derivatives_participant_flow"],
                "items": {},
            }
        by_segment = {}
        for segment in sorted({row.segment for row in records}):
            rows = [row for row in records if row.segment == segment]
            by_segment[segment] = {
                "net_value": _sum(rows, "net_value"),
                "contracts_net": _sum(rows, "contracts_net"),
                "oi_net": _sum(rows, "oi_net"),
                "participants": _by_participant(rows),
            }
        fii_index_futures = _sum([row for row in records if row.segment == "INDEX_FUTURES" and row.participant_type == "FII"], "net_value")
        fii_index_options = _sum([row for row in records if row.segment == "INDEX_OPTIONS" and row.participant_type == "FII"], "net_value")
        derivative_bias = _derivative_bias(fii_index_futures, fii_index_options)
        return {
            "ok": True,
            "status": "OK",
            "lookback_days": lookback_days or settings.participant_flow_lookback_days,
            "derivative_bias": derivative_bias,
            "index_futures_bias": _value_bias(fii_index_futures),
            "index_options_bias": _value_bias(fii_index_options),
            "options_participant_bias": _options_participant_bias(records),
            "hedging_pressure": "ELEVATED" if fii_index_options < 0 else "UNKNOWN",
            "speculative_pressure": "ELEVATED" if abs(fii_index_futures) > abs(fii_index_options) else "UNKNOWN",
            "items": by_segment,
            "notes": ["Derivatives participant context is conservative and depends on manually imported data."],
        }

    def context(self, db: Session, symbol: str = "NIFTY", lookback_days: int | None = None) -> dict[str, Any]:
        symbol = symbol.strip().upper()
        cash = self.fii_dii_summary(db, lookback_days)
        derivatives = self.derivatives_summary(db, lookback_days)
        if not cash.get("ok"):
            result = {
                "ok": True,
                "status": "NO_DATA",
                "symbol": symbol,
                "participant_context_status": "NO_DATA",
                "participant_bias": "NO_DATA",
                "participant_score": 0,
                "warnings": ["No participant-flow records are available."],
                "missing_data": ["fii_dii_cash", "derivatives_participant_flow"],
                "reasons": [cash.get("message", "No FII/DII data.")],
                "generated_at": datetime.now(timezone.utc).isoformat(),
            }
            self._audit(db, "PARTICIPANT_FLOW_NO_DATA", "Participant-flow context has no data.", "INFO")
            return result

        fii_net = cash.get("fii_cash_net", 0) or 0
        dii_net = cash.get("dii_cash_net", 0) or 0
        derivative_bias = derivatives.get("derivative_bias", "PARTIAL_DATA")
        score_data = self._score_context(fii_net, dii_net, cash, derivatives)
        reasons = self._reasons(fii_net, dii_net, cash, derivatives, score_data)
        warnings = list(cash.get("warnings", []))
        missing = []
        if derivatives.get("status") == "PARTIAL_DATA":
            missing.append("derivatives_participant_flow")
        if cash.get("status") == "STALE_DATA":
            missing.append("fresh_participant_flow")
        result = {
            "ok": True,
            "status": cash.get("status", "OK"),
            "symbol": symbol,
            "market_date": cash.get("latest_record_date"),
            "data_freshness": cash.get("data_freshness"),
            "participant_context_status": score_data["label"],
            "participant_bias": score_data["bias"],
            "participant_score": score_data["score"],
            "fii_cash_net": fii_net,
            "dii_cash_net": dii_net,
            "fii_dii_divergence": cash.get("fii_dii_divergence", False),
            "dii_supporting_fii_selling": cash.get("dii_supporting_fii_selling", False),
            "derivative_bias": derivative_bias,
            "risk_on_score": score_data["risk_on_score"],
            "risk_off_score": score_data["risk_off_score"],
            "cash_summary": cash,
            "derivatives_summary": derivatives,
            "warnings": warnings,
            "missing_data": missing,
            "reasons": reasons,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }
        self._last_context_at = datetime.now(timezone.utc)
        self._audit(db, "PARTICIPANT_FLOW_CONTEXT_GENERATED", "Participant-flow context generated.", "INFO")
        return result

    def nifty_bias(self, db: Session, lookback_days: int | None = None) -> dict[str, Any]:
        context = self.context(db, settings.participant_flow_default_symbol, lookback_days)
        return {
            "ok": True,
            "symbol": settings.participant_flow_default_symbol,
            "bias": context.get("participant_bias", "NO_DATA"),
            "score": context.get("participant_score", 0),
            "context_status": context.get("participant_context_status", "NO_DATA"),
            "risk_on_score": context.get("risk_on_score", 0),
            "risk_off_score": context.get("risk_off_score", 0),
            "reasons": context.get("reasons", []),
            "warnings": context.get("warnings", []),
            "missing_data": context.get("missing_data", []),
        }

    def explain(self, db: Session, symbol: str = "NIFTY", lookback_days: int | None = None) -> dict[str, Any]:
        context = self.context(db, symbol, lookback_days)
        explanation = _explain(context)
        return {"ok": True, "symbol": symbol.upper(), "explanation": explanation, "context": context}

    def history(self, db: Session, lookback_days: int | None = None) -> dict[str, Any]:
        records = self._records(db, None, lookback_days or 30)
        return {
            "ok": True,
            "lookback_days": lookback_days or 30,
            "count": len(records),
            "items": [ParticipantFlowRecordResponse.model_validate(row).model_dump(mode="json") for row in records],
        }

    def _records(self, db: Session, symbol: str | None, lookback_days: int | None) -> list[ParticipantFlowRecord]:
        days = lookback_days or settings.participant_flow_lookback_days
        cutoff = date.today() - timedelta(days=max(1, min(days, 365)))
        query = select(ParticipantFlowRecord).where(ParticipantFlowRecord.market_date >= cutoff)
        if symbol:
            normalized = symbol.strip().upper()
            query = query.where(
                (ParticipantFlowRecord.symbol == normalized) | (ParticipantFlowRecord.underlying == normalized)
            )
        return list(db.scalars(query.order_by(ParticipantFlowRecord.market_date.desc(), ParticipantFlowRecord.id.desc())))

    def _freshness(self, latest_date: date | None) -> str:
        if latest_date is None:
            return "NO_DATA"
        age = (date.today() - latest_date).days
        if age > settings.participant_flow_warn_if_data_older_than_days:
            return "STALE_DATA"
        return "FRESH"

    def _daily_cash_trend(self, records: list[ParticipantFlowRecord]) -> list[dict[str, Any]]:
        days = sorted({row.market_date for row in records})
        return [
            {
                "market_date": item.isoformat(),
                "fii_cash_net": _sum([row for row in records if row.market_date == item and row.participant_type == "FII"], "net_value"),
                "dii_cash_net": _sum([row for row in records if row.market_date == item and row.participant_type == "DII"], "net_value"),
            }
            for item in days[-10:]
        ]

    def _score_context(self, fii_net: float, dii_net: float, cash: dict[str, Any], derivatives: dict[str, Any]) -> dict[str, Any]:
        risk_on = 0.0
        risk_off = 0.0
        if fii_net > 0:
            risk_on += 25
        elif fii_net < 0:
            risk_off += 25
        if dii_net > 0:
            risk_on += 20 if fii_net >= 0 else 12
        elif dii_net < 0:
            risk_off += 20 if fii_net <= 0 else 8
        derivative_bias = derivatives.get("derivative_bias")
        if derivative_bias == "BULLISH_DERIVATIVES":
            risk_on += 20
        elif derivative_bias == "BEARISH_DERIVATIVES":
            risk_off += 20
        elif derivative_bias == "MIXED_DERIVATIVES":
            risk_on += 6
            risk_off += 6
        if cash.get("data_freshness") == "FRESH":
            risk_on += 5
            risk_off += 5
        score = max(risk_on, risk_off)
        if score >= 80:
            label = "STRONG_BULLISH_CONTEXT" if risk_on >= risk_off else "STRONG_BEARISH_CONTEXT"
        elif score >= 60:
            label = "MODERATE_CONTEXT"
        elif score >= 40:
            label = "MIXED_CONTEXT"
        else:
            label = "WEAK_OR_STALE_CONTEXT"
        if cash.get("data_freshness") == "STALE_DATA":
            label = "STALE_DATA"
        bias = _context_bias(fii_net, dii_net, derivative_bias, risk_on, risk_off)
        return {"score": round(score, 2), "risk_on_score": round(risk_on, 2), "risk_off_score": round(risk_off, 2), "label": label, "bias": bias}

    def _reasons(self, fii_net: float, dii_net: float, cash: dict[str, Any], derivatives: dict[str, Any], score: dict[str, Any]) -> list[str]:
        reasons = []
        if fii_net > 0 and dii_net > 0:
            reasons.append("FII and DII cash flows are both net positive, suggesting risk-on support.")
        elif fii_net < 0 and dii_net > 0:
            reasons.append("FII cash selling is being partly or fully offset by DII buying.")
        elif fii_net < 0 and dii_net < 0:
            reasons.append("FII and DII cash flows are both net negative, suggesting risk-off pressure.")
        elif fii_net > 0 and dii_net < 0:
            reasons.append("FII cash buying is positive, but DII selling creates mixed local context.")
        else:
            reasons.append("FII/DII cash flow is flat or incomplete.")
        if derivatives.get("status") == "OK":
            reasons.append(f"Derivatives participant bias is {derivatives.get('derivative_bias')}.")
        else:
            reasons.append("Derivative participant data is unavailable, so context is partial.")
        reasons.append(f"Participant context score is {score['score']}; this is context only, not trade approval.")
        return reasons

    def _no_data(self, status: str, message: str) -> dict[str, Any]:
        return {
            "ok": False,
            "status": status,
            "message": message,
            "missing_data": ["participant_flow_records"],
            "data_mode": settings.participant_flow_data_mode,
            "import_required": True,
            "import_hint": "FII/DII cash flow is not a live Dhan feed. Import official/provisional cash flow when available.",
            "import_guidance": self.import_guidance(),
        }

    def import_guidance(self) -> dict[str, Any]:
        return {
            "status": "MANUAL_IMPORT_REQUIRED",
            "why": "FII/DII cash flow is delayed institutional data, so the app stores it from manual/official imports instead of treating it as a live tick feed.",
            "quick_import_endpoint": "/api/participant-flow/import-fii-dii-cash",
            "full_import_endpoint": "/api/participant-flow/import",
            "nse_fetch_endpoint": "/api/participant-flow/fetch-nse",
            "template_endpoint": "/api/participant-flow/import-template",
            "sample_quick_payload": {
                "market_date": date.today().isoformat(),
                "source": "MANUAL_FII_DII",
                "fii_cash_net": -2000.0,
                "dii_cash_net": 2000.0,
                "is_provisional": True,
            },
        }

    def _refresh_from_nse(self, db: Session) -> None:
        try:
            from app.services.participant_flow_nse_service import get_participant_flow_nse_service

            get_participant_flow_nse_service().fetch_and_import(db)
        except Exception:
            return

    def _audit(self, db: Session, event_type: str, message: str, severity: str) -> None:
        if not settings.participant_flow_enable_audit:
            return
        AuditLogger().log(db, event_type, message, severity=severity, source="PARTICIPANT_FLOW")


def _sum(rows: list[ParticipantFlowRecord], field: str) -> float:
    total = 0.0
    for row in rows:
        value = getattr(row, field, None)
        if value is not None:
            total += float(value)
    return round(total, 2)


def _opposite_signs(left: float, right: float) -> bool:
    return (left > 0 > right) or (left < 0 < right)


def _cash_bias(fii_net: float, dii_net: float) -> str:
    if fii_net > 0 and dii_net > 0:
        return "RISK_ON"
    if fii_net < 0 and dii_net > 0:
        return "DII_SUPPORT"
    if fii_net < 0 and dii_net < 0:
        return "RISK_OFF"
    if fii_net > 0 and dii_net < 0:
        return "FII_SUPPORT_BUT_LOCAL_SELLING"
    return "NEUTRAL"


def _value_bias(value: float) -> str:
    if value > 0:
        return "BULLISH"
    if value < 0:
        return "BEARISH"
    return "NEUTRAL"


def _derivative_bias(fii_index_futures: float, fii_index_options: float) -> str:
    combined = fii_index_futures + fii_index_options
    if combined > 0:
        return "BULLISH_DERIVATIVES"
    if combined < 0:
        return "BEARISH_DERIVATIVES"
    return "MIXED_DERIVATIVES"


def _options_participant_bias(records: list[ParticipantFlowRecord]) -> str:
    options = [row for row in records if row.segment in {"INDEX_OPTIONS", "STOCK_OPTIONS"}]
    total = _sum(options, "net_value") + _sum(options, "contracts_net")
    return _value_bias(total)


def _by_participant(rows: list[ParticipantFlowRecord]) -> dict[str, dict[str, float]]:
    output = {}
    for participant in sorted({row.participant_type for row in rows}):
        items = [row for row in rows if row.participant_type == participant]
        output[participant] = {
            "net_value": _sum(items, "net_value"),
            "contracts_net": _sum(items, "contracts_net"),
            "oi_net": _sum(items, "oi_net"),
        }
    return output


def _context_bias(fii_net: float, dii_net: float, derivative_bias: str, risk_on: float, risk_off: float) -> str:
    if risk_on == 0 and risk_off == 0:
        return "NO_DATA"
    if fii_net < 0 and dii_net > 0:
        return "DII_SUPPORT"
    if risk_on > risk_off * 1.2:
        return "BULLISH_CONTEXT" if derivative_bias != "BULLISH_DERIVATIVES" else "RISK_ON"
    if risk_off > risk_on * 1.2:
        return "BEARISH_CONTEXT" if derivative_bias != "BEARISH_DERIVATIVES" else "RISK_OFF"
    return "MIXED_CONTEXT"


def _explain(context: dict[str, Any]) -> list[str]:
    if context.get("participant_bias") == "NO_DATA":
        return ["No participant-flow records are available yet. Import manual FII/DII data first."]
    lines = list(context.get("reasons", []))
    if context.get("data_freshness") == "STALE_DATA":
        lines.append("Participant-flow data is stale; use it as delayed context only.")
    lines.append("FII/DII data can be delayed or provisional and should not be treated as live institutional positioning.")
    return lines


participant_flow_service = ParticipantFlowService()


def get_participant_flow_service() -> ParticipantFlowService:
    return participant_flow_service
