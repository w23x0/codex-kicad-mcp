"""Hierarchical schematic traversal and bus geometry extraction."""

from __future__ import annotations

from itertools import pairwise
from pathlib import Path
from typing import Any

from codex_kicad_mcp import config
from codex_kicad_mcp.project import artifact_file, inside_workspace, read_text, rel_posix, safe_relative, workspace
from codex_kicad_mcp.response import artifact_source, envelope, parse_artifact
from codex_kicad_mcp.schematic import SCHEMATIC_LABEL_KINDS
from codex_kicad_mcp.sexpr import as_float, children, first_child, parse_sexpr, scalar_child

MAX_HIERARCHY_DEPTH = 64


def _load_schematic(path: Path) -> tuple[list[Any], list[Any]]:
    try:
        text = read_text(path)
        root = parse_sexpr(text)
    except (OSError, UnicodeError, ValueError) as exc:
        raise ValueError(f"could not parse schematic: {path.name}: {exc}") from exc
    top = next((node for node in root if isinstance(node, list) and node and node[0] == "kicad_sch"), None)
    if top is None:
        raise ValueError(f"schematic does not contain a kicad_sch root: {path.name}")
    return text, top


def _sheet_props(node: list[Any]) -> dict[str, str]:
    return {str(prop[1]): str(prop[2]) for prop in children(node, "property") if len(prop) >= 3}


def _position(node: Any) -> dict[str, float | None] | None:
    at = first_child(node, "at")
    if at and len(at) >= 3:
        return {"x": as_float(at[1]), "y": as_float(at[2])}
    return None


def read_hierarchy(project: str) -> dict[str, object]:
    root_path = artifact_file(project, ".kicad_sch")
    root_text, _root_top = _load_schematic(root_path)
    source = artifact_source(root_path, root_text)
    root = rel_posix(root_path.with_suffix(".kicad_pro"))
    warnings: list[str] = []
    nodes: list[dict[str, object]] = []
    visited: set[str] = set()

    def walk(path: Path, name: str, sheet_path: str, uuid_path: str, depth: int) -> str:
        canonical = str(path.resolve(strict=True))
        if canonical in visited:
            warning = f"hierarchy cycle skipped: {safe_relative(path, workspace()) or path.name}"
            config.bounded_append(warnings, warning, "hierarchy warnings")
            return canonical
        visited.add(canonical)
        _, top = _load_schematic(path)
        sheets: list[dict[str, object]] = []
        hierarchical_labels = [
            {
                "name": label[1] if len(label) > 1 and isinstance(label[1], str) else None,
                "position": _position(label),
                "uuid": scalar_child(label, "uuid"),
            }
            for label in top[1:]
            if isinstance(label, list) and label and label[0] == "hierarchical_label"
        ]
        for sheet in top[1:]:
            if not isinstance(sheet, list) or not sheet or sheet[0] != "sheet":
                continue
            props = _sheet_props(sheet)
            relative_file = props.get("Sheetfile")
            if not relative_file:
                config.bounded_append(
                    warnings,
                    f"sheet has no Sheetfile property: {sheet_path}",
                    "hierarchy warnings",
                )
                continue
            try:
                child_path = inside_workspace(str(path.parent / relative_file)).resolve(strict=True)
            except (OSError, RuntimeError, ValueError):
                child_path = None
            if child_path is None or child_path.suffix.lower() != ".kicad_sch" or not child_path.is_file():
                config.bounded_append(
                    warnings,
                    f"missing or outside-workspace sheet file: {relative_file}",
                    "hierarchy warnings",
                )
                continue
            child_name = props.get("Sheetname") or Path(relative_file).stem
            child_uuid = scalar_child(sheet, "uuid")
            child_sheet_path = f"{sheet_path}{child_name}/"
            child_uuid_path = f"{uuid_path}{child_uuid or ''}/" if child_uuid else uuid_path
            config.bounded_append(
                sheets,
                {
                    "name": child_name,
                    "uuid": child_uuid,
                    "file": safe_relative(child_path, workspace()),
                    "sheetPath": child_sheet_path,
                    "uuidPath": child_uuid_path,
                    "pins": [
                        {
                            "name": pin[1] if len(pin) > 1 else None,
                            "direction": pin[2] if len(pin) > 2 else None,
                            "position": _position(pin),
                            "uuid": scalar_child(pin, "uuid"),
                        }
                        for pin in children(sheet, "pin")
                    ],
                    "depth": depth + 1,
                },
                "hierarchy sheets",
            )
            if depth + 1 >= MAX_HIERARCHY_DEPTH:
                config.bounded_append(warnings, f"hierarchy depth limit reached at {child_name}", "hierarchy warnings")
                continue
            walk(child_path, child_name, child_sheet_path, child_uuid_path, depth + 1)
        config.bounded_append(
            nodes,
            {
                "name": name,
                "file": safe_relative(path, workspace()),
                "sheetPath": sheet_path,
                "uuidPath": uuid_path,
                "depth": depth,
                "hierarchicalLabels": hierarchical_labels,
                "sheets": sheets,
            },
            "hierarchy nodes",
        )
        return canonical

    walk(root_path, root_path.stem, "/", "/", 0)
    nodes.reverse()
    data = {
        "path": (root_path.relative_to(workspace())).as_posix(),
        "root": root,
        "nodes": nodes,
    }
    counts = {
        "nodes": len(nodes),
        "sheets": sum(len(node["sheets"]) for node in nodes),
        "hierarchicalLabels": sum(len(node["hierarchicalLabels"]) for node in nodes),
    }
    return envelope(root, source, data, counts, warnings=warnings)


