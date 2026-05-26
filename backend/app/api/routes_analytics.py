from fastapi import APIRouter, Depends, HTTPException, Query
from typing import Dict, Any
from sqlalchemy.orm import Session
from pydantic import BaseModel


from app.db.database import get_db
from app.services.data_science_service import data_science_service
from app.engine.paper_engine import PaperEngine

router = APIRouter(prefix="/api/analytics", tags=["Analytics & Data Science"])

@router.get("/trade-distribution")
async def get_trade_distribution(db: Session = Depends(get_db)):
    """
    Returns the historical trade distribution curve for the Research Lab UI.
    """
    try:
        # Fetch all historical paper trades
        trades = PaperEngine().list_trades(db)
        trade_dicts = [t.model_dump(mode="json") for t in trades]
        
        distribution = data_science_service.calculate_trade_distribution(trade_dicts)
        return distribution
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/advanced-metrics")
async def get_advanced_metrics(db: Session = Depends(get_db)):
    """
    Returns advanced metrics like Sharpe Ratio and Max Drawdown.
    """
    try:
        trades = PaperEngine().list_trades(db)
        trade_dicts = [t.model_dump(mode="json") for t in trades]
        
        metrics = data_science_service.compute_advanced_metrics(trade_dicts)
        return metrics
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/market-regime")
async def get_market_regime(
    symbol: str,
    interval: str,
    db: Session = Depends(get_db)
):
    """
    Runs K-Means clustering on candles to classify the active market regime.
    """
    try:
        result = data_science_service.classify_market_regime(db, symbol, interval)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

class MonteCarloRequest(BaseModel):
    source: str = "custom"
    initial_capital: float = 100000.0
    risk_per_trade_pct: float = 5.0
    num_simulations: int = 2000
    num_trades_per_run: int = 100
    ruin_threshold_pct: float = 50.0
    win_rate: float = 55.0
    avg_win: float = 5000.0
    avg_loss: float = 3000.0

@router.post("/monte-carlo")
async def run_monte_carlo_stress_test(
    payload: MonteCarloRequest,
    db: Session = Depends(get_db)
):
    """
    Executes a Monte Carlo stress-testing simulation using trade distributions.
    """
    try:
        trades_pnl = []
        if payload.source == "historical":
            trades = PaperEngine().list_trades(db)
            # Filter for closed trades
            trades_pnl = [t.pnl for t in trades if t.pnl is not None and t.result in ["WIN", "LOSS", "BREAKEVEN"]]
            
        result = data_science_service.run_monte_carlo(
            trades_pnl=trades_pnl,
            initial_capital=payload.initial_capital,
            risk_per_trade_pct=payload.risk_per_trade_pct,
            num_simulations=payload.num_simulations,
            num_trades_per_run=payload.num_trades_per_run,
            ruin_threshold_pct=payload.ruin_threshold_pct,
            win_rate=payload.win_rate,
            avg_win=payload.avg_win,
            avg_loss=payload.avg_loss,
            source=payload.source
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/confidence-calibration")
async def get_confidence_calibration(
    lookback_days: int = Query(default=30, ge=7, le=90),
    min_trades: int = Query(default=20, ge=5, le=100),
    db: Session = Depends(get_db)
):
    try:
        from app.analytics.confidence_calibration import (
            calculate_confidence_calibration
        )
        return calculate_confidence_calibration(db, lookback_days, min_trades)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/filter-scorecard")
async def get_filter_scorecard(
    lookback_days: int = Query(default=30, ge=7, le=90),
    min_trades: int = Query(default=15, ge=5, le=100),
    db: Session = Depends(get_db)
):
    try:
        from app.analytics.filter_contribution_scorer import (
            calculate_filter_scorecard
        )
        return calculate_filter_scorecard(db, lookback_days, min_trades)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))



