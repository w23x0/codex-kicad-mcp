"""Protocol-level and function-level tests for MCP resources and prompts."""

from __future__ import annotations

import asyncio
import json
from urllib.parse import quote

import pytest

from codex_kicad_mcp import resources, server
from test_server import demo_workspace, workspace  # noqa: F401 - fixtures

# ---------------------------------------------------------------------------
# Listing (protocol surface)
# ---------------------------------------------------------------------------


def test_resource_templates_listing():
    templates = asyncio.run(server.mcp.list_resource_templates())
    names = {t.name for t in templates}
    assert names == {
        "project_manifest",
        "project_raw",
        "project_schematic",
        "project_pcb",
        "project_hierarchy",
        "project_netlist",
        "project_bom",
        "project_stackup",
        "project_report",
    }
    for template in templates:
        assert template.uriTemplate.startswith("codex-kicad://projects/{project}/")
        assert template.mimeType in {None, "application/json", "text/plain"}


def test_prompts_listing():
    prompts = asyncio.run(server.mcp.list_prompts())
    assert {p.name for p in prompts} == {
        "audit_project",
        "generate_bom_report",
        "review_power_distribution",
        "review_signal_integrity",
        "cross_probe_issue",
        "prepare_fabrication",
        "summarize_project_for_handoff",
    }


def test_tools_listing_unchanged():
    tools = asyncio.run(server.mcp.list_tools())
    # 23 read-only tools plus 5 write-API tools (Step 8).
    assert len(tools) == 28
    names = {t.name for t in tools}
    assert "audit_project" not in names
    assert {"preview_write", "confirm_write", "rollback_snapshot", "list_snapshots", "get_write_audit"} <= names


def test_catalog_tools_match_mcp_listing():
    """The catalog must list exactly the registered MCP tools.

    This is the drift guard for catalog.json: when a tool is added or renamed
    in server.py, the catalog entry has to follow, and this test fails on
    either side of the mismatch.
    """
    import json
    from pathlib import Path

    catalog_path = Path(__file__).resolve().parents[2] / "catalog" / "catalog.json"
    if not catalog_path.is_file():
        pytest.skip("catalog.json is not present in this checkout")
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    entry = next(item for item in catalog["mcps"] if item["id"] == "kicad")
    listed = {tool.name for tool in asyncio.run(server.mcp.list_tools())}
    assert set(entry["tools"]) == listed, (
        f"catalog tools differ from MCP listing; missing from catalog: "
        f"{sorted(listed - set(entry['tools']))}, stale in catalog: "
        f"{sorted(set(entry['tools']) - listed)}"
    )


# ---------------------------------------------------------------------------
# encode/decode
# ---------------------------------------------------------------------------


def test_encode_decode_roundtrip():
    value = "boards/nested/demo.kicad_pro"
    encoded = resources.encode_project(value)
    assert "/" not in encoded
    assert resources.decode_project(encoded) == value


def test_decode_rejects_empty():
    with pytest.raises(ValueError, match="must not be empty"):
        resources.decode_project("")


def test_decode_lenient_raw_slashes():
    assert resources.decode_project("sub/x.kicad_pro") == "sub/x.kicad_pro"


# ---------------------------------------------------------------------------
# Resource reads
# ---------------------------------------------------------------------------


def _uri(workspace_dir, project: str, name: str) -> str:
    return f"codex-kicad://projects/{quote(project, safe='')}/{name}"


def _read_raw(uri: str) -> str:
    return asyncio.run(server.mcp.read_resource(uri))[0].content


def test_manifest_resource_fixture(demo_workspace):
    result = json.loads(_read_raw(_uri(demo_workspace, "demo.kicad_pro", "manifest")))
    assert result["workspaceRelative"] is True
    assert result["project"]["project"] == "demo.kicad_pro"
    assert any(f["path"].endswith(".kicad_sch") for f in result["inventory"]["files"])


def test_schematic_resource_fixture(demo_workspace):
    result = json.loads(_read_raw(_uri(demo_workspace, "demo.kicad_pro", "schematic")))
    assert result["schemaVersion"] == "1.0"
    assert result["counts"]["symbols"] == 11
    assert result["source"]["path"] == "demo.kicad_sch"


def test_pcb_resource_fixture(demo_workspace):
    result = json.loads(_read_raw(_uri(demo_workspace, "demo.kicad_pro", "pcb")))
    assert result["counts"]["footprints"] == 4
    assert result["data"]["metadata"]["thickness"] == "1.6"


