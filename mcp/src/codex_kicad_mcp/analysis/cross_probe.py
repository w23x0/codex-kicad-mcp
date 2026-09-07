"""Cross-probing between schematic symbols/labels and PCB objects."""

from __future__ import annotations

from codex_kicad_mcp.analysis.context import ProjectContext, load_context
from codex_kicad_mcp.analysis.findings import findings_report


def _matches(text: object, query: str) -> bool:
    return isinstance(text, str) and text.casefold() == query


def _schematic_matches(context: ProjectContext, query: str) -> list[dict[str, object]]:
    data = context.schematic["data"]
    result: list[dict[str, object]] = []
    source = context.schematic["source"]
    for symbol in data.get("symbols", []):
        if not isinstance(symbol, dict):
            continue
        if any(_matches(symbol.get(key), query) for key in ("reference", "value", "libId")):
            result.append(
                {
                    "kind": "symbol",
                    "name": str(symbol.get("reference") or symbol.get("value") or query),
                    "path": source["path"],
                    "position": symbol.get("position"),
                    "uuid": symbol.get("uuid"),
                }
            )
    for label in data.get("labels", []):
        if isinstance(label, dict) and _matches(label.get("text"), query):
            result.append(
                {
                    "kind": "label",
                    "name": str(label.get("text")),
                    "path": source["path"],
                    "position": label.get("position"),
                    "uuid": label.get("uuid"),
                }
            )
    return result


def _netlist_matches(context: ProjectContext, query: str) -> list[dict[str, object]]:
    if context.connectivity is None:
        return []
    data = context.connectivity["data"]
    result: list[dict[str, object]] = []
    source = context.connectivity["source"]
    for component in data.get("components", []):
        if not isinstance(component, dict):
            continue
        if any(_matches(component.get(key), query) for key in ("reference", "value", "footprint")):
            result.append(
                {
                    "kind": "netlist-component",
                    "name": str(component.get("reference") or query),
                    "path": source["path"],
                    "sheetPath": component.get("sheetPath"),
                    "uuid": component.get("uuid"),
                }
            )
    for net in data.get("nets", []):
        if isinstance(net, dict) and _matches(net.get("name"), query):
            result.append(
                {
                    "kind": "netlist-net",
                    "name": str(net.get("name")),
                    "path": source["path"],
                    "nodes": net.get("nodes", []),
                }
            )
    return result


def _pcb_matches(context: ProjectContext, query: str) -> list[dict[str, object]]:
    data = context.pcb["data"]
    source = context.pcb["source"]
    result: list[dict[str, object]] = []
    for footprint in data.get("footprints", []):
        if not isinstance(footprint, dict):
            continue
        if any(_matches(footprint.get(key), query) for key in ("reference", "value", "name")):
            result.append(
                {
                    "kind": "footprint",
                    "name": str(footprint.get("reference") or query),
                    "path": source["path"],
                    "position": footprint.get("position"),
                    "layer": footprint.get("layer"),
                    "uuid": footprint.get("uuid"),
                }
            )
        for pad in footprint.get("pads", []):
            if isinstance(pad, dict) and _matches(pad.get("netName"), query):
                result.append(
                    {
                        "kind": "pad",
                        "name": f"{footprint.get('reference')}.{pad.get('number')}",
                        "path": source["path"],
                        "position": pad.get("position"),
                        "layer": footprint.get("layer"),
                        "uuid": footprint.get("uuid"),
                    }
                )
    for key, kind in (("segments", "track"), ("vias", "via"), ("zones", "zone")):
        for item in data.get(key, []):
            if isinstance(item, dict) and _matches(item.get("netName"), query):
                position = (
                    item.get("start") or item.get("position") or (item.get("polygons") or [None])[0]
                    if key != "zones"
                    else (item.get("polygons") or [None])[0]
                )
                result.append(
                    {
                        "kind": kind,
                        "name": str(item.get("netName") or query),
                        "path": source["path"],
                        "position": position,
                        "layer": item.get("layer"),
                        "uuid": item.get("uuid"),
                    }
                )
    return result


def cross_probe(project: str, query: str) -> dict[str, object]:
    """Return locations for one reference, value, net name, or label."""
    if not isinstance(query, str) or not query.strip():
        raise ValueError("query must be a non-empty string")
    query = query.strip()
    context = load_context(project)
    groups = {
        "schematic": _schematic_matches(context, query.casefold()),
        "netlist": _netlist_matches(context, query.casefold()),
        "pcb": _pcb_matches(context, query.casefold()),
    }
    counts = {
        "schematic": len(groups["schematic"]),
        "netlist": len(groups["netlist"]),
        "pcb": len(groups["pcb"]),
        "matches": sum(len(items) for items in groups.values()),
    }
    return findings_report(
        context.project,
        context.schematic["source"],
        [],
        data={"query": query, "matches": groups},
        counts=counts,
        warnings=[
            *context.schematic.get("warnings", []),
            *context.pcb.get("warnings", []),
            *(context.connectivity or {}).get("warnings", []),
        ],
        confidence="parsed" if counts["pcb"] or counts["schematic"] else "cli",
    )
