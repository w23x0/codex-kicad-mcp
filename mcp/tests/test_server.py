import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest
from mcp.server.mcpserver.exceptions import ResourceError, ToolError

from codex_kicad_mcp import diagnostics, kicad_cli, server

EXPECTED_ERRORS = (ValueError, RuntimeError, ToolError, ResourceError)

FIXTURES = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "demo"
REPORTS = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "reports"


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    monkeypatch.setenv("KICAD_WORKSPACE", str(tmp_path))
    (tmp_path / "demo.kicad_pro").write_text("{}", encoding="utf-8")
    (tmp_path / "demo.kicad_sch").write_text("(kicad_sch)", encoding="utf-8")
    (tmp_path / "demo.kicad_pcb").write_text("(kicad_pcb)", encoding="utf-8")
    return tmp_path


@pytest.fixture
def demo_workspace(monkeypatch):
    monkeypatch.setenv("KICAD_WORKSPACE", str(FIXTURES))
    return FIXTURES


def assert_envelope(result: dict[str, object], project: str = "demo.kicad_pro") -> None:
    assert result["schemaVersion"] == "1.0"
    assert result["project"] == project
    assert result["confidence"] in {"parsed", "cli", "heuristic"}
    source = result["source"]
    assert isinstance(source, dict)
    assert len(source["sha256"]) == 64
    assert int(source["sizeBytes"]) > 0
    assert isinstance(result["data"], dict)
    assert isinstance(result["counts"], dict)
    assert isinstance(result["warnings"], list)


def fake_cli_writer(writer: Callable[[Path, list[str]], None]):
    def run(command, **kwargs):
        output = Path(command[command.index("--output") + 1])
        writer(output, command)
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    return run


def test_list_and_inspect(workspace):
    assert server.list_kicad_projects() == [{"path": "demo.kicad_pro", "name": "demo"}]
    assert len(server.inspect_project("demo.kicad_pro")["files"]) == 3
    summary = server.project_summary("demo.kicad_pro")
    assert summary["boardPresent"] is True
    assert summary["schematicPresent"] is True


def test_nested_projects_are_relative_and_hidden_trees_are_skipped(workspace):
    nested = workspace / "boards" / "sensor"
    nested.mkdir(parents=True)
    (nested / "sensor.kicad_pro").write_text("{}", encoding="utf-8")
    git_tree = workspace / ".git" / "fixtures"
    git_tree.mkdir(parents=True)
    (git_tree / "ignored.kicad_pro").write_text("{}", encoding="utf-8")

    projects = server.list_kicad_projects()

    assert projects == [
        {"path": "boards/sensor/sensor.kicad_pro", "name": "sensor"},
        {"path": "demo.kicad_pro", "name": "demo"},
    ]


def test_rejects_path_escape(workspace):
    with pytest.raises(EXPECTED_ERRORS, match="inside"):
        server.inspect_project("../outside.kicad_pro")


def test_requires_workspace(monkeypatch):
    monkeypatch.delenv("KICAD_WORKSPACE", raising=False)

    with pytest.raises(EXPECTED_ERRORS, match="not configured"):
        server.list_kicad_projects()


def test_project_summary_rejects_invalid_json(workspace):
    (workspace / "demo.kicad_pro").write_text("not-json", encoding="utf-8")

    with pytest.raises(EXPECTED_ERRORS, match="valid KiCad JSON"):
        server.project_summary("demo.kicad_pro")


def test_check_validates_kind(workspace):
    with pytest.raises(EXPECTED_ERRORS, match=r"sch.*pcb"):
        server.run_kicad_cli_check("demo.kicad_pro", "gerber")


def test_read_schematic_fixture_envelope(demo_workspace):
    result = server.read_schematic("demo.kicad_pro")
    assert_envelope(result)
    assert result["confidence"] == "parsed"
    assert result["source"]["path"] == "demo.kicad_sch"
    assert result["counts"] == {"symbols": 11, "labels": 2, "wires": 12, "sheets": 1}
    assert result["data"]["metadata"]["title"] == "Codex KiCad demo fixture"
    assert result["data"]["sheets"][0]["file"] == "sub/power.kicad_sch"
    assert result["data"]["sheets"][0]["pins"][0]["name"] == "+3V3"
    u1 = next(item for item in result["data"]["symbols"] if item["reference"] == "U1")
    assert len(u1["pins"]) == 8
    assert all(len(item["uuid"]) == 36 for item in result["data"]["symbols"])


