"""Shared read context for the analysis subpackage."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from codex_kicad_mcp import netlist, pcb, project, schematic


@dataclass(frozen=True)
class ProjectContext:
    project: str
    schematic: dict[str, Any]
    pcb: dict[str, Any]
    connectivity: dict[str, Any] | None
    settings: dict[str, Any]


def _project_settings(project_path: str) -> dict[str, Any]:
    path = project.artifact_file(project_path, ".kicad_pro")
    value = json.loads(project.read_text(path))
    if not isinstance(value, dict):
        raise ValueError("project file is not valid KiCad JSON")
    board = value.get("board")
    return board.get("design_settings", {}) if isinstance(board, dict) else {}


def load_context(project_name: str, *, require_netlist: bool = True) -> ProjectContext:
    """Parse all read-only design inputs once for a review request.

    ``require_netlist=False`` is intentionally available to geometry-only
    analyzers so those tools still work without a KiCad CLI installation.
    """
    schematic_result = schematic.read_schematic(project_name)
    pcb_result = pcb.read_pcb(project_name)
    connectivity_result = netlist.read_netlist(project_name) if require_netlist else None
    project_value = schematic_result["project"]
    if not isinstance(project_value, str):
        raise ValueError("project path must be a string")
    return ProjectContext(
        project=project_value,
        schematic=schematic_result,
        pcb=pcb_result,
        connectivity=connectivity_result,
        settings=_project_settings(project_name),
    )
