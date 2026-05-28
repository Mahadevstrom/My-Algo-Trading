import json
import os
import tempfile
import uuid
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, File, Query, UploadFile
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.engine.specialist.label_importer import import_jsonl_labels, import_xlsx_labels
from app.engine.specialist.market_structure_engine import MarketStructureEngine, build_market_structure_data
from app.engine.specialist.models import LabelRecord, SpecialistEngineLog
from app.engine.specialist.nifty_momentum_engine import (
    NiftyMomentumValidationEngine,
    build_nifty_momentum_data,
)
from app.engine.specialist.option_chain_engine import OptionChainEngine, build_option_chain_market_data
from app.engine.specialist.shadow_logger import log_engine_evidence

router = APIRouter(tags=["specialist-engine"])


def _decode_json(value: str | None):
    if not value:
        return None
    try:
        return json.loads(value)
    except Exception:
        return value


def _log_to_dict(record: SpecialistEngineLog) -> dict:
    return {
        "id": record.id,
        "created_at": record.created_at.isoformat() if record.created_at else None,
        "evaluation_id": record.evaluation_id,
        "signal_id": record.signal_id,
        "engine_name": record.engine_name,
        "score": record.score,
        "direction": record.direction,
        "verdict": record.verdict,
        "confidence": record.confidence,
        "blocking": record.blocking,
        "blocking_reason": record.blocking_reason,
        "warnings": _decode_json(record.warnings_json) or [],
        "evidence": _decode_json(record.evidence_json) or {},
        "evaluated_at": record.evaluated_at.isoformat() if record.evaluated_at else None,
        "signal_engine_v2_decision": record.signal_engine_v2_decision,
        "market_result": record.market_result,
        "label_source": record.label_source,
        "comparison_verdict": record.comparison_verdict,
    }


def _label_to_dict(record: LabelRecord) -> dict:
    return {
        "id": record.id,
        "created_at": record.created_at.isoformat() if record.created_at else None,
        "imported_at": record.imported_at.isoformat() if record.imported_at else None,
        "date": record.date_str,
        "time": record.time_str,
        "signal_id": record.signal_id,
        "evaluation_id": record.evaluation_id,
        "instrument": record.instrument,
        "setup": record.setup,
        "action_taken": record.action_taken,
        "direction": record.direction,
        "strike": record.strike,
        "entry_price": record.entry_price,
        "exit_price": record.exit_price,
        "result": record.result,
        "r_multiple": record.r_multiple,
        "confidence": record.confidence,
        "wrong_block_reason": record.wrong_block_reason,
        "notes": record.notes,
        "label_source": record.label_source,
    }


@router.get("/option-chain-engine/evaluate")
async def evaluate_option_chain_engine(
    underlying: str = Query(default="NIFTY"),
    db: Session = Depends(get_db),
) -> dict:
    market_data = await build_option_chain_market_data(db, underlying)
    evidence = OptionChainEngine().safe_evaluate(market_data)
    evidence.evaluation_id = str(uuid.uuid4())
    try:
        log_engine_evidence(db, evidence)
    except Exception:
        pass
    return evidence.model_dump(mode="json")


@router.get("/option-chain-engine/latest")
def latest_option_chain_engine(db: Session = Depends(get_db)) -> dict:
    record = (
        db.query(SpecialistEngineLog)
        .filter(SpecialistEngineLog.engine_name == "option_chain_engine")
        .order_by(SpecialistEngineLog.created_at.desc(), SpecialistEngineLog.id.desc())
        .first()
    )
    if not record:
        return {"status": "NO_DATA"}
    return _log_to_dict(record)


@router.get("/market-structure-engine/evaluate")
async def evaluate_market_structure_engine(
    underlying: str = Query(default="NIFTY"),
    timeframe: str = Query(default="5min"),
    db: Session = Depends(get_db),
) -> dict:
    market_data = await build_market_structure_data(db, underlying, timeframe)
    evidence = MarketStructureEngine().safe_evaluate(market_data)
    evidence.evaluation_id = str(uuid.uuid4())
    try:
        log_engine_evidence(db, evidence)
    except Exception:
        pass
    return evidence.model_dump(mode="json")


@router.get("/market-structure-engine/latest")
def latest_market_structure_engine(db: Session = Depends(get_db)) -> dict:
    record = (
        db.query(SpecialistEngineLog)
        .filter(SpecialistEngineLog.engine_name == "market_structure_engine")
        .order_by(SpecialistEngineLog.created_at.desc(), SpecialistEngineLog.id.desc())
        .first()
    )
    if not record:
        return {"status": "NO_DATA"}
    return _log_to_dict(record)


@router.get("/nifty-momentum-engine/evaluate")
async def evaluate_nifty_momentum_engine(
    underlying: str = Query(default="NIFTY"),
    db: Session = Depends(get_db),
) -> dict:
    market_data = await build_nifty_momentum_data(db, underlying)
    evidence = NiftyMomentumValidationEngine().safe_evaluate(market_data)
    evidence.evaluation_id = str(uuid.uuid4())
    try:
        log_engine_evidence(db, evidence)
    except Exception:
        pass
    return evidence.model_dump(mode="json")


@router.get("/nifty-momentum-engine/latest")
def latest_nifty_momentum_engine(db: Session = Depends(get_db)) -> dict:
    record = (
        db.query(SpecialistEngineLog)
        .filter(SpecialistEngineLog.engine_name == "nifty_momentum_engine")
        .order_by(SpecialistEngineLog.created_at.desc(), SpecialistEngineLog.id.desc())
        .first()
    )
    if not record:
        return {"status": "NO_DATA"}
    return _log_to_dict(record)


