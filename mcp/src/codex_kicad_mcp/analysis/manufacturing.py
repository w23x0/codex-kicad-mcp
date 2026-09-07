"""Manufacturing readiness checks over PCB geometry and project rules."""

from __future__ import annotations

import math
from collections import defaultdict
from typing import Any

from codex_kicad_mcp.analysis.context import ProjectContext, load_context
from codex_kicad_mcp.analysis.findings import finding, findings_report
from codex_kicad_mcp.geometry import as_xy
from codex_kicad_mcp.response import parse_artifact
from codex_kicad_mcp.sexpr import children

_MAX_COMMON_DRILL_MM = 6.5


def _finding(
    rule_id: str,
    severity: str,
    message: str,
    source_path: str,
    confidence: str,
    *,
    objects: list[dict[str, object]] | None = None,
    pcb: dict[str, object] | None = None,
    suggestions: list[str] | None = None,
) -> dict[str, object]:
    return finding(
        rule_id,
        kind="manufacturing",
        severity=severity,
        message=message,
        source_path=source_path,
        confidence=confidence,
        objects=objects,
        pcb=pcb,
        suggestions=suggestions,
    )


def _drills(context: ProjectContext) -> list[tuple[str, float | None, dict[str, Any] | None, str | None]]:
    data = context.pcb["data"]
    result: list[tuple[str, float | None, dict[str, Any] | None, str | None]] = []
    for via in data.get("vias", []):
        if isinstance(via, dict):
            result.append(("via", via.get("drill"), via.get("position"), via.get("uuid")))
    for footprint in data.get("footprints", []):
        if not isinstance(footprint, dict):
            continue
        for pad in footprint.get("pads", []):
            if isinstance(pad, dict) and pad.get("drill") is not None:
                result.append(
                    (
                        f"{footprint.get('reference')}.{pad.get('number')}",
                        pad.get("drill"),
                        pad.get("position"),
                        footprint.get("uuid"),
                    )
                )
    return result


def _outline_graph(
    context: ProjectContext,
) -> tuple[dict[tuple[float, float], int], list[tuple[tuple[float, float], tuple[float, float]]]]:
    degree: dict[tuple[float, float], int] = defaultdict(int)
    edges: list[tuple[tuple[float, float], tuple[float, float]]] = []
    for item in context.pcb["data"].get("outline", []):
        if not isinstance(item, dict):
            continue
        if item.get("points"):
            vertices = []
            for raw in item["points"]:
                point = as_xy(raw)
                if point is not None:
                    vertices.append((round(point[0], 6), round(point[1], 6)))
            for first, second in zip(vertices, vertices[1:] + vertices[:1], strict=True):
                if first != second:
                    degree[first] += 1
                    degree[second] += 1
                    edges.append((first, second))
        else:
            start = as_xy(item.get("start"))
            end = as_xy(item.get("end"))
            if start is None or end is None:
                continue
            a = (round(start[0], 6), round(start[1], 6))
            b = (round(end[0], 6), round(end[1], 6))
            if a == b:
                continue
            degree[a] += 1
            degree[b] += 1
            edges.append((a, b))
    return degree, edges


def _outline_closed(context: ProjectContext) -> bool:
    degree, edges = _outline_graph(context)
    if not edges or any(count != 2 for count in degree.values()):
        return False
    adjacency: dict[tuple[float, float], set[tuple[float, float]]] = defaultdict(set)
    for first, second in edges:
        adjacency[first].add(second)
        adjacency[second].add(first)
    start = next(iter(adjacency))
    visited = {start}
    pending = [start]
    while pending:
        current = pending.pop()
        for neighbor in adjacency[current]:
            if neighbor not in visited:
                visited.add(neighbor)
                pending.append(neighbor)
    return visited == set(adjacency)


def _courtyard_uuids(project: str) -> tuple[str, set[str]]:
    _, artifact_path, top, _ = parse_artifact(project, ".kicad_pcb", "kicad_pcb")
    uuids: set[str] = set()
    for footprint in children(top, "footprint"):
        uuid = next(
            (child[1] for child in footprint[1:] if isinstance(child, list) and child and child[0] == "uuid"), None
        )
        for shape in (
            children(footprint, "fp_line")
            + children(footprint, "fp_rect")
            + children(footprint, "fp_poly")
            + children(footprint, "fp_circle")
        ):
            layer = next(
                (child[1] for child in shape[1:] if isinstance(child, list) and child and child[0] == "layer"), None
            )
            if isinstance(layer, str) and layer.casefold().endswith(".crtyd") and isinstance(uuid, str):
                uuids.add(uuid)
    return artifact_path, uuids


