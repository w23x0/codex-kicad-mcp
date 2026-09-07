"""PCB (.kicad_pcb) extraction for the MCP server."""

from __future__ import annotations

from typing import Any

from codex_kicad_mcp import config
from codex_kicad_mcp.response import envelope, parse_artifact
from codex_kicad_mcp.sexpr import as_float, as_int, children, first_child, scalar_child


def _point(node: list[Any], name: str) -> dict[str, float | None] | None:
    child = first_child(node, name)
    if child and len(child) >= 3:
        return {"x": as_float(child[1]), "y": as_float(child[2])}
    return None


def _points(node: list[Any]) -> list[dict[str, float | None]]:
    result: list[dict[str, float | None]] = []
    pts = first_child(node, "pts")
    for xy in children(pts, "xy") if pts else []:
        if len(xy) >= 3:
            config.bounded_append(result, {"x": as_float(xy[1]), "y": as_float(xy[2])}, "PCB points")
    return result


def _net_value(node: list[Any] | None) -> tuple[int | str | None, str | None]:
    if not node or len(node) < 2:
        return None, None
    number = as_int(node[1])
    if number is not None:
        return number, str(node[2]) if len(node) > 2 and isinstance(node[2], str) else None
    return node[1], str(node[1])


def read_pcb(project: str) -> dict[str, object]:
    project_path, artifact_path, top, source = parse_artifact(project, ".kicad_pcb", "kicad_pcb")

    layers: list[dict[str, object]] = []
    nets: list[dict[str, object]] = []
    net_names: dict[int, str] = {}
    footprints: list[dict[str, object]] = []
    segments: list[dict[str, object]] = []
    vias: list[dict[str, object]] = []
    zones: list[dict[str, object]] = []
    outline: list[dict[str, object]] = []

    for child in top[1:]:
        if not isinstance(child, list) or not child:
            continue
        kind = child[0]
        if kind == "layers":
            for layer in child[1:]:
                if isinstance(layer, list) and len(layer) >= 3:
                    config.bounded_append(
                        layers,
                        {
                            "id": parsed_id if (parsed_id := as_int(layer[0])) is not None else layer[0],
                            "name": layer[1],
                            "type": layer[2] if len(layer) > 2 else None,
                            "user": layer[3] if len(layer) > 3 else None,
                        },
                        "PCB layers",
                    )
        elif kind == "net" and len(child) >= 3:
            net_id = as_int(child[1])
            name = str(child[2])
            if net_id is not None:
                net_names[net_id] = name
            config.bounded_append(nets, {"id": net_id if net_id is not None else child[1], "name": name}, "PCB nets")
        elif kind == "footprint":
            at = first_child(child, "at")
            layer = first_child(child, "layer")
            props = {str(item[1]): str(item[2]) for item in children(child, "property") if len(item) >= 3}
            pads: list[dict[str, Any]] = []
            for pad in children(child, "pad"):
                pad_layers = first_child(pad, "layers")
                pad_id, pad_name = _net_value(first_child(pad, "net"))
                if pad_name and pad_id is None:
                    pad_id = next((item["id"] for item in nets if item["name"] == pad_name), None)
                config.bounded_append(
                    pads,
                    {
                        "number": pad[1] if len(pad) > 1 else None,
                        "type": pad[2] if len(pad) > 2 else None,
                        "shape": pad[3] if len(pad) > 3 else None,
                        "position": _point(pad, "at"),
                        "size": _point(pad, "size"),
                        "drill": as_float(scalar_child(pad, "drill")),
                        "layers": pad_layers[1:] if pad_layers else [],
                        "net": pad_id if pad_id is not None else pad_name,
                        "netName": pad_name,
                    },
                    "PCB pads",
                )
            config.bounded_append(
                footprints,
                {
                    "name": child[1] if len(child) > 1 else None,
                    "reference": props.get("Reference"),
                    "value": props.get("Value"),
                    "layer": layer[1] if layer and len(layer) > 1 else None,
                    "uuid": scalar_child(child, "uuid"),
                    "position": (
                        {
                            "x": as_float(at[1]),
                            "y": as_float(at[2]),
                            "angle": as_float(at[3]) if at and len(at) > 3 else 0.0,
                        }
                        if at and len(at) >= 3
                        else None
                    ),
                    "pads": pads,
                },
                "PCB footprints",
            )
        elif kind in {"segment", "gr_line", "gr_arc", "gr_rect", "gr_poly", "gr_circle"}:
            layer = first_child(child, "layer")
            item: dict[str, Any] = {
                "kind": kind,
                "layer": layer[1] if layer and len(layer) > 1 else None,
                "uuid": scalar_child(child, "uuid"),
            }
            for point_name in ("start", "mid", "end", "center"):
                if point := _point(child, point_name):
                    item[point_name] = point
            if kind == "gr_poly":
                item["points"] = _points(child)
            if kind == "segment":
                width = first_child(child, "width")
                net_id, net_name = _net_value(first_child(child, "net"))
                if net_name and net_id is None:
                    net_id = next((entry["id"] for entry in nets if entry["name"] == net_name), None)
                item["width"] = as_float(width[1]) if width and len(width) > 1 else None
                item["net"] = net_id if net_id is not None else net_name
                item["netName"] = net_name
                config.bounded_append(segments, item, "PCB segments")
            elif item["layer"] == "Edge.Cuts":
                config.bounded_append(outline, item, "PCB outline items")
        elif kind == "via":
            layer_nodes = first_child(child, "layers")
            net_id, net_name = _net_value(first_child(child, "net"))
            if net_name and net_id is None:
                net_id = next((entry["id"] for entry in nets if entry["name"] == net_name), None)
            size = first_child(child, "size")
            drill = first_child(child, "drill")
            config.bounded_append(
                vias,
                {
                    "position": _point(child, "at"),
                    "size": as_float(size[1]) if size and len(size) > 1 else None,
                    "drill": as_float(drill[1]) if drill and len(drill) > 1 else None,
                    "layers": layer_nodes[1:] if layer_nodes else [],
                    "net": net_id if net_id is not None else net_name,
                    "netName": net_name,
                    "type": scalar_child(child, "type") or scalar_child(child, "via_type") or "through",
                    "uuid": scalar_child(child, "uuid"),
                },
                "PCB vias",
            )
        elif kind == "zone":
            layer = first_child(child, "layer")
            zone_layers = first_child(child, "layers")
            net_id, net_name = _net_value(first_child(child, "net"))
            if net_name and net_id is None:
                net_id = next((entry["id"] for entry in nets if entry["name"] == net_name), None)
            polygons: list[list[dict[str, float | None]]] = []
            for polygon in children(child, "polygon"):
                points = _points(polygon)
                if points:
                    config.bounded_append(polygons, points, "zone points")
            config.bounded_append(
                zones,
                {
                    "layer": layer[1] if layer and len(layer) > 1 else None,
                    "layers": zone_layers[1:] if zone_layers else [],
                    "net": net_id if net_id is not None else net_name,
                    "netName": net_name,
                    "uuid": scalar_child(child, "uuid"),
                    "polygons": polygons,
                },
                "PCB zones",
            )

    general = first_child(top, "general")
    setup = first_child(top, "setup")
    metadata = {
        "version": scalar_child(top, "version"),
        "generator": scalar_child(top, "generator"),
        "thickness": scalar_child(general, "thickness") if general else None,
        "plotReference": scalar_child(setup, "plot_on_all_layers_selection") if setup else None,
    }
    data = {
        "path": artifact_path,
        "metadata": metadata,
        "layers": layers,
        "nets": nets,
        "footprints": footprints,
        "segments": segments,
        "vias": vias,
        "zones": zones,
        "outline": outline,
    }
    counts = {
        "layers": len(layers),
        "nets": len(nets),
        "footprints": len(footprints),
        "segments": len(segments),
        "vias": len(vias),
        "zones": len(zones),
        "outline": len(outline),
    }
    return envelope(project_path, source, data, counts)
