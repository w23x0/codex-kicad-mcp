"""Workspace boundary, project discovery, and artifact resolution.

Every path a tool touches is resolved below the ``KICAD_WORKSPACE`` root by
the helpers in this module; they are the only place allowed to turn user
input into filesystem paths.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from codex_kicad_mcp import config


def workspace() -> Path:
    raw_root = os.environ.get("KICAD_WORKSPACE")
    if raw_root is None or not raw_root.strip():
        raise ValueError("KICAD_WORKSPACE is not configured")
    try:
        path = Path(raw_root).expanduser().resolve(strict=True)
    except (OSError, RuntimeError, ValueError) as exc:
        raise ValueError("KICAD_WORKSPACE could not be resolved") from exc
    if not path.is_dir():
        raise ValueError(f"KICAD_WORKSPACE is not a directory: {path}")
    return path


def inside_workspace(value: str) -> Path:
    if not isinstance(value, str):
        raise ValueError("path must be a string")
    if not value or not value.strip():
        raise ValueError("path must not be empty")
    if "\x00" in value:
        raise ValueError("path contains a NUL character")
    root = workspace()
    try:
        candidate = Path(value)
        # ``Path(root) / absolute`` discards root on all supported platforms;
        # spelling this out makes the security boundary obvious and testable.
        path = (candidate if candidate.is_absolute() else root / candidate).resolve(strict=False)
        path.relative_to(root)
    except ValueError as exc:
        raise ValueError("path must stay inside KICAD_WORKSPACE") from exc
    except (OSError, RuntimeError) as exc:
        raise ValueError("path could not be resolved safely") from exc
    return path


def project_file(project: str) -> Path:
    path = inside_workspace(project)
    if path.suffix.lower() != ".kicad_pro" or not path.is_file():
        raise ValueError("project must be an existing .kicad_pro file")
    # Resolve once more after the existence check.  This does not attempt to
    # make a mutable filesystem atomic, but it closes the common symlink escape
    # case and keeps the returned path canonical.
    try:
        path = path.resolve(strict=True)
        path.relative_to(workspace())
    except (OSError, RuntimeError, ValueError) as exc:
        raise ValueError("project must stay inside KICAD_WORKSPACE") from exc
    if not path.is_file():
        raise ValueError("project must be an existing .kicad_pro file")
    return path


def artifact_file(project: str, suffix: str) -> Path:
    """Resolve a KiCad artifact beside a validated project file."""
    pro = project_file(project)
    if not suffix.startswith(".") or "/" in suffix or "\\" in suffix:
        raise ValueError("invalid artifact suffix")
    target = pro.with_suffix(suffix)
    # A missing artifact must surface as ``missing project artifact``, not as
    # a workspace escape: resolve leniently first so ``strict`` resolution of
    # a non-existent path cannot be mistaken for a boundary violation.
    try:
        target = target.resolve(strict=False)
        target.relative_to(workspace())
    except (OSError, RuntimeError, ValueError) as exc:
        raise ValueError("project artifact must stay inside KICAD_WORKSPACE") from exc
    if not target.is_file():
        raise ValueError(f"missing project artifact: {target.name}")
    return target


def safe_relative(path: Path, root: Path) -> str | None:
    """Return a workspace-relative path, filtering symlink escapes.

    Response paths always use forward slashes regardless of the host OS: MCP
    clients may run on another platform than the server, and KiCad's own
    Sheetfile references are slash-separated.
    """
    try:
        resolved = path.resolve(strict=True)
        resolved.relative_to(root)
        return resolved.relative_to(root).as_posix()
    except (OSError, RuntimeError, ValueError):
        return None


def rel_posix(path: Path) -> str:
    """Workspace-relative, forward-slash project path for responses."""
    return path.relative_to(workspace()).as_posix()


def read_text(path: Path) -> str:
    """Read a UTF-8 artifact without allowing unbounded memory use."""
    try:
        limit = config.max_file_bytes()
        # Read one byte over the limit so a file that grew after ``stat`` is
        # still rejected.  This also avoids allocating an arbitrarily large
        # string for a malicious or accidentally selected artifact.
        with path.open("rb") as handle:
            payload = handle.read(limit + 1)
    except (OSError, ValueError) as exc:
        raise ValueError(f"could not read artifact: {path.name}") from exc
    if len(payload) > limit:
        raise ValueError(f"artifact exceeds KICAD_MAX_FILE_BYTES ({limit} bytes): {path.name}")
    try:
        return payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError(f"artifact is not valid UTF-8: {path.name}") from exc


def list_kicad_projects() -> list[dict[str, str]]:
    root = workspace()
    projects: list[dict[str, str]] = []
    # ``rglob`` may yield a symlink that resolves outside the workspace (and
    # platform-specific directory traversal behaviour differs).  Filter every
    # candidate through the canonical boundary before exposing it.
    try:
        candidates = sorted(root.rglob("*.kicad_pro"), key=lambda item: str(item).casefold())
    except OSError as exc:
        raise RuntimeError("could not enumerate KICAD_WORKSPACE") from exc
    for candidate in candidates:
        if ".git" in candidate.parts or "node_modules" in candidate.parts:
            continue
        relative = safe_relative(candidate, root)
        if relative is None or not candidate.is_file():
            continue
        config.bounded_append(projects, {"path": relative, "name": candidate.stem}, "project list")
    return projects


def inspect_project(project: str) -> dict[str, object]:
    pro = project_file(project)
    base = pro.with_suffix("")
    files: list[dict[str, Any]] = []
    for suffix in (".kicad_pro", ".kicad_sch", ".kicad_pcb", ".kicad_prl"):
        candidate = Path(str(base) + suffix)
        relative = safe_relative(candidate, workspace())
        if relative is None or not candidate.is_file():
            continue
        try:
            size = candidate.stat().st_size
        except OSError as exc:
            raise RuntimeError(f"could not stat project artifact: {candidate.name}") from exc
        config.bounded_append(files, {"path": relative, "bytes": size}, "project inventory")
    return {"project": (pro.relative_to(workspace())).as_posix(), "files": files}


def project_summary(project: str) -> dict[str, object]:
    pro = project_file(project)
    try:
        data = json.loads(read_text(pro))
    except (ValueError, json.JSONDecodeError, TypeError) as exc:
        raise ValueError("project file is not valid KiCad JSON") from exc
    inventory = inspect_project(project)
    return {
        "project": inventory["project"],
        "fileCount": len(inventory["files"]),
        "fileBytes": sum(item["bytes"] for item in inventory["files"]),
        "metaKeys": sorted(data.keys()),
        "boardPresent": any(item["path"].endswith(".kicad_pcb") for item in inventory["files"]),
        "schematicPresent": any(item["path"].endswith(".kicad_sch") for item in inventory["files"]),
    }
