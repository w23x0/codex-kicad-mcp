"""Dump the demo fixture into one JSON blob for the visualization artifact.

Uses the project's own parser modules (dogfooding) plus a few raw
S-expression fields the read tools do not expose yet (bus, sheet, vias,
zone).  Run from the repository root with the project venv:

    KICAD_WORKSPACE=mcp/tests/fixtures uv run --directory mcp python scripts/dump_fixture_json.py
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from codex_kicad_mcp import kicad_cli, pcb, project, schematic
from codex_kicad_mcp.sexpr import children, first_child, parse_sexpr, as_float, as_int

ROOT = Path(__file__).resolve().parents[1]
FIXTURE_DIR = ROOT / "mcp" / "tests" / "fixtures" / "demo"

os.environ.setdefault("KICAD_WORKSPACE", str(FIXTURE_DIR))

out: dict[str, object] = {}
out["schematic"] = schematic.read_schematic("demo.kicad_pro")
out["pcb"] = pcb.read_pcb("demo.kicad_pro")
out["inventory"] = project.inspect_project("demo.kicad_pro")
out["projects"] = project.list_kicad_projects()
out["cli_version"] = kicad_cli.kicad_cli_version()["version"]

# ---- raw schematic extras: bus, bus_entry, sheet, no_connect -------------
sch_path = FIXTURE_DIR / "demo.kicad_sch"
root = parse_sexpr(sch_path.read_text(encoding="utf-8"))
top = next(n for n in root if isinstance(n, list) and n and n[0] == "kicad_sch")
extras: dict[str, list] = {"bus": [], "bus_entry": [], "sheet": [], "no_connect": [], "junction": []}
for node in children(top, "bus"):
    pts = children(node, "pts")[0]
    extras["bus"].append([(as_float(p[1]), as_float(p[2])) for p in children(pts, "xy")])
for node in children(top, "bus_entry"):
    at = first_child(node, "at")
    size = first_child(node, "size")
    extras["bus_entry"].append({
        "at": [as_float(at[1]), as_float(at[2])],
        "size": [as_float(size[1]), as_float(size[2])],
    })
for node in children(top, "sheet"):
    at = first_child(node, "at")
    size = first_child(node, "size")
    pins = []
    for pin in children(node, "pin"):
        pat = first_child(pin, "at")
        pins.append({"name": pin[1], "at": [as_float(pat[1]), as_float(pat[2])]})
    name = first_child(node, 'property')
    extras["sheet"].append({
        "at": [as_float(at[1]), as_float(at[2])],
        "size": [as_float(size[1]), as_float(size[2])],
        "name": "power",
        "pins": pins,
    })
for node in children(top, "no_connect"):
    at = first_child(node, "at")
    extras["no_connect"].append([as_float(at[1]), as_float(at[2])])
out["sch_extras"] = extras

# ---- raw PCB extras: vias, zone -----------------------------------------
pcb_path = FIXTURE_DIR / "demo.kicad_pcb"
proot = parse_sexpr(pcb_path.read_text(encoding="utf-8"))
ptop = next(n for n in proot if isinstance(n, list) and n and n[0] == "kicad_pcb")
vias = []
for node in children(ptop, "via"):
    at = first_child(node, "at")
    size = first_child(node, "size")
    drill = first_child(node, "drill")
    net = first_child(node, "net")
    layers = first_child(node, "layers")
    vias.append({
        "at": [as_float(at[1]), as_float(at[2])],
        "diameter": as_float(size[1]) if size else None,
        "drill": as_float(drill[1]) if drill else None,
        "net": as_int(net[1]) if net else None,
        "layers": [str(x) for x in layers[1:]] if layers else [],
    })
out["vias"] = vias
zones = []
for node in children(ptop, "zone"):
    net = first_child(node, "net")
    layer = first_child(node, "layer")
    poly = first_child(node, "polygon")
    pts = children(poly, "pts")[0] if poly else None
    zones.append({
        "net": as_int(net[1]) if net else None,
        "layer": layer[1] if layer else None,
        "points": [[as_float(p[1]), as_float(p[2])] for p in children(pts, "xy")] if pts else [],
    })
out["zones"] = zones

# ---- netlist (authoritative connectivity, parsed from kicadsexpr) --------
with tempfile.TemporaryDirectory() as td:
    net_path = Path(td) / "net.net"
    subprocess.run(
        ["kicad-cli", "sch", "export", "netlist", "--format", "kicadsexpr",
         "-o", str(net_path), str(sch_path)],
        capture_output=True, text=True, timeout=120, check=False,
    )
    nroot = parse_sexpr(net_path.read_text(encoding="utf-8"))
    nets = []
    for comp in nroot:
        if isinstance(comp, list) and comp and comp[0] == "export":
            design = first_child(comp, "design")
            for sheet in (children(design, "sheet") if design else []):
                pass
            for section in comp[1:]:
                if isinstance(section, list) and section and section[0] == "nets":
                    for net in children(section, "net"):
                        name_node = first_child(net, "name")
                        nodes = []
                        for node in children(net, "node"):
                            ref = first_child(node, "ref")
                            pin = first_child(node, "pin")
                            ptype = first_child(node, "pintype")
                            nodes.append({
                                "ref": ref[1] if ref else None,
                                "pin": pin[1] if pin else None,
                                "pintype": ptype[1] if ptype else None,
                            })
                        nets.append({
                            "name": name_node[1] if name_node else "?",
                            "nodes": nodes,
                        })
    out["nets"] = nets

# ---- ERC / DRC reports via kicad-cli -------------------------------------
with tempfile.TemporaryDirectory() as td:
    erc_json = Path(td) / "erc.json"
    drc_json = Path(td) / "drc.json"
    subprocess.run(
        ["kicad-cli", "sch", "erc", "--severity-all", "--format", "json",
         "-o", str(erc_json), str(sch_path)],
        capture_output=True, text=True, timeout=120, check=False,
    )
    subprocess.run(
        ["kicad-cli", "pcb", "drc", "--severity-all", "--format", "json",
         "-o", str(drc_json), str(pcb_path)],
        capture_output=True, text=True, timeout=120, check=False,
    )
    out["erc"] = json.loads(erc_json.read_text(encoding="utf-8"))
    out["drc"] = json.loads(drc_json.read_text(encoding="utf-8"))

dest = ROOT / "scripts" / "fixture_dump.json"
dest.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
print("wrote", dest, "| schematic symbols:", len(out["schematic"]["symbols"]),
      "| pcb segments:", len(out["pcb"]["segments"]),
      "| erc violations:", sum(len(s.get("violations", [])) for s in out["erc"]["sheets"]),
      "| drc violations:", len(out["drc"]["violations"]))
