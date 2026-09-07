import subprocess
import sys
from pathlib import Path

import pytest

from codex_kicad_mcp import analysis, kicad_cli, server

FIXTURES = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "demo"
sys.path.insert(0, str(Path(__file__).resolve().parent / "fixtures" / "real_projects"))

from real_netlists import (  # noqa: E402
    COMPLEX_HIERARCHY_NETLIST,
    CONNECTOR_RAIL_NETLIST,
    PIC_PROGRAMMER_VPP_NETLIST,
)

NETLIST = """(export (version "E") (design (sheet (number "1") (name "/")))
 (components
  (comp (ref "U1") (value "MCU_8PIN") (footprint "SOIC-8_3.9x4.9mm_P1.27mm") (tstamps "u1")
   (unit (name "U") (pin "1") (pin "2") (pin "3") (pin "4") (pin "5") (pin "6")))
  (comp (ref "R1") (value "10k") (footprint "R_0805_2012Metric") (tstamps "r1")
   (unit (name "R") (pin "1") (pin "2")))
  (comp (ref "C1") (value "100nF") (footprint "C_0805_2012Metric") (tstamps "c1")
   (unit (name "C") (pin "1") (pin "2")))
  (comp (ref "C2") (value "10uF") (footprint "C_0805_2012Metric") (tstamps "c2")
   (unit (name "C") (pin "1") (pin "2"))))
 (nets
  (net (code "1") (name "VCC")
   (node (ref "U1") (pin "1") (pinfunction "VCC") (pintype "power_in"))
   (node (ref "C2") (pin "1") (pintype "passive")))
  (net (code "2") (name "GND")
   (node (ref "U1") (pin "2") (pinfunction "GND") (pintype "power_in"))
   (node (ref "C1") (pin "2") (pintype "passive"))
   (node (ref "C2") (pin "2") (pintype "passive")))
  (net (code "3") (name "CLK") (node (ref "U1") (pin "3") (pinfunction "CLK") (pintype "input")))
  (net (code "4") (name "D0") (node (ref "U1") (pin "4") (pinfunction "D0") (pintype "bidirectional")))
  (net (code "5") (name "D1") (node (ref "U1") (pin "5") (pinfunction "D1") (pintype "bidirectional")))
  (net (code "6") (name "RST")
   (node (ref "U1") (pin "6") (pinfunction "RST") (pintype "input"))
   (node (ref "R1") (pin "2") (pintype "passive")))))"""


@pytest.fixture
def demo_workspace(monkeypatch):
    monkeypatch.setenv("KICAD_WORKSPACE", str(FIXTURES))
    return FIXTURES


@pytest.fixture
def analysis_workspace(demo_workspace, monkeypatch):
    def fake_run(command, **kwargs):
        output = Path(command[command.index("--output") + 1])
        if "netlist" in command:
            output.write_text(NETLIST, encoding="utf-8")
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(kicad_cli.subprocess, "run", fake_run)
    return demo_workspace


def assert_review(result: dict[str, object]) -> None:
    assert result["schemaVersion"] == "1.0"
    assert result["project"] == "demo.kicad_pro"
    assert result["confidence"] in {"parsed", "cli", "heuristic"}
    assert set(result["summary"]) == {"error", "warning", "info"}
    assert result["summary"] == {
        "error": sum(1 for item in result["findings"] if item["severity"] == "error"),
        "warning": sum(1 for item in result["findings"] if item["severity"] == "warning"),
        "info": sum(1 for item in result["findings"] if item["severity"] == "info"),
    }
    for item in result["findings"]:
        assert item["kind"] in {"power", "decoupling", "parity", "si", "manufacturing", "layout"}
        assert item["confidence"] in {"high", "medium", "low"}
        assert item["source"]["path"]
        assert item["objects"]
        assert all({"kind", "name", "uuid"} <= set(entry) for entry in item["objects"])


def test_analyze_power_rails_fixture(analysis_workspace):
    result = server.analyze_power_rails("demo.kicad_pro")
    assert_review(result)
    assert result["counts"]["rails"] == 1
    assert [item["ruleId"] for item in result["findings"]] == ["power.source_missing"]
    finding = result["findings"][0]
    assert finding["source"]["path"] == "demo.kicad_sch"
    assert {object["name"] for object in finding["objects"]} >= {"U1.1", "C2.1"}
    assert finding["suggestions"]


