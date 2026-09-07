"""Normalization for KiCad ERC/DRC JSON reports."""

from __future__ import annotations

import hashlib
import json
from typing import Any

_SEVERITY_MAP = {
    "error": "error",
    "warning": "warning",
    "info": "info",
    "exclusion": "excluded",
    "excluded": "excluded",
    "ignore": "excluded",
}


def normalize_severity(value: Any) -> str:
    if not isinstance(value, str):
        return "info"
    return _SEVERITY_MAP.get(value.lower(), "info")


def stable_rule_id(prefix: str, value: Any) -> str:
    text = str(value)
    return hashlib.sha256(f"{prefix}\0{text}".encode()).hexdigest()[:12]


def _scale_for_erc(report: dict[str, Any]) -> tuple[float, str | None]:
    # KiCad 10.0.6 labels ERC coordinates as mm while emitted values are two
    # decimal orders smaller (for example, a 59.69 mm pin is reported as
    # 0.5969).  DRC coordinates are already mm.  Keep this conversion isolated
    # so it can be removed if upstream fixes the report schema.
    units = report.get("coordinate_units")
    if isinstance(units, str) and units.lower() == "cm":
        return 10.0, "ERC JSON coordinates were declared cm and normalized to mm"
    return 100.0, "ERC JSON coordinates from KiCad 10.0.6 are scaled by 0.01 and were normalized to mm"


def _position(value: Any, scale: float = 1.0) -> dict[str, float | None] | None:
    if not isinstance(value, dict):
        return None
    x, y = value.get("x"), value.get("y")
    if not isinstance(x, (int, float)) or not isinstance(y, (int, float)):
        return None
    return {"x": round(x * scale, 6), "y": round(y * scale, 6), "unit": "mm"}


def _items(value: Any, scale: float) -> list[dict[str, object]]:
    if not isinstance(value, list):
        return []
    result: list[dict[str, object]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        result.append(
            {
                "description": item.get("description"),
                "position": _position(item.get("pos"), scale),
                "uuid": item.get("uuid"),
            }
        )
    return result


def _issue(
    raw: dict[str, Any],
    *,
    category: str,
    scale: float,
    context: dict[str, Any] | None = None,
) -> dict[str, object]:
    rule_type = raw.get("type")
    issue: dict[str, object] = {
        "category": category,
        "severity": normalize_severity(raw.get("severity")),
        "ruleId": rule_type
        if isinstance(rule_type, str) and rule_type
        else stable_rule_id(category, raw.get("description")),
        "message": raw.get("description"),
        "items": _items(raw.get("items"), scale),
    }
    if context is not None:
        issue["context"] = context
    return issue


def normalize_check_report(
    report: dict[str, Any], *, check: str
) -> tuple[list[dict[str, object]], list[str], dict[str, int]]:
    if not isinstance(report, dict):
        raise ValueError("KiCad check report is not a JSON object")
    issues: list[dict[str, object]] = []
    warnings: list[str] = []
    if check == "sch":
        scale, warning = _scale_for_erc(report)
        if warning:
            warnings.append(warning)
    else:
        scale = 1.0
    severity_counts = {"error": 0, "warning": 0, "info": 0, "excluded": 0}
    sheets = report.get("sheets") if isinstance(report.get("sheets"), list) else []
    for sheet in sheets:
        if not isinstance(sheet, dict):
            continue
        context = {
            "path": sheet.get("path"),
            "uuidPath": sheet.get("uuid_path"),
        }
        violations = sheet.get("violations") if isinstance(sheet.get("violations"), list) else []
        for raw in violations:
            if not isinstance(raw, dict):
                continue
            issue = _issue(raw, category="violation", scale=scale, context=context)
            severity_counts[str(issue["severity"])] += 1
            issues.append(issue)
    for key in ("unconnected_items", "schematic_parity"):
        entries = report.get(key) if isinstance(report.get(key), list) else []
        for raw in entries:
            if not isinstance(raw, dict):
                continue
            issue = _issue(raw, category=key, scale=scale)
            severity_counts[str(issue["severity"])] += 1
            issues.append(issue)
    top_violations = report.get("violations") if isinstance(report.get("violations"), list) else []
    for raw in top_violations:
        if not isinstance(raw, dict):
            continue
        issue = _issue(raw, category="violation", scale=scale)
        severity_counts[str(issue["severity"])] += 1
        issues.append(issue)
    return issues, warnings, severity_counts


def parse_check_json(text: str) -> dict[str, Any]:
    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"kicad-cli check report is not valid JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError("kicad-cli check report is not a JSON object")
    return value
