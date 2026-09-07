"""Connectivity and component helpers shared by review analyzers."""

from __future__ import annotations

import math
import re
from typing import Any

from codex_kicad_mcp.geometry import as_xy

_SUPPLY_RE = re.compile(
    r"^(?:\+[0-9]+(?:\.[0-9]+)?V|VBUS|V[A-Z]{1,3}|[0-9]+V[0-9A-Z]*|[A-Z]+V[0-9A-Z]*)$", re.IGNORECASE
)
_GROUND_RE = re.compile(r"^(?:GND|AGND|DGND|PGND|VSS)$", re.IGNORECASE)
_SUPPLY_PIN_RE = re.compile(r"^(?:VCC|VDD|VBIAS|VBAT|VBUS|V\+|AVDD|DVDD|\+[0-9]+(?:\.[0-9]+)?V)$", re.IGNORECASE)
_CAPACITANCE_RE = re.compile(r"^([0-9]+(?:\.[0-9]+)?)\s*(u|µ|n|p)?F?$", re.IGNORECASE)


def is_ground(name: object) -> bool:
    return isinstance(name, str) and bool(_GROUND_RE.fullmatch(name.strip()))


def is_supply_rail(name: object) -> bool:
    return isinstance(name, str) and bool(_SUPPLY_RE.fullmatch(name.strip()))


def is_supply_pin(name: object) -> bool:
    return isinstance(name, str) and bool(_SUPPLY_PIN_RE.fullmatch(name.strip()))


def parse_capacitance(value: object) -> float | None:
    if not isinstance(value, str):
        return None
    match = _CAPACITANCE_RE.fullmatch(value.strip())
    if not match:
        return None
    number = float(match.group(1))
    multiplier = {"u": 1e-6, "µ": 1e-6, "n": 1e-9, "p": 1e-12}.get(
        match.group(2).lower() if match.group(2) else "f", 1.0
    )
    result = number * multiplier
    return result if math.isfinite(result) and result > 0 else None


def is_capacitor(reference: object) -> bool:
    return isinstance(reference, str) and reference.strip().upper().startswith("C") and not reference.startswith("#")


def is_power_symbol(reference: object) -> bool:
    return isinstance(reference, str) and reference.startswith("#PWR")


def pcb_net_names(pcb: dict[str, Any]) -> set[str]:
    """Return non-empty net names from KiCad 9/10 declarations and copper objects."""
    data = pcb.get("data")
    names: set[str] = set()
    if not isinstance(data, dict):
        return names
    for net in data.get("nets", []):
        if isinstance(net, dict) and isinstance(net.get("name"), str):
            names.add(net["name"])
    for key in ("footprints", "segments", "vias", "zones"):
        items = data.get(key, [])
        for item in items:
            if not isinstance(item, dict):
                continue
            candidates = [item.get("netName")]
            if key == "footprints":
                candidates.extend(pad.get("netName") for pad in item.get("pads", []) if isinstance(pad, dict))
            names.update(name for name in candidates if isinstance(name, str) and name)
    return names


def pad_board_position(footprint: dict[str, Any], pad: dict[str, Any]) -> tuple[float, float] | None:
    """Transform a footprint-local pad position to board coordinates."""
    origin = as_xy(footprint.get("position"))
    local = as_xy(pad.get("position"))
    if origin is None or local is None:
        return None
    angle = footprint.get("position", {}).get("angle") if isinstance(footprint.get("position"), dict) else 0.0
    radians = math.radians(float(angle) if isinstance(angle, (int, float)) and math.isfinite(float(angle)) else 0.0)
    x, y = local
    return (
        origin[0] + x * math.cos(radians) - y * math.sin(radians),
        origin[1] + x * math.sin(radians) + y * math.cos(radians),
    )


def component_pins(component: dict[str, Any]) -> set[str]:
    result: set[str] = set()
    for unit in component.get("units", []):
        if not isinstance(unit, dict):
            continue
        result.update(str(pin) for pin in unit.get("pins", []) if pin is not None)
    return result


def normalized_footprint(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        return ""
    return value.split(":", 1)[-1].strip().casefold()