def _parse_range(name: str | None) -> dict[str, str | int | None] | None:
    if not name or "[" not in name or ".." not in name or "]" not in name:
        return None
    try:
        prefix, bracket = name.split("[", 1)
        body, suffix = bracket.rsplit("]", 1)
        first, last = body.split("..", 1)
        width = len(first)
        return {
            "prefix": prefix,
            "first": int(first),
            "last": int(last),
            "suffix": suffix,
            "digits": width,
        }
    except (TypeError, ValueError):
        return None


def _point_on_bus(point: dict[str, float | None], points: list[dict[str, float | None]]) -> bool:
    px, py = point.get("x") or 0.0, point.get("y") or 0.0
    for first, second in pairwise(points):
        x1, y1 = first.get("x") or 0.0, first.get("y") or 0.0
        x2, y2 = second.get("x") or 0.0, second.get("y") or 0.0
        cross = (px - x1) * (y2 - y1) - (py - y1) * (x2 - x1)
        within = min(x1, x2) - 1e-6 <= px <= max(x1, x2) + 1e-6 and min(y1, y2) - 1e-6 <= py <= max(y1, y2) + 1e-6
        if abs(cross) <= 1e-6 and within:
            return True
    return False


def read_buses(project: str) -> dict[str, object]:
    project_path, artifact_path, top, source = parse_artifact(project, ".kicad_sch", "kicad_sch")
    warnings: list[str] = []
    labels = [node for node in top[1:] if isinstance(node, list) and node and node[0] in SCHEMATIC_LABEL_KINDS]
    buses: list[dict[str, object]] = []
    entries: list[dict[str, object]] = []
    for bus in top[1:]:
        if not isinstance(bus, list) or not bus or bus[0] != "bus":
            continue
        pts = first_child(bus, "pts")
        points = [{"x": as_float(xy[1]), "y": as_float(xy[2])} for xy in children(pts, "xy") if pts and len(xy) >= 3]
        matching = []
        for label in labels:
            position = _position(label)
            if position and _point_on_bus(position, points):
                matching.append(label)
        name = next(
            (
                label[1]
                for label in matching
                if len(label) > 1 and isinstance(label[1], str) and ("[" in label[1] or "<" in label[1])
            ),
            None,
        )
        if name is None and matching:
            name = matching[0][1] if len(matching[0]) > 1 else None
        if name is None:
            config.bounded_append(warnings, "bus has no matching range label", "schematic buses")
        bus_uuid = scalar_child(bus, "uuid")
        bus_entry: dict[str, object] = {
            "name": name,
            "range": _parse_range(name),
            "uuid": bus_uuid,
            "points": points,
            "entries": [],
        }
        for entry in top[1:]:
            if not isinstance(entry, list) or not entry or entry[0] != "bus_entry":
                continue
            bus_point = _position(entry)
            size = first_child(entry, "size")
            wire_point = None
            if bus_point and size and len(size) >= 3:
                wire_point = {
                    "x": (bus_point["x"] or 0) + (as_float(size[1]) or 0),
                    "y": (bus_point["y"] or 0) + (as_float(size[2]) or 0),
                }
            if bus_point and _point_on_bus(bus_point, points):
                item = {
                    "busPoint": bus_point,
                    "wirePoint": wire_point,
                    "uuid": scalar_child(entry, "uuid"),
                    "busUuid": bus_uuid,
                }
                config.bounded_append(entries, item, "bus entries")
                config.bounded_append(bus_entry["entries"], item, "bus entries")
        config.bounded_append(buses, bus_entry, "schematic buses")
    data = {
        "path": artifact_path,
        "buses": buses,
        "busEntries": entries,
    }
    counts = {
        "buses": len(buses),
        "busEntries": len(entries),
    }
    return envelope(project_path, source, data, counts, warnings=warnings)
