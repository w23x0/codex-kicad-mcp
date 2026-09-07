"""PCB metrics, stackup, via, and zone extraction."""

from __future__ import annotations

from typing import Any

from codex_kicad_mcp.geometry import as_xy, bounding_box, distance, polygon_area
from codex_kicad_mcp.pcb import read_pcb
from codex_kicad_mcp.response import envelope, parse_artifact
from codex_kicad_mcp.sexpr import as_int, first_child, scalar_child


def _points_from(value: Any) -> list[tuple[float, float]]:
    if not isinstance(value, list):
        return []
    result = [as_xy(point) for point in value]
    return [point for point in result if point is not None]


def read_board_metrics(project: str) -> dict[str, object]:
    result = read_pcb(project)
    data = result["data"]
    assert isinstance(data, dict)
    coordinates: list[tuple[float, float]] = []
    outline_coordinates: list[tuple[float, float]] = []
    track_length = 0.0
    length_by_layer: dict[str, float] = {}
    for segment in data.get("segments", []):
        points = _points_from([segment.get("start"), segment.get("end")])
        coordinates.extend(points)
        if len(points) == 2:
            length = distance(points[0], points[1])
            track_length += length
            layer = str(segment.get("layer") or "unknown")
            length_by_layer[layer] = length_by_layer.get(layer, 0.0) + length
    for item in (*data.get("outline", []), *data.get("footprints", [])):
        if isinstance(item, dict):
            coordinates.extend(
                _points_from([item.get("start"), item.get("end"), item.get("center"), item.get("position")])
            )
    for via in data.get("vias", []):
        coordinates.extend(_points_from([via.get("position")]))
    for item in data.get("outline", []):
        if isinstance(item, dict):
            outline_coordinates.extend(_points_from([item.get("start"), item.get("end"), item.get("center")]))
    zone_area = 0.0
    for zone in data.get("zones", []):
        if not isinstance(zone, dict):
            continue
        for polygon in zone.get("polygons", []):
            points = _points_from(polygon)
            coordinates.extend(points)
            zone_area += polygon_area(points)
    box = bounding_box(outline_coordinates or coordinates)
    geometry_box = bounding_box(coordinates)
    size = {
        "width": round(box["maxX"] - box["minX"], 6) if box else 0.0,
        "height": round(box["maxY"] - box["minY"], 6) if box else 0.0,
        "boundingBox": box,
        "geometryBoundingBox": geometry_box,
        "unit": "mm",
    }
    pad_count = sum(len(item.get("pads", [])) for item in data.get("footprints", []) if isinstance(item, dict))
    metadata = data.get("metadata", {})
    metrics = {
        "size": size,
        "thickness": metadata.get("thickness"),
        "copperLayers": sum(
            1 for layer in data.get("layers", []) if isinstance(layer, dict) and layer.get("type") == "signal"
        ),
        "trackLength": round(track_length, 6),
        "trackLengthByLayer": {key: round(value, 6) for key, value in sorted(length_by_layer.items())},
        "zoneArea": round(zone_area, 6),
        "unit": "mm",
    }
    counts = {
        "layers": len(data.get("layers", [])),
        "nets": len(data.get("nets", [])),
        "footprints": len(data.get("footprints", [])),
        "pads": pad_count,
        "segments": len(data.get("segments", [])),
        "vias": len(data.get("vias", [])),
        "zones": len(data.get("zones", [])),
        "outline": len(data.get("outline", [])),
    }
    return envelope(
        result["project"],
        result["source"],
        {"metrics": metrics, "counts": counts},
        counts,
    )