def test_hierarchy_resource_fixture(demo_workspace):
    result = json.loads(_read_raw(_uri(demo_workspace, "demo.kicad_pro", "hierarchy")))
    assert result["counts"]["nodes"] == 2
    assert result["data"]["nodes"][0]["sheetPath"] == "/"


def test_stackup_resource_fixture(demo_workspace):
    result = json.loads(_read_raw(_uri(demo_workspace, "demo.kicad_pro", "stackup")))
    assert result["data"]["source"] == "layer-table"
    assert result["data"]["items"][0]["name"] == "F.Cu"


def test_netlist_resource_uses_mocked_cli(demo_workspace, monkeypatch):
    from codex_kicad_mcp import kicad_cli
    from test_server import fake_cli_writer

    payload = (
        '(export (version "E") (components (comp (ref "U1") (value "MCU"))) '
        '(nets (net (code "1") (name "GND") (node (ref "U1") (pin "1")))))'
    )
    monkeypatch.setattr(
        kicad_cli.subprocess, "run", fake_cli_writer(lambda out, cmd: out.write_text(payload, encoding="utf-8"))
    )
    result = json.loads(_read_raw(_uri(demo_workspace, "demo.kicad_pro", "netlist")))
    assert result["confidence"] == "cli"
    assert result["counts"]["components"] == 1


def test_bom_resource_uses_mocked_cli(demo_workspace, monkeypatch):
    from codex_kicad_mcp import kicad_cli
    from test_server import fake_cli_writer

    payload = '"Reference","Value","Quantity"\n"U1","MCU","1"\n'
    monkeypatch.setattr(
        kicad_cli.subprocess, "run", fake_cli_writer(lambda out, cmd: out.write_text(payload, encoding="utf-8"))
    )
    result = json.loads(_read_raw(_uri(demo_workspace, "demo.kicad_pro", "bom")))
    assert result["data"]["rows"][0]["Reference"] == "U1"


def test_report_resource_reads_local_erc_json(demo_workspace):
    (demo_workspace / "erc.json").write_text(
        json.dumps(
            {
                "kicad_version": "10.0.6",
                "violations": [{"severity": "warning", "type": "test_warn", "description": "demo", "items": []}],
            }
        ),
        encoding="utf-8",
    )
    try:
        result = json.loads(_read_raw(_uri(demo_workspace, "demo.kicad_pro", "report")))
        assert result["source"]["kind"] == "erc"
        assert result["counts"]["issues"] == 1
        assert result["counts"]["warning"] == 1
    finally:
        (demo_workspace / "erc.json").unlink()


def test_report_resource_stem_fallback_for_gui_default_name(demo_workspace):
    (demo_workspace / "demo.json").write_text(
        json.dumps(
            {
                "kicad_version": "10.0.6",
                "violations": [{"severity": "error", "type": "test_err", "description": "demo", "items": []}],
            }
        ),
        encoding="utf-8",
    )
    try:
        result = json.loads(_read_raw(_uri(demo_workspace, "demo.kicad_pro", "report")))
        assert result["source"]["path"] == "demo.json"
        assert result["counts"]["error"] == 1
    finally:
        (demo_workspace / "demo.json").unlink()


def test_report_resource_invalid_json_raises(demo_workspace):
    (demo_workspace / "erc.json").write_text("not-json", encoding="utf-8")
    try:
        with pytest.raises(ValueError, match="not valid KiCad JSON"):
            _read_raw(_uri(demo_workspace, "demo.kicad_pro", "report"))
    finally:
        (demo_workspace / "erc.json").unlink()


def test_report_resource_missing_reports(demo_workspace):
    with pytest.raises(ValueError, match=r"no erc\.json or drc\.json"):
        asyncio.run(server.mcp.read_resource(_uri(demo_workspace, "demo.kicad_pro", "report")))


def test_raw_resource_returns_text(demo_workspace):
    raw = _read_raw(_uri(demo_workspace, "demo.kicad_sch", "raw"))
    expected = (demo_workspace / "demo.kicad_sch").read_text(encoding="utf-8")
    assert raw.replace("\r\n", "\n") == expected.replace("\r\n", "\n")


def test_raw_resource_rejects_unknown_suffix(demo_workspace):
    (demo_workspace / "notes.txt").write_text("nope", encoding="utf-8")
    try:
        with pytest.raises(ValueError, match="only serves"):
            _read_raw(_uri(demo_workspace, "notes.txt", "raw"))
    finally:
        (demo_workspace / "notes.txt").unlink()


