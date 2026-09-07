"""Signal-integrity layout heuristics focused on layer changes and stubs."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from codex_kicad_mcp.analysis.connectivity import pad_board_position, pcb_net_names
from codex_kicad_mcp.analysis.context import ProjectContext, load_context
from codex_kicad_mcp.analysis.findings import finding, findings_report
from codex_kicad_mcp.geometry import as_xy


def _point(value: Any) -> tuple[float, float] | None:
    result = as_xy(value)
    return (round(result[0], 6), round(result[1], 6)) if result else None


def _nets_and_layers(context: ProjectContext) -> tuple[dict[str, list[dict[str, Any]]], set[str]]:
    data = context.pcb["data"]
    nets: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for segment in data.get("segments", []):
        if isinstance(segment, dict) and segment.get("netName"):
            nets[str(segment["netName"])].append(segment)
    copper_layers = {
        str(layer.get("name"))
        for layer in data.get("layers", [])
        if isinstance(layer, dict) and layer.get("type") == "signal" and layer.get("name")
    }
    return nets, copper_layers


def _terminals(context: ProjectContext, net_name: str) -> set[tuple[float, float]]:
    terminals: set[tuple[float, float]] = set()
    for footprint in context.pcb["data"].get("footprints", []):
        if not isinstance(footprint, dict):
            continue
        for pad in footprint.get("pads", []):
            if not isinstance(pad, dict):
                continue
            position = pad_board_position(footprint, pad)
            if position is not None:
                terminals.add((round(position[0], 6), round(position[1], 6)))
    return terminals


def review_signal_integrity(context: ProjectContext) -> dict[str, object]:
    """Detect uncontrolled layer transitions and electrically dangling stubs."""
    data = context.pcb["data"]
    nets, _ = _nets_and_layers(context)
    vias_by_point: dict[tuple[float, float], list[dict[str, Any]]] = defaultdict(list)
    for via in data.get("vias", []):
        if not isinstance(via, dict):
            continue
        point = _point(via.get("position"))
        if point is not None:
            vias_by_point[point].append(via)
    endpoints: dict[str, list[tuple[tuple[float, float], str, dict[str, Any], str]]] = defaultdict(list)
    segments: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for net_name, items in nets.items():
        segments[net_name].extend(items)
        for segment in items:
            for endpoint_key in ("start", "end"):
                point = _point(segment.get(endpoint_key))
                layer = str(segment.get("layer") or "unknown")
                if point is not None:
                    endpoints[net_name].append((point, layer, segment, endpoint_key))

    findings: list[dict[str, object]] = []
    for net_name in sorted(nets):
        terminals = _terminals(context, net_name)
        for point, layer, segment, _endpoint_key in endpoints[net_name]:
            degree = sum(
                1
                for other_point, other_layer, _, _ in endpoints[net_name]
                if other_point == point and other_layer == layer
            )
            terminal = any(
                (point[0] - terminal_point[0]) ** 2 + (point[1] - terminal_point[1]) ** 2 <= 0.01**2
                for terminal_point in terminals
            ) or any(layer in [str(item) for item in via.get("layers", [])] for via in vias_by_point.get(point, []))
            if degree == 1 and not terminal:
                findings.append(
                    finding(
                        "si.stub_detected",
                        kind="si",
                        severity="warning",
                        message=f"Track endpoint for net {net_name} is an unconnected stub on {layer}",
                        source_path=context.pcb["source"]["path"],
                        confidence="high",
                        objects=[{"kind": "track", "name": f"{net_name} on {layer}", "uuid": segment.get("uuid")}],
                        pcb={
                            "footprint": None,
                            "layer": layer,
                            "position": {"x": point[0], "y": point[1], "unit": "mm"},
                        },
                        suggestions=["Remove the stub or connect it to the intended terminal"],
                    )
                )

        layers_by_point: dict[tuple[float, float], set[str]] = defaultdict(set)
        for point, layer, _, _ in endpoints[net_name]:
            layers_by_point[point].add(layer)
        for point, layers in sorted(layers_by_point.items()):
            if len(layers) < 2:
                continue
            controlling_vias = [
                via for via in vias_by_point.get(point, []) if {str(item) for item in via.get("layers", [])} >= layers
            ]
            if not controlling_vias:
                findings.append(
                    finding(
                        "si.uncontrolled_layer_change",
                        kind="si",
                        severity="error",
                        message=f"Net {net_name} changes between {', '.join(sorted(layers))} without a via",
                        source_path=context.pcb["source"]["path"],
                        confidence="high",
                        objects=[{"kind": "net", "name": net_name, "uuid": None}],
                        pcb={
                            "footprint": None,
                            "layer": ",".join(sorted(layers)),
                            "position": {"x": point[0], "y": point[1], "unit": "mm"},
                        },
                        suggestions=["Add a via at the layer transition or reroute the net on one layer"],
                    )
                )
    counts = {
        "findings": len(findings),
        "rules": len({str(item["ruleId"]) for item in findings}),
        "nets": len(pcb_net_names(context.pcb)),
        "routedNets": len(nets),
        "copperLayers": len(data.get("layers", [])),
    }
    return findings_report(
        context.project,
        context.pcb["source"],
        findings,
        counts=counts,
        warnings=list(context.pcb.get("warnings", [])),
        confidence="heuristic",
    )


def analyze_signal_integrity(project: str) -> dict[str, object]:
    return review_signal_integrity(load_context(project, require_netlist=False))