def test_read_schematic_extracts_instances(workspace):
    (workspace / "demo.kicad_sch").write_text(
        "(kicad_sch (version 20231120) (generator eeschema) "
        '(symbol (lib_id "Device:R") (at 10 20 90) (uuid "abc") '
        '(property "Reference" "R1") (property "Value" "10k")) '
        '(label "VCC" (at 1 2)) '
        "(wire (pts (xy 1 2) (xy 3 4))))",
        encoding="utf-8",
    )
    result = server.read_schematic("demo.kicad_pro")
    assert result["counts"] == {"symbols": 1, "labels": 1, "wires": 1, "sheets": 0}
    assert result["data"]["symbols"][0]["reference"] == "R1"
    assert result["data"]["symbols"][0]["position"]["angle"] == 90.0
    assert result["data"]["wires"][0]["points"][1] == {"x": 3.0, "y": 4.0}
    assert_envelope(result)


def test_read_hierarchy_fixture(demo_workspace):
    result = server.read_hierarchy("demo.kicad_pro")
    assert_envelope(result)
    assert result["counts"] == {"nodes": 2, "sheets": 1, "hierarchicalLabels": 1}
    root, leaf = result["data"]["nodes"]
    assert root["sheetPath"] == "/"
    assert leaf["name"] == "power"
    assert leaf["file"] == "sub/power.kicad_sch"
    assert leaf["uuidPath"].endswith("/power/") or "+3V3" in str(leaf["hierarchicalLabels"])


def test_read_buses_fixture_geometry(demo_workspace):
    result = server.read_buses("demo.kicad_pro")
    assert_envelope(result)
    assert result["counts"] == {"buses": 1, "busEntries": 2}
    bus = result["data"]["buses"][0]
    assert bus["name"] == "D[1..0]"
    assert bus["range"]["prefix"] == "D"
    assert bus["entries"][0]["busPoint"] == {"x": 86.36, "y": 88.9}
    assert bus["entries"][0]["wirePoint"] == {"x": 88.9, "y": 86.36}


def test_read_netlist_fixture_golden_ten_nets(demo_workspace, monkeypatch):
    nets = "\n".join(
        f'(net (code "{code}") (name "NET{code}") (node (ref "U1") (pin "{code}")))' for code in range(1, 11)
    )
    payload = (
        '(export (version "E") (design (sheet (number "1") (name "/"))) '
        '(components (comp (ref "U1") (value "MCU_8PIN") '
        '(footprint "Package_SO:SOIC-8_3.9x4.9mm_P1.27mm"))) '
        f"(nets {nets}))"
    )

    def write(output, command):
        output.write_text(payload, encoding="utf-8")

    monkeypatch.setattr(kicad_cli.subprocess, "run", fake_cli_writer(write))
    result = server.read_netlist("demo.kicad_pro")
    assert_envelope(result)
    assert result["confidence"] == "cli"
    assert result["counts"]["nets"] == 10
    assert result["counts"]["components"] == 1
    assert result["data"]["nets"][0]["nodes"][0]["reference"] == "U1"
    assert "--format" in result["data"]["command"]
    assert result["data"]["command"][result["data"]["command"].index("--format") + 1] == "kicadsexpr"


def test_read_bom_fixture_rows(demo_workspace, monkeypatch):
    payload = (
        '"Reference","Value","Footprint","Quantity","DNP"\n'
        '"C1","100nF","","1",""\n'
        '"C2","10uF","","1",""\n'
        '"R1","10k","","1",""\n'
        '"U1","MCU_8PIN","Package_SO:SOIC-8_3.9x4.9mm_P1.27mm","1",""\n'
    )

    def write(output, command):
        output.write_text(payload, encoding="utf-8")

    monkeypatch.setattr(kicad_cli.subprocess, "run", fake_cli_writer(write))
    result = server.read_bom("demo.kicad_pro")
    assert_envelope(result)
    assert result["confidence"] == "cli"
    assert result["counts"] == {"columns": 5, "rows": 4}
    assert result["data"]["rows"][-1]["Reference"] == "U1"
    assert "--labels" in result["data"]["command"]


def test_read_pcb_fixture_golden(demo_workspace):
    result = server.read_pcb("demo.kicad_pro")
    assert_envelope(result)
    assert result["counts"] == {
        "layers": 24,
        "nets": 0,
        "footprints": 4,
        "segments": 18,
        "vias": 1,
        "zones": 1,
        "outline": 4,
    }
    assert result["data"]["metadata"]["thickness"] == "1.6"
    assert result["data"]["layers"][0] == {"id": 0, "name": "F.Cu", "type": "signal", "user": None}
    u1 = next(item for item in result["data"]["footprints"] if item["reference"] == "U1")
    assert len(u1["pads"]) == 8
    assert u1["pads"][2]["netName"] == "CLK"
    via = result["data"]["vias"][0]
    assert via["position"] == {"x": 30.0, "y": 20.0}
    assert via["drill"] == 0.3
    assert result["data"]["zones"][0]["polygons"][0][0] == {"x": 0.5, "y": 0.5}


