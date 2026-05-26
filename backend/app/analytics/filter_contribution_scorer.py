import json
import statistics
from datetime import datetime, timezone, timedelta
from typing import Any
from sqlalchemy import select, and_
from sqlalchemy.orm import Session

from app.models.trade import PaperTrade
from app.config import settings

def calculate_filter_scorecard(
    db: Session,
    lookback_days: int = 30,
    min_trades: int = 15
) -> dict:
    # STEP 4A: Query closed trades with birth certificates
    cutoff = datetime.now(timezone.utc) - timedelta(days=lookback_days)
    
    query = select(PaperTrade).where(
        and_(
            PaperTrade.result.in_(["WIN", "LOSS", "BREAKEVEN"]),
            PaperTrade.filter_states_json.isnot(None),
            PaperTrade.birth_cert_version.isnot(None),
            PaperTrade.exit_time >= cutoff
        )
    )
    trades = list(db.scalars(query))
    count = len(trades)
    
    if count < min_trades:
        return {
            "status": "INSUFFICIENT_DATA",
            "message": "Not enough closed trades with filter data to score contributions. Keep paper trading.",
            "min_required": min_trades,
            "current_count": count,
            "trades_needed": min_trades - count
        }

    # STEP 4B: Parse filter_states_json safely
    parsed_trades = []
    malformed_count = 0
    for t in trades:
        try:
            states = json.loads(t.filter_states_json)
            if not isinstance(states, dict):
                raise ValueError("Not a dictionary")
            parsed_trades.append((t, states))
        except Exception:
            malformed_count += 1
            
    winning_parsed = [item for item in parsed_trades if item[0].result == "WIN"]
    losing_parsed = [item for item in parsed_trades if item[0].result == "LOSS"]
    
    win_count_total = len(winning_parsed)
    loss_count_total = len(losing_parsed)
    
    if win_count_total == 0 or loss_count_total == 0:
        return {
            "status": "INSUFFICIENT_SPREAD",
            "message": "Need both winning and losing trades to score filters. Currently only one outcome type exists in the data.",
            "win_count": win_count_total,
            "loss_count": loss_count_total
        }

    # STEP 4C: Score each filter
    THE_8_FILTERS = [
        "trend_filter", "momentum_filter", "chop_filter",
        "volatility_filter", "time_filter", "market_flow_filter",
        "liquidity_filter", "option_chain_filter"
    ]
    
    DISPLAY_NAMES = {
        "trend_filter":        "Trend Filter (EMA/VWAP)",
        "momentum_filter":     "Momentum Filter (RSI)",
        "chop_filter":         "Chop Filter (ADX)",
        "volatility_filter":   "Volatility Filter (ATR)",
        "time_filter":         "Time/Session Filter",
        "market_flow_filter":  "Market Flow Filter",
        "liquidity_filter":    "Liquidity/Spread Filter",
        "option_chain_filter": "Option Chain Filter (OI/PCR)"
    }
    
    min_trades_per_filter = getattr(settings, "filter_scorer_min_trades_per_filter", 5)
    filter_results = []
    
    for f_name in THE_8_FILTERS:
        # Wins with filter passed
        wins_passed = 0
        for t, states in winning_parsed:
            f_state = states.get(f_name)
            if isinstance(f_state, dict) and f_state.get("passed") is True:
                wins_passed += 1
                
        # Losses with filter passed
        losses_passed = 0
        for t, states in losing_parsed:
            f_state = states.get(f_name)
            if isinstance(f_state, dict) and f_state.get("passed") is True:
                losses_passed += 1
                
        presence_wins_pct = round((wins_passed / win_count_total) * 100, 1) if win_count_total > 0 else 0.0
        presence_losses_pct = round((losses_passed / loss_count_total) * 100, 1) if loss_count_total > 0 else 0.0
        edge_score = round(presence_wins_pct - presence_losses_pct, 1)
        
        # Trades with this filter data
        trades_with_data = 0
        for t, states in parsed_trades:
            if f_name in states:
                trades_with_data += 1
                
        data_coverage_pct = round((trades_with_data / len(parsed_trades)) * 100, 1) if len(parsed_trades) > 0 else 0.0
        
        # Verdict
        if edge_score >= 25.0:
            verdict = "HIGH_VALUE"
            rec = "Keep as a core gate. This filter reliably separates winning from losing trades."
        elif edge_score >= 10.0:
            verdict = "USEFUL"
            rec = "Retain this filter. It shows a positive edge but may benefit from tuning."
        elif edge_score >= 0.0:
            verdict = "WEAK"
            rec = "Review this filter's scoring logic. It shows little difference between wins and losses."
        elif edge_score >= -10.0:
            verdict = "QUESTIONABLE"
            rec = "This filter may be adding noise. Consider raising its required score threshold."
        else:
            verdict = "HARMFUL"
            rec = "This filter is present in MORE losing trades than winning trades. Investigate urgently — it may be blocking good signals or allowing bad ones."
            
        # Reliability
        if trades_with_data < min_trades_per_filter:
            reliability = "LOW_SAMPLE"
            reliability_note = f"Only {trades_with_data} trades have data for this filter. Score may not be statistically reliable yet."
        else:
            reliability = "OK"
            reliability_note = None
            
        # Average scores on wins/losses
        win_scores = []
        for t, states in winning_parsed:
            f_state = states.get(f_name)
            if isinstance(f_state, dict) and f_state.get("score") is not None:
                win_scores.append(f_state["score"])
        avg_score_wins = round(statistics.mean(win_scores), 2) if win_scores else None
        
        loss_scores = []
        for t, states in losing_parsed:
            f_state = states.get(f_name)
            if isinstance(f_state, dict) and f_state.get("score") is not None:
                loss_scores.append(f_state["score"])
        avg_score_losses = round(statistics.mean(loss_scores), 2) if loss_scores else None
        
        filter_results.append({
            "filter_name": f_name,
            "display_name": DISPLAY_NAMES[f_name],
            "edge_score": edge_score,
            "presence_in_winning_trades_pct": presence_wins_pct,
            "presence_in_losing_trades_pct": presence_losses_pct,
            "avg_score_on_wins": avg_score_wins,
            "avg_score_on_losses": avg_score_losses,
            "trades_with_data": trades_with_data,
            "data_coverage_pct": data_coverage_pct,
            "verdict": verdict,
            "recommendation": rec,
            "reliability": reliability,
            "reliability_note": reliability_note
        })

    # STEP 4D: Calculate summary metrics
    ok_filters = [f for f in filter_results if f["reliability"] != "LOW_SAMPLE"]
    
    if not ok_filters:
        strongest_filter = None
        weakest_filter = None
    else:
        strongest_filter = max(ok_filters, key=lambda x: x["edge_score"])["filter_name"]
        weakest_filter = min(ok_filters, key=lambda x: x["edge_score"])["filter_name"]
        
    harmful_filters = [f["filter_name"] for f in filter_results if f["verdict"] == "HARMFUL"]
    
    # Sort descending by edge_score
    filter_results.sort(key=lambda x: x["edge_score"], reverse=True)
    
    # minimum_filters_for_entry logic
    minimum_filters_for_entry = None
    minimum_filters_note = "No filter count threshold achieves 55% win rate with current data."
    
    for N in range(8, 0, -1):
        matching_trades = []
        for t, states in parsed_trades:
            passed_count = sum(1 for f in states.values() if isinstance(f, dict) and f.get("passed") is True)
            if passed_count == N:
                matching_trades.append(t)
                
        t_count = len(matching_trades)
        if t_count >= 3:
            wins = sum(1 for t in matching_trades if t.result == "WIN")
            win_rate = (wins / t_count) * 100
            if win_rate >= 55.0:
                minimum_filters_for_entry = N
                minimum_filters_note = f"Trades with {N} filters passing achieve {round(win_rate, 1)}% win rate."
                break

    # STEP 4E: Build the regime breakdown
    regimes_map = {}
    for t, _ in parsed_trades:
        regime = t.regime_at_entry or "UNKNOWN"
        if regime not in regimes_map:
            regimes_map[regime] = {"win_count": 0, "loss_count": 0, "total_count": 0}
        regimes_map[regime]["total_count"] += 1
        if t.result == "WIN":
            regimes_map[regime]["win_count"] += 1
        elif t.result == "LOSS":
            regimes_map[regime]["loss_count"] += 1
            
    regime_breakdown = []
    for r_name, stats in regimes_map.items():
        r_total = stats["total_count"]
        r_wins = stats["win_count"]
        r_win_rate = round((r_wins / r_total) * 100, 1) if r_total > 0 else 0.0
        
        if r_win_rate >= 55.0:
            r_verdict = "FAVORABLE"
        elif r_win_rate >= 45.0:
            r_verdict = "NEUTRAL"
        else:
            r_verdict = "UNFAVORABLE"
            
        regime_breakdown.append({
            "regime": r_name,
            "trade_count": r_total,
            "win_rate_pct": r_win_rate,
            "verdict": r_verdict
        })

    # STEP 4F: Return the complete result
    return {
        "status": "OK",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "lookback_days": lookback_days,
        "total_trades_analyzed": len(parsed_trades),
        "win_count_total": win_count_total,
        "loss_count_total": loss_count_total,
        "malformed_birth_cert_count": malformed_count,
        "strongest_filter": strongest_filter,
        "weakest_filter": weakest_filter,
        "harmful_filters": harmful_filters,
        "minimum_filters_for_entry": minimum_filters_for_entry,
        "minimum_filters_note": minimum_filters_note,
        "filters": filter_results,
        "regime_breakdown": regime_breakdown,
        "display_names": DISPLAY_NAMES
    }
