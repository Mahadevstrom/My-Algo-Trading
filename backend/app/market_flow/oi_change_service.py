from collections import defaultdict
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit.audit_logger import AuditLogger
from app.models.option_chain_snapshot import OptionChainSnapshot, OptionChainStrikeSnapshot


class OIChangeService:
    def analyze_snapshot_pair(
        self,
        db: Session,
        latest: OptionChainSnapshot | None,
        previous: OptionChainSnapshot | None,
        audit: bool = True,
    ) -> dict[str, Any]:
        if latest is None:
            return {
                "ok": False,
                "status": "NO_LATEST_SNAPSHOT",
                "message": "No latest option-chain snapshot is available.",
                "oi_change_available": False,
            }
        if previous is None:
            if audit:
                AuditLogger().log(
                    db,
                    "OI_CHANGE_NO_PREVIOUS_SNAPSHOT",
                    "OI change analysis needs at least two option-chain snapshots.",
                    severity="INFO",
                    source="MARKET_FLOW",
                    payload={"symbol": latest.symbol, "expiry": latest.expiry.isoformat(), "snapshot_id": latest.id},
                )
            return {
                "ok": True,
                "status": "NO_PREVIOUS_SNAPSHOT",
                "message": "Capture at least two snapshots to calculate OI change.",
                "symbol": latest.symbol,
                "expiry": latest.expiry.isoformat(),
                "latest_snapshot_id": latest.id,
                "latest_snapshot_at": latest.snapshot_at.isoformat(),
                "previous_snapshot_at": None,
                "oi_change_available": False,
                "summary": {},
                "items": [],
            }

        latest_rows = self._rows_by_key(db, latest.id)
        previous_rows = self._rows_by_key(db, previous.id)
        items = []
        totals: dict[str, float] = defaultdict(float)
        for key, latest_row in latest_rows.items():
            previous_row = previous_rows.get(key)
            if previous_row is None:
                continue
            item = self._compare_row(latest_row, previous_row, latest.spot_price)
            items.append(item)
            prefix = latest_row.option_type.lower()
            totals[f"{prefix}_oi_change"] += item["oi_change"] or 0
            totals[f"{prefix}_volume_change"] += item["volume_change"] or 0
            totals[f"{prefix}_ltp_change"] += item["ltp_change"] or 0

        summary = {
            "ce_oi_change": round(totals["ce_oi_change"], 2),
            "pe_oi_change": round(totals["pe_oi_change"], 2),
            "ce_volume_change": round(totals["ce_volume_change"], 2),
            "pe_volume_change": round(totals["pe_volume_change"], 2),
            "ce_ltp_change": round(totals["ce_ltp_change"], 2),
            "pe_ltp_change": round(totals["pe_ltp_change"], 2),
            "pcr_oi_change": _diff(latest.pcr_oi, previous.pcr_oi),
            "pcr_volume_change": _diff(latest.pcr_volume, previous.pcr_volume),
            "total_oi_change": round(totals["ce_oi_change"] + totals["pe_oi_change"], 2),
            "total_volume_change": round(totals["ce_volume_change"] + totals["pe_volume_change"], 2),
            "top_ce_buildup_strikes": _top(items, "CE", {"CE_OI_BUILDUP", "CE_LONG_BUILDUP", "CE_WRITING_PRESSURE"}),
            "top_pe_buildup_strikes": _top(items, "PE", {"PE_OI_BUILDUP", "PE_LONG_BUILDUP", "PE_WRITING_SUPPORT"}),
            "top_ce_unwinding_strikes": _top(items, "CE", {"CE_UNWINDING", "CE_SHORT_COVERING"}),
            "top_pe_unwinding_strikes": _top(items, "PE", {"PE_UNWINDING", "PE_SHORT_COVERING"}),
        }
        summary.update(self._flow_change(summary, items, latest, previous))
        result = {
            "ok": True,
            "status": "OK",
            "symbol": latest.symbol,
            "expiry": latest.expiry.isoformat(),
            "latest_snapshot_id": latest.id,
            "previous_snapshot_id": previous.id,
            "latest_snapshot_at": latest.snapshot_at.isoformat(),
            "previous_snapshot_at": previous.snapshot_at.isoformat(),
            "oi_change_available": True,
            "summary": summary,
            "items": sorted(items, key=lambda item: (item["strike"], item["option_type"])),
        }
        if audit:
            AuditLogger().log(
                db,
                "OI_CHANGE_ANALYSIS_RUN",
                "Option-chain OI change analysis completed.",
                source="MARKET_FLOW",
                payload={
                    "symbol": latest.symbol,
                    "expiry": latest.expiry.isoformat(),
                    "latest_snapshot_id": latest.id,
                    "previous_snapshot_id": previous.id,
                    "flow_change_bias": summary.get("flow_change_bias"),
                },
            )
        return result

    def strike_change(
        self,
        db: Session,
        latest: OptionChainSnapshot | None,
        previous: OptionChainSnapshot | None,
        strike: float,
        option_type: str,
    ) -> dict[str, Any]:
        if latest is None:
            return {"ok": False, "status": "NO_LATEST_SNAPSHOT", "message": "No latest snapshot is available."}
        if previous is None:
            return {
                "ok": False,
                "status": "NO_PREVIOUS_SNAPSHOT",
                "message": "Capture at least two snapshots to calculate strike-level OI change.",
            }
        option_type = option_type.strip().upper()
        if option_type not in {"CE", "PE"}:
            return {"ok": False, "status": "INVALID_OPTION_TYPE", "message": "option_type must be CE or PE."}
        latest_row = self._row(db, latest.id, strike, option_type)
        previous_row = self._row(db, previous.id, strike, option_type)
        if latest_row is None or previous_row is None:
            return {
                "ok": False,
                "status": "STRIKE_NOT_FOUND",
                "message": "Strike snapshot was not found in both latest and previous snapshots.",
            }
        return {
            "ok": True,
            "status": "OK",
            "symbol": latest.symbol,
            "expiry": latest.expiry.isoformat(),
            "latest_snapshot_at": latest.snapshot_at.isoformat(),
            "previous_snapshot_at": previous.snapshot_at.isoformat(),
            "change": self._compare_row(latest_row, previous_row, latest.spot_price),
        }

    def _rows_by_key(self, db: Session, snapshot_id: int) -> dict[tuple[float, str], OptionChainStrikeSnapshot]:
        rows = db.scalars(
            select(OptionChainStrikeSnapshot).where(OptionChainStrikeSnapshot.snapshot_id == snapshot_id)
        )
        return {(float(row.strike), row.option_type): row for row in rows}

    def _row(
        self,
        db: Session,
        snapshot_id: int,
        strike: float,
        option_type: str,
    ) -> OptionChainStrikeSnapshot | None:
        return db.scalar(
            select(OptionChainStrikeSnapshot).where(
                OptionChainStrikeSnapshot.snapshot_id == snapshot_id,
                OptionChainStrikeSnapshot.strike == float(strike),
                OptionChainStrikeSnapshot.option_type == option_type,
            )
        )

    def _compare_row(
        self,
        latest: OptionChainStrikeSnapshot,
        previous: OptionChainStrikeSnapshot,
        spot_price: float | None,
    ) -> dict[str, Any]:
        oi_change = _diff(latest.oi, previous.oi)
        volume_change = _diff(latest.volume, previous.volume)
        ltp_change = _diff(latest.ltp, previous.ltp)
        classification, confidence, reason = _classify(latest.option_type, oi_change, ltp_change, latest.strike, spot_price)
        return {
            "strike": latest.strike,
            "option_type": latest.option_type,
            "security_id": latest.security_id,
            "trading_symbol": latest.trading_symbol,
            "latest_ltp": latest.ltp,
            "previous_ltp": previous.ltp,
            "ltp_change": ltp_change,
            "latest_oi": latest.oi,
            "previous_oi": previous.oi,
            "oi_change": oi_change,
            "latest_volume": latest.volume,
            "previous_volume": previous.volume,
            "volume_change": volume_change,
            "classification": classification,
            "confidence": confidence,
            "reason": reason,
        }

    def _flow_change(
        self,
        summary: dict[str, Any],
        items: list[dict[str, Any]],
        latest: OptionChainSnapshot,
        previous: OptionChainSnapshot,
    ) -> dict[str, Any]:
        ce_change = summary["ce_oi_change"]
        pe_change = summary["pe_oi_change"]
        pcr_change = summary["pcr_oi_change"]
        resistance_change = _strike_oi_change(items, latest.resistance_strike, "CE")
        support_change = _strike_oi_change(items, latest.support_strike, "PE")
        if pe_change > abs(ce_change) * 1.2 and pe_change > 0:
            bias = "BULLISH_SUPPORT"
        elif ce_change > abs(pe_change) * 1.2 and ce_change > 0:
            bias = "BEARISH_RESISTANCE"
        elif resistance_change is not None and resistance_change < 0 and _diff(latest.spot_price, previous.spot_price):
            bias = "BULLISH_BREAKOUT_SUPPORT"
        elif support_change is not None and support_change < 0:
            bias = "BEARISH_BREAKDOWN_SUPPORT"
        elif ce_change > 0 and pe_change > 0:
            bias = "RANGE_COMPRESSION"
        else:
            bias = "NO_EDGE"
        return {
            "support_strength_change": support_change,
            "resistance_strength_change": resistance_change,
            "flow_change_bias": bias,
            "buildup_summary": _count_classifications(items, "BUILDUP"),
            "unwinding_summary": _count_classifications(items, "UNWINDING"),
            "pcr_oi_trend": "RISING" if (pcr_change or 0) > 0 else "FALLING" if (pcr_change or 0) < 0 else "FLAT",
        }


