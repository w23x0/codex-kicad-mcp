"""Decoupling and local power-delivery heuristics."""

from __future__ import annotations

from typing import Any

from codex_kicad_mcp.analysis.connectivity import (
    is_power_symbol,
    is_supply_pin,
    is_supply_rail,
    pad_board_position,
    parse_capacitance,
)
from codex_kicad_mcp.analysis.context import ProjectContext, load_context
from codex_kicad_mcp.analysis.findings import finding, findings_report


def _index_components(connectivity: dict[str, Any]) -> dict[str, dict[str, Any]]:
    data = connectivity["data"]
    return {
        str(component.get("reference")): component
        for component in data.get("components", [])
        if isinstance(component, dict) and component.get("reference")
    }


def _net_map(connectivity: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    result: dict[str, list[dict[str, Any]]] = {}
    for net in connectivity["data"].get("nets", []):
        if isinstance(net, dict) and isinstance(net.get("name"), str):
            result[net["name"]] = [node for node in net.get("nodes", []) if isinstance(node, dict)]
    return result


def _supply_ics(nodes: list[dict[str, Any]], components: dict[str, dict[str, Any]]) -> set[str]:
    result: set[str] = set()
    for node in nodes:
        reference = str(node.get("reference") or "")
        component = components.get(reference)
        if component is None or reference.startswith("#") or is_power_symbol(reference):
            continue
        if is_supply_pin(node.get("pinFunction")) or "power" in str(node.get("pinType") or "").casefold():
            result.add(reference)
    return result


def _object(reference: str, component: dict[str, Any]) -> dict[str, object]:
    return {"kind": "component", "name": reference, "uuid": component.get("uuid")}


def review_decoupling(context: ProjectContext, near_pin_mm: float = 5.0) -> dict[str, object]:
    """Check capacitor connectivity, sharing, bulk coverage, and placement."""
    if context.connectivity is None:
        raise ValueError("decoupling analysis requires a netlist export")
    if not isinstance(near_pin_mm, (int, float)) or isinstance(near_pin_mm, bool) or not 0 < float(near_pin_mm) <= 100:
        raise ValueError("near_pin_mm must be between 0 and 100")
    near_pin_mm = float(near_pin_mm)
    connectivity = context.connectivity
    components = _index_components(connectivity)
    nets = _net_map(connectivity)
    caps: list[dict[str, Any]] = []
    for reference, component in sorted(components.items()):
        if reference.startswith("#") or not reference.upper().startswith("C"):
            continue
        fields = component.get("fields", {}) if isinstance(component.get("fields"), dict) else {}
        if str(fields.get("DNP") or "").strip().upper() in {"1", "TRUE", "YES"}:
            continue
        connected = {
            net_name
            for net_name, nodes in nets.items()
            if any(str(node.get("reference")) == reference for node in nodes)
        }
        caps.append(
            {
                "reference": reference,
                "component": component,
                "nets": connected,
                "capacitance": parse_capacitance(component.get("value")),
            }
        )

    bypass_count_by_net: dict[str, int] = {}
    for cap in caps:
        if cap["capacitance"] is not None and cap["capacitance"] > 1e-6:
            continue
        for net_name in cap["nets"]:
            if is_supply_rail(net_name):
                bypass_count_by_net[net_name] = bypass_count_by_net.get(net_name, 0) + 1

    findings: list[dict[str, object]] = []
    bypass_caps: list[dict[str, Any]] = []
    bulk_caps: list[dict[str, Any]] = []
    for cap in caps:
        reference = str(cap["reference"])
        component = cap["component"]
        net_names = {str(name) for name in cap["nets"]}
        if len(net_names) < 2:
            findings.append(
                finding(
                    "decoupling.cap_missing",
                    kind="decoupling",
                    severity="warning",
                    message=f"Capacitor {reference} is not connected to both a supply and return path",
                    source_path=connectivity["source"]["path"],
                    confidence="medium",
                    objects=[_object(reference, component)],
                    schematic={"symbol": reference, "sheetPath": component.get("sheetPath")},
                    suggestions=["Connect the capacitor across its intended supply rail and ground"],
                )
            )
        capacitance = cap["capacitance"]
        (bulk_caps if capacitance is not None and capacitance > 1e-6 else bypass_caps).append(cap)
        if capacitance is not None and capacitance > 1e-6:
            # Bulk storage is intentionally shared and may be placed away from
            # an individual IC supply pin; only bypass caps use the placement rule.
            continue
        supply_nets = sorted(name for name in net_names if is_supply_rail(name))
        if not supply_nets:
            continue
        pcb_footprints = context.pcb["data"].get("footprints", [])
        pcb_cap = next(
            (
                footprint
                for footprint in pcb_footprints
                if isinstance(footprint, dict) and footprint.get("reference") == reference
            ),
            None,
        )
        if pcb_cap is None:
            continue
        for supply_name in supply_nets:
            ics = sorted(_supply_ics(nets.get(supply_name, []), components))
            if not ics:
                continue
            distances: list[float] = []
            for ic_reference in ics:
                ic_footprint = next(
                    (
                        footprint
                        for footprint in pcb_footprints
                        if isinstance(footprint, dict) and footprint.get("reference") == ic_reference
                    ),
                    None,
                )
                if ic_footprint is None:
                    continue
                cap_positions = [
                    pad_board_position(pcb_cap, pad)
                    for pad in pcb_cap.get("pads", [])
                    if isinstance(pad, dict) and pad.get("netName") == supply_name
                ]
                ic_positions = [
                    pad_board_position(ic_footprint, pad)
                    for pad in ic_footprint.get("pads", [])
                    if isinstance(pad, dict)
                    and (
                        pad.get("netName") == supply_name
                        or is_supply_pin(
                            next(
                                (
                                    node.get("pinFunction")
                                    for node in nets.get(supply_name, [])
                                    if str(node.get("reference")) == ic_reference
                                ),
                                None,
                            )
                        )
                    )
                ]
                distances.extend(
                    ((cap_position[0] - ic_position[0]) ** 2 + (cap_position[1] - ic_position[1]) ** 2) ** 0.5
                    for cap_position in cap_positions
                    if cap_position is not None
                    for ic_position in ic_positions
                    if ic_position is not None
                )
            if distances and min(distances) > near_pin_mm:
                findings.append(
                    finding(
                        "decoupling.cap_not_near_pin",
                        kind="decoupling",
                        severity="warning",
                        message=f"Bypass capacitor {reference} is {min(distances):.2f} mm from the nearest {supply_name} IC pin",
                        source_path=context.pcb["source"]["path"],
                        confidence="medium",
                        objects=[
                            _object(reference, component),
                            _object(str(ics[0]), components.get(ics[0], {})),
                        ],
                        pcb={
                            "footprint": reference,
                            "layer": pcb_cap.get("layer"),
                            "position": pcb_cap.get("position"),
                        },
                        suggestions=["Move the bypass capacitor closer to the IC supply pin or add a closer capacitor"],
                    )
                )
            if len(ics) > 1 and bypass_count_by_net.get(supply_name, 0) == 1:
                findings.append(
                    finding(
                        "decoupling.shared_capacitor",
                        kind="decoupling",
                        severity="warning",
                        message=f"Capacitor {reference} is the only bypass capacitor shared by {len(ics)} ICs on {supply_name}",
                        source_path=connectivity["source"]["path"],
                        confidence="medium",
                        objects=[
                            _object(reference, component),
                            *[_object(reference, components[name]) for name in ics],
                        ],
                        suggestions=["Provide a dedicated bypass capacitor at each IC supply pin"],
                    )
                )
    for rail in sorted({name for cap in bypass_caps for name in cap["nets"] if is_supply_rail(name)}):
        has_consumer = any(_supply_ics(nets.get(rail, []), components))
        if has_consumer and not any(rail in bulk_cap["nets"] for bulk_cap in bulk_caps):
            findings.append(
                finding(
                    "decoupling.missing_bulk_capacitor",
                    kind="decoupling",
                    severity="warning",
                    message=f"Rail {rail} has bypass capacitors and consumers but no bulk capacitor above 1 uF",
                    source_path=connectivity["source"]["path"],
                    confidence="medium",
                    objects=[{"kind": "net", "name": rail, "uuid": None}],
                    suggestions=["Add a local bulk storage capacitor to the rail"],
                )
            )
    counts = {
        "findings": len(findings),
        "rules": len({str(item["ruleId"]) for item in findings}),
        "capacitors": len(caps),
        "bypassCapacitors": len(bypass_caps),
        "bulkCapacitors": len(bulk_caps),
    }
    return findings_report(
        context.project,
        connectivity["source"],
        findings,
        counts=counts,
        warnings=list(connectivity.get("warnings", [])),
        confidence="cli",
    )


def check_decoupling(project: str, near_pin_mm: float = 5.0) -> dict[str, object]:
    return review_decoupling(load_context(project), near_pin_mm)
