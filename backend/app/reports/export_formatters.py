from __future__ import annotations

import csv
import io
import json
from typing import Any


def format_report(report: dict[str, Any], output_format: str) -> dict[str, Any]:
    fmt = output_format.strip().lower()
    if fmt == "json":
        return {
            "format": "json",
            "content_type": "application/json",
            "content": json.dumps(_redact(report), indent=2, default=str),
        }
    if fmt == "csv":
        return {"format": "csv", "content_type": "text/csv", "content": _to_csv(_redact(report))}
    if fmt == "md":
        return {"format": "md", "content_type": "text/markdown", "content": _to_markdown(_redact(report))}
    raise ValueError("Unsupported report format. Use one of: json, csv, md.")


def _to_csv(report: dict[str, Any]) -> str:
    rows = list(_flatten(report))
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["path", "value"])
    writer.writerows(rows)
    return buffer.getvalue()


def _to_markdown(report: dict[str, Any]) -> str:
    lines = [f"# {str(report.get('report_type', 'Report')).replace('_', ' ').title()}", ""]
    for key, value in report.items():
        if key == "sections" and isinstance(value, dict):
            for section, section_value in value.items():
                lines.append(f"## {section.replace('_', ' ').title()}")
                lines.extend(_markdown_value(section_value))
                lines.append("")
        elif key not in {"sections"}:
            lines.append(f"- **{key}**: `{_short(value)}`")
    return "\n".join(lines).strip() + "\n"


def _markdown_value(value: Any) -> list[str]:
    if isinstance(value, dict):
        return [f"- **{key}**: `{_short(item)}`" for key, item in value.items()]
    if isinstance(value, list):
        return [f"- `{_short(item)}`" for item in value[:20]]
    return [f"- `{_short(value)}`"]


def _flatten(value: Any, prefix: str = ""):
    if isinstance(value, dict):
        for key, item in value.items():
            yield from _flatten(item, f"{prefix}.{key}" if prefix else str(key))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from _flatten(item, f"{prefix}[{index}]")
    else:
        yield (prefix, value)


def _redact(value: Any) -> Any:
    if isinstance(value, dict):
        redacted = {}
        for key, item in value.items():
            lowered = str(key).lower()
            if "token" in lowered or "access" in lowered or "authorization" in lowered:
                redacted[key] = "[REDACTED]"
            else:
                redacted[key] = _redact(item)
        return redacted
    if isinstance(value, list):
        return [_redact(item) for item in value]
    return value


def _short(value: Any) -> str:
    text = json.dumps(value, default=str) if isinstance(value, (dict, list)) else str(value)
    return text if len(text) <= 240 else text[:237] + "..."
