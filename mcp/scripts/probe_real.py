"""Temporary probe: run review tools against a real KiCad demo project.

Usage: uv run python scripts/probe_real.py <workspace> <project> [checks]
"""

from __future__ import annotations

import json
import os
import sys


def main() -> int:
    workspace, project = sys.argv[1], sys.argv[2]
    os.environ["KICAD_WORKSPACE"] = workspace
    from codex_kicad_mcp import server

    out: dict[str, object] = {}
    power = server.analyze_power_rails(project)
    out["power"] = {
        "summary": power["summary"],
        "findings": [{k: f.get(k) for k in ("ruleId", "severity", "message", "confidence")} for f in power["findings"]],
    }
    parity = server.compare_schematic_pcb(project)
    out["parity"] = {
        "summary": parity["summary"],
        "findings": [
            {k: f.get(k) for k in ("ruleId", "severity", "message", "confidence")} for f in parity["findings"]
        ][:40],
    }
    review = server.run_design_review(project)
    out["review"] = {"summary": review["summary"], "counts": review["counts"]}
    print(json.dumps(out, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
