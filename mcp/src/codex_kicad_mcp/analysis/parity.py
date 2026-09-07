"""Schematic-to-PCB parity checks."""

from __future__ import annotations

import re
from typing import Any

from codex_kicad_mcp.analysis.connectivity import (
    component_pins,
    normalized_footprint,
    pcb_net_names,
)
from codex_kicad_mcp.analysis.context import ProjectContext, load_context
from codex_kicad_mcp.analysis.findings import finding, findings_report

# KiCad auto-generates these names for nets without a user label.  They are
# per-view local identifiers, so a schematic-side name does not have to match
# the PCB-side spelling for the same electrical net; flagging them produces
# noise on real boards (the empty PCB net 0 and suffixless Net-() variants
# included).
_AUTO_NET_RE = re.compile(r"^(?:Net-\(.*\)|unconnected-)", re.IGNORECASE)


def _user_net(name: object) -> bool:
    return isinstance(name, str) and bool(name.strip()) and not _AUTO_NET_RE.fullmatch(name.strip())


def _component(reference: str, components: list[dict[str, Any]]) -> dict[str, Any] | None:
    return next((component for component in components if component.get("reference") == reference), None)


def _footprint(reference: str, footprints: list[dict[str, Any]]) -> dict[str, Any] | None:
    return next((footprint for footprint in footprints if footprint.get("reference") == reference), None)


def _component_object(kind: str, reference: str, component: dict[str, Any] | None) -> dict[str, object]:
    return {"kind": kind, "name": reference, "uuid": component.get("uuid") if component else None}


def review_parity(context: ProjectContext) -> dict[str, object]:
    """Compare netlist components, pins, and nets with PCB placement/copper."""
    if context.connectivity is None:
        raise ValueError("parity analysis requires a netlist export")
    connectivity = context.connectivity
    netlist_components = [item for item in connectivity["data"].get("components", []) if isinstance(item, dict)]
    pcb_footprints = [item for item in context.pcb["data"].get("footprints", []) if isinstance(item, dict)]
    netlist_by_ref = {str(item.get("reference")): item for item in netlist_components if item.get("reference")}
    pcb_by_ref = {str(item.get("reference")): item for item in pcb_footprints if item.get("reference")}
    schematic_source = connectivity["source"]["path"]
    findings: list[dict[str, object]] = []

    for reference in sorted(set(netlist_by_ref) - set(pcb_by_ref)):
        component = netlist_by_ref[reference]
        findings.append(
            finding(
                "parity.footprint_mismatch",
                kind="parity",
                severity="error",
                message=f"Component {reference} exists in the schematic but has no PCB footprint",
                source_path=schematic_source,
                confidence="medium",
                objects=[_component_object("component", reference, component)],
                schematic={"symbol": reference, "sheetPath": component.get("sheetPath")},
                suggestions=["Import the schematic changes into the PCB or assign the missing footprint"],
            )
        )
    for reference in sorted(set(pcb_by_ref) - set(netlist_by_ref)):
        footprint = pcb_by_ref[reference]
        findings.append(
            finding(
                "parity.footprint_mismatch",
                kind="parity",
                severity="warning",
                message=f"PCB footprint {reference} has no matching schematic component",
                source_path=context.pcb["source"]["path"],
                confidence="medium",
                objects=[_component_object("footprint", reference, footprint)],
                pcb={"footprint": reference, "layer": footprint.get("layer"), "position": footprint.get("position")},
                suggestions=["Remove the stale PCB footprint or import the missing schematic symbol"],
            )
        )
    for reference in sorted(set(netlist_by_ref) & set(pcb_by_ref)):
        component = netlist_by_ref[reference]
        footprint = pcb_by_ref[reference]
        schematic_fp = normalized_footprint(component.get("footprint"))
        pcb_fp = normalized_footprint(footprint.get("name"))
        if schematic_fp and pcb_fp and schematic_fp != pcb_fp:
            findings.append(
                finding(
                    "parity.footprint_mismatch",
                    kind="parity",
                    severity="error",
                    message=f"Footprint for {reference} differs: {schematic_fp} vs {pcb_fp}",
                    source_path=schematic_source,
                    confidence="high",
                    objects=[
                        _component_object("component", reference, component),
                        _component_object("footprint", reference, footprint),
                    ],
                    pcb={"footprint": reference, "layer": footprint.get("layer")},
                    suggestions=["Update the footprint assignment or replace the PCB footprint"],
                )
            )
        missing_pins = sorted(
            component_pins(component)
            - {str(pad.get("number")) for pad in footprint.get("pads", []) if pad.get("number") is not None}
        )
        for pin in missing_pins:
            findings.append(
                finding(
                    "parity.pin_missing",
                    kind="parity",
                    severity="error",
                    message=f"Pin {reference}.{pin} has no matching PCB pad",
                    source_path=schematic_source,
                    confidence="high",
                    objects=[{"kind": "pin", "name": f"{reference}.{pin}", "uuid": component.get("uuid")}],
                    schematic={"symbol": reference, "pin": pin, "sheetPath": component.get("sheetPath")},
                    suggestions=["Refresh the PCB from the schematic or correct the footprint pad numbering"],
                )
            )

    netlist_nets = {
        str(net.get("name"))
        for net in connectivity["data"].get("nets", [])
        if isinstance(net, dict) and _user_net(net.get("name"))
    }
    pcb_nets = {name for name in pcb_net_names(context.pcb) if _user_net(name)}
    for net in sorted(netlist_nets - pcb_nets):
        findings.append(
            finding(
                "parity.net_mismatch",
                kind="parity",
                severity="warning",
                message=f"Schematic net {net} is not represented on the PCB",
                source_path=schematic_source,
                confidence="medium",
                objects=[{"kind": "net", "name": net, "uuid": None}],
                suggestions=["Route the net or update the PCB netlist"],
            )
        )
    for net in sorted(pcb_nets - netlist_nets):
        findings.append(
            finding(
                "parity.net_mismatch",
                kind="parity",
                severity="warning",
                message=f"PCB net {net} has no matching schematic netlist entry",
                source_path=context.pcb["source"]["path"],
                confidence="medium",
                objects=[{"kind": "net", "name": net, "uuid": None}],
                suggestions=["Re-import the netlist or remove stale PCB net assignments"],
            )
        )
    counts = {
        "findings": len(findings),
        "rules": len({str(item["ruleId"]) for item in findings}),
        "netlistComponents": len(netlist_components),
        "pcbFootprints": len(pcb_footprints),
        "netlistNets": len(netlist_nets),
        "pcbNets": len(pcb_nets),
    }
    return findings_report(
        context.project,
        connectivity["source"],
        findings,
        counts=counts,
        warnings=[*connectivity.get("warnings", []), *context.pcb.get("warnings", [])],
        confidence="cli",
    )


def compare_schematic_pcb(project: str) -> dict[str, object]:
    return review_parity(load_context(project))
