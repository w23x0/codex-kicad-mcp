"""Layout constraints and occupancy measurements."""

from __future__ import annotations

import math
from typing import Any

from codex_kicad_mcp.analysis.connectivity import pad_board_position
from codex_kicad_mcp.analysis.context import ProjectContext, load_context
from codex_kicad_mcp.analysis.findings import finding, findings_report
from codex_kicad_mcp.geometry import as_xy, bounding_box


def _board_size(context: ProjectContext) -> tuple[float, float, dict[str, float] | None]:
    outline: list[tuple[float, float]] = []
    for item in context.pcb["data"].get("outline", []):
        if not isinstance(item, dict):
            continue
        for key in ("start", "end", "center"):
            point = as_xy(item.get(key))
            if point is not None:
                outline.append(point)
        for polygon in item.get("points", []) if isinstance(item.get("points"), list) else []:
            point = as_xy(polygon)
            if point is not None:
                outline.append(point)
    box = bounding_box(outline)
    if box is None:
        return 0.0, 0.0, None
    return round(box["maxX"] - box["minX"], 6), round(box["maxY"] - box["minY"], 6), box


def _occupied_cells(context: ProjectContext, cell_size: float) -> set[tuple[int, int]]:
    occupied: set[tuple[int, int]] = set()

    def mark(point: Any) -> None:
        value = as_xy(point)
        if value is not None:
            occupied.add((math.floor(value[0] / cell_size), math.floor(value[1] / cell_size)))

    data = context.pcb["data"]
    for footprint in data.get("footprints", []):
        if not isinstance(footprint, dict):
            continue
        mark(footprint.get("position"))
        for pad in footprint.get("pads", []):
            if isinstance(pad, dict):
                position = pad_board_position(footprint, pad)
                mark({"x": position[0], "y": position[1]} if position else None)
    for segment in data.get("segments", []):
        if not isinstance(segment, dict):
            continue
        mark(segment.get("start"))
        mark(segment.get("end"))
    for via in data.get("vias", []):
        if isinstance(via, dict):
            mark(via.get("position"))
    return occupied


def review_layout(context: ProjectContext, minimum_track_width_mm: float | None = None) -> dict[str, object]:
    """Compare track widths with the project or caller-provided target."""
    rules = context.settings.get("rules", {}) if isinstance(context.settings.get("rules"), dict) else {}
    project_target = rules.get("min_track_width")
    if minimum_track_width_mm is None:
        if (
            isinstance(project_target, (int, float))
            and not isinstance(project_target, bool)
            and math.isfinite(float(project_target))
        ):
            target = float(project_target)
            target_source = "project"
        else:
            target = 0.2
            target_source = "default"
    else:
        if (
            not isinstance(minimum_track_width_mm, (int, float))
            or isinstance(minimum_track_width_mm, bool)
            or not 0 < float(minimum_track_width_mm) <= 25
        ):
            raise ValueError("minimum_track_width_mm must be between 0 and 25")
        target = float(minimum_track_width_mm)
        target_source = "request"
    source_path = context.pcb["source"]["path"]
    findings: list[dict[str, object]] = []
    for segment in context.pcb["data"].get("segments", []):
        if not isinstance(segment, dict):
            continue
        width = segment.get("width")
        if not isinstance(width, (int, float)) or isinstance(width, bool) or not math.isfinite(float(width)):
            findings.append(
                finding(
                    "layout.track_width_below_target",
                    kind="layout",
                    severity="error",
                    message=f"Track segment has no finite width; target is {target:g} mm",
                    source_path=source_path,
                    confidence="medium",
                    objects=[
                        {
                            "kind": "track",
                            "name": str(segment.get("netName") or "unassigned"),
                            "uuid": segment.get("uuid"),
                        }
                    ],
                    pcb={"footprint": None, "layer": segment.get("layer"), "position": segment.get("start")},
                    suggestions=["Assign a copper width at or above the configured target"],
                )
            )
        elif float(width) + 1e-9 < target:
            findings.append(
                finding(
                    "layout.track_width_below_target",
                    kind="layout",
                    severity="warning",
                    message=f"Track width {float(width):g} mm is below the {target:g} mm target",
                    source_path=source_path,
                    confidence="high" if target_source in {"project", "request"} else "medium",
                    objects=[
                        {
                            "kind": "track",
                            "name": str(segment.get("netName") or "unassigned"),
                            "uuid": segment.get("uuid"),
                        }
                    ],
                    pcb={"footprint": None, "layer": segment.get("layer"), "position": segment.get("start")},
                    suggestions=["Increase the track width or document the current-limiting rationale"],
                )
            )
    widths: list[float] = []
    for segment in context.pcb["data"].get("segments", []):
        if not isinstance(segment, dict):
            continue
        width = segment.get("width")
        if isinstance(width, (int, float)) and not isinstance(width, bool) and math.isfinite(float(width)):
            widths.append(float(width))
    counts = {
        "findings": len(findings),
        "rules": len({str(item["ruleId"]) for item in findings}),
        "tracks": len(context.pcb["data"].get("segments", [])),
    }
    data = {
        "targetWidth": target,
        "targetSource": target_source,
        "unit": "mm",
        "minimumTrackWidth": round(min(widths), 6) if widths else None,
    }
    return findings_report(
        context.project,
        source_path,
        findings,
        data=data,
        counts=counts,
        confidence="parsed",
    )


def analyze_board_density(
    project: str, cell_size_mm: float = 2.0, high_density_ratio: float = 0.8
) -> dict[str, object]:
    """Measure board occupancy on a fixed square grid without heuristic findings."""
    for name, value in (("cell_size_mm", cell_size_mm), ("high_density_ratio", high_density_ratio)):
        if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(float(value)):
            raise ValueError(f"{name} must be finite")
    if not 0 < float(cell_size_mm) <= 100:
        raise ValueError("cell_size_mm must be between 0 and 100")
    if not 0 < float(high_density_ratio) <= 1:
        raise ValueError("high_density_ratio must be between 0 and 1")
    context = load_context(project, require_netlist=False)
    width, height, bounding = _board_size(context)
    cell_size = float(cell_size_mm)
    grid_width = math.ceil(width / cell_size) if width > 0 else 0
    grid_height = math.ceil(height / cell_size) if height > 0 else 0
    occupied = _occupied_cells(context, cell_size)
    in_bounds = {cell for cell in occupied if 0 <= cell[0] < grid_width and 0 <= cell[1] < grid_height}
    total_cells = grid_width * grid_height
    ratio = len(in_bounds) / total_cells if total_cells else 0.0
    metrics = {
        "board": {"width": width, "height": height, "boundingBox": bounding, "unit": "mm"},
        "grid": {
            "cellSize": cell_size,
            "widthCells": grid_width,
            "heightCells": grid_height,
            "totalCells": total_cells,
            "occupiedCells": len(in_bounds),
            "density": round(ratio, 6),
            "highDensityRatio": float(high_density_ratio),
        },
    }
    counts = {
        "findings": 0,
        "rules": 0,
        "footprints": len(context.pcb["data"].get("footprints", [])),
        "pads": sum(
            len(item.get("pads", [])) for item in context.pcb["data"].get("footprints", []) if isinstance(item, dict)
        ),
        "vias": len(context.pcb["data"].get("vias", [])),
        "tracks": len(context.pcb["data"].get("segments", [])),
        "occupiedCells": len(in_bounds),
    }
    return findings_report(
        context.project,
        context.pcb["source"],
        [],
        data={"density": metrics},
        counts=counts,
        confidence="parsed",
    )
