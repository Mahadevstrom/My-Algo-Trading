import uuid
import statistics
from datetime import datetime, timezone, timedelta
from sqlalchemy import select, and_
from sqlalchemy.orm import Session

from app.models.trade import PaperTrade
from app.analytics.confidence_calibration import calculate_confidence_calibration
from app.analytics.filter_contribution_scorer import calculate_filter_scorecard
from app.agent_evolution.failure_patterns import detect_all_patterns

def run_analysis(
    db: Session,
    lookback_days: int = 30,
    min_trades: int = 20
) -> dict:
    run_id = str(uuid.uuid4())
    started_at = datetime.now(timezone.utc)
    
    # Step 1: Get confidence calibration
    calibration = calculate_confidence_calibration(db, lookback_days, min_trades)
    
    if calibration.get("status") == "INSUFFICIENT_DATA":
        return {
            "run_id": run_id,
            "started_at": started_at.isoformat(),
            "lookback_days": lookback_days,
            "status": "INSUFFICIENT_DATA",
            "message": calibration.get("message"),
            "min_required": min_trades,
            "current_count": calibration.get("current_count", 0),
            "trades_needed": calibration.get("trades_needed", min_trades)
        }
        
    # Step 2: Get filter scorecard
    scorecard = calculate_filter_scorecard(db, lookback_days, min_trades=5) # use lower threshold for scorecard inside run_analysis if needed, or follow lookback
    
    # Step 3: Get raw trades for pattern detection
    cutoff = started_at - timedelta(days=lookback_days)
    query = select(PaperTrade).where(
        and_(
            PaperTrade.result.in_(["WIN", "LOSS", "BREAKEVEN"]),
            PaperTrade.birth_cert_version.isnot(None),
            PaperTrade.exit_time >= cutoff
        )
    )
    trades = list(db.scalars(query))
    
    # Step 4: Run failure pattern detection
    patterns = detect_all_patterns(trades)
    
    # Step 5: Build PnL summary
    total_trades = len(trades)
    win_count = sum(1 for t in trades if t.result == "WIN")
    loss_count = sum(1 for t in trades if t.result == "LOSS")
    
    pnl_values = [t.pnl for t in trades if t.pnl is not None]
    total_pnl = sum(pnl_values) if pnl_values else 0.0
    avg_pnl = statistics.mean(pnl_values) if pnl_values else 0.0
    win_rate_pct = round((win_count / total_trades) * 100, 1) if total_trades > 0 else 0.0
    best_trade_pnl = max(pnl_values) if pnl_values else 0.0
    worst_trade_pnl = min(pnl_values) if pnl_values else 0.0
    
    # Step 6: Return full analysis report
    return {
        "run_id": run_id,
        "started_at": started_at.isoformat(),
        "lookback_days": lookback_days,
        "status": "OK",
        "confidence_calibration": calibration,
        "filter_scorecard": scorecard,
        "failure_patterns": patterns,
        "trade_summary": {
            "total_trades": total_trades,
            "win_count": win_count,
            "loss_count": loss_count,
            "win_rate_pct": win_rate_pct,
            "total_pnl": round(total_pnl, 2),
            "avg_pnl": round(avg_pnl, 2),
            "best_trade_pnl": round(best_trade_pnl, 2),
            "worst_trade_pnl": round(worst_trade_pnl, 2)
        }
    }
