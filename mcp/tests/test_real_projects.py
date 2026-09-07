"""Real-project scan tests against KiCad's installed demos.

These are the regression insurance for the ``fixture-green / real-board-red``
failure mode: the 273-false-error drill-parse bug shipped with a green suite
because no test parsed a real KiCad project.  The tests copy small demo
projects out of the KiCad installation into a temporary workspace and run the
complete tool surface with the real ``kicad-cli``.  They skip cleanly when
KiCad is absent, so the suite stays green in CI without KiCad.

Set ``KICAD_DEMO_ROOT`` to override the demo directory (useful for custom
KiCad installs); by default the standard Windows/Linux install paths are probed.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from codex_kicad_mcp import kicad_cli
from test_server import workspace  # noqa: F401 - fixture

DEFAULT_DEMO_ROOTS = (
    r"C:\Program Files\KiCad\10.0\share\kicad\demos",
    "/usr/share/kicad/demos",
    "/usr/local/share/kicad/demos",
    "/Applications/KiCad/KiCad.app/Contents/SharedSupport/kicad/demos",
)

# The two smallest demo projects with a schematic and a routed PCB.  Both are
# redistributed with KiCad under GPL/CC-BY-SA-compatible terms and stay on the
# user's disk; the test copies, never modifies, the originals.
DEMO_PROJECTS = (
    ("complex_hierarchy", "complex_hierarchy.kicad_pro"),
    ("kit-dev-coldfire-xilinx_5213", "kit-dev-coldfire-xilinx_5213.kicad_pro"),
)


def _demo_root() -> Path | None:
    override = os.environ.get("KICAD_DEMO_ROOT")
    candidates = [Path(override)] if override else [Path(p) for p in DEFAULT_DEMO_ROOTS]
    for candidate in candidates:
        if candidate.is_dir():
            return candidate
    return None


def _kicad_cli_available() -> bool:
    try:
        result = subprocess.run(
            [kicad_cli.CLI_COMMAND, "--version"],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0


DEMO_ROOT = _demo_root()
CLI_OK = _kicad_cli_available()
SKIP_REASON = "kicad-cli or KiCad demos not available on this machine"

requires_kicad = pytest.mark.skipif(
    not (DEMO_ROOT and CLI_OK),
    reason=SKIP_REASON,
)


@pytest.fixture
def real_workspace(workspace):
    """Copy the demo projects into the per-test temporary workspace."""
    for folder, pro_name in DEMO_PROJECTS:
        assert DEMO_ROOT is not None
        source = DEMO_ROOT / folder / pro_name
        if not source.is_file():
            pytest.skip(f"demo project missing: {source}")
        target_dir = workspace / folder
        target_dir.mkdir(parents=True, exist_ok=True)
        for item in (DEMO_ROOT / folder).iterdir():
            if item.suffix in {".kicad_pro", ".kicad_sch", ".kicad_pcb", ".kicad_prl", ".kicad_mod"} or item.is_dir():
                if item.is_dir():
                    shutil.copytree(item, target_dir / item.name, dirs_exist_ok=True)
                else:
                    shutil.copy2(item, target_dir / item.name)
    return workspace


@requires_kicad
def test_every_review_tool_runs_on_real_projects(real_workspace):
    """All read tools and the full design review must run without raising."""
    from codex_kicad_mcp import server

    for folder, pro_name in DEMO_PROJECTS:
        project = f"{folder}/{pro_name}"
        assert server.inspect_project(project)["files"]
        assert server.read_schematic(project)["counts"]["symbols"] > 0
        assert server.read_pcb(project)["counts"]["footprints"] > 0
        netlist = server.read_netlist(project)
        assert netlist["counts"]["components"] > 0
        assert server.read_bom(project)["counts"]["rows"] > 0
        review = server.run_design_review(project)
        assert review["counts"]["checks"] == 6


@requires_kicad
def test_real_projects_error_findings_are_bounded(real_workspace):
    """The design review must not flood a healthy demo with errors.

    The drill-parse bug produced 273 error findings on complex_hierarchy; this
    upper bound is the tripwire.  A handful of heuristic warnings is expected
    on real boards; a single-digit error count is the ceiling for demos that
    are known-good designs.
    """
    from codex_kicad_mcp import server

    for folder, pro_name in DEMO_PROJECTS:
        project = f"{folder}/{pro_name}"
        review = server.run_design_review(project)
        errors = review["summary"]["error"]
        assert errors <= 9, (
            f"{project}: {errors} error findings — suspected false-positive "
            f"regression: {[f['ruleId'] for f in review['findings'] if f['severity'] == 'error']}"
        )


@requires_kicad
def test_real_projects_semantic_calibration_rules(real_workspace):
    """The Step 6 calibration must hold on real exports: the +12V external
    input rail is a warning, not an error, and parity is free of Net-(...)/
    unconnected- noise."""
    from codex_kicad_mcp import server

    result = server.analyze_power_rails("complex_hierarchy/complex_hierarchy.kicad_pro")
    for item in result["findings"]:
        if item["ruleId"] == "power.source_missing" and "+12V" in str(item["message"]):
            assert item["severity"] == "warning"
            assert "external input rail" in str(item["message"])

    parity = server.compare_schematic_pcb("complex_hierarchy/complex_hierarchy.kicad_pro")
    for item in parity["findings"]:
        if item["ruleId"] == "parity.net_mismatch":
            name = str(item["objects"][0]["name"])
            assert not name.startswith(("Net-(", "unconnected-")), name


@requires_kicad
def test_real_projects_erc_drc_checks_run(real_workspace):
    """ERC/DRC via the real CLI must produce normalized envelopes."""
    from codex_kicad_mcp import server

    project = "complex_hierarchy/complex_hierarchy.kicad_pro"
    erc = server.run_kicad_cli_check(project, "sch")
    assert erc["confidence"] == "cli"
    assert isinstance(erc["counts"]["issues"], int)
    drc = server.run_kicad_cli_check(project, "pcb")
    assert drc["confidence"] == "cli"
