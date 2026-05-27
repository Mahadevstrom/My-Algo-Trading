import uuid
from collections import Counter, defaultdict
from datetime import datetime, timedelta

from fastapi import APIRouter, Body, Depends, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.engine.context.context_classifier import ContextClassifier
from app.engine.context.context_logger import log_context_classification
from app.engine.context.event_calendar import add_event, get_upcoming_events
from app.engine.context.models import ContextClassificationLog
from app.models.trade import PaperTrade

router = APIRouter(tags=["context-classifier"])


def _log_to_dict(record: ContextClassificationLog) -> dict:
    return {
        "id": record.id,
        "created_at": record.created_at.isoformat() if record.created_at else None,
        "evaluation_id": record.evaluation_id,
        "signal_id": record.signal_id,
        "context_type": record.context_type,
        "context_confidence": record.context_confidence,
        "secondary_context": record.secondary_context,
        "ist_time_str": record.ist_time_str,
        "ist_date_str": record.ist_date_str,
        "day_of_week": record.day_of_week,
        "is_expiry_day": record.is_expiry_day,
        "is_monthly_expiry": record.is_monthly_expiry,
        "days_to_expiry": record.days_to_expiry,
        "opening_gap_pct": record.opening_gap_pct,
        "vix_value": record.vix_value,
        "vix_vs_20day_avg_pct": record.vix_vs_20day_avg_pct,
        "is_known_event_day": record.is_known_event_day,
        "known_event_name": record.known_event_name,
        "data_quality_status": record.data_quality_status,
        "confidence_modifier": record.confidence_modifier,
        "context_summary": record.context_summary,
        "signal_v2_decision": record.signal_v2_decision,
    }


@router.get("/classify")
def classify_context(underlying: str = Query(default="NIFTY"), db: Session = Depends(get_db)) -> dict:
    context = ContextClassifier().safe_classify(db=db, market_data={}, underlying=underlying)
    context.evaluation_id = str(uuid.uuid4())
    try:
        log_context_classification(db, context)
    except Exception:
        pass
    return context.model_dump(mode="json")


@router.get("/latest")
def latest_context(db: Session = Depends(get_db)) -> dict:
    record = (
        db.query(ContextClassificationLog)
        .order_by(ContextClassificationLog.created_at.desc(), ContextClassificationLog.id.desc())
        .first()
    )
    if not record:
        return {"status": "NO_DATA"}
    return _log_to_dict(record)


@router.get("/history")
def context_history(
    days: int = Query(default=7, ge=1, le=90),
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
) -> dict:
    cutoff = datetime.utcnow() - timedelta(days=days)
    records = (
        db.query(ContextClassificationLog)
        .filter(ContextClassificationLog.created_at >= cutoff)
        .order_by(ContextClassificationLog.created_at.desc(), ContextClassificationLog.id.desc())
        .limit(limit)
        .all()
    )
    by_day: dict[str, Counter] = defaultdict(Counter)
    for record in records:
        by_day[record.ist_date_str or "UNKNOWN"][record.context_type] += 1
    dominant = {
        day: counter.most_common(1)[0][0]
        for day, counter in by_day.items()
        if counter
    }
    return {"period_days": days, "count": len(records), "daily_dominant_context": dominant, "items": [_log_to_dict(row) for row in records]}


@router.get("/summary")
def context_summary(
    days: int = Query(default=30, ge=1, le=180),
    db: Session = Depends(get_db),
) -> dict:
    cutoff = datetime.utcnow() - timedelta(days=days)
    logs = (
        db.query(ContextClassificationLog)
        .filter(ContextClassificationLog.created_at >= cutoff)
        .all()
    )
    distribution = dict(Counter(row.context_type for row in logs))
    trades = (
        db.query(PaperTrade)
        .filter(PaperTrade.context_type_at_entry.isnot(None), PaperTrade.entry_time >= cutoff)
        .all()
    )
    grouped: dict[str, list[PaperTrade]] = defaultdict(list)
    for trade in trades:
        grouped[trade.context_type_at_entry].append(trade)
    win_rates = {}
    best_context = None
    worst_context = None
    best_rate = -1.0
    worst_rate = 101.0
    for context_type, items in grouped.items():
        if len(items) < 3:
            win_rates[context_type] = {"trade_count": len(items), "win_rate_pct": None}
            continue
        wins = sum(1 for trade in items if str(trade.result).upper() == "WIN")
        rate = round(wins / len(items) * 100, 2)
        win_rates[context_type] = {"trade_count": len(items), "win_rate_pct": rate}
        if rate > best_rate:
            best_rate = rate
            best_context = context_type
        if rate < worst_rate:
            worst_rate = rate
            worst_context = context_type
    insight = "No context-labelled paper trade data yet. Let shadow context logs accumulate during paper trading."
    if any(item.get("win_rate_pct") is not None for item in win_rates.values()):
        insight = f"Best context is {best_context}; weakest context is {worst_context} over the last {days} days."
    return {
        "period_days": days,
        "context_distribution": distribution,
        "context_win_rates": win_rates,
        "best_context": best_context,
        "worst_context": worst_context,
        "insight": insight,
    }


@router.get("/events")
def upcoming_context_events(days_ahead: int = Query(default=7, ge=0, le=365)) -> dict:
    events = get_upcoming_events(days_ahead)
    return {"days_ahead": days_ahead, "count": len(events), "events": events}


@router.post("/events")
def add_context_event(payload: dict = Body(...)) -> dict:
    add_event(str(payload.get("date")), str(payload.get("name")), str(payload.get("impact") or "MEDIUM"))
    return {"ok": True, "events": get_upcoming_events(365)}