def test_read_pcb_extracts_layers_footprints_and_tracks(workspace):
    (workspace / "demo.kicad_pcb").write_text(
        "(kicad_pcb (version 20240108) (generator pcbnew) "
        '(layers (0 "F.Cu" signal) (31 "B.Cu" signal) (36 "B.SilkS" user "b.silkscreen") (44 "Edge.Cuts" user)) '
        '(net 0 "") (net 1 "GND") '
        '(footprint "Resistor_SMD:R_0805" (layer "F.Cu") (at 10 20) '
        '(property "Reference" "R1") (property "Value" "10k") '
        '(pad "1" smd roundrect (at 0 0) (layers "F.Cu" "F.Paste" "F.Mask") (net 1 "GND"))) '
        '(segment (start 1 2) (end 3 4) (width 0.25) (layer "F.Cu") (net 1)) '
        '(gr_rect (start 0 0) (end 50 30) (layer "Edge.Cuts") (width 0.05)))',
        encoding="utf-8",
    )
    result = server.read_pcb("demo.kicad_pro")
    assert result["counts"] == {
        "layers": 4,
        "nets": 2,
        "footprints": 1,
        "segments": 1,
        "vias": 0,
        "zones": 0,
        "outline": 1,
    }
    assert result["data"]["footprints"][0]["reference"] == "R1"
    assert result["data"]["footprints"][0]["pads"][0]["net"] == 1
    assert result["data"]["segments"][0]["net"] == 1
    assert result["data"]["outline"][0]["kind"] == "gr_rect"
    assert_envelope(result)


def test_read_board_metrics_fixture_golden(demo_workspace):
    result = server.read_board_metrics("demo.kicad_pro")
    assert_envelope(result)
    metrics = result["data"]["metrics"]
    assert metrics["size"]["width"] == 50.0
    assert metrics["size"]["height"] == 30.0
    assert metrics["copperLayers"] == 2
    assert metrics["zoneArea"] == 1421.0
    assert metrics["trackLengthByLayer"]["B.Cu"] == 6.0
    assert result["counts"]["pads"] == 14


def test_read_layer_stackup_derives_from_layer_table(demo_workspace):
    result = server.read_layer_stackup("demo.kicad_pro")
    assert_envelope(result)
    assert result["confidence"] == "heuristic"
    assert result["data"]["source"] == "layer-table"
    assert result["data"]["thickness"] == "1.6"
    assert result["counts"] == {"items": 24, "copperLayers": 2}
    assert result["warnings"]


def test_read_zones_fixture_polygon_area(demo_workspace):
    result = server.read_zones("demo.kicad_pro")
    assert_envelope(result)
    assert result["counts"] == {"zones": 1, "polygons": 1}
    polygon = result["data"]["zones"][0]["polygons"][0]
    assert polygon["area"] == 1421.0
    assert polygon["boundingBox"]["maxX"] == 49.5


def test_read_vias_fixture(demo_workspace):
    result = server.read_vias("demo.kicad_pro")
    assert_envelope(result)
    assert result["counts"] == {"vias": 1, "types": 1, "nets": 1, "layerPairs": 1}
    assert result["data"]["vias"][0]["netName"] == "CLK"
    assert result["data"]["byLayerPair"] == {"F.Cu,B.Cu": 1}


def test_kicad_cli_version_returns_structured_result(monkeypatch):
    completed = subprocess.CompletedProcess(["kicad-cli", "--version"], 0, stdout="9.0.1\n", stderr="")
    monkeypatch.setattr(kicad_cli.subprocess, "run", lambda *args, **kwargs: completed)

    assert server.kicad_cli_version() == {"exitCode": 0, "version": "9.0.1", "stderr": ""}


def test_cli_check_uses_json_and_normalizes_erc_golden(demo_workspace, monkeypatch):
    report = (REPORTS / "erc.json").read_text(encoding="utf-8")

    def write(output, command):
        output.write_text(report, encoding="utf-8")

    monkeypatch.setattr(kicad_cli.subprocess, "run", fake_cli_writer(write))
    result = server.run_kicad_cli_check("demo.kicad_pro", "sch")
    assert_envelope(result)
    assert result["confidence"] == "cli"
    assert result["counts"]["issues"] == 15
    assert result["counts"]["error"] == 7
    assert result["counts"]["warning"] == 8
    assert result["data"]["passed"] is True
    first = result["data"]["issues"][0]
    assert first["ruleId"] == "pin_not_connected"
    assert first["items"][0]["position"]["x"] == 59.69
    assert first["items"][0]["position"]["y"] == 97.79
    assert "--format" in result["data"]["command"]
    assert result["data"]["command"][result["data"]["command"].index("--format") + 1] == "json"
    assert result["warnings"]


