import asyncio
import json
from datetime import date, datetime, timedelta, timezone
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.api.routes_option_chain import _build_chain_analysis
from app.audit.audit_logger import AuditLogger
from app.config import settings
from app.engine.dhan_instrument_importer import DhanInstrumentImporter
from app.market_flow.oi_change_service import get_oi_change_service
from app.models.instrument import InstrumentMaster
from app.models.option_chain_snapshot import OptionChainSnapshot, OptionChainStrikeSnapshot
from app.schemas.option_chain_snapshot import OptionChainSnapshotSummary, StrikeSnapshotSummary


class OptionChainSnapshotService:
    def __init__(self) -> None:
        self._last_audit_at_by_key: dict[str, datetime] = {}
        self._task: asyncio.Task | None = None

    def start_scheduler(self) -> None:
        if not settings.enable_option_chain_snapshots or not settings.option_chain_snapshot_auto_capture:
            return
        if self._task is not None and not self._task.done():
            return
        self._task = asyncio.create_task(self._scheduler_loop())

    async def shutdown_scheduler(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def _scheduler_loop(self) -> None:
        from app.db.database import SessionLocal
        from app.services.session_gate_service import get_session_gate_service
        
        # Wait a small warmup duration before first capture
        await asyncio.sleep(5)
        
        while True:
            try:
                with SessionLocal() as db:
                    gate = get_session_gate_service().status()
                    if gate.session_status == "ACTIVE_MORNING" or gate.session_status == "MIDDAY_CAUTION" or gate.session_status == "ACTIVE_AFTERNOON" or gate.session_status == "SQUARE_OFF_WINDOW" or gate.is_market_open:
                        await self.capture_snapshot(
                            db,
                            symbol=settings.option_chain_snapshot_default_symbol,
                            expiry=None,
                        )
            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"Error in option-chain snapshot scheduler: {e}")
            
            await asyncio.sleep(max(10, settings.option_chain_snapshot_interval_seconds))

    def status(self, db: Session) -> dict[str, Any]:
        latest = self.get_latest_snapshot(db, settings.option_chain_snapshot_default_symbol)
        return {
            "enabled": settings.enable_option_chain_snapshots,
            "auto_capture": settings.option_chain_snapshot_auto_capture,
            "default_symbol": settings.option_chain_snapshot_default_symbol,
            "interval_seconds": settings.option_chain_snapshot_interval_seconds,
            "retention_days": settings.option_chain_snapshot_retention_days,
            "latest_snapshot_at": latest.snapshot_at.isoformat() if latest else None,
            "snapshot_count": db.scalar(select(func.count(OptionChainSnapshot.id))) or 0,
            "live_order_status": settings.safety_status["live_order_status"],
        }

    async def capture_snapshot(
        self,
        db: Session,
        symbol: str = "NIFTY",
        expiry: date | None = None,
        max_strikes: int | None = None,
    ) -> dict[str, Any]:
        symbol = symbol.strip().upper()
        if not settings.enable_option_chain_snapshots:
            return {
                "ok": False,
                "status": "SNAPSHOTS_DISABLED",
                "message": "Option-chain snapshots are disabled by config.",
            }
        resolved_expiry = self._resolve_expiry(db, symbol, expiry)
        if resolved_expiry is None:
            return {
                "ok": False,
                "status": "NO_VALID_EXPIRY",
                "message": "No valid expiry found for this symbol.",
                "symbol": symbol,
            }
        warnings = []
        latest_existing = self.get_latest_snapshot(db, symbol, resolved_expiry)
        if latest_existing is not None:
            age_seconds = (datetime.now(timezone.utc) - latest_existing.snapshot_at.astimezone(timezone.utc)).total_seconds()
            if age_seconds < settings.option_chain_snapshot_min_seconds_between:
                warnings.append(
                    "Snapshot was captured sooner than OPTION_CHAIN_SNAPSHOT_MIN_SECONDS_BETWEEN; "
                    "manual capture is allowed, but changes may be flat."
                )
        chain = await _build_chain_analysis(db, symbol, resolved_expiry)
        if not chain.get("ok"):
            self._audit(
                db,
                "OPTION_CHAIN_SNAPSHOT_FAILED",
                "Option-chain snapshot capture failed.",
                "WARNING",
                {"symbol": symbol, "expiry": resolved_expiry.isoformat(), "status": chain.get("status")},
            )
            return {
                "ok": False,
                "status": chain.get("status", "OPTION_CHAIN_UNAVAILABLE"),
                "message": chain.get("message", "Option chain unavailable."),
                "symbol": symbol,
                "expiry": resolved_expiry.isoformat(),
            }
        strikes = self._limit_strikes(
            chain.get("strikes") or [],
            chain.get("summary") or {},
            max_strikes or settings.option_chain_snapshot_max_strikes,
        )
        if not strikes:
            return {
                "ok": False,
                "status": "NO_STRIKES",
                "message": "Option-chain analyzer returned no strikes.",
                "symbol": symbol,
                "expiry": resolved_expiry.isoformat(),
            }
        snapshot_at = datetime.now(timezone.utc)
        summary = chain.get("summary") or {}
        header = OptionChainSnapshot(
            source="DHAN",
            symbol=symbol,
            underlying=symbol,
            expiry=resolved_expiry,
            spot_price=_num(summary.get("spot_price")),
            atm_strike=_num(summary.get("atm_strike")),
            pcr_oi=_num(summary.get("pcr_oi")),
            pcr_volume=_num(summary.get("pcr_volume")),
            total_ce_oi=_sum(strikes, "ce_oi"),
            total_pe_oi=_sum(strikes, "pe_oi"),
            total_ce_volume=_sum(strikes, "ce_volume"),
            total_pe_volume=_sum(strikes, "pe_volume"),
            support_strike=_num(summary.get("support_strike")),
            resistance_strike=_num(summary.get("resistance_strike")),
            chain_bias=summary.get("chain_bias"),
            snapshot_at=snapshot_at,
            raw_summary_json=_safe_json(summary) if settings.option_chain_snapshot_store_raw else None,
        )
        db.add(header)
        db.flush()

        instrument_map = self._option_instrument_map(db, symbol, resolved_expiry)
        saved_strikes = 0
        for row in strikes:
            strike = _num(row.get("strike"))
            if strike is None:
                continue
            for option_type in ("CE", "PE"):
                payload = self._strike_payload(
                    header.id,
                    symbol,
                    resolved_expiry,
                    snapshot_at,
                    row,
                    option_type,
                    instrument_map.get((round(strike, 2), option_type)),
                    summary.get("spot_price"),
                )
                if payload is None:
                    continue
                db.add(OptionChainStrikeSnapshot(**payload))
                saved_strikes += 1
        db.commit()
        db.refresh(header)
        self._audit(
            db,
            "OPTION_CHAIN_SNAPSHOT_CAPTURED",
            "Option-chain snapshot captured.",
            "INFO",
            {
                "symbol": symbol,
                "expiry": resolved_expiry.isoformat(),
                "snapshot_id": header.id,
                "strike_rows": saved_strikes,
            },
        )
        return {
            "ok": True,
            "status": "CAPTURED",
            "message": "Option-chain snapshot captured.",
            "snapshot": OptionChainSnapshotSummary.model_validate(header).model_dump(mode="json"),
            "strike_rows_saved": saved_strikes,
            "warnings": warnings,
        }

    def get_latest_snapshot(self, db: Session, symbol: str, expiry: date | None = None) -> OptionChainSnapshot | None:
        query = select(OptionChainSnapshot).where(OptionChainSnapshot.symbol == symbol.strip().upper())
        if expiry:
            query = query.where(OptionChainSnapshot.expiry == expiry)
        return db.scalar(query.order_by(OptionChainSnapshot.snapshot_at.desc(), OptionChainSnapshot.id.desc()).limit(1))

    def get_previous_snapshot(
        self,
        db: Session,
        symbol: str,
        expiry: date | None = None,
        before_snapshot_at: datetime | None = None,
    ) -> OptionChainSnapshot | None:
        latest = self.get_latest_snapshot(db, symbol, expiry)
        if latest is None:
            return None
        before = before_snapshot_at or latest.snapshot_at
        query = (
            select(OptionChainSnapshot)
            .where(
                OptionChainSnapshot.symbol == symbol.strip().upper(),
                OptionChainSnapshot.expiry == latest.expiry if expiry is None else OptionChainSnapshot.expiry == expiry,
                OptionChainSnapshot.snapshot_at < before,
            )
            .order_by(OptionChainSnapshot.snapshot_at.desc(), OptionChainSnapshot.id.desc())
            .limit(1)
        )
        return db.scalar(query)

    def get_snapshot_pair(self, db: Session, symbol: str, expiry: date | None = None) -> tuple[OptionChainSnapshot | None, OptionChainSnapshot | None]:
        latest = self.get_latest_snapshot(db, symbol, expiry)
        if latest is None:
            return None, None
        previous = self.get_previous_snapshot(db, symbol, latest.expiry, latest.snapshot_at)
        return latest, previous

    def get_snapshot_history(self, db: Session, symbol: str, expiry: date | None = None, limit: int = 20) -> list[OptionChainSnapshot]:
        query = select(OptionChainSnapshot).where(OptionChainSnapshot.symbol == symbol.strip().upper())
        if expiry:
            query = query.where(OptionChainSnapshot.expiry == expiry)
        return list(
            db.scalars(
                query.order_by(OptionChainSnapshot.snapshot_at.desc(), OptionChainSnapshot.id.desc()).limit(max(1, min(limit, 200)))
            )
        )

    def get_strike_snapshots(self, db: Session, snapshot_id: int) -> dict[str, Any]:
        snapshot = db.get(OptionChainSnapshot, snapshot_id)
        if snapshot is None:
            return {"ok": False, "status": "SNAPSHOT_NOT_FOUND", "message": "Snapshot id was not found."}
        rows = list(
            db.scalars(
                select(OptionChainStrikeSnapshot)
                .where(OptionChainStrikeSnapshot.snapshot_id == snapshot_id)
                .order_by(OptionChainStrikeSnapshot.strike, OptionChainStrikeSnapshot.option_type)
            )
        )
        return {
            "ok": True,
            "snapshot": OptionChainSnapshotSummary.model_validate(snapshot).model_dump(mode="json"),
            "count": len(rows),
            "items": [StrikeSnapshotSummary.model_validate(row).model_dump(mode="json") for row in rows],
        }

    def changes(self, db: Session, symbol: str, expiry: date | None = None) -> dict[str, Any]:
        latest, previous = self.get_snapshot_pair(db, symbol, expiry)
        return get_oi_change_service().analyze_snapshot_pair(db, latest, previous)

    def strike_change(
        self,
        db: Session,
        symbol: str,
        expiry: date | None,
        strike: float,
        option_type: str,
    ) -> dict[str, Any]:
        latest, previous = self.get_snapshot_pair(db, symbol, expiry)
        return get_oi_change_service().strike_change(db, latest, previous, strike, option_type)

    def purge_old_snapshots(self, db: Session, retention_days: int | None = None) -> dict[str, Any]:
        days = retention_days or settings.option_chain_snapshot_retention_days
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        ids = list(db.scalars(select(OptionChainSnapshot.id).where(OptionChainSnapshot.snapshot_at < cutoff)))
        if not ids:
            return {"ok": True, "status": "NO_OLD_SNAPSHOTS", "deleted_snapshots": 0, "retention_days": days}
        db.execute(delete(OptionChainStrikeSnapshot).where(OptionChainStrikeSnapshot.snapshot_id.in_(ids)))
        db.execute(delete(OptionChainSnapshot).where(OptionChainSnapshot.id.in_(ids)))
        db.commit()
        self._audit(
            db,
            "OPTION_CHAIN_SNAPSHOT_PURGED",
            "Old option-chain snapshots purged.",
            "INFO",
            {"deleted_snapshots": len(ids), "retention_days": days},
        )
        return {"ok": True, "status": "PURGED", "deleted_snapshots": len(ids), "retention_days": days}

    def _resolve_expiry(self, db: Session, symbol: str, requested: date | None) -> date | None:
        if requested:
            return requested
        today = datetime.now(timezone.utc).date()
        expiries = DhanInstrumentImporter().expiries(db, symbol)
        future = [item for item in expiries if item >= today]
        return future[0] if future else expiries[0] if expiries else None

    def _limit_strikes(self, strikes: list[dict[str, Any]], summary: dict[str, Any], max_strikes: int) -> list[dict[str, Any]]:
        max_strikes = max(1, min(max_strikes, 200))
        if len(strikes) <= max_strikes:
            return strikes
        atm = _num(summary.get("atm_strike"))
        if atm is None:
            return sorted(strikes, key=lambda row: _num(row.get("strike")) or 0)[:max_strikes]
        ranked = sorted(strikes, key=lambda row: abs((_num(row.get("strike")) or atm) - atm))
        return sorted(ranked[:max_strikes], key=lambda row: _num(row.get("strike")) or 0)

    def _option_instrument_map(
        self,
        db: Session,
        symbol: str,
        expiry: date,
    ) -> dict[tuple[float, str], InstrumentMaster]:
        items = DhanInstrumentImporter().options(db, symbol, expiry)
        mapped = {}
        for item in items:
            if item.strike is not None and item.option_type:
                mapped[(round(float(item.strike), 2), item.option_type)] = item
        return mapped

    def _strike_payload(
        self,
        snapshot_id: int,
        symbol: str,
        expiry: date,
        snapshot_at: datetime,
        row: dict[str, Any],
        option_type: str,
        instrument: InstrumentMaster | None,
        spot_price: Any,
    ) -> dict[str, Any] | None:
        prefix = option_type.lower()
        strike = _num(row.get("strike"))
        oi = _num(row.get(f"{prefix}_oi"))
        volume = _num(row.get(f"{prefix}_volume"))
        ltp = _num(row.get(f"{prefix}_ltp"))
        if strike is None or (oi is None and volume is None and ltp is None):
            return None
        spot = _num(spot_price)
        return {
            "snapshot_id": snapshot_id,
            "source": "DHAN",
            "symbol": symbol,
            "underlying": symbol,
            "expiry": expiry,
            "strike": strike,
            "option_type": option_type,
            "security_id": instrument.security_id if instrument else None,
            "trading_symbol": instrument.trading_symbol if instrument else None,
            "ltp": ltp,
            "oi": oi,
            "volume": volume,
            "iv": _num(row.get(f"{prefix}_iv")),
            "bid_price": _num(row.get(f"{prefix}_bid")),
            "ask_price": _num(row.get(f"{prefix}_ask")),
            "bid_qty": _num(row.get(f"{prefix}_bid_quantity")),
            "ask_qty": _num(row.get(f"{prefix}_ask_quantity")),
            "liquidity_score": _num(row.get(f"{prefix}_liquidity_score")),
            "moneyness": row.get("moneyness") or row.get(f"{prefix}_moneyness"),
            "distance_from_spot": round(strike - spot, 2) if spot is not None else None,
            "snapshot_at": snapshot_at,
            "raw_json": _safe_json(row) if settings.option_chain_snapshot_store_raw else None,
        }

    def _audit(
        self,
        db: Session,
        event_type: str,
        message: str,
        severity: str,
        payload: dict[str, Any],
    ) -> None:
        now = datetime.now(timezone.utc)
        key = f"{event_type}:{payload.get('symbol')}:{payload.get('expiry')}"
        last = self._last_audit_at_by_key.get(key)
        if last and (now - last).total_seconds() < settings.option_chain_snapshot_audit_throttle_seconds:
            return
        self._last_audit_at_by_key[key] = now
        AuditLogger().log(db, event_type, message, severity=severity, source="MARKET_FLOW", payload=payload)


def _sum(rows: list[dict[str, Any]], key: str) -> float:
    return round(sum(_num(row.get(key)) or 0 for row in rows), 2)


def _num(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _safe_json(value: Any) -> str:
    return json.dumps(value, default=str)[:20000]


option_chain_snapshot_service = OptionChainSnapshotService()


def get_option_chain_snapshot_service() -> OptionChainSnapshotService:
    return option_chain_snapshot_service
