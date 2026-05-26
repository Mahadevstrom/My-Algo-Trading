from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from app.backtest.backtest_runner import BacktestRunner
from app.db.database import get_db
from app.models.backtest_run import BacktestRunRead
from app.models.backtest_trade import BacktestTradeRead


router = APIRouter(prefix="/api/backtest", tags=["backtest"])
walk_forward_router = APIRouter(tags=["backtest"])


class BacktestRunRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=160)
    underlying: str = Field(..., min_length=1, max_length=50)
    expiry: str = Field(..., min_length=1, max_length=30)
    interval: str = Field(..., min_length=1, max_length=20)
    from_date: str = Field(..., min_length=1)
    to_date: str = Field(..., min_length=1)
    initial_capital: float = Field(..., gt=0)
    max_risk_per_trade: float = Field(..., gt=0)
    lot_size: int = Field(..., gt=0)
    entry_model: Literal["NEXT_CANDLE_OPEN", "CURRENT_CANDLE_CLOSE"] = "NEXT_CANDLE_OPEN"
    same_candle_priority: Literal["SL_FIRST", "TARGET_FIRST"] = "SL_FIRST"
    strategy_config: dict | None = None

    @field_validator("underlying", mode="before")
    @classmethod
    def normalize_underlying(cls, value: str) -> str:
        return str(value).strip().upper()


class BacktestWalkForwardRequest(BacktestRunRequest):
    in_sample_days: int = Field(60, gt=0)
    out_of_sample_days: int = Field(20, gt=0)


class BacktestOptimizeRequest(BacktestRunRequest):
    name: str = Field("Optimization Run", min_length=1, max_length=160)
    stop_loss_pct_range: list[float] = Field(default=[10.0, 25.0, 5.0])
    target_1_pct_range: list[float] = Field(default=[15.0, 35.0, 5.0])


@router.post("/run")
def run_backtest(payload: BacktestRunRequest, db: Session = Depends(get_db)) -> dict:
    return BacktestRunner().run(db, payload)


@router.post("/walk-forward")
def run_backtest_walk_forward(payload: BacktestWalkForwardRequest, db: Session = Depends(get_db)) -> dict:
    # Paper/backtest-only validation route: no broker orders, live orders, or real execution are placed here.
    return BacktestRunner().walk_forward(db, payload)


@router.post("/optimize")
def run_backtest_optimization(payload: BacktestOptimizeRequest, db: Session = Depends(get_db)) -> dict:
    # Paper/backtest-only validation route: no broker orders, live orders, or real execution are placed here.
    return BacktestRunner().optimize(db, payload)


@walk_forward_router.post("/api/backtest-walk-forward")
def run_backtest_walk_forward_alias(payload: BacktestWalkForwardRequest, db: Session = Depends(get_db)) -> dict:
    # Paper/backtest-only validation route: no broker orders, live orders, or real execution are placed here.
    return BacktestRunner().walk_forward(db, payload)


@router.get("/runs")
def list_backtest_runs(db: Session = Depends(get_db)) -> dict:
    runs = BacktestRunner().list_runs(db)
    return {"ok": True, "count": len(runs), "items": [BacktestRunRead.model_validate(item) for item in runs]}


@router.get("/runs/{run_id}")
def get_backtest_run(run_id: int, db: Session = Depends(get_db)) -> BacktestRunRead:
    run = BacktestRunner().get_run(db, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Backtest run not found.")
    return BacktestRunRead.model_validate(run)


@router.get("/runs/{run_id}/trades")
def get_backtest_trades(run_id: int, db: Session = Depends(get_db)) -> dict:
    trades = BacktestRunner().trades(db, run_id)
    return {"ok": True, "run_id": run_id, "count": len(trades), "items": [BacktestTradeRead.model_validate(item) for item in trades]}


@router.get("/runs/{run_id}/equity-curve")
def get_backtest_equity_curve(run_id: int, db: Session = Depends(get_db)) -> dict:
    return BacktestRunner().equity_curve(db, run_id)


@router.get("/runs/{run_id}/metrics")
def get_backtest_metrics(run_id: int, db: Session = Depends(get_db)) -> dict:
    return BacktestRunner().metrics(db, run_id)


@router.get("/runs/{run_id}/rejections")
def get_backtest_rejections(run_id: int, db: Session = Depends(get_db)) -> dict:
    result = BacktestRunner().rejections(db, run_id)
    result["items"] = [BacktestTradeRead.model_validate(item) for item in result["items"]]
    return result
