from typing import Any

from pydantic import BaseModel, Field


class StrategyMetrics(BaseModel):
    total_trades: int = 0
    open_trades: int = 0
    closed_trades: int = 0
    wins: int = 0
    losses: int = 0
    breakeven: int = 0
    win_rate: float = 0.0
    gross_pnl: float = 0.0
    net_pnl: float = 0.0
    average_win: float = 0.0
    average_loss: float = 0.0
    expectancy: float = 0.0
    profit_factor: float = 0.0
    max_drawdown: float = 0.0
    average_holding_time: float = 0.0
    max_losing_streak: int = 0
    average_signal_score: float = 0.0
    rejected_signal_count: int = 0
    rejection_reason_breakdown: dict[str, int] = Field(default_factory=dict)


class StrategyEvaluationStatus(BaseModel):
    enabled: bool
    mode: str
    live_order_status: str
    lookback_days: int
    min_sample_size: int
    source: str = "READ_ONLY_ANALYTICS"


class StrategyHealthScore(BaseModel):
    status: str
    score: float
    label: str
    reasons: list[str] = Field(default_factory=list)
    metrics: StrategyMetrics


class BacktestVsPaperComparison(BaseModel):
    status: str
    message: str
    backtest: StrategyMetrics
    paper: StrategyMetrics
    deltas: dict[str, Any] = Field(default_factory=dict)


class SignalV1VsV2Comparison(BaseModel):
    status: str
    latest_v1: dict[str, Any] | None = None
    latest_v2: dict[str, Any] | None = None
    v2_is_stricter: bool = False
    v2_rejected_weak_signal: bool = False
    v2_has_better_context: bool = True
    recommendation: str

