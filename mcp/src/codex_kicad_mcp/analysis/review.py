"""Aggregated design review over the analysis rule modules."""

from __future__ import annotations

from typing import Any

from codex_kicad_mcp.analysis import (
    decoupling,
    layout,
    manufacturing,
    parity,
    power,
    signal_integrity,
)
from codex_kicad_mcp.analysis.context import ProjectContext, load_context
from codex_kicad_mcp.analysis.findings import findings_report

SUPPORTED_CHECKS = {"power", "decoupling", "parity", "si", "manufacturing", "layout"}
_SEVERITY_ORDER = {"error": 0, "warning": 1, "info": 2}


def _check_findings(context: ProjectContext, check: str, **kwargs: Any) -> list[dict[str, object]]:
    result = {
        "power": lambda: power.review_power(context, kwargs.get("rails")),
        "decoupling": lambda: decoupling.review_decoupling(context, kwargs.get("near_pin_mm", 5.0)),
        "parity": lambda: parity.review_parity(context),
        "si": lambda: signal_integrity.review_signal_integrity(context),
        "manufacturing": lambda: manufacturing.review_manufacturing(context),
        "layout": lambda: layout.review_layout(context, kwargs.get("minimum_track_width_mm")),
    }[check]()
    findings = result["findings"]
    assert isinstance(findings, list)
    return findings


def run_design_review(
    project: str,
    *,
    checks: list[str] | None = None,
    rails: list[str] | None = None,
    near_pin_mm: float = 5.0,
    minimum_track_width_mm: float | None = None,
) -> dict[str, object]:
    """Run selected read-only analyzers and merge their finding lists."""
    selected = checks or sorted(SUPPORTED_CHECKS)
    if not isinstance(selected, list) or not selected or any(not isinstance(item, str) for item in selected):
        raise ValueError("checks must be a non-empty list of check names")
    unknown = sorted(set(selected) - SUPPORTED_CHECKS)
    if unknown:
        raise ValueError(f"unknown checks: {', '.join(unknown)}; expected {', '.join(sorted(SUPPORTED_CHECKS))}")
    context = load_context(project)
    findings: list[dict[str, object]] = []
    counts: dict[str, int] = {"findings": 0, "rules": 0, "checks": len(set(selected))}
    for check in dict.fromkeys(selected):
        items = _check_findings(
            context,
            check,
            rails=rails,
            near_pin_mm=near_pin_mm,
            minimum_track_width_mm=minimum_track_width_mm,
        )
        counts[check] = len(items)
        findings.extend(items)
    findings.sort(
        key=lambda item: (
            _SEVERITY_ORDER.get(str(item.get("severity")), 99),
            str(item.get("kind")),
            str(item.get("ruleId")),
            str(item.get("message")),
        )
    )
    counts["findings"] = len(findings)
    counts["rules"] = len({str(item.get("ruleId")) for item in findings})
    return findings_report(
        context.project,
        context.schematic["source"],
        findings,
        data={"checks": list(dict.fromkeys(selected))},
        counts=counts,
        warnings=[
            *context.schematic.get("warnings", []),
            *context.pcb.get("warnings", []),
            *((context.connectivity or {}).get("warnings", [])),
        ],
        confidence="cli",
    )