def test_raw_resource_rejects_missing_file(demo_workspace):
    (demo_workspace / "ghost.kicad_prl").touch()  # disallowed suffix list still applies
    (demo_workspace / "ghost.kicad_prl").unlink()
    with pytest.raises(ValueError, match=r"inside KICAD_WORKSPACE|does not exist"):
        asyncio.run(server.mcp.read_resource(_uri(demo_workspace, "ghost.kicad_pro", "raw")))


def test_resource_escape_rejected(workspace):
    with pytest.raises(ValueError):
        asyncio.run(server.mcp.read_resource(_uri(workspace, "../escape.kicad_pro", "manifest")))


def test_resource_missing_artifact(workspace):
    (workspace / "demo.kicad_pcb").unlink()
    with pytest.raises(ValueError, match=r"must stay inside KICAD_WORKSPACE|missing project artifact"):
        asyncio.run(server.mcp.read_resource(_uri(workspace, "demo.kicad_pro", "pcb")))


def test_nested_project_resource(workspace):
    nested = workspace / "boards" / "sensor"
    nested.mkdir(parents=True)
    (nested / "sensor.kicad_pro").write_text("{}", encoding="utf-8")
    (nested / "sensor.kicad_sch").write_text("(kicad_sch)", encoding="utf-8")
    result = json.loads(_read_raw(_uri(workspace, "boards/sensor/sensor.kicad_pro", "schematic")))
    assert result["project"] == "boards/sensor/sensor.kicad_pro"


# ---------------------------------------------------------------------------
# Prompt rendering
# ---------------------------------------------------------------------------


def test_audit_project_prompt(demo_workspace):
    result = asyncio.run(server.mcp.get_prompt("audit_project", {"project": "demo.kicad_pro"}))
    text = result.messages[0].content.text
    assert "demo.kicad_pro" in text
    assert "run_design_review" in text
    assert "read-only" in text.lower()
    assert len(result.messages) == 1


def test_generate_bom_report_prompt(demo_workspace):
    result = asyncio.run(
        server.mcp.get_prompt("generate_bom_report", {"project": "demo.kicad_pro", "purpose": "handoff"})
    )
    text = result.messages[0].content.text
    assert "handoff" in text
    assert "read_bom" in text


def test_generate_bom_report_default_purpose(demo_workspace):
    result = asyncio.run(server.mcp.get_prompt("generate_bom_report", {"project": "demo.kicad_pro"}))
    assert "review" in result.messages[0].content.text


def test_review_power_distribution_prompt_rails(demo_workspace):
    result = asyncio.run(
        server.mcp.get_prompt("review_power_distribution", {"project": "demo.kicad_pro", "rails": "+3V3,GND"})
    )
    assert "+3V3,GND" in result.messages[0].content.text


def test_cross_probe_prompt_requires_query(demo_workspace):
    with pytest.raises(ValueError, match="Missing required arguments"):
        asyncio.run(server.mcp.get_prompt("cross_probe_issue", {"project": "demo.kicad_pro"}))


def test_cross_probe_prompt_includes_query(demo_workspace):
    result = asyncio.run(server.mcp.get_prompt("cross_probe_issue", {"project": "demo.kicad_pro", "query": "U1"}))
    assert "U1" in result.messages[0].content.text


def test_every_prompt_rejects_missing_project():
    for name in (
        "audit_project",
        "generate_bom_report",
        "review_power_distribution",
        "review_signal_integrity",
        "prepare_fabrication",
        "summarize_project_for_handoff",
    ):
        with pytest.raises(ValueError):
            asyncio.run(server.mcp.get_prompt(name, {}))


def test_every_prompt_rejects_nonexistent_project(demo_workspace):
    for name, args in (
        ("audit_project", {}),
        ("generate_bom_report", {}),
        ("review_power_distribution", {}),
        ("review_signal_integrity", {}),
        ("cross_probe_issue", {"query": "R1"}),
        ("prepare_fabrication", {}),
        ("summarize_project_for_handoff", {}),
    ):
        with pytest.raises(ValueError):
            asyncio.run(server.mcp.get_prompt(name, {"project": "ghost.kicad_pro", **args}))


def test_unknown_prompt_rejected():
    with pytest.raises(ValueError, match="Unknown prompt"):
        asyncio.run(server.mcp.get_prompt("does_not_exist", {}))