@router.get("/shadow-comparison")
def shadow_comparison(
    engine_name: str = Query(default="option_chain_engine"),
    days: int = Query(default=7, ge=1, le=90),
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
) -> dict:
    cutoff = datetime.utcnow() - timedelta(days=days)
    records = (
        db.query(SpecialistEngineLog)
        .filter(
            SpecialistEngineLog.engine_name == engine_name,
            SpecialistEngineLog.market_result.isnot(None),
            SpecialistEngineLog.created_at >= cutoff,
        )
        .order_by(SpecialistEngineLog.created_at.desc(), SpecialistEngineLog.id.desc())
        .limit(limit)
        .all()
    )
    return {"engine": engine_name, "period_days": days, "count": len(records), "items": [_log_to_dict(row) for row in records]}


@router.get("/shadow-comparison/multi-engine")
def shadow_comparison_multi_engine(
    days: int = Query(default=7, ge=1, le=90),
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
) -> list[dict]:
    cutoff = datetime.utcnow() - timedelta(days=days)
    records = (
        db.query(SpecialistEngineLog)
        .filter(SpecialistEngineLog.created_at >= cutoff)
        .order_by(SpecialistEngineLog.created_at.desc(), SpecialistEngineLog.id.desc())
        .limit(limit)
        .all()
    )
    grouped: dict[str, list[SpecialistEngineLog]] = {}
    for record in records:
        key = record.signal_id or record.evaluation_id or str(record.id)
        grouped.setdefault(key, []).append(record)

    items = []
    for evaluation_id, rows in grouped.items():
        directions = [row.direction for row in rows if row.direction in {"BULLISH", "BEARISH"}]
        agreement = len(set(directions)) <= 1 if directions else False
        first = rows[0]
        engines = {
            row.engine_name: {
                "verdict": row.verdict,
                "score": row.score,
                "direction": row.direction,
                "confidence": row.confidence,
            }
            for row in rows
        }
        items.append(
            {
                "evaluation_id": evaluation_id,
                "evaluated_at": first.evaluated_at.isoformat() if first.evaluated_at else None,
                "signal_v2_decision": first.signal_engine_v2_decision,
                "engines": engines,
                "market_result": first.market_result,
                "agreement": agreement,
            }
        )
    return items


@router.get("/shadow-comparison/summary")
def shadow_comparison_summary(
    engine_name: str = Query(default="option_chain_engine"),
    days: int = Query(default=7, ge=1, le=90),
    db: Session = Depends(get_db),
) -> dict:
    cutoff = datetime.utcnow() - timedelta(days=days)
    records = (
        db.query(SpecialistEngineLog)
        .filter(SpecialistEngineLog.engine_name == engine_name, SpecialistEngineLog.created_at >= cutoff)
        .all()
    )
    labelled = [row for row in records if row.market_result is not None]

    def pct(count: int) -> float | None:
        if not labelled:
            return None
        return round((count / len(labelled)) * 100, 2)

    agreement = sum(1 for row in labelled if row.comparison_verdict == "AGREEMENT")
    engine_better = sum(1 for row in labelled if row.comparison_verdict == "ENGINE_BETTER")
    signal_better = sum(1 for row in labelled if row.comparison_verdict == "SIGNAL_V2_BETTER")
    both_wrong = sum(1 for row in labelled if row.comparison_verdict == "BOTH_WRONG")
    blocking_correct = sum(1 for row in labelled if row.blocking and row.market_result == "NO_TRADE_CORRECT")
    blocking_wrong = sum(1 for row in labelled if row.blocking and row.market_result != "NO_TRADE_CORRECT")
    insight = "No labelled data yet. Import daily labels to see comparison results."
    if labelled:
        insight = f"{engine_name} has {len(labelled)} labelled comparison records over {days} days."
    return {
        "engine": engine_name,
        "period_days": days,
        "total_evaluated": len(records),
        "total_labelled": len(labelled),
        "agreement_rate_pct": pct(agreement),
        "engine_better_pct": pct(engine_better),
        "signal_v2_better_pct": pct(signal_better),
        "both_wrong_pct": pct(both_wrong),
        "engine_blocking_correct_pct": pct(blocking_correct),
        "engine_blocking_wrong_pct": pct(blocking_wrong),
        "insight": insight,
    }


def _save_upload(file: UploadFile) -> str:
    suffix = os.path.splitext(file.filename or "")[1]
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as handle:
        while True:
            chunk = file.file.read(1024 * 1024)
            if not chunk:
                break
            handle.write(chunk)
        return handle.name


@router.post("/labels/import-jsonl")
def upload_jsonl_labels(file: UploadFile = File(...), db: Session = Depends(get_db)) -> dict:
    path = _save_upload(file)
    try:
        return import_jsonl_labels(db, path)
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


@router.post("/labels/import-xlsx")
def upload_xlsx_labels(file: UploadFile = File(...), db: Session = Depends(get_db)) -> dict:
    path = _save_upload(file)
    try:
        return import_xlsx_labels(db, path)
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


@router.get("/labels")
def list_labels(
    days: int = Query(default=7, ge=1, le=90),
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
) -> dict:
    cutoff = datetime.utcnow() - timedelta(days=days)
    records = (
        db.query(LabelRecord)
        .filter(LabelRecord.created_at >= cutoff)
        .order_by(LabelRecord.created_at.desc(), LabelRecord.id.desc())
        .limit(limit)
        .all()
    )
    total = db.scalar(func.count(LabelRecord.id)) or 0
    return {"period_days": days, "count": len(records), "total": total, "items": [_label_to_dict(row) for row in records]}
