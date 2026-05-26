from __future__ import annotations

from typing import Any


def build_recommendations(report: dict[str, Any]) -> list[str]:
    recommendations: list[str] = []
    status = str(report.get("report_status") or report.get("status") or "")
    if status in {"NO_DATA", "PARTIAL_DATA"}:
        recommendations.append("NEED_MORE_DATA")
    if _has_warning(report, "data quality"):
        recommendations.append("REVIEW_DATA_QUALITY")
    if _has_warning(report, "stale"):
        recommendations.append("UPDATE_STALE_CONTEXT_DATA")
    if _contains(report, "trap"):
        recommendations.append("AVOID_WEAK_SIGNALS")
    if _contains(report, "DIVERGENCE"):
        recommendations.append("WAIT_FOR_BREADTH_CONFIRMATION")
    if not recommendations:
        recommendations.append("CONTINUE_PAPER_TESTING")
    return _dedupe(recommendations)


def _has_warning(report: dict[str, Any], pattern: str) -> bool:
    text = " ".join(str(item).lower() for item in report.get("warnings", []))
    return pattern.lower() in text


def _contains(value: Any, pattern: str) -> bool:
    if isinstance(value, dict):
        return any(_contains(item, pattern) for item in value.values())
    if isinstance(value, list):
        return any(_contains(item, pattern) for item in value)
    return pattern.lower() in str(value).lower()


def _dedupe(items: list[str]) -> list[str]:
    output = []
    for item in items:
        if item not in output:
            output.append(item)
    return output