def _diff(latest: Any, previous: Any) -> float | None:
    try:
        return round(float(latest) - float(previous), 2)
    except (TypeError, ValueError):
        return None


def _classify(
    option_type: str,
    oi_change: float | None,
    ltp_change: float | None,
    strike: float,
    spot_price: float | None,
) -> tuple[str, str, str]:
    if oi_change is None:
        return "UNKNOWN", "LOW", "OI change is unavailable."
    prefix = option_type
    if abs(oi_change) < 1:
        return "NEUTRAL", "MEDIUM", "OI change is flat."
    if ltp_change is None:
        if oi_change > 0:
            label = "CE_OI_BUILDUP" if option_type == "CE" else "PE_OI_BUILDUP"
            return label, "LOW", "OI increased but LTP change is unavailable."
        label = "CE_UNWINDING" if option_type == "CE" else "PE_UNWINDING"
        return label, "LOW", "OI decreased but LTP change is unavailable."
    if oi_change > 0 and ltp_change > 0:
        return f"{prefix}_LONG_BUILDUP", "HIGH", "OI and option premium increased together."
    if oi_change > 0 and ltp_change < 0:
        if option_type == "CE":
            return "CE_WRITING_PRESSURE", "HIGH", "CE OI increased while CE premium fell, suggesting call writing pressure."
        return "PE_WRITING_SUPPORT", "HIGH", "PE OI increased while PE premium fell, suggesting put writing support."
    if oi_change < 0 and ltp_change > 0:
        return f"{prefix}_SHORT_COVERING", "HIGH", "OI fell while option premium increased, suggesting short covering."
    if oi_change < 0 and ltp_change < 0:
        return f"{prefix}_UNWINDING", "HIGH", "OI and option premium fell together, suggesting long unwinding."
    return "NEUTRAL", "MEDIUM", "OI or premium changed without a clean buildup/unwinding signal."


def _top(items: list[dict[str, Any]], option_type: str, labels: set[str], limit: int = 5) -> list[dict[str, Any]]:
    rows = [
        item for item in items
        if item["option_type"] == option_type and item["classification"] in labels
    ]
    rows.sort(key=lambda item: abs(item.get("oi_change") or 0), reverse=True)
    return rows[:limit]


def _strike_oi_change(items: list[dict[str, Any]], strike: float | None, option_type: str) -> float | None:
    if strike is None:
        return None
    for item in items:
        if item["option_type"] == option_type and float(item["strike"]) == float(strike):
            return item.get("oi_change")
    return None


def _count_classifications(items: list[dict[str, Any]], token: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in items:
        label = item["classification"]
        if token in label:
            counts[label] = counts.get(label, 0) + 1
    return counts


oi_change_service = OIChangeService()


def get_oi_change_service() -> OIChangeService:
    return oi_change_service