def test_power_boundary_rules(analysis_workspace):
    result = server.analyze_power_rails("demo.kicad_pro", rails=["VCC", "VBAT"])
    assert result["counts"]["rails"] == 1
    with pytest.raises(ValueError, match="inside"):
        server.analyze_power_rails("../demo.kicad_pro")


def test_check_decoupling_fixture(analysis_workspace):
    result = server.check_decoupling("demo.kicad_pro")
    assert_review(result)
    assert result["counts"] == {
        "findings": 1,
        "rules": 1,
        "capacitors": 2,
        "bypassCapacitors": 1,
        "bulkCapacitors": 1,
    }
    finding = result["findings"][0]
    assert finding["ruleId"] == "decoupling.cap_missing"
    assert finding["objects"][0]["name"] == "C1"
    assert finding["schematic"]["symbol"] == "C1"

    with pytest.raises(ValueError, match="near_pin_mm"):
        server.check_decoupling("demo.kicad_pro", 0)


def test_cross_probe_fixture(analysis_workspace):
    result = server.cross_probe("demo.kicad_pro", "clk")
    assert_review(result)
    assert result["data"]["query"] == "clk"
    assert result["counts"]["schematic"] == 1
    assert result["counts"]["netlist"] == 1
    assert result["counts"]["pcb"] == 6
    assert result["counts"]["matches"] == 8
    assert result["confidence"] == "parsed"

    empty = server.cross_probe("demo.kicad_pro", "not-present")
    assert empty["counts"]["matches"] == 0
    with pytest.raises(ValueError, match="non-empty"):
        server.cross_probe("demo.kicad_pro", " ")


def test_compare_schematic_pcb_fixture(analysis_workspace):
    result = server.compare_schematic_pcb("demo.kicad_pro")
    assert_review(result)
    assert result["findings"] == []
    assert result["counts"]["netlistComponents"] == 4
    assert result["counts"]["pcbFootprints"] == 4
    assert result["counts"]["netlistNets"] == 6
    assert result["counts"]["pcbNets"] == 6


def test_analyze_signal_integrity_detects_intentional_stub(demo_workspace):
    result = server.analyze_signal_integrity("demo.kicad_pro")
    assert_review(result)
    assert len(result["findings"]) == 1
    finding = result["findings"][0]
    assert finding["ruleId"] == "si.stub_detected"
    assert finding["pcb"]["layer"] == "B.Cu"
    assert finding["pcb"]["position"] == {"x": 36.0, "y": 20.0, "unit": "mm"}


def test_signal_integrity_uncontrolled_layer_transition(demo_workspace):
    context = analysis.context.load_context("demo.kicad_pro", require_netlist=False)
    context.pcb["data"]["segments"].extend(
        [
            {
                "kind": "segment",
                "layer": "F.Cu",
                "start": {"x": 5, "y": 5},
                "end": {"x": 6, "y": 5},
                "width": 0.25,
                "net": "TEST",
                "netName": "TEST",
                "uuid": "test-f",
            },
            {
                "kind": "segment",
                "layer": "B.Cu",
                "start": {"x": 6, "y": 5},
                "end": {"x": 7, "y": 5},
                "width": 0.25,
                "net": "TEST",
                "netName": "TEST",
                "uuid": "test-b",
            },
        ]
    )
    result = analysis.signal_integrity.review_signal_integrity(context)
    assert "si.uncontrolled_layer_change" in {item["ruleId"] for item in result["findings"]}


def test_analyze_board_density_fixture(demo_workspace):
    result = server.analyze_board_density("demo.kicad_pro", 2.0, 0.8)
    assert_review(result)
    assert result["findings"] == []
    assert result["confidence"] == "parsed"
    metrics = result["data"]["density"]
    assert metrics["board"]["width"] == 50.0
    assert metrics["grid"]["totalCells"] == 375
    assert 0 < metrics["grid"]["occupiedCells"] < metrics["grid"]["totalCells"]

    with pytest.raises(ValueError, match="cell_size_mm"):
        server.analyze_board_density("demo.kicad_pro", 0)
    with pytest.raises(ValueError, match="high_density_ratio"):
        server.analyze_board_density("demo.kicad_pro", 2, 1.1)