def test_cli_check_normalizes_drc_golden(demo_workspace, monkeypatch):
    report = (REPORTS / "drc.json").read_text(encoding="utf-8")

    def write(output, command):
        output.write_text(report, encoding="utf-8")

    monkeypatch.setattr(kicad_cli.subprocess, "run", fake_cli_writer(write))
    result = server.run_kicad_cli_check("demo.kicad_pro", "pcb")
    assert_envelope(result)
    assert result["counts"]["issues"] == 1
    assert result["counts"]["warning"] == 1
    assert result["data"]["issues"][0]["ruleId"] == "track_dangling"
    assert result["data"]["issues"][0]["items"][0]["position"] == {"x": 30.0, "y": 20.0, "unit": "mm"}
    assert result["warnings"] == []


def test_check_exit_code_and_nonzero_violations(demo_workspace, monkeypatch):
    report = (REPORTS / "drc.json").read_text(encoding="utf-8")

    def fake_run(command, **kwargs):
        output = Path(command[command.index("--output") + 1])
        output.write_text(report, encoding="utf-8")
        return subprocess.CompletedProcess(command, 5, stdout="", stderr="")

    monkeypatch.setattr(kicad_cli.subprocess, "run", fake_run)
    result = server.run_kicad_cli_check("demo.kicad_pro", "pcb")
    assert result["data"]["exitCode"] == 5
    assert result["data"]["passed"] is False


def test_check_normalizes_unconnected_and_parity_keys():
    report = {
        "coordinate_units": "mm",
        "violations": [],
        "unconnected_items": [{"type": "unconnected_items", "severity": "error", "description": "A to B", "items": []}],
        "schematic_parity": [{"severity": "exclusion", "description": "parity difference", "items": []}],
    }
    issues, warnings, counts = diagnostics.normalize_check_report(report, check="pcb")
    assert [issue["category"] for issue in issues] == ["unconnected_items", "schematic_parity"]
    assert [issue["severity"] for issue in issues] == ["error", "excluded"]
    assert issues[0]["ruleId"] == "unconnected_items"
    assert len(issues[1]["ruleId"]) == 12
    assert counts == {"error": 1, "warning": 0, "info": 0, "excluded": 1}
    assert warnings == []


def test_parse_check_rejects_malformed_json():
    with pytest.raises(ValueError, match="not valid JSON"):
        diagnostics.parse_check_json("1 violation")


def test_malformed_schematic_tools(workspace):
    (workspace / "demo.kicad_sch").write_text("(kicad_sch (version 1)", encoding="utf-8")
    for call in (server.read_schematic, server.read_hierarchy, server.read_buses):
        with pytest.raises(EXPECTED_ERRORS, match=r"valid KiCad S-expression|unbalanced"):
            call("demo.kicad_pro")


def test_malformed_pcb_tools(workspace):
    (workspace / "demo.kicad_pcb").write_text("(kicad_pcb (version 1)", encoding="utf-8")
    for call in (
        server.read_pcb,
        server.read_board_metrics,
        server.read_layer_stackup,
        server.read_zones,
        server.read_vias,
    ):
        with pytest.raises(EXPECTED_ERRORS, match=r"valid KiCad S-expression|unbalanced"):
            call("demo.kicad_pro")


def test_malformed_netlist_export(workspace, monkeypatch):
    def write(output, command):
        output.write_text("(export (components))", encoding="utf-8")

    monkeypatch.setattr(kicad_cli.subprocess, "run", fake_cli_writer(write))
    with pytest.raises(EXPECTED_ERRORS, match="missing components or nets"):
        server.read_netlist("demo.kicad_pro")


def test_malformed_bom_export(workspace, monkeypatch):
    def write(output, command):
        output.write_text('Reference,Value\n"R1', encoding="utf-8")

    monkeypatch.setattr(kicad_cli.subprocess, "run", fake_cli_writer(write))
    with pytest.raises(EXPECTED_ERRORS, match="not valid CSV"):
        server.read_bom("demo.kicad_pro")


# ---------------------------------------------------------------------------
# Entry point smoke
# ---------------------------------------------------------------------------


def test_main_smoke(monkeypatch):
    """``server.main`` must delegate to the FastMCP stdio runner."""
    calls: dict[str, object] = {}

    class FakeMcp:
        def run(self):
            calls["ran"] = True

    monkeypatch.setattr(server, "mcp", FakeMcp())
    server.main()
    assert calls["ran"] is True
