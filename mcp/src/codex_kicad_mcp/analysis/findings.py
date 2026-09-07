"""Shared finding schema and report construction for review analyzers."""

from __future__ import annotations

from typing import Any

_SEVERITIES = {"error", "warning", "info"}
_KINDS = {"power", "decoupling", "parity", "si", "manufacturing", "layout"}
_CONFIDENCE = {"high", "medium", "low"}


def finding(
    rule_id: str,
    *,
    kind: str,
    severity: str,
    message: str,
    source_path: str | None,
    confidence: str,
    objects: list[dict[str, object]] | None = None,
    schematic: dict[str, object] | None = None,
    pcb: dict[str, object] | None = None,
    suggestions: list[str] | None = None,
) -> dict[str, object]:
    """Create one rule finding with mandatory provenance and confidence."""
    if not rule_id or not isinstance(rule_id, str):
        raise ValueError("finding rule_id must be a non-empty string")
    if kind not in _KINDS:
        raise ValueError(f"finding kind must be one of {sorted(_KINDS)}")
    if severity not in _SEVERITIES:
        raise ValueError(f"finding severity must be one of {sorted(_SEVERITIES)}")
    if confidence not in _CONFIDENCE:
        raise ValueError(f"finding confidence must be one of {sorted(_CONFIDENCE)}")
    if not message:
        raise ValueError("finding message must not be empty")
    result: dict[str, object] = {
        "ruleId": rule_id,
        "kind": kind,
        "severity": severity,
        "confidence": confidence,
        "message": message,
        "source": {"path": source_path},
        "objects": [
            {
                "kind": str(item.get("kind") or "object"),
                "name": str(item.get("name") or "unknown"),
                "uuid": item.get("uuid"),
            }
            for item in (objects or [])
            if isinstance(item, dict)
        ],
        "suggestions": suggestions or [],
    }
    if schematic is not None:
        result["schematic"] = schematic
    if pcb is not None:
        result["pcb"] = pcb
    return result


def summary(findings: list[dict[str, object]]) -> dict[str, int]:
    result = {"error": 0, "warning": 0, "info": 0}
    for item in findings:
        severity = str(item.get("severity"))
        if severity in result:
            result[severity] += 1
    return result


def findings_report(
    project: str,
    source: dict[str, Any],
    findings: list[dict[str, object]],
    *,
    data: dict[str, object] | None = None,
    counts: dict[str, int] | None = None,
    warnings: list[str] | None = None,
    confidence: str = "heuristic",
) -> dict[str, object]:
    """Build the review-facing envelope around the shared finding list."""
    result: dict[str, object] = {
        "schemaVersion": "1.0",
        "project": project,
        "source": source,
        "findings": findings,
        "summary": summary(findings),
        "counts": counts or {"findings": len(findings), "rules": len({str(item.get("ruleId")) for item in findings})},
        "warnings": warnings or [],
    }
    if data is not None:
        result["data"] = data
    result["confidence"] = confidence
    return result