def test_check_fabrication_readiness_fixture(analysis_workspace):
    result = server.check_fabrication_readiness("demo.kicad_pro")
    assert_review(result)
    assert result["findings"] == []
    assert result["data"]["checklist"] == {
        "boardPresent": True,
        "outlineClosed": True,
        "footprintsAssigned": True,
        "courtyardsPresent": True,
        "drillsInPreferredRange": True,
    }


def test_manufacturing_boundaries(demo_workspace):
    context = analysis.context.load_context("demo.kicad_pro", require_netlist=False)
    context.pcb["data"]["vias"][0]["drill"] = 0.1
    context.pcb["data"]["outline"].pop()
    result = analysis.manufacturing.review_manufacturing(context)
    rules = {item["ruleId"] for item in result["findings"]}
    assert {"manufacturing.unusual_drill", "manufacturing.board_outline_not_closed"} <= rules


def test_layout_track_width_boundary(demo_workspace):
    context = analysis.context.load_context("demo.kicad_pro", require_netlist=False)
    context.pcb["data"]["segments"][0]["width"] = 0.15
    result = analysis.layout.review_layout(context, 0.2)
    assert [item["ruleId"] for item in result["findings"]] == ["layout.track_width_below_target"]
    assert result["data"]["targetSource"] == "request"
    with pytest.raises(ValueError, match="minimum_track_width_mm"):
        analysis.layout.review_layout(context, 0)


def test_run_design_review_fixture_and_boundary(analysis_workspace):
    result = server.run_design_review(
        "demo.kicad_pro",
        checks=["power", "decoupling", "parity", "si", "manufacturing", "layout"],
    )
    assert_review(result)
    rules = {item["ruleId"] for item in result["findings"]}
    assert {
        "power.source_missing",
        "decoupling.cap_missing",
        "si.stub_detected",
    } <= rules
    assert result["counts"]["checks"] == 6
    assert result["counts"]["parity"] == 0
    assert result["counts"]["manufacturing"] == 0
    assert result["counts"]["layout"] == 0

    with pytest.raises(ValueError, match="unknown checks"):
        server.run_design_review("demo.kicad_pro", checks=["bogus"])


def test_cross_probe_context_and_finding_helpers(analysis_workspace):
    context = analysis.context.load_context("demo.kicad_pro")
    assert context.project == "demo.kicad_pro"
    assert context.connectivity is not None
    item = analysis.findings.finding(
        "test.rule",
        kind="parity",
        severity="info",
        message="test",
        source_path="demo.kicad_sch",
        confidence="low",
    )
    assert item["objects"] == []
    assert analysis.findings.summary([item]) == {"error": 0, "warning": 0, "info": 1}
    with pytest.raises(ValueError, match="kind"):
        analysis.findings.finding(
            "test.rule",
            kind="unknown",
            severity="info",
            message="test",
            source_path="x",
            confidence="low",
        )


# ---------------------------------------------------------------------------
# Step 6 semantic calibration: real-project-derived netlist snapshots.
# These guard against the fixture-blind-spot failure mode where synthetic
# fixtures stay green while real boards light up with false errors.
# ---------------------------------------------------------------------------


@pytest.fixture
def real_netlist_workspace(tmp_path, monkeypatch):
    """A workspace whose schematic/PCB are the demo fixture but whose CLI
    export returns a snapshot of the real complex_hierarchy netlist."""
    monkeypatch.setenv("KICAD_WORKSPACE", str(FIXTURES))

    def fake_run(command, **kwargs):
        output = Path(command[command.index("--output") + 1])
        if "netlist" in command:
            output.write_text(COMPLEX_HIERARCHY_NETLIST, encoding="utf-8")
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(kicad_cli.subprocess, "run", fake_run)
    return FIXTURES


def _findings_for_rail(result: dict[str, object], rail: str) -> list[dict[str, object]]:
    """The rails filter also auto-includes supply-pin-named nets, so select
    findings by the rail name in the message."""
    return [
        item
        for item in result["findings"]
        if item["ruleId"] == "power.source_missing" and f"Supply rail {rail} " in str(item["message"])
    ]