def read_layer_stackup(project: str) -> dict[str, object]:
    project_path, artifact_path, top, source = parse_artifact(project, ".kicad_pcb", "kicad_pcb")
    setup = first_child(top, "setup")
    stackup = first_child(setup, "stackup") if setup else None
    warnings: list[str] = []
    confidence = "parsed"
    items: list[dict[str, object]] = []
    if stackup:
        for child in stackup[1:]:
            if not isinstance(child, list) or not child:
                continue
            if child[0] == "layer":
                config_item: dict[str, object] = {
                    "kind": "layer",
                    "name": child[1] if len(child) > 1 else None,
                    "type": scalar_child(child, "type"),
                    "thickness": scalar_child(child, "thickness"),
                    "material": scalar_child(child, "material"),
                    "color": scalar_child(child, "color"),
                }
            elif child[0] == "dielectric":
                config_item = {
                    "kind": "dielectric",
                    "name": child[1] if isinstance(child[1], str) else None,
                    "type": scalar_child(child, "type"),
                    "thickness": scalar_child(child, "thickness"),
                    "material": scalar_child(child, "material"),
                    "epsilonR": scalar_child(child, "epsilon_r"),
                    "lossTangent": scalar_child(child, "loss tangent") or scalar_child(child, "loss_tangent"),
                }
            else:
                continue
            items.append(config_item)
    else:
        confidence = "heuristic"
        warnings.append("PCB has no embedded stackup; deriving a physical layer list from the layer table")
        for child in top[1:]:
            if not isinstance(child, list) or not child or child[0] != "layers":
                continue
            for layer in child[1:]:
                if isinstance(layer, list) and len(layer) >= 3:
                    items.append(
                        {
                            "kind": "layer",
                            "id": parsed_id if (parsed_id := as_int(layer[0])) is not None else layer[0],
                            "name": layer[1],
                            "type": layer[2] if len(layer) > 2 else None,
                            "user": layer[3] if len(layer) > 3 else None,
                        }
                    )
    general = first_child(top, "general")
    data = {
        "path": artifact_path,
        "source": "stackup" if stackup else "layer-table",
        "thickness": scalar_child(general, "thickness") if general else None,
        "items": items,
    }
    counts = {
        "items": len(items),
        "copperLayers": sum(1 for item in items if item.get("type") == "signal"),
    }
    return envelope(project_path, source, data, counts, warnings=warnings, confidence=confidence)


def read_vias(project: str) -> dict[str, object]:
    result = read_pcb(project)
    data = result["data"]
    assert isinstance(data, dict)
    vias = data.get("vias", [])
    by_type: dict[str, int] = {}
    by_net: dict[str, int] = {}
    by_layer_pair: dict[str, int] = {}
    for via in vias:
        if not isinstance(via, dict):
            continue
        by_type[str(via.get("type") or "unknown")] = by_type.get(str(via.get("type") or "unknown"), 0) + 1
        net = str(via.get("netName") or via.get("net") or "")
        by_net[net or "unassigned"] = by_net.get(net or "unassigned", 0) + 1
        pair = ",".join(str(layer) for layer in via.get("layers", []))
        by_layer_pair[pair or "unknown"] = by_layer_pair.get(pair or "unknown", 0) + 1
    counts = {
        "vias": len(vias),
        "types": len(by_type),
        "nets": len(by_net),
        "layerPairs": len(by_layer_pair),
    }
    return envelope(
        result["project"],
        result["source"],
        {"vias": vias, "byType": by_type, "byNet": by_net, "byLayerPair": by_layer_pair},
        counts,
    )


def read_zones(project: str) -> dict[str, object]:
    result = read_pcb(project)
    data = result["data"]
    assert isinstance(data, dict)
    zones: list[dict[str, object]] = []
    for zone in data.get("zones", []):
        if not isinstance(zone, dict):
            continue
        polygons: list[dict[str, object]] = []
        for points in zone.get("polygons", []):
            coordinates = _points_from(points)
            polygons.append(
                {
                    "points": [{"x": x, "y": y} for x, y in coordinates],
                    "area": round(polygon_area(coordinates), 6),
                    "boundingBox": bounding_box(coordinates),
                }
            )
        zones.append(
            {
                "layer": zone.get("layer"),
                "layers": zone.get("layers", []),
                "net": zone.get("net"),
                "netName": zone.get("netName"),
                "uuid": zone.get("uuid"),
                "polygons": polygons,
            }
        )
    counts = {
        "zones": len(zones),
        "polygons": sum(len(zone.get("polygons", [])) for zone in zones),
    }
    return envelope(
        result["project"],
        result["source"],
        {"zones": zones},
        counts,
    )