def review_manufacturing(context: ProjectContext) -> dict[str, object]:
    """Check drill bounds, outline closure, and footprint courtyard presence."""
    rules = context.settings.get("rules", {}) if isinstance(context.settings.get("rules"), dict) else {}
    minimum_drill = rules.get("min_through_hole_diameter", 0.1)
    minimum_drill = (
        float(minimum_drill) if isinstance(minimum_drill, (int, float)) and math.isfinite(float(minimum_drill)) else 0.1
    )
    source_path = context.pcb["source"]["path"]
    findings: list[dict[str, object]] = []
    for name, drill, position, uuid in _drills(context):
        value = float(drill) if isinstance(drill, (int, float)) and math.isfinite(float(drill)) else None
        if value is None:
            findings.append(
                _finding(
                    "manufacturing.unusual_drill",
                    "error",
                    f"Drill on {name} is missing or non-finite",
                    source_path,
                    "medium",
                    objects=[{"kind": "drill", "name": name, "uuid": uuid}],
                    pcb={"footprint": None, "position": position},
                    suggestions=["Assign a finite drill diameter supported by the fabricator"],
                )
            )
        elif not minimum_drill <= value <= _MAX_COMMON_DRILL_MM:
            findings.append(
                _finding(
                    "manufacturing.unusual_drill",
                    "warning",
                    f"Drill {value:g} mm on {name} is outside {minimum_drill:g}-{_MAX_COMMON_DRILL_MM:g} mm",
                    source_path,
                    "medium",
                    objects=[{"kind": "drill", "name": name, "uuid": uuid}],
                    pcb={"footprint": None, "position": position},
                    suggestions=["Confirm the drill capability or choose a standard drill size"],
                )
            )

    if not _outline_closed(context):
        findings.append(
            _finding(
                "manufacturing.board_outline_not_closed",
                "error",
                "Edge.Cuts geometry is not a closed outline",
                source_path,
                "high",
                objects=[{"kind": "outline", "name": "Edge.Cuts", "uuid": None}],
                pcb={"footprint": None, "layer": "Edge.Cuts"},
                suggestions=["Close the board outline with collinear endpoints on every edge"],
            )
        )

    courtyard_path, courtyard_uuids = _courtyard_uuids(context.project)
    for footprint in context.pcb["data"].get("footprints", []):
        if not isinstance(footprint, dict) or not footprint.get("uuid"):
            continue
        if str(footprint.get("uuid")) not in courtyard_uuids:
            findings.append(
                _finding(
                    "manufacturing.missing_courtyard",
                    "warning",
                    f"Footprint {footprint.get('reference') or footprint.get('name')} has no courtyard geometry",
                    courtyard_path,
                    "high",
                    objects=[
                        {
                            "kind": "footprint",
                            "name": str(footprint.get("reference") or footprint.get("name")),
                            "uuid": footprint.get("uuid"),
                        }
                    ],
                    pcb={
                        "footprint": footprint.get("reference"),
                        "layer": footprint.get("layer"),
                        "position": footprint.get("position"),
                    },
                    suggestions=["Add or update a courtyard outline before fabrication"],
                )
            )
    counts = {
        "findings": len(findings),
        "rules": len({str(item["ruleId"]) for item in findings}),
        "drills": len(_drills(context)),
        "outlineItems": len(context.pcb["data"].get("outline", [])),
        "footprints": len(context.pcb["data"].get("footprints", [])),
    }
    return findings_report(context.project, context.pcb["source"], findings, counts=counts, confidence="heuristic")


def review_fabrication_context(context: ProjectContext) -> dict[str, object]:
    """Return manufacturing findings plus a high-level fabrication checklist."""
    result = review_manufacturing(context)
    findings = result["findings"]
    assert isinstance(findings, list)
    counts = result["counts"]
    assert isinstance(counts, dict)
    unassigned = []
    for component in (context.connectivity or {}).get("data", {}).get("components", []):
        if isinstance(component, dict) and not component.get("footprint"):
            unassigned.append(component.get("reference"))
    checklist = {
        "boardPresent": bool(context.pcb["data"].get("footprints")),
        "outlineClosed": not any(
            str(item.get("ruleId")) == "manufacturing.board_outline_not_closed" for item in findings
        ),
        "footprintsAssigned": not unassigned,
        "courtyardsPresent": not any(str(item.get("ruleId")) == "manufacturing.missing_courtyard" for item in findings),
        "drillsInPreferredRange": not any(
            str(item.get("ruleId")) == "manufacturing.unusual_drill" for item in findings
        ),
    }
    result["data"] = {"checklist": checklist, "unassignedFootprints": unassigned}
    counts["checklistItems"] = len(checklist)
    return result


def check_fabrication_readiness(project: str) -> dict[str, object]:
    return review_fabrication_context(load_context(project))
