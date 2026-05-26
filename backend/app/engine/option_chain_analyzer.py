from typing import Any


class OptionChainAnalyzer:
    def analyze(
        self,
        strikes: list[dict[str, Any]],
        underlying: str,
        expiry: str,
        spot_price: float | None = None,
    ) -> dict[str, Any]:
        if not strikes:
            return {
                "underlying": underlying.upper(),
                "expiry": expiry,
                "spot_price": spot_price,
                "atm_strike": None,
                "total_ce_oi": 0,
                "total_pe_oi": 0,
                "pcr_oi": None,
                "total_ce_volume": 0,
                "total_pe_volume": 0,
                "pcr_volume": None,
                "max_ce_oi_strike": None,
                "max_pe_oi_strike": None,
                "max_ce_volume_strike": None,
                "max_pe_volume_strike": None,
                "support_strike": None,
                "resistance_strike": None,
                "chain_bias": "NEUTRAL",
                "confidence": 0,
                "reason": "No option chain data found.",
            }

        atm_strike = next((row["strike"] for row in strikes if row.get("atm_marker") == "ATM"), None)
        total_ce_oi = sum(_num(row.get("ce_oi")) or 0 for row in strikes)
        total_pe_oi = sum(_num(row.get("pe_oi")) or 0 for row in strikes)
        total_ce_volume = sum(_num(row.get("ce_volume")) or 0 for row in strikes)
        total_pe_volume = sum(_num(row.get("pe_volume")) or 0 for row in strikes)
        pcr_oi = _ratio(total_pe_oi, total_ce_oi)
        pcr_volume = _ratio(total_pe_volume, total_ce_volume)

        max_ce_oi_row = _max_row(strikes, "ce_oi")
        max_pe_oi_row = _max_row(strikes, "pe_oi")
        max_ce_volume_row = _max_row(strikes, "ce_volume")
        max_pe_volume_row = _max_row(strikes, "pe_volume")
        avg_liquidity = _avg(
            [
                value
                for row in strikes
                for value in [row.get("ce_liquidity_score"), row.get("pe_liquidity_score")]
                if value is not None
            ]
        )

        chain_bias, reason = _bias(pcr_oi, pcr_volume, max_pe_oi_row, max_ce_oi_row)
        confidence = _confidence(pcr_oi, pcr_volume, avg_liquidity, total_ce_oi + total_pe_oi)

        return {
            "underlying": underlying.upper(),
            "expiry": expiry,
            "spot_price": spot_price,
            "atm_strike": atm_strike,
            "total_ce_oi": round(total_ce_oi, 2),
            "total_pe_oi": round(total_pe_oi, 2),
            "pcr_oi": pcr_oi,
            "total_ce_volume": round(total_ce_volume, 2),
            "total_pe_volume": round(total_pe_volume, 2),
            "pcr_volume": pcr_volume,
            "max_ce_oi_strike": _strike(max_ce_oi_row),
            "max_pe_oi_strike": _strike(max_pe_oi_row),
            "max_ce_volume_strike": _strike(max_ce_volume_row),
            "max_pe_volume_strike": _strike(max_pe_volume_row),
            "support_strike": _strike(max_pe_oi_row),
            "resistance_strike": _strike(max_ce_oi_row),
            "chain_bias": chain_bias,
            "confidence": confidence,
            "reason": reason,
        }


def _num(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _ratio(numerator: float, denominator: float) -> float | None:
    if denominator <= 0:
        return None
    return round(numerator / denominator, 2)


def _max_row(rows: list[dict[str, Any]], key: str) -> dict[str, Any] | None:
    candidates = [row for row in rows if (_num(row.get(key)) or 0) > 0]
    if not candidates:
        return None
    return max(candidates, key=lambda row: _num(row.get(key)) or 0)


def _strike(row: dict[str, Any] | None) -> float | None:
    return row.get("strike") if row else None


def _avg(values: list[Any]) -> float:
    nums = [_num(value) for value in values]
    clean = [value for value in nums if value is not None]
    if not clean:
        return 0
    return sum(clean) / len(clean)


def _bias(
    pcr_oi: float | None,
    pcr_volume: float | None,
    max_pe_oi_row: dict[str, Any] | None,
    max_ce_oi_row: dict[str, Any] | None,
) -> tuple[str, str]:
    if pcr_oi is None:
        return "NEUTRAL", "PCR could not be calculated because call OI is unavailable."

    volume_diverges = (
        pcr_volume is not None
        and ((pcr_oi >= 1.15 and pcr_volume <= 0.85) or (pcr_oi <= 0.85 and pcr_volume >= 1.15))
    )
    if volume_diverges:
        return "CHOPPY", "OI and volume PCR are pointing in different directions."

    support = _strike(max_pe_oi_row)
    resistance = _strike(max_ce_oi_row)
    context = f" Support near {support}, resistance near {resistance}." if support and resistance else ""

    if pcr_oi >= 1.25:
        return "BULLISH", f"Put OI is meaningfully higher than call OI; PCR(OI)={pcr_oi}.{context}"
    if pcr_oi <= 0.75:
        return "BEARISH", f"Call OI is meaningfully higher than put OI; PCR(OI)={pcr_oi}.{context}"
    if 0.90 <= pcr_oi <= 1.10:
        return "NEUTRAL", f"PCR(OI)={pcr_oi}, suggesting balanced positioning.{context}"
    return "CHOPPY", f"PCR(OI)={pcr_oi}, a mild imbalance without strong confirmation.{context}"


def _confidence(
    pcr_oi: float | None,
    pcr_volume: float | None,
    avg_liquidity: float,
    total_oi: float,
) -> int:
    if pcr_oi is None or total_oi <= 0:
        return 10
    pcr_strength = min(abs(pcr_oi - 1.0) * 60, 35)
    volume_confirmation = 10 if pcr_volume is not None and (pcr_oi - 1) * (pcr_volume - 1) > 0 else 0
    liquidity_component = min(avg_liquidity * 0.55, 45)
    return int(round(max(0, min(100, 10 + pcr_strength + volume_confirmation + liquidity_component))))

