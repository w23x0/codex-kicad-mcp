"""Power distribution heuristics based on a KiCad netlist export."""

from __future__ import annotations

import re
from typing import Any

from codex_kicad_mcp.analysis.connectivity import (
    is_ground,
    is_power_symbol,
    is_supply_pin,
    is_supply_rail,
)
from codex_kicad_mcp.analysis.context import ProjectContext, load_context
from codex_kicad_mcp.analysis.findings import finding, findings_report

_SOURCE_TYPES = ("power_out", "powerout", "output")
_CONSUMER_TYPES = ("power_in", "powerin", "input", "passive")
# Connector reference convention (P1, J2, CN3); other leading letters are
# component classes that never mark a board power entry.
_CONNECTOR_RE = re.compile(r"^(?:CN|P|J)[0-9]+$", re.IGNORECASE)


def _component_index(connectivity: dict[str, Any]) -> dict[str, dict[str, Any]]:
    data = connectivity.get("data")
    components = data.get("components", []) if isinstance(data, dict) else []
    return {
        str(component.get("reference")): component
        for component in components
        if isinstance(component, dict) and component.get("reference")
    }


def _source_nets_by_ref(data: dict[str, Any]) -> dict[str, set[str]]:
    """Map every reference to the nets where it drives a power_out-style pin."""
    result: dict[str, set[str]] = {}
    for net in data.get("nets", []):
        if not isinstance(net, dict):
            continue
        name = str(net.get("name") or "")
        for node in net.get("nodes", []):
            if isinstance(node, dict) and _is_source(node):
                reference = str(node.get("reference") or "")
                if reference:
                    result.setdefault(reference, set()).add(name)
    return result


def _is_root_sheet(sheet_path: object) -> bool:
    return not isinstance(sheet_path, str) or sheet_path.strip().rstrip("/") == ""


def _external_input_reason(
    rail_name: str,
    nodes: list[dict[str, Any]],
    components: dict[str, dict[str, Any]],
    source_nets: dict[str, set[str]],
) -> str | None:
    """Explain why a rail without a power_out source is probably fed externally.

    Returns a short reason string for the finding message, or ``None`` when
    nothing indicates the power enters the board from outside the netlist's
    source model (in which case the missing source stays an error).
    """
    rail_refs = {str(node.get("reference")) for node in nodes if isinstance(node, dict) and node.get("reference")}
    for reference in sorted(rail_refs):
        if _CONNECTOR_RE.fullmatch(reference) and not is_power_symbol(reference):
            return f"connector {reference} sits on the rail"
    for reference in sorted(rail_refs):
        driven = source_nets.get(reference, set())
        downstream = sorted(driven - {rail_name})
        if downstream:
            return f"{reference} feeds {', '.join(downstream)} from this rail"
    power_inputs = [
        node
        for node in nodes
        if isinstance(node, dict)
        and "power_in" in str(node.get("pinType") or "").casefold().replace("-", "_")
        and not is_power_symbol(str(node.get("reference") or ""))
    ]
    # Power-flag symbols (#PWR…) are excluded above: a rail that is only
    # labelled, never driven, must keep its error severity.
    if power_inputs and all(
        _is_root_sheet((components.get(str(node.get("reference"))) or {}).get("sheetPath")) for node in power_inputs
    ):
        return "all component power_in pins are on the root sheet"
    return None


def _rails(connectivity: dict[str, Any], requested: list[str] | None) -> list[dict[str, Any]]:
    data = connectivity.get("data")
    nets = data.get("nets", []) if isinstance(data, dict) else []
    return [
        net
        for net in nets
        if isinstance(net, dict)
        and (requested is None or str(net.get("name")) in requested or is_supply_pin(net.get("name")))
        and is_supply_rail(net.get("name"))
    ]


def _is_source(node: dict[str, Any]) -> bool:
    pin_type = str(node.get("pinType") or "").casefold().replace("-", "_")
    return any(marker in pin_type for marker in _SOURCE_TYPES)


def _is_consumer(node: dict[str, Any], component: dict[str, Any] | None) -> bool:
    if component is not None and is_power_symbol(component.get("reference")):
        return False
    pin_type = str(node.get("pinType") or "").casefold().replace("-", "_")
    if any(marker in pin_type for marker in _CONSUMER_TYPES):
        return True
    return component is not None and not is_power_symbol(component.get("reference"))


def _node_object(node: dict[str, Any], component: dict[str, Any] | None) -> dict[str, object]:
    reference = str(node.get("reference") or (component or {}).get("reference") or "unknown")
    return {
        "kind": "component-pin",
        "name": f"{reference}.{node.get('pin') or '?'}",
        "uuid": (component or {}).get("uuid"),
    }


