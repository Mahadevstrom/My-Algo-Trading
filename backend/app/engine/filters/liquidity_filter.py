from typing import Any


def evaluate_liquidity(candidate: dict[str, Any] | None, min_score: int = 60) -> dict:
    if not candidate:
        return {"status": "NO_CANDIDATE", "score": 0, "message": "No option candidate was selected for liquidity analysis."}
    ltp = _float(candidate.get("ltp"))
    liquidity_score = _float(candidate.get("liquidity_score")) or 0
    spread = _float(candidate.get("spread"))
    if ltp is None or ltp <= 0:
        return {"status": "NO_LTP", "score": 0, "message": "Selected option has no valid LTP."}
    if liquidity_score < min_score:
        return {"status": "ILLIQUID", "score": 0, "message": f"Selected option liquidity score is below {min_score}."}
    if spread is not None and spread > max(ltp * 0.08, 5):
        return {"status": "WIDE_SPREAD", "score": 0, "message": "Selected option bid/ask spread is too wide."}
    return {"status": "ACCEPTABLE", "score": 5, "message": "Selected option liquidity and spread are acceptable."}


def _float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None

