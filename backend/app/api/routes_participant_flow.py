from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.config import settings
from app.db.database import get_db
from app.schemas.participant_flow import ParticipantFlowCashQuickImportRequest, ParticipantFlowImportRequest
from app.services.participant_flow_import_service import get_participant_flow_import_service
from app.services.participant_flow_nse_service import get_participant_flow_nse_service
from app.services.participant_flow_service import get_participant_flow_service


router = APIRouter(prefix="/api/participant-flow", tags=["participant-flow"])


@router.get("/status")
def participant_flow_status(db: Session = Depends(get_db)) -> dict:
    return {"ok": True, **get_participant_flow_service().status(db)}


@router.post("/import")
def import_participant_flow(
    request: ParticipantFlowImportRequest,
    db: Session = Depends(get_db),
) -> dict:
    return get_participant_flow_import_service().import_records(db, request)


@router.get("/import-template")
def participant_flow_import_template() -> dict:
    service = get_participant_flow_service()
    return {
        "ok": True,
        "message": "Use quick import for daily FII/DII cash net values, or full import for derivatives/participant records.",
        "guidance": service.import_guidance(),
        "full_import_payload": {
            "records": [
                {
                    "market_date": "2026-05-26",
                    "source": "MANUAL_FII_DII",
                    "segment": "CASH",
                    "participant_type": "FII",
                    "net_value": -2000.0,
                    "is_provisional": True,
                },
                {
                    "market_date": "2026-05-26",
                    "source": "MANUAL_FII_DII",
                    "segment": "CASH",
                    "participant_type": "DII",
                    "net_value": 2000.0,
                    "is_provisional": True,
                },
            ]
        },
    }


@router.post("/import-fii-dii-cash")
def import_fii_dii_cash(
    request: ParticipantFlowCashQuickImportRequest,
    db: Session = Depends(get_db),
) -> dict:
    records = []
    if request.fii_cash_net is not None:
        records.append(
            {
                "market_date": request.market_date,
                "source": request.source,
                "segment": "CASH",
                "participant_type": "FII",
                "net_value": request.fii_cash_net,
                "is_provisional": request.is_provisional,
            }
        )
    if request.dii_cash_net is not None:
        records.append(
            {
                "market_date": request.market_date,
                "source": request.source,
                "segment": "CASH",
                "participant_type": "DII",
                "net_value": request.dii_cash_net,
                "is_provisional": request.is_provisional,
            }
        )
    result = get_participant_flow_import_service().import_records(db, ParticipantFlowImportRequest(records=records))
    result["quick_import"] = True
    result["context_after_import"] = get_participant_flow_service().context(db, "NIFTY")
    return result


@router.post("/fetch-nse")
def fetch_nse_fii_dii(
    force: bool = Query(default=False),
    db: Session = Depends(get_db),
) -> dict:
    result = get_participant_flow_nse_service().fetch_and_import(db, force=force)
    if result.get("ok"):
        result["context_after_import"] = get_participant_flow_service().context(db, "NIFTY")
    return result


@router.get("/fii-dii")
def fii_dii_summary(
    lookback_days: int = Query(default=10, ge=1, le=365),
    db: Session = Depends(get_db),
) -> dict:
    return get_participant_flow_service().fii_dii_summary(db, lookback_days)


@router.get("/derivatives")
def derivatives_summary(
    lookback_days: int = Query(default=10, ge=1, le=365),
    db: Session = Depends(get_db),
) -> dict:
    return get_participant_flow_service().derivatives_summary(db, lookback_days)


@router.get("/nifty-bias")
def nifty_participant_bias(
    lookback_days: int = Query(default=10, ge=1, le=365),
    db: Session = Depends(get_db),
) -> dict:
    return get_participant_flow_service().nifty_bias(db, lookback_days)


@router.get("/context")
def participant_context(
    symbol: str = Query(default="NIFTY"),
    lookback_days: int = Query(default=10, ge=1, le=365),
    db: Session = Depends(get_db),
) -> dict:
    return get_participant_flow_service().context(db, symbol, lookback_days)


@router.get("/explain")
def participant_flow_explain(
    symbol: str = Query(default="NIFTY"),
    lookback_days: int = Query(default=10, ge=1, le=365),
    db: Session = Depends(get_db),
) -> dict:
    return get_participant_flow_service().explain(db, symbol, lookback_days)


@router.get("/history")
def participant_flow_history(
    lookback_days: int = Query(default=30, ge=1, le=365),
    db: Session = Depends(get_db),
) -> dict:
    return get_participant_flow_service().history(db, lookback_days)


@router.post("/sample-data")
def participant_flow_sample_data(db: Session = Depends(get_db)) -> dict:
    if not settings.enable_participant_flow_sample_data:
        return {
            "ok": False,
            "status": "SAMPLE_DATA_DISABLED",
            "message": "Sample participant-flow data is disabled. Set ENABLE_PARTICIPANT_FLOW_SAMPLE_DATA=true only for local testing.",
        }
    request = ParticipantFlowImportRequest(
        records=[
            {
                "market_date": __import__("datetime").date.today().isoformat(),
                "source": "LOCAL_SAMPLE",
                "segment": "CASH",
                "participant_type": "FII",
                "buy_value": 10000,
                "sell_value": 12000,
                "net_value": -2000,
                "is_provisional": True,
            },
            {
                "market_date": __import__("datetime").date.today().isoformat(),
                "source": "LOCAL_SAMPLE",
                "segment": "CASH",
                "participant_type": "DII",
                "buy_value": 9000,
                "sell_value": 7000,
                "net_value": 2000,
                "is_provisional": True,
            },
        ]
    )
    result = get_participant_flow_import_service().import_records(db, request)
    result["sample_data"] = True
    return result
