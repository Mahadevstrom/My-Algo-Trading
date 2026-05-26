import json

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.engine.signal_engine import SignalEngine
from app.engine.signal_engine_v1 import SignalEngineV1
from app.models.signal import (
    SignalAnalysisRequest,
    SignalAnalyzeAndPaperResponse,
    SignalGenerateRequest,
    SignalRecordRead,
    SignalResponse,
)


router = APIRouter(prefix="/api/signals", tags=["signals"])


@router.post("/generate", response_model=SignalResponse)
def generate_signal(payload: SignalGenerateRequest) -> SignalResponse:
    return SignalEngine().generate(payload)


@router.post("/analyze")
async def analyze_signal(
    payload: SignalAnalysisRequest,
    db: Session = Depends(get_db),
) -> dict:
    signal = await SignalEngineV1().analyze(db, payload)
    return signal.model_dump(mode="json")


@router.post("/analyze-and-paper")
async def analyze_and_paper(
    payload: SignalAnalysisRequest,
    db: Session = Depends(get_db),
) -> dict:
    signal, paper_trade, message = await SignalEngineV1().analyze_and_paper(db, payload)
    response = SignalAnalyzeAndPaperResponse(
        signal=signal,
        paper_trade=paper_trade,
        message=message,
    )
    return response.model_dump(mode="json")


@router.get("/latest")
def latest_signals(
    limit: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
) -> dict:
    records = SignalEngineV1().latest(db, limit=limit)
    return {
        "count": len(records),
        "items": [_signal_record_to_dict(record) for record in records],
    }


def _signal_record_to_dict(record) -> dict:
    body = SignalRecordRead.model_validate(record).model_dump(mode="json")
    body["reason"] = _json_list(body.pop("reason_json"))
    body["warnings"] = _json_list(body.pop("warnings_json"))
    return body


def _json_list(value: str) -> list[str]:
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return []
    return parsed if isinstance(parsed, list) else []