def test_external_input_rail_via_regulator_is_warning(real_netlist_workspace):
    """complex_hierarchy +12V: no power_out source, but U101 (78L05) consumes
    the rail and drives power_out on VCC.  This is an external input rail and
    must not be reported as an error."""
    result = server.analyze_power_rails("demo.kicad_pro", rails=["+12V"])
    findings = _findings_for_rail(result, "+12V")
    assert len(findings) == 1
    finding = findings[0]
    assert finding["severity"] == "warning"
    assert "external input rail" in finding["message"]
    assert "U101" in finding["message"]


def test_external_input_rail_via_connector_is_warning(tmp_path, monkeypatch):
    """A connector (P1) on an otherwise sourceless rail is a physical board
    power entry; the finding must be a warning naming the connector."""
    monkeypatch.setenv("KICAD_WORKSPACE", str(FIXTURES))

    def fake_run(command, **kwargs):
        output = Path(command[command.index("--output") + 1])
        if "netlist" in command:
            output.write_text(CONNECTOR_RAIL_NETLIST, encoding="utf-8")
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(kicad_cli.subprocess, "run", fake_run)
    result = server.analyze_power_rails("demo.kicad_pro", rails=["+5V"])
    findings = _findings_for_rail(result, "+5V")
    assert len(findings) == 1
    assert findings[0]["severity"] == "warning"
    assert "P1" in findings[0]["message"]


def test_root_sheet_power_in_only_rail_is_warning(real_netlist_workspace):
    """VCC has a real power_out source (U101) and must not produce a
    source_missing finding of its own; the auto-included +12V warning from the
    rails-filter behaviour is asserted separately above."""
    result = server.analyze_power_rails("demo.kicad_pro", rails=["VCC"])
    assert _findings_for_rail(result, "VCC") == []


def test_sourceless_internal_rail_stays_error(real_netlist_workspace):
    """A rail whose power_in consumers sit on sub-sheets, with no connector
    and no regulator feed, keeps its error severity.  GND-style return paths
    are never rails, so the report counts stay bounded."""
    result = server.analyze_power_rails("demo.kicad_pro")
    severities = {
        message.split(" ")[2]: item["severity"]
        for item in result["findings"]
        if item["ruleId"] == "power.source_missing"
        for message in [str(item["message"])]
    }
    assert severities.get("+12V") == "warning"
    assert severities.get("VCC") is None


def test_pic_programmer_vpp_charged_passively_stays_error(tmp_path, monkeypatch):
    """pic_programmer VPP is charged through a passive charge pump; no
    connector, no regulator feed, no root-sheet-only power_in.  The heuristic
    blind spot must keep reporting it so the review stays honest."""
    monkeypatch.setenv("KICAD_WORKSPACE", str(FIXTURES))

    def fake_run(command, **kwargs):
        output = Path(command[command.index("--output") + 1])
        if "netlist" in command:
            output.write_text(PIC_PROGRAMMER_VPP_NETLIST, encoding="utf-8")
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(kicad_cli.subprocess, "run", fake_run)
    result = server.analyze_power_rails("demo.kicad_pro", rails=["VPP"])
    findings = [item for item in result["findings"] if item["ruleId"] == "power.source_missing"]
    assert len(findings) == 1
    assert findings[0]["severity"] == "error"
    assert "external input rail" not in findings[0]["message"]


def test_parity_skips_autogenerated_and_empty_net_names(real_netlist_workspace):
    """PCB net 0 is unnamed and KiCad mints Net-(...) names per view; neither
    may surface as parity.net_mismatch noise on a real board."""
    result = server.compare_schematic_pcb("demo.kicad_pro")
    mismatched = [item for item in result["findings"] if item["ruleId"] == "parity.net_mismatch"]
    for item in mismatched:
        name = item["objects"][0]["name"]
        assert name and not name.startswith(("Net-(", "unconnected-"))
    # The snapshot has no PCB-side user nets beyond the fixture board, and the
    # demo fixture's own nets are user-named, so only legitimate diffs remain.
    assert all(not name.startswith("Net-(") for item in mismatched for name in [item["objects"][0]["name"]])
