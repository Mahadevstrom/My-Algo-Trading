from typing import Any

from app.engine.setup.setup_evidence import SetupRequirementResult


def evaluate_condition(
    condition: dict,
    oc_evidence: dict,
    ms_evidence: dict,
    context_evidence: dict,
) -> SetupRequirementResult:
    description = str(condition.get("description") or condition.get("field") or "Condition")
    expected = condition.get("value")
    try:
        source = _source_dict(condition.get("engine"), oc_evidence, ms_evidence, context_evidence)
        field = condition.get("field")
        if field not in source:
            return SetupRequirementResult(
                requirement=description,
                passed=False,
                actual_value="FIELD_NOT_FOUND",
                expected=str(expected),
            )
        actual = source.get(field)
        operator = str(condition.get("operator") or "eq").lower()
        passed = _apply_operator(actual, operator, expected)
        return SetupRequirementResult(
            requirement=description,
            passed=passed,
            actual_value=str(actual),
            expected=str(expected),
        )
    except Exception as exc:
        return SetupRequirementResult(
            requirement=description,
            passed=False,
            actual_value=f"ERROR: {type(exc).__name__}",
            expected=str(expected),
        )


def _source_dict(engine: Any, oc_evidence: dict, ms_evidence: dict, context_evidence: dict) -> dict:
    if engine == "option_chain_engine":
        return oc_evidence
    if engine == "market_structure_engine":
        return ms_evidence
    if engine == "context":
        return context_evidence
    return {}


def _apply_operator(actual: Any, operator: str, expected: Any) -> bool:
    if operator == "eq":
        return actual == expected
    if operator == "neq":
        return actual != expected
    if operator == "in":
        return actual in (expected or [])
    if operator == "not_in":
        return actual not in (expected or [])
    if operator == "gte":
        return float(actual) >= float(expected)
    if operator == "lte":
        return float(actual) <= float(expected)
    return False