def review_power(context: ProjectContext, rails: list[str] | None = None) -> dict[str, object]:
    """Review named supply nets for sources, consumers, and ground shorts."""
    if context.connectivity is None:
        raise ValueError("power analysis requires a netlist export")
    connectivity = context.connectivity
    data = connectivity["data"]
    if not isinstance(data, dict):
        raise ValueError("netlist data must be an object")
    components = _component_index(connectivity)
    data = connectivity["data"]
    if not isinstance(data, dict):
        raise ValueError("netlist data must be an object")
    source_nets = _source_nets_by_ref(data)
    findings: list[dict[str, object]] = []
    for net in _rails(connectivity, rails):
        name = str(net.get("name"))
        nodes = [node for node in net.get("nodes", []) if isinstance(node, dict)]
        sources = [node for node in nodes if _is_source(node)]
        consumers = [
            node
            for node in nodes
            if _is_consumer(node, components.get(str(node.get("reference"))))
            and not is_power_symbol(str(node.get("reference") or ""))
        ]
        if consumers and not sources:
            external_reason = _external_input_reason(name, nodes, components, source_nets)
            severity = "warning" if external_reason else "error"
            hint = f" (assumed external input rail: {external_reason})" if external_reason else ""
            findings.append(
                finding(
                    "power.source_missing",
                    kind="power",
                    severity=severity,
                    message=f"Supply rail {name} has consumers but no recognized power source pin{hint}",
                    source_path=connectivity["source"]["path"],
                    confidence="medium",
                    objects=[_node_object(node, components.get(str(node.get("reference")))) for node in nodes],
                    suggestions=[f"Add a regulator, power flag, or supply source that drives {name}"],
                )
            )
        if len(sources) > 1:
            findings.append(
                finding(
                    "power.multiple_sources_same_rail",
                    kind="power",
                    severity="warning",
                    message=f"Supply rail {name} contains {len(sources)} power source pins",
                    source_path=connectivity["source"]["path"],
                    confidence="medium",
                    objects=[_node_object(node, components.get(str(node.get("reference")))) for node in sources],
                    suggestions=["Confirm that parallel sources are intended and current sharing is acceptable"],
                )
            )
        ground_nodes = [
            node for node in nodes if is_ground((components.get(str(node.get("reference"))) or {}).get("value"))
        ]
        if ground_nodes:
            findings.append(
                finding(
                    "power.rail_short_to_ground",
                    kind="power",
                    severity="error",
                    message=f"Ground-referenced power symbol appears on supply rail {name}",
                    source_path=connectivity["source"]["path"],
                    confidence="medium",
                    objects=[_node_object(node, components.get(str(node.get("reference")))) for node in ground_nodes],
                    suggestions=["Remove the ground connection from the supply rail or correct the rail label"],
                )
            )

    # A component supply pin can also have an unrecognized net name; report one
    # finding per net rather than duplicating it for every affected pin.
    unknown_supply_nets: dict[str, list[dict[str, Any]]] = {}
    for net in data.get("nets", []):
        if not isinstance(net, dict) or is_supply_rail(net.get("name")):
            continue
        for node in net.get("nodes", []):
            if not isinstance(node, dict) or not is_supply_pin(node.get("pinFunction")):
                continue
            component = components.get(str(node.get("reference")))
            if component is not None and is_power_symbol(component.get("reference")):
                continue
            unknown_supply_nets.setdefault(str(net.get("name") or "unknown"), []).append(node)
    for net_name, nodes in sorted(unknown_supply_nets.items()):
        findings.append(
            finding(
                "power.consumer_missing_rail",
                kind="power",
                severity="warning",
                message=f"Supply-style pin is connected to unrecognized net {net_name}",
                source_path=connectivity["source"]["path"],
                confidence="medium",
                objects=[_node_object(node, components.get(str(node.get("reference")))) for node in nodes],
                suggestions=[f"Connect the supply pin to its intended rail or rename net {net_name}"],
            )
        )
    counts = {
        "findings": len(findings),
        "rules": len({str(item["ruleId"]) for item in findings}),
        "rails": len(_rails(connectivity, rails)),
        "nets": len(data.get("nets", [])),
    }
    return findings_report(
        context.project,
        connectivity["source"],
        findings,
        data={"rails": [net.get("name") for net in _rails(connectivity, rails)]},
        counts=counts,
        warnings=list(connectivity.get("warnings", [])),
        confidence="cli",
    )


def analyze_power_rails(project: str, rails: list[str] | None = None) -> dict[str, object]:
    return review_power(load_context(project), rails)
