"""Schematic (.kicad_sch) extraction for the MCP server."""

from __future__ import annotations

from typing import Any

from codex_kicad_mcp import config
from codex_kicad_mcp.response import envelope, parse_artifact
from codex_kicad_mcp.sexpr import as_float, children, first_child, scalar_child

SCHEMATIC_LABEL_KINDS = {"label", "global_label", "hierarchical_label"}


def read_schematic(project: str) -> dict[str, object]:
    project_path, artifact_path, top, source = parse_artifact(project, ".kicad_sch", "kicad_sch")

    symbols: list[dict[str, object]] = []
    labels: list[dict[str, object]] = []
    wires: list[dict[str, object]] = []
    sheets: list[dict[str, object]] = []

    # Use an explicit stack rather than recursive descent.  Real projects can
    # contain deeply nested embedded library data, and a malformed file should
    # produce a tool error instead of a Python ``RecursionError``.
    pending: list[list[Any]] = [top]
    while pending:
        node = pending.pop()
        if not node:
            continue
        kind = node[0]
        if kind == "lib_symbols":
            # Library definitions can contain thousands of symbol fragments;
            # they are not placed instances and are intentionally omitted.
            continue
        if kind == "symbol":
            props: dict[str, str] = {}
            for prop in children(node, "property"):
                if len(prop) >= 3 and isinstance(prop[1], str):
                    props[prop[1]] = str(prop[2])
            lib_id = first_child(node, "lib_id")
            position = None
            at = first_child(node, "at")
            if at and len(at) >= 3:
                position = {
                    "x": as_float(at[1]),
                    "y": as_float(at[2]),
                    "angle": as_float(at[3]) if len(at) > 3 else 0.0,
                }
            config.bounded_append(
                symbols,
                {
                    "reference": props.get("Reference"),
                    "value": props.get("Value"),
                    "libId": lib_id[1] if lib_id and len(lib_id) > 1 else None,
                    "uuid": scalar_child(node, "uuid"),
                    "position": position,
                    "properties": props,
                    "pins": [
                        {
                            "number": pin[1] if len(pin) > 1 else None,
                            "uuid": scalar_child(pin, "uuid"),
                        }
                        for pin in children(node, "pin")
                    ],
                },
                "schematic symbols",
            )
        elif kind in SCHEMATIC_LABEL_KINDS:
            at = first_child(node, "at")
            config.bounded_append(
                labels,
                {
                    "kind": kind,
                    "text": node[1] if len(node) > 1 and isinstance(node[1], str) else None,
                    "position": {
                        "x": as_float(at[1]),
                        "y": as_float(at[2]),
                    }
                    if at and len(at) >= 3
                    else None,
                    "uuid": scalar_child(node, "uuid"),
                },
                "schematic labels",
            )
        elif kind == "wire":
            pts = children(node, "pts")
            points: list[dict[str, float | None]] = []
            if pts:
                for xy in children(pts[0], "xy"):
                    if len(xy) >= 3:
                        config.bounded_append(
                            points,
                            {"x": as_float(xy[1]), "y": as_float(xy[2])},
                            "wire points",
                        )
            config.bounded_append(
                wires,
                {"points": points, "uuid": scalar_child(node, "uuid")},
                "schematic wires",
            )
        elif kind == "sheet":
            props = {str(prop[1]): str(prop[2]) for prop in children(node, "property") if len(prop) >= 3}
            at = first_child(node, "at")
            size = first_child(node, "size")
            config.bounded_append(
                sheets,
                {
                    "uuid": scalar_child(node, "uuid"),
                    "name": props.get("Sheetname"),
                    "file": props.get("Sheetfile"),
                    "position": {
                        "x": as_float(at[1]),
                        "y": as_float(at[2]),
                    }
                    if at and len(at) >= 3
                    else None,
                    "size": {
                        "width": as_float(size[1]),
                        "height": as_float(size[2]),
                    }
                    if size and len(size) >= 3
                    else None,
                    "pins": [
                        {
                            "name": pin[1] if len(pin) > 1 else None,
                            "direction": pin[2] if len(pin) > 2 else None,
                            "position": (
                                {
                                    "x": as_float(pin_at[1]),
                                    "y": as_float(pin_at[2]),
                                }
                                if (pin_at := first_child(pin, "at")) and len(pin_at) >= 3
                                else None
                            ),
                            "uuid": scalar_child(pin, "uuid"),
                        }
                        for pin in children(node, "pin")
                    ],
                },
                "schematic sheets",
            )
        for child in reversed(node[1:]):
            if isinstance(child, list):
                pending.append(child)

    title_block = first_child(top, "title_block")
    metadata = {
        "version": scalar_child(top, "version"),
        "generator": scalar_child(top, "generator"),
        "title": scalar_child(title_block, "title") if title_block else None,
        "date": scalar_child(title_block, "date") if title_block else None,
        "revision": scalar_child(title_block, "rev") if title_block else None,
        "company": scalar_child(title_block, "company") if title_block else None,
    }
    data = {
        "path": artifact_path,
        "metadata": metadata,
        "symbols": symbols,
        "labels": labels,
        "wires": wires,
        "sheets": sheets,
    }
    counts = {
        "symbols": len(symbols),
        "labels": len(labels),
        "wires": len(wires),
        "sheets": len(sheets),
    }
    return envelope(project_path, source, data, counts)
