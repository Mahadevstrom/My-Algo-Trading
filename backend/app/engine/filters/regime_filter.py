def classify_regime(adx: float | None, bb_width: float | None, avg_range_pct: float | None) -> dict:
    """Classify intraday market regime from ADX, Bollinger Band width, and range.

    TRENDING means directional strength and band expansion are both present, so a slightly lower
    signal threshold can be acceptable.
    RANGING means weak trend and tight bands, so the setup bar should be raised.
    VOLATILE means bands or candle ranges are expanded enough to require caution.
    NEUTRAL is the fallback when inputs do not confirm a clear regime.
    """
    if adx is not None and bb_width is not None and adx >= 25 and bb_width >= 2.0:
        return {
            "regime": "TRENDING",
            "recommended_min_score": 65,
            "bonus_context": "Strong trend confirmed",
            "adx_input": adx,
            "bb_width_input": bb_width,
        }
    if adx is not None and bb_width is not None and adx < 20 and bb_width < 1.5:
        return {
            "regime": "RANGING",
            "recommended_min_score": 80,
            "bonus_context": None,
            "warning": "Choppy market - raise bar",
            "adx_input": adx,
            "bb_width_input": bb_width,
        }
    if (bb_width is not None and bb_width > 5.0) or (avg_range_pct is not None and avg_range_pct > 1.5):
        return {
            "regime": "VOLATILE",
            "recommended_min_score": 75,
            "bonus_context": None,
            "warning": "High volatility - caution",
            "adx_input": adx,
            "bb_width_input": bb_width,
        }
    return {
        "regime": "NEUTRAL",
        "recommended_min_score": 70,
        "bonus_context": None,
        "adx_input": adx,
        "bb_width_input": bb_width,
    }
