"""MCP resources: stable project-scoped read-only resources.

Resources expose the same data as the read tools through a stable URI scheme so
hosts can list and subscribe to project state without invoking tools.  Every
URI embeds a workspace-relative project parameter, percent-encoded by callers
because the SDK template matcher does not match across ``/``.  Resources reuse
the data-layer modules directly; they do not parse beyond what the tools
already parse.
"""

from __future__ import annotations

import urllib.parse
from pathlib import Path
from typing import Any

from codex_kicad_mcp import board, bom, hierarchy, netlist, pcb, schematic
from codex_kicad_mcp import project as project_module
from codex_kicad_mcp.diagnostics import normalize_check_report, parse_check_json


def encode_project(project: str) -> str:
    """Percent-encode a workspace-relative project path for a resource URI."""
    return urllib.parse.quote(project, safe="")


def decode_project(value: str) -> str:
    """Decode the project parameter from a resource URI.

    Lenient for hosts that leave ``/`` unescaped; the workspace boundary check
    runs on the decoded value, so traversal attempts are rejected by the same
    shared validation every tool uses.
    """
    if not isinstance(value, str) or not value.strip():
        raise ValueError("resource project parameter must not be empty")
    return urllib.parse.unquote(value)


SCHEMA_MIME = "application/json"
TEXT_MIME = "text/plain"

RAW_ALLOWED_SUFFIXES = {
    ".kicad_pro",
    ".kicad_sch",
    ".kicad_pcb",
    ".kicad_prl",
    ".kicad_sym",
}


def raw_artifact(project: str) -> str:
    """Return the raw text of a project artifact, bounded and validated.

    Only KiCad file suffixes are served and the size limit follows
    ``KICAD_MAX_FILE_BYTES`` so raw reads cannot bypass the parser budget.
    """
    path = project_module.inside_workspace(decode_project(project))
    if path.suffix.lower() not in RAW_ALLOWED_SUFFIXES:
        raise ValueError(
            "raw artifact resource only serves .kicad_pro/.kicad_sch/.kicad_pcb/.kicad_prl/.kicad_sym files"
        )
    if not path.is_file():
        raise ValueError(f"raw artifact does not exist: {path.name}")
    return project_module.read_text(path)


def _report_resource(project: str, artifact_suffix: str, check: str, candidates: list[str]) -> dict[str, Any]:
    """Read a normalized ERC/DRC JSON report without invoking kicad-cli."""
    project = decode_project(project)
    try:
        artifact_path = project_module.artifact_file(project, artifact_suffix)
    except ValueError:
        return {}
    for name in candidates:
        report_path = artifact_path.with_name(name)
        if not report_path.is_file():
            continue
        text = project_module.read_text(report_path)
        try:
            report = parse_check_json(text)
        except ValueError as exc:
            raise ValueError(f"{report_path.name} is not valid KiCad JSON: {exc}") from exc
        issues, warnings, severity_counts = normalize_check_report(report, check=check)
        return {
            "schemaVersion": "1.0",
            "project": project_module.rel_posix(artifact_path.with_suffix(".kicad_pro")),
            "source": {
                "path": (report_path.relative_to(project_module.workspace())).as_posix(),
                "kind": "erc" if check == "sch" else "drc",
            },
            "data": {
                "check": "ERC" if check == "sch" else "DRC",
                "kicadVersion": report.get("kicad_version"),
                "coordinateUnits": report.get("coordinate_units"),
                "includedSeverities": report.get("included_severities", []),
                "ignoredChecks": report.get("ignored_checks", []),
                "issues": issues,
            },
            "counts": {"issues": len(issues), **severity_counts},
            "warnings": warnings,
            "confidence": "parsed",
        }
    return {}


def report_resource(project: str) -> dict[str, Any]:
    """Return normalized findings from a local ERC or DRC report artifact.

    Prefers ERC (``erc.json`` or KiCad's GUI default ``<stem>.json`` beside the
    root schematic) and falls back to DRC (``drc.json`` or ``<stem>.json``
    beside the board); raises ``ValueError`` when neither exists.
    """
    project = decode_project(project)
    stem = Path(project).stem
    result = _report_resource(project, ".kicad_sch", "sch", ["erc.json", f"{stem}.json"])
    if not result:
        result = _report_resource(project, ".kicad_pcb", "pcb", ["drc.json", f"{stem}.json"])
    if not result:
        raise ValueError("no erc.json or drc.json report artifact found for this project")
    return result


def manifest_resource(project: str) -> dict[str, Any]:
    """Return a project manifest: identity, files, and summary metadata."""
    project = decode_project(project)
    return {
        "project": project_module.project_summary(project),
        "inventory": project_module.inspect_project(project),
        "workspaceRelative": True,
    }


def schematic_resource(project: str) -> dict[str, Any]:
    """Return parsed schematic data (symbols, labels, wires, sheets)."""
    return schematic.read_schematic(decode_project(project))


def pcb_resource(project: str) -> dict[str, Any]:
    """Return parsed PCB data (layers, nets, footprints, tracks, outline)."""
    return pcb.read_pcb(decode_project(project))


def hierarchy_resource(project: str) -> dict[str, Any]:
    """Return the parsed schematic sheet hierarchy."""
    return hierarchy.read_hierarchy(decode_project(project))


def netlist_resource(project: str) -> dict[str, Any]:
    """Return a freshly exported KiCad netlist (requires kicad-cli)."""
    return netlist.read_netlist(decode_project(project))


def bom_resource(project: str) -> dict[str, Any]:
    """Return a freshly exported BOM as normalized rows (requires kicad-cli)."""
    return bom.read_bom(decode_project(project))


def stackup_resource(project: str) -> dict[str, Any]:
    """Return the parsed or derived board layer stackup."""
    return board.read_layer_stackup(decode_project(project))
