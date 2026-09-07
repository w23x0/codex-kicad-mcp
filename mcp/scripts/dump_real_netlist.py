"""Dump the real exported netlist nodes for specific rails plus PCB net names."""

from __future__ import annotations

import json
import os
import sys


def main() -> int:
    os.environ["KICAD_WORKSPACE"] = sys.argv[1]
    project = sys.argv[2]
    from codex_kicad_mcp import netlist

    result = netlist.read_netlist(project)
    data = result["data"]
    out: dict[str, object] = {"components": []}
    for comp in data["components"]:
        out["components"].append({"ref": comp["reference"], "value": comp["value"], "sheetPath": comp["sheetPath"]})
    nets: list[object] = []
    for net in data["nets"]:
        nets.append({"name": net["name"], "nodes": net["nodes"]})
    out["nets"] = nets
    from codex_kicad_mcp import pcb as pcb_mod

    pcb_result = pcb_mod.read_pcb(project)
    out["pcbNets"] = pcb_result["data"]["nets"]
    pad_net_names = set()
    for fp in pcb_result["data"]["footprints"]:
        for pad in fp["pads"]:
            pad_net_names.add(pad.get("netName"))
    out["pcbPadNetNames"] = sorted(n for n in pad_net_names if n)
    seg_names = {seg.get("netName") for seg in pcb_result["data"]["segments"]}
    out["pcbSegmentNetNames"] = sorted(n for n in seg_names if n)
    print(json.dumps(out, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
