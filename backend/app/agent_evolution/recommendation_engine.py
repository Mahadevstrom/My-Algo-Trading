import json
from sqlalchemy import select, and_
from sqlalchemy.orm import Session
from app.agent_evolution.models import AgentEvolutionRecommendation

def generate_recommendations(
    db: Session,
    analysis_report: dict,
    run_id: str,
    max_recs: int = 5
) -> list[AgentEvolutionRecommendation]:
    if analysis_report.get("status") == "INSUFFICIENT_DATA":
        return []

    calibration = analysis_report["confidence_calibration"]
    scorecard = analysis_report["filter_scorecard"]
    patterns = analysis_report["failure_patterns"]

    current_floor = calibration.get("current_confidence_floor", 0.60)
    recommended_floor = calibration.get("recommended_floor", current_floor)
    grade = calibration.get("calibration_grade", "UNKNOWN")
    grade_explanation = calibration.get("grade_explanation", "")

    raw_recs = []

    # Rule 1: Calibration grade is POOR or FAIR
    if grade in ["POOR", "FAIR"]:
        raw_recs.append({
            "recommendation_type": "RAISE_CONFIDENCE_FLOOR",
            "affected_module": "confidence_gate",
            "issue_detected": f"Calibration grade is {grade}. Higher confidence is not predicting higher win rate.",
            "evidence_summary": json.dumps({
                "current_count": calibration.get("total_trades_analyzed"),
                "calibration_grade": grade,
                "grade_explanation": grade_explanation,
                "buckets": calibration.get("buckets", [])
            }),
            "suggested_change": "Investigate the scoring weights in Signal Engine v2. Run at least 50 trades before changing the confidence floor.",
            "expected_benefit": "Better signal quality once scoring weights reflect actual market conditions.",
            "risk_level": "MEDIUM",
            "confidence": 0.75,
            "data_snapshot": json.dumps(calibration)
        })

    # Rule 2: HARMFUL filter detected
    harmful_filters_list = scorecard.get("harmful_filters", [])
    filters_detail = scorecard.get("filters", [])
    for f_detail in filters_detail:
        if f_detail.get("filter_name") in harmful_filters_list or f_detail.get("verdict") == "HARMFUL":
            f_name = f_detail["filter_name"]
            raw_recs.append({
                "recommendation_type": "INVESTIGATE_FILTER",
                "affected_module": f_name,
                "issue_detected": f"{f_name} is present in more losing trades than winning trades.",
                "evidence_summary": json.dumps({
                    "edge_score": f_detail.get("edge_score"),
                    "presence_in_winning_trades_pct": f_detail.get("presence_in_winning_trades_pct"),
                    "presence_in_losing_trades_pct": f_detail.get("presence_in_losing_trades_pct")
                }),
                "suggested_change": f"Audit the {f_name} scoring logic. Check if the passed/failed threshold is set correctly.",
                "expected_benefit": "Removing a harmful filter gate could allow better signals through.",
                "risk_level": "HIGH",
                "confidence": 0.80,
                "data_snapshot": json.dumps(f_detail)
            })

    # Rule 3: CHOP_TRAP pattern detected
    chop_trap = next((p for p in patterns if p.get("pattern") == "CHOP_TRAP"), None)
    if chop_trap:
        raw_recs.append({
            "recommendation_type": "REGIME_THRESHOLD_CHANGE",
            "affected_module": "signal_engine_v2",
            "issue_detected": "Trades in SIDEWAYS regime have low win rate.",
            "evidence_summary": json.dumps(chop_trap),
            "suggested_change": f"Raise confidence floor by 10 points when regime_at_entry is SIDEWAYS. Target: {int(current_floor * 100) + 10}% threshold.",
            "expected_benefit": "Fewer trades in unfavorable conditions.",
            "risk_level": "LOW",
            "confidence": 0.85,
            "data_snapshot": json.dumps(chop_trap)
        })

    # Rule 4: MIDDAY_WEAKNESS pattern detected
    midday = next((p for p in patterns if p.get("pattern") == "MIDDAY_WEAKNESS"), None)
    if midday:
        raw_recs.append({
            "recommendation_type": "SESSION_WINDOW_ADJUSTMENT",
            "affected_module": "session_gate",
            "issue_detected": "Midday trades underperform morning trades.",
            "evidence_summary": json.dumps(midday),
            "suggested_change": "Consider raising the confidence threshold by 8 points during MIDDAY_CAUTION sessions, or review whether MIDDAY_CAUTION should block new entries entirely.",
            "expected_benefit": "Avoid low-probability midday trades.",
            "risk_level": "LOW",
            "confidence": 0.80,
            "data_snapshot": json.dumps(midday)
        })

    # Rule 5: HIGH_CONFIDENCE_FAILURE pattern detected
    high_conf_fail = next((p for p in patterns if p.get("pattern") == "HIGH_CONFIDENCE_FAILURE"), None)
    if high_conf_fail:
        raw_recs.append({
            "recommendation_type": "FILTER_WEIGHT_REVIEW",
            "affected_module": "signal_engine_v2",
            "issue_detected": "Signals above 75% confidence are losing too often. Overconfidence detected.",
            "evidence_summary": json.dumps(high_conf_fail),
            "suggested_change": "Audit which filters are most active during high-confidence signals. Check if the option chain filter is working correctly at high confidence levels.",
            "expected_benefit": "More reliable high-confidence signals.",
            "risk_level": "HIGH",
            "confidence": 0.75,
            "data_snapshot": json.dumps(high_conf_fail)
        })

    # Rule 6: OI_CONTRADICTION pattern detected
    oi_contra = next((p for p in patterns if p.get("pattern") == "OI_CONTRADICTION"), None)
    if oi_contra:
        raw_recs.append({
            "recommendation_type": "INVESTIGATE_FILTER",
            "affected_module": "option_chain_filter",
            "issue_detected": "Trades taken against OI direction have high loss rate.",
            "evidence_summary": json.dumps(oi_contra),
            "suggested_change": "Make OI direction a hard gate for signal direction. CE signals should require BULLISH OI. PE signals should require BEARISH or NEUTRAL OI.",
            "expected_benefit": "Eliminate contra-OI trades which are systematically losing.",
            "risk_level": "MEDIUM",
            "confidence": 0.85,
            "data_snapshot": json.dumps(oi_contra)
        })

    # Rule 7: Recommended floor is higher than current floor
    if recommended_floor > current_floor and calibration.get("total_trades_analyzed", 0) >= 30:
        raw_recs.append({
            "recommendation_type": "RAISE_CONFIDENCE_FLOOR",
            "affected_module": "confidence_gate",
            "issue_detected": f"Data suggests floor of {recommended_floor*100:.0f}% performs better than current {current_floor*100:.0f}%.",
            "evidence_summary": json.dumps({
                "recommended_floor": recommended_floor,
                "current_floor": current_floor,
                "buckets": calibration.get("buckets", [])
            }),
            "suggested_change": f"Consider raising SIGNAL_V2_MIN_CONFIDENCE from {current_floor} to {recommended_floor} in config. Test for 2 weeks before making permanent.",
            "expected_benefit": "Estimated removal of lowest-performing trade bucket.",
            "risk_level": "LOW",
            "confidence": 0.70,
            "data_snapshot": json.dumps(calibration)
        })

    # Sort by confidence descending
    raw_recs.sort(key=lambda x: x["confidence"], reverse=True)

    # Process and save with deduplication and limit
    saved_recs = []
    
    for item in raw_recs:
        if len(saved_recs) >= max_recs:
            break
            
        # Deduplication: Check if there's a PENDING rec with the same type and module in DB
        stmt = select(AgentEvolutionRecommendation).where(
            and_(
                AgentEvolutionRecommendation.recommendation_type == item["recommendation_type"],
                AgentEvolutionRecommendation.affected_module == item["affected_module"],
                AgentEvolutionRecommendation.status == "PENDING"
            )
        )
        existing = db.scalars(stmt).first()
        if existing is not None:
            continue  # duplicate PENDING recommendation exists, skip

        # Construct SQLAlchemy object
        rec = AgentEvolutionRecommendation(
            recommendation_type=item["recommendation_type"],
            affected_module=item["affected_module"],
            issue_detected=item["issue_detected"],
            evidence_summary=item["evidence_summary"],
            suggested_change=item["suggested_change"],
            expected_benefit=item["expected_benefit"],
            risk_level=item["risk_level"],
            confidence=item["confidence"],
            status="PENDING",
            run_id=run_id,
            data_snapshot=item["data_snapshot"]
        )
        db.add(rec)
        db.commit()
        db.refresh(rec)
        saved_recs.append(rec)

    return saved_recs
