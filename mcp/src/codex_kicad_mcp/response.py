"""Common response envelope and artifact parsing helpers.

All data-facing tools return the same top-level contract so MCP callers can
apply one schema to schematic, PCB, CLI export, and diagnostic results.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from codex_kicad_mcp.project import artifact_file, read_text, workspace
from codex_kicad_mcp.sexpr import parse_sexpr


def _relative(path: Path) -> str:
    return (path.relative_to(workspace())).as_posix()


def artifact_source(path: Path, text: str) -> dict[str, str | int]:
    """Build source provenance from exactly the bytes exposed to the parser."""
    payload = text.encode("utf-8")
    return {
        "path": _relative(path),
        "sha256": hashlib.sha256(payload).hexdigest(),
        "sizeBytes": len(payload),
    }


def load_artifact(project: str, suffix: str) -> tuple[str, str, str, dict[str, str | int]]:
    """Validate, read, hash, and locate a project artifact.

    The returned project and path values are workspace-relative.  Returning
    the decoded text lets a tool hash the same representation it parses.
    """
    path = artifact_file(project, suffix)
    text = read_text(path)
    project_path = path.with_suffix(".kicad_pro")
    return (
        (project_path.relative_to(workspace())).as_posix(),
        (path.relative_to(workspace())).as_posix(),
        text,
        artifact_source(path, text),
    )


def parse_artifact(project: str, suffix: str, root_name: str) -> tuple[str, str, list[Any], dict[str, str | int]]:
    """Parse a KiCad S-expression artifact and return its root node."""
    project_path, artifact_path, text, source = load_artifact(project, suffix)
    try:
        root = parse_sexpr(text)
    except ValueError as exc:
        raise ValueError(f"artifact is not valid KiCad S-expression: {Path(artifact_path).name}: {exc}") from exc
    top = next((node for node in root if isinstance(node, list) and node and node[0] == root_name), None)
    if top is None:
        raise ValueError(f"artifact does not contain a {root_name} root: {Path(artifact_path).name}")
    return project_path, artifact_path, top, source


def envelope(
    project: str,
    source: dict[str, str | int],
    data: dict[str, Any],
    counts: dict[str, int],
    *,
    warnings: list[str] | None = None,
    confidence: str = "parsed",
) -> dict[str, object]:
    if confidence not in {"parsed", "cli", "heuristic"}:
        raise ValueError("confidence must be 'parsed', 'cli', or 'heuristic'")
    return {
        "schemaVersion": "1.0",
        "project": project,
        "source": source,
        "data": data,
        "counts": counts,
        "warnings": warnings or [],
        "confidence": confidence,
    }
