def detect_late_entry_pattern(trades: list) -> dict or None:
    loss_trades = [t for t in trades if t.result == "LOSS"]
    total_losses = len(loss_trades)
    
    matching_losses = []
    for t in loss_trades:
        if t.pnl is not None and t.pnl < 0:
            if t.option_type == "CE" and t.oi_direction_at_entry == "BULLISH":
                matching_losses.append(t)
            elif t.option_type == "PE" and t.oi_direction_at_entry == "BEARISH":
                matching_losses.append(t)
                
    count = len(matching_losses)
    if total_losses > 0 and (count / total_losses) > 0.25:
        pct = round((count / total_losses) * 100, 1)
        return {
            "pattern": "LATE_ENTRY",
            "frequency": count,
            "frequency_pct": pct,
            "description": f"Correct direction but still lost — entered after the move already happened. Found in {count} trades ({pct}% of losses).",
            "severity": "MEDIUM"
        }
    return None

def detect_chop_trap_pattern(trades: list) -> dict or None:
    sideways_trades = [t for t in trades if t.regime_at_entry == "SIDEWAYS"]
    count = len(sideways_trades)
    if count >= 5:
        wins = sum(1 for t in sideways_trades if t.result == "WIN")
        win_rate = (wins / count) * 100
        if win_rate < 40.0:
            return {
                "pattern": "CHOP_TRAP",
                "frequency": count,
                "win_rate_pct": round(win_rate, 1),
                "description": f"Trades in sideways market regime are losing significantly. Win rate is only {round(win_rate, 1)}% across {count} trades. The system needs a harder block in sideways conditions.",
                "severity": "HIGH"
            }
    return None

def detect_midday_weakness_pattern(trades: list) -> dict or None:
    midday = [t for t in trades if t.session_window_at_entry == "MIDDAY_CAUTION"]
    morning = [t for t in trades if t.session_window_at_entry == "ACTIVE_MORNING"]
    
    mid_count = len(midday)
    morn_count = len(morning)
    
    if mid_count >= 5 and morn_count > 0:
        mid_wins = sum(1 for t in midday if t.result == "WIN")
        morn_wins = sum(1 for t in morning if t.result == "WIN")
        
        mid_wr = (mid_wins / mid_count) * 100
        morn_wr = (morn_wins / morn_count) * 100
        
        if mid_wr < (morn_wr - 15.0):
            gap = round(morn_wr - mid_wr, 1)
            return {
                "pattern": "MIDDAY_WEAKNESS",
                "midday_win_rate": round(mid_wr, 1),
                "morning_win_rate": round(morn_wr, 1),
                "gap_pct": gap,
                "description": f"Midday trades perform significantly worse than morning trades. Midday win rate is {round(mid_wr, 1)}% vs morning win rate of {round(morn_wr, 1)}% (gap: {gap}%).",
                "severity": "MEDIUM"
            }
    return None

def detect_high_confidence_failure_pattern(trades: list) -> dict or None:
    high_conf = []
    for t in trades:
        val = t.confidence_score_at_entry
        if val is not None:
            if val > 1.0:
                val = val / 100.0
            if val >= 0.75:
                high_conf.append(t)
                
    count = len(high_conf)
    if count >= 5:
        wins = sum(1 for t in high_conf if t.result == "WIN")
        win_rate = (wins / count) * 100
        if win_rate < 45.0:
            return {
                "pattern": "HIGH_CONFIDENCE_FAILURE",
                "high_conf_trade_count": count,
                "high_conf_win_rate": round(win_rate, 1),
                "description": f"High-confidence signals are not translating to wins. Win rate is {round(win_rate, 1)}% across {count} high-confidence trades. The scoring system may be overconfident.",
                "severity": "HIGH"
            }
    return None

def detect_oi_contradiction_pattern(trades: list) -> dict or None:
    contradictions = []
    for t in trades:
        if t.option_type == "CE" and t.oi_direction_at_entry == "BEARISH":
            contradictions.append(t)
        elif t.option_type == "PE" and t.oi_direction_at_entry == "BULLISH":
            contradictions.append(t)
            
    count = len(contradictions)
    if count >= 3:
        losses = sum(1 for t in contradictions if t.result == "LOSS")
        loss_rate = (losses / count) * 100
        if loss_rate > 60.0:
            return {
                "pattern": "OI_CONTRADICTION",
                "contradiction_count": count,
                "loss_rate_pct": round(loss_rate, 1),
                "description": f"Trades were taken against OI direction. Contradictions have a {round(loss_rate, 1)}% loss rate across {count} trades.",
                "severity": "HIGH"
            }
    return None

def detect_low_filter_count_pattern(trades: list) -> dict or None:
    low_filter = [t for t in trades if t.filters_passed_count is not None and t.filters_passed_count <= 5]
    count = len(low_filter)
    if count >= 5:
        wins = sum(1 for t in low_filter if t.result == "WIN")
        win_rate = (wins / count) * 100
        if win_rate < 40.0:
            return {
                "pattern": "LOW_FILTER_COUNT",
                "low_filter_trade_count": count,
                "low_filter_win_rate": round(win_rate, 1),
                "threshold_used": 5,
                "description": f"Trades taken when fewer than 6 filters pass are performing poorly. Win rate is {round(win_rate, 1)}% across {count} trades.",
                "severity": "MEDIUM"
            }
    return None

def detect_premium_decay_risk(trades: list) -> dict or None:
    losses = [t for t in trades if t.result == "LOSS" and t.pnl is not None]
    if losses:
        avg_loss = sum(t.pnl for t in losses) / len(losses)
        large_losses = sum(1 for t in losses if t.pnl <= -500.0)
        pct = (large_losses / len(losses)) * 100
        if avg_loss < -800.0 and pct > 40.0:
            return {
                "pattern": "PREMIUM_DECAY_RISK",
                "avg_loss_amount": round(avg_loss, 2),
                "large_loss_pct": round(pct, 1),
                "description": f"Large average losses ({round(avg_loss, 2)}) suggest premium decay is eating positions that stay open too long. {round(pct, 1)}% of losses exceed 500 rupees. Consider tighter time-based exits.",
                "severity": "MEDIUM"
            }
    return None

def detect_all_patterns(trades: list) -> list:
    pattern_functions = [
        detect_late_entry_pattern,
        detect_chop_trap_pattern,
        detect_midday_weakness_pattern,
        detect_high_confidence_failure_pattern,
        detect_oi_contradiction_pattern,
        detect_low_filter_count_pattern,
        detect_premium_decay_risk
    ]
    
    detected = []
    for func in pattern_functions:
        res = func(trades)
        if res is not None:
            detected.append(res)
            
    severity_order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
    detected.sort(key=lambda x: severity_order.get(x.get("severity", "MEDIUM"), 1))
    return detected
