import statistics
from datetime import datetime, timezone, timedelta
from typing import Any
from sqlalchemy import select, and_
from sqlalchemy.orm import Session

from app.models.trade import PaperTrade
from app.config import settings

def calculate_confidence_calibration(
    db: Session,
    lookback_days: int = 30,
    min_trades: int = 20
) -> dict:
    # STEP 4A: Query closed trades with birth certificates
    cutoff = datetime.now(timezone.utc) - timedelta(days=lookback_days)
    
    query = select(PaperTrade).where(
        and_(
            PaperTrade.result.in_(["WIN", "LOSS", "BREAKEVEN"]),
            PaperTrade.confidence_score_at_entry.isnot(None),
            PaperTrade.birth_cert_version.isnot(None),
            PaperTrade.exit_time >= cutoff
        )
    )
    trades = list(db.scalars(query))
    count = len(trades)
    
    if count < min_trades:
        return {
            "status": "INSUFFICIENT_DATA",
            "message": "Not enough closed trades with birth certificates to run calibration. Keep paper trading.",
            "min_required": min_trades,
            "current_count": count,
            "trades_needed": min_trades - count,
            "note": "Birth certificates are attached to trades created after Phase 3.1 was deployed."
        }

    # STEP 4B: Define the 6 confidence buckets
    BUCKETS = [
        {"key": "50-60", "display": "50% – 60%", "low": 0.50, "high": 0.60},
        {"key": "60-65", "display": "60% – 65%", "low": 0.60, "high": 0.65},
        {"key": "65-70", "display": "65% – 70%", "low": 0.65, "high": 0.70},
        {"key": "70-75", "display": "70% – 75%", "low": 0.70, "high": 0.75},
        {"key": "75-80", "display": "75% – 80%", "low": 0.75, "high": 0.80},
        {"key": "80+",   "display": "80% +",     "low": 0.80, "high": 1.01},
    ]
    
    bucket_results = []
    total_trades = count
    
    for bucket in BUCKETS:
        low = bucket["low"]
        high = bucket["high"]
        
        # Filter trades in this bucket
        bucket_trades = []
        for t in trades:
            val = t.confidence_score_at_entry
            if val is not None:
                # Normalize if stored as percentage
                if val > 1.0:
                    val = val / 100.0
                if low <= val < high:
                    bucket_trades.append(t)
        
        b_count = len(bucket_trades)
        
        if b_count > 0:
            win_count = sum(1 for t in bucket_trades if t.result == "WIN")
            loss_count = sum(1 for t in bucket_trades if t.result == "LOSS")
            breakeven_count = sum(1 for t in bucket_trades if t.result == "BREAKEVEN")
            
            win_rate_pct = round((win_count / b_count) * 100, 1)
            avg_pnl = round(statistics.mean([t.pnl for t in bucket_trades]), 2)
            
            win_pnls = [t.pnl for t in bucket_trades if t.result == "WIN"]
            avg_pnl_wins = round(statistics.mean(win_pnls), 2) if win_pnls else None
            
            loss_pnls = [t.pnl for t in bucket_trades if t.result == "LOSS"]
            avg_pnl_losses = round(statistics.mean(loss_pnls), 2) if loss_pnls else None
            
            if win_rate_pct >= 55.0:
                bar_color = "green"
            elif win_rate_pct >= 40.0:
                bar_color = "yellow"
            else:
                bar_color = "red"
        else:
            win_count = 0
            loss_count = 0
            breakeven_count = 0
            win_rate_pct = None
            avg_pnl = None
            avg_pnl_wins = None
            avg_pnl_losses = None
            bar_color = "gray"
            
        bucket_results.append({
            "key": bucket["key"],
            "range_display": bucket["display"],
            "trade_count": b_count,
            "win_count": win_count,
            "loss_count": loss_count,
            "breakeven_count": breakeven_count,
            "win_rate_pct": win_rate_pct,
            "avg_pnl": avg_pnl,
            "avg_pnl_wins": avg_pnl_wins,
            "avg_pnl_losses": avg_pnl_losses,
            "bar_color": bar_color
        })

    # STEP 4C: Calculate calibration grade
    non_empty = [b for b in bucket_results if b["trade_count"] > 0]
    
    if len(non_empty) <= 1:
        grade = "INSUFFICIENT_SPREAD"
        grade_explanation = "All trades cluster in one confidence range. Need trades across multiple confidence levels to measure calibration."
    else:
        correct_steps = 0
        total_steps = len(non_empty) - 1
        
        for i in range(total_steps):
            if non_empty[i+1]["win_rate_pct"] > non_empty[i]["win_rate_pct"]:
                correct_steps += 1
                
        ratio = correct_steps / total_steps
        
        if ratio >= 0.80:
            grade = "EXCELLENT"
            grade_explanation = "Higher confidence reliably predicts higher win rate. Your scoring is working."
        elif ratio >= 0.60:
            grade = "GOOD"
            grade_explanation = "Generally, higher confidence predicts better outcomes. Minor inconsistencies exist."
        elif ratio >= 0.40:
            grade = "FAIR"
            grade_explanation = "Weak relationship between confidence and win rate. Scoring logic needs review."
        else:
            grade = "POOR"
            grade_explanation = "Confidence score is NOT predicting win rate. The signal scoring system needs recalibration. Do not increase trade size."

    # STEP 4D: Calculate recommended confidence floor
    current_floor = getattr(settings, "SIGNAL_V2_MIN_CONFIDENCE", None)
    if current_floor is None:
        paper_min = getattr(settings, "signal_v2_paper_min_score", 70)
        current_floor = float(paper_min)
        if current_floor > 1.0:
            current_floor = current_floor / 100.0
            
    recommended_floor = current_floor
    lowest_qualifying_low = None
    
    for b_res in bucket_results:
        # Find low float threshold from key
        key = b_res["key"]
        low_val = None
        for b in BUCKETS:
            if b["key"] == key:
                low_val = b["low"]
                break
        
        if b_res["win_rate_pct"] is not None and b_res["win_rate_pct"] >= 55.0 and b_res["trade_count"] >= 3:
            if low_val is not None:
                if lowest_qualifying_low is None or low_val < lowest_qualifying_low:
                    lowest_qualifying_low = low_val
                    
    if lowest_qualifying_low is not None:
        # never recommend lowering below current floor
        recommended_floor = max(lowest_qualifying_low, current_floor)
        
    if recommended_floor == current_floor:
        floor_advice = "Current floor appears reasonable given available data."
    elif recommended_floor > current_floor:
        floor_advice = f"Raising the floor to {int(recommended_floor*100)}% could remove your lowest-performing trades."
    else:
        floor_advice = "Current floor appears reasonable."

    # STEP 4E: Generate insight string
    high_bucket = next((b for b in reversed(bucket_results) if b["trade_count"] > 0 and b["win_rate_pct"] is not None), None)
    low_bucket = next((b for b in bucket_results if b["trade_count"] > 0 and b["win_rate_pct"] is not None), None)
    
    if high_bucket and low_bucket and high_bucket != low_bucket:
        insight_string = f"Trades above {high_bucket['range_display'].split(' ')[0]} confidence win {high_bucket['win_rate_pct']}% of the time versus {low_bucket['win_rate_pct']}% below {low_bucket['range_display'].split(' ')[-1]}. Raising your floor to {int(recommended_floor*100)}% could eliminate most losing trades."
    elif grade == "POOR":
        insight_string = "Your confidence score shows no consistent pattern yet. A 65% confidence trade wins almost as often as an 80% confidence trade. The scoring weights may need adjustment."
    else:
        insight_string = f"Higher confidence scores show a {grade.lower()} correlation with win rate. The scoring system is functioning as expected."

    # STEP 4F: Detect and build danger signals
    danger_signals = []
    
    # Check 1: Inverse calibration
    if grade == "POOR":
        danger_signals.append({
            "type": "INVERSE_CALIBRATION",
            "message": "Lower confidence trades are outperforming higher confidence trades. This is a signal quality issue.",
            "severity": "HIGH",
            "action": "Review the filter scoring weights in Signal Engine v2."
        })
        
    # Check 2: High confidence, poor outcome
    for b_res in bucket_results:
        key = b_res["key"]
        low_val = None
        for b in BUCKETS:
            if b["key"] == key:
                low_val = b["low"]
                break
        if low_val is not None and low_val >= 0.75 and b_res["trade_count"] >= 3:
            if b_res["win_rate_pct"] is not None and b_res["win_rate_pct"] < 45.0:
                danger_signals.append({
                    "type": "HIGH_CONFIDENCE_POOR_OUTCOME",
                    "message": "Signals above 75% confidence are losing more than 55% of the time. Do not increase trade size until this is resolved.",
                    "severity": "HIGH",
                    "action": "Audit the option chain filter and market flow filter for high-confidence signals."
                })
                
    # Check 3: Confidence bunching
    bunching_bucket = next((b for b in bucket_results if b["key"] == "60-65"), None)
    if bunching_bucket and bunching_bucket["trade_count"] > 0:
        if (bunching_bucket["trade_count"] / total_trades) > 0.60:
            danger_signals.append({
                "type": "CONFIDENCE_BUNCHING",
                "message": "Over 60% of all trades cluster in the 60-65% confidence range. The scoring system may not be discriminating well enough.",
                "severity": "MEDIUM",
                "action": "Review whether all 8 filters are contributing meaningfully to the final score."
            })
            
    # Check 4: Too few trades in high confidence buckets
    high_bucket_trades = sum(
        b["trade_count"] for b in bucket_results if b["key"] in ("70-75", "75-80", "80+")
    )
    if high_bucket_trades == 0 and total_trades >= 20:
        danger_signals.append({
            "type": "NO_HIGH_CONFIDENCE_TRADES",
            "message": "No trades have been taken above 70% confidence. The confidence floor may be too high, or high-quality signals are being generated but not paper-traded.",
            "severity": "MEDIUM",
            "action": "Check if the signal engine is generating any signals above 70% confidence."
        })

    # STEP 4G: Return the complete result
    return {
        "status": "OK",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "lookback_days": lookback_days,
        "total_trades_analyzed": total_trades,
        "current_confidence_floor": current_floor,
        "recommended_floor": recommended_floor,
        "floor_advice": floor_advice,
        "calibration_grade": grade,
        "grade_explanation": grade_explanation,
        "insight": insight_string,
        "danger_signals": danger_signals,
        "danger_signal_count": len(danger_signals),
        "buckets": bucket_results,
        "bar_color_rules": {
            "green": "win_rate_pct >= 55%",
            "yellow": "win_rate_pct 40-55%",
            "red": "win_rate_pct < 40%",
            "gray": "no trades in this bucket"
        }
    }
