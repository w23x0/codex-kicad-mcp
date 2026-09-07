"""Failure-injection and happy-path tests for the opt-in write API."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from mcp.server.mcpserver.exceptions import ResourceError, ToolError

from codex_kicad_mcp import server
from codex_kicad_mcp.writes import pipeline, store
from codex_kicad_mcp.writes.edits import EditError
from codex_kicad_mcp.writes.textops import find_child_properties, find_named_blocks, fmt_number, sexpr_escape
from test_server import workspace  # noqa: F401 - fixture

EXPECTED_ERRORS = (ValueError, RuntimeError, ToolError, ResourceError)

SCHEMATIC = (
    "(kicad_sch (version 20250114)\n"
    '\t(symbol (lib_id "Device:R") (at 10 20) (uuid "u1")\n'
    '\t\t(property "Reference" "R1" (at 10 18) (uuid "u1r"))\n'
    '\t\t(property "Value" "10k" (at 10 22) (uuid "u1v")))\n'
    '\t(symbol (lib_id "Device:C") (at 30 40) (uuid "u2")\n'
    '\t\t(property "Reference" "C?" (at 30 38) (uuid "u2r"))\n'
    '\t\t(property "Value" "1u" (at 30 42) (uuid "u2v")))\n'
    ")\n"
)

PCB = (
    '(kicad_pcb (footprint "R_0805" (at 10 20 90) (property "Reference" "R1"))'
    '(footprint "C_0402" (at 30 40) (property "Reference" "C1")))'
)


@pytest.fixture
def write_workspace(workspace, monkeypatch):
    """A workspace with writes enabled and a snapshot root outside the tree."""
    monkeypatch.setenv("KICAD_ENABLE_WRITES", "1")
    monkeypatch.setenv("KICAD_SNAPSHOT_ROOT", str(workspace.parent / f"{workspace.name}-snaps"))
    (workspace / "demo.kicad_sch").write_text(SCHEMATIC, encoding="utf-8", newline="")
    (workspace / "demo.kicad_pcb").write_text(PCB, encoding="utf-8", newline="")
    store.reset_tokens()
    store.reset_previews()
    yield workspace
    store.reset_tokens()
    store.reset_previews()


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Opt-in gate
# ---------------------------------------------------------------------------


def test_every_write_tool_requires_opt_in(workspace, monkeypatch):
    monkeypatch.delenv("KICAD_ENABLE_WRITES", raising=False)
    with pytest.raises(ValueError, match="KICAD_ENABLE_WRITES"):
        pipeline.preview_write("demo.kicad_pro", "set_property", {})
    with pytest.raises(ValueError, match="KICAD_ENABLE_WRITES"):
        pipeline.confirm_write("demo.kicad_pro", "h", "s", "t")
    with pytest.raises(ValueError, match="KICAD_ENABLE_WRITES"):
        pipeline.rollback_snapshot("demo.kicad_pro", "s")
    with pytest.raises(ValueError, match="KICAD_ENABLE_WRITES"):
        pipeline.list_snapshots("demo.kicad_pro")
    with pytest.raises(ValueError, match="KICAD_ENABLE_WRITES"):
        pipeline.get_write_audit("demo.kicad_pro")


def test_writes_reject_wrong_flag_values(workspace, monkeypatch):
    for value in ("true", "yes", "0", "1 ", "2"):
        monkeypatch.setenv("KICAD_ENABLE_WRITES", value)
        with pytest.raises(ValueError, match="KICAD_ENABLE_WRITES"):
            pipeline.list_snapshots("demo.kicad_pro")


# ---------------------------------------------------------------------------
# Path escape and validation
# ---------------------------------------------------------------------------


def test_preview_rejects_path_escape(write_workspace):
    with pytest.raises(ValueError, match="inside KICAD_WORKSPACE"):
        pipeline.preview_write("../escape.kicad_pro", "set_property", {})


def test_preview_rejects_unknown_op(write_workspace):
    with pytest.raises(EditError, match="unsupported write operation"):
        pipeline.preview_write("demo.kicad_pro", "replot_board", {})


def test_preview_rejects_missing_target(write_workspace):
    with pytest.raises(EditError, match="not found"):
        pipeline.preview_write("demo.kicad_pro", "set_property", {"reference": "R99", "name": "Value", "value": "1"})


def test_preview_rejects_bad_numbers(write_workspace):
    with pytest.raises(EditError, match="within"):
        pipeline.preview_write("demo.kicad_pro", "rotate_footprint", {"reference": "R1", "angle": 720})
    with pytest.raises(ValueError, match="finite"):
        pipeline.preview_write("demo.kicad_pro", "move_footprint", {"reference": "R1", "x": float("inf"), "y": 0})


# ---------------------------------------------------------------------------
# Confirm-token binding failures
# ---------------------------------------------------------------------------


def test_confirm_rejects_wrong_token(write_workspace):
    preview = pipeline.preview_write(
        "demo.kicad_pro", "set_property", {"reference": "R1", "name": "Value", "value": "22k"}
    )
    with pytest.raises(ValueError, match="confirm token"):
        pipeline.confirm_write("demo.kicad_pro", preview["planHash"], preview["snapshotId"], "bogus")
    # original file untouched
    assert '"10k"' in read_text(write_workspace / "demo.kicad_sch")


def test_confirm_rejects_wrong_plan_hash(write_workspace):
    preview = pipeline.preview_write(
        "demo.kicad_pro", "set_property", {"reference": "R1", "name": "Value", "value": "22k"}
    )
    store.reset_previews()  # force a fresh preview so the second token exists
    other = pipeline.preview_write(
        "demo.kicad_pro", "set_property", {"reference": "R1", "name": "Value", "value": "33k"}
    )
    # token from `other` bound to other's plan hash, used with preview's ids
    with pytest.raises(ValueError, match=r"no active preview|does not match"):
        pipeline.confirm_write("demo.kicad_pro", preview["planHash"], preview["snapshotId"], other["confirmToken"])


def test_confirm_rejects_wrong_snapshot_id(write_workspace):
    preview = pipeline.preview_write(
        "demo.kicad_pro", "set_property", {"reference": "R1", "name": "Value", "value": "22k"}
    )
    # The token check fires first: the token is bound to the previewed
    # snapshot id, so a forged snapshot id is rejected before any file I/O.
    with pytest.raises(ValueError, match="does not match this snapshot id"):
        pipeline.confirm_write("demo.kicad_pro", preview["planHash"], "staged-forged", preview["confirmToken"])


def test_confirm_rejects_stale_hash(write_workspace):
    preview = pipeline.preview_write(
        "demo.kicad_pro", "set_property", {"reference": "R1", "name": "Value", "value": "22k"}
    )
    # mutate the file after the preview so the pre-hash no longer matches
    (write_workspace / "demo.kicad_sch").write_text(SCHEMATIC.replace('"10k"', '"11k"'), encoding="utf-8", newline="")
    with pytest.raises(EditError, match=r"source hash changed|stale"):
        pipeline.confirm_write("demo.kicad_pro", preview["planHash"], preview["snapshotId"], preview["confirmToken"])
    assert '"11k"' in read_text(write_workspace / "demo.kicad_sch")


# ---------------------------------------------------------------------------
# Happy path + audit + rollback
# ---------------------------------------------------------------------------


def test_full_write_cycle_with_audit_and_rollback(write_workspace):
    preview = pipeline.preview_write(
        "demo.kicad_pro", "set_property", {"reference": "R1", "name": "Value", "value": "22k"}
    )
    result = pipeline.confirm_write(
        "demo.kicad_pro", preview["planHash"], preview["snapshotId"], preview["confirmToken"]
    )
    assert result["applied"] is True
    assert '"22k"' in read_text(write_workspace / "demo.kicad_sch")

    audit = pipeline.get_write_audit("demo.kicad_pro")
    stages = [record["stage"] for record in audit["records"]]
    assert "preview" in stages and "execute" in stages
    execute_record = next(record for record in audit["records"] if record["stage"] == "execute")
    assert execute_record["ok"] is True
    assert execute_record["tokenHash"]
    assert execute_record["planHash"] == preview["planHash"]

    # rollback to the snapshot
    rollback = pipeline.rollback_snapshot("demo.kicad_pro", result["snapshotId"])
    assert rollback["rolledBack"] is True
    assert '"10k"' in read_text(write_workspace / "demo.kicad_sch")
    rollback_record = pipeline.get_write_audit("demo.kicad_pro")["records"][-1]
    assert rollback_record["stage"] == "rollback"


def test_move_and_rotate_footprint(write_workspace):
    preview = pipeline.preview_write("demo.kicad_pro", "move_footprint", {"reference": "R1", "x": 42.5, "y": 24})
    pipeline.confirm_write("demo.kicad_pro", preview["planHash"], preview["snapshotId"], preview["confirmToken"])
    assert "(at 42.5 24 90)" in read_text(write_workspace / "demo.kicad_pcb")

    preview = pipeline.preview_write("demo.kicad_pro", "rotate_footprint", {"reference": "C1", "angle": -90})
    pipeline.confirm_write("demo.kicad_pro", preview["planHash"], preview["snapshotId"], preview["confirmToken"])
    assert "(at 30 40 -90)" in read_text(write_workspace / "demo.kicad_pcb")


def test_auto_annotate_assigns_and_preserves(write_workspace):
    preview = pipeline.preview_write("demo.kicad_pro", "auto_annotate", {})
    assert preview["warnings"] == []
    pipeline.confirm_write("demo.kicad_pro", preview["planHash"], preview["snapshotId"], preview["confirmToken"])
    text = read_text(write_workspace / "demo.kicad_sch")
    assert '"R1"' in text and '"C1"' in text
    assert '"C?"' not in text


def test_auto_annotate_no_op_warns(write_workspace):
    text = SCHEMATIC.replace('"C?"', '"C1"')
    (write_workspace / "demo.kicad_sch").write_text(text, encoding="utf-8", newline="")
    preview = pipeline.preview_write("demo.kicad_pro", "auto_annotate", {})
    assert preview["warnings"] == ["no unannotated symbols; nothing to do"]
    pipeline.confirm_write("demo.kicad_pro", preview["planHash"], preview["snapshotId"], preview["confirmToken"])
    # confirm on a no-op plan still succeeds and rewrites identical content
    assert '"C1"' in read_text(write_workspace / "demo.kicad_sch")


# ---------------------------------------------------------------------------
# Post-validate failure injection
# ---------------------------------------------------------------------------


def test_post_validate_rolls_back_on_unparseable_result(write_workspace, monkeypatch):
    preview = pipeline.preview_write(
        "demo.kicad_pro", "set_property", {"reference": "R1", "name": "Value", "value": "22k"}
    )
    snapshot_id = preview["snapshotId"]

    # Corrupt the plan transform after preview but before validation runs:
    # the pipeline validates edits before the first atomic write, so inject
    # into ``parse_sexpr`` usage via the validator itself.
    import codex_kicad_mcp.writes.pipeline as pipeline_module

    real_validate = pipeline_module._validate_sexpr

    def corrupting_validate(text: str, name: str) -> None:
        if '"22k"' in text:
            real_validate("(unbalanced", name)  # raise as if the write broke it
            raise AssertionError("validator should have raised")
        real_validate(text, name)

    monkeypatch.setattr(pipeline_module, "_validate_sexpr", corrupting_validate)
    with pytest.raises(ValueError, match="not valid KiCad S-expression"):
        pipeline.confirm_write("demo.kicad_pro", preview["planHash"], snapshot_id, preview["confirmToken"])
    # file unchanged (validation happens before any write)
    assert '"10k"' in read_text(write_workspace / "demo.kicad_sch")
    record = pipeline.get_write_audit("demo.kicad_pro")["records"][-1]
    assert record["ok"] is False


def test_post_write_hash_mismatch_triggers_rollback(write_workspace, monkeypatch):
    preview = pipeline.preview_write(
        "demo.kicad_pro", "set_property", {"reference": "R1", "name": "Value", "value": "22k"}
    )
    snapshot_id = preview["snapshotId"]

    import codex_kicad_mcp.writes.store as store_module

    real_atomic = store_module.atomic_write_bytes
    calls = {"n": 0}

    def flaky_atomic(path, payload):
        calls["n"] += 1
        if calls["n"] == 1:
            # write something wrong the first time to force a hash mismatch
            real_atomic(path, b"(kicad_sch (corrupted)")
        else:
            real_atomic(path, payload)

    monkeypatch.setattr(store_module, "atomic_write_bytes", flaky_atomic)
    with pytest.raises(RuntimeError, match="post-write hash mismatch"):
        pipeline.confirm_write("demo.kicad_pro", preview["planHash"], snapshot_id, preview["confirmToken"])
    # rollback restored the original bytes
    assert '"10k"' in read_text(write_workspace / "demo.kicad_sch")
    assert '"22k"' not in read_text(write_workspace / "demo.kicad_sch")
    record = pipeline.get_write_audit("demo.kicad_pro")["records"][-1]
    assert record["ok"] is False
    assert record["rolledBack"]


def test_lock_blocks_concurrent_write(write_workspace):
    lock = store.project_lock("demo.kicad_pro")
    lock.acquire()
    try:
        preview = pipeline.preview_write(
            "demo.kicad_pro", "set_property", {"reference": "R1", "name": "Value", "value": "22k"}
        )
        with pytest.raises(ValueError, match="holds the lock"):
            pipeline.confirm_write(
                "demo.kicad_pro", preview["planHash"], preview["snapshotId"], preview["confirmToken"]
            )
    finally:
        lock.release()
    # lock released: the same token is still valid (preview burned? no - the
    # failed attempt popped the token). Re-preview and succeed.
    preview = pipeline.preview_write(
        "demo.kicad_pro", "set_property", {"reference": "R1", "name": "Value", "value": "22k"}
    )
    result = pipeline.confirm_write(
        "demo.kicad_pro", preview["planHash"], preview["snapshotId"], preview["confirmToken"]
    )
    assert result["applied"] is True


def test_snapshot_root_env_override(write_workspace):
    root = write_workspace.parent / f"{write_workspace.name}-snaps"
    preview = pipeline.preview_write(
        "demo.kicad_pro", "set_property", {"reference": "R1", "name": "Value", "value": "22k"}
    )
    pipeline.confirm_write("demo.kicad_pro", preview["planHash"], preview["snapshotId"], preview["confirmToken"])
    assert root.is_dir()
    assert (root / "audit.jsonl").is_file()
    # The key assertion: no snapshot directory inside the workspace itself.
    assert not (write_workspace / ".kicad-mcp-snapshots").exists()


def test_snapshot_missing_id_rejected(write_workspace):
    with pytest.raises(ValueError, match="invalid snapshot id"):
        store.snapshot_dir("../escape")
    with pytest.raises(ValueError, match="does not exist"):
        store.snapshot_dir("ghost-snapshot")


def test_rollback_project_mismatch(write_workspace):
    preview = pipeline.preview_write(
        "demo.kicad_pro", "set_property", {"reference": "R1", "name": "Value", "value": "22k"}
    )
    pipeline.confirm_write("demo.kicad_pro", preview["planHash"], preview["snapshotId"], preview["confirmToken"])
    with pytest.raises(EditError, match="different project"):
        pipeline.rollback_snapshot("other.kicad_pro", preview["snapshotId"])


def test_newline_preservation(write_workspace):
    # Windows-style CRLF artifacts must keep their line endings byte-exact.
    crlf = SCHEMATIC.replace("\n", "\r\n")
    (write_workspace / "demo.kicad_sch").write_bytes(crlf.encode("utf-8"))
    preview = pipeline.preview_write(
        "demo.kicad_pro", "set_property", {"reference": "R1", "name": "Value", "value": "22k"}
    )
    pipeline.confirm_write("demo.kicad_pro", preview["planHash"], preview["snapshotId"], preview["confirmToken"])
    payload = (write_workspace / "demo.kicad_sch").read_bytes()
    assert b"\r\n" in payload and b"\n" not in payload.replace(b"\r\n", b"")


# ---------------------------------------------------------------------------
# textops unit checks
# ---------------------------------------------------------------------------


def test_find_named_blocks_excludes_nested():
    text = '(root (lib_symbols (symbol "inner")) (symbol (property "Reference" "R1")))'
    spans = find_named_blocks(text, "symbol", parent_depth=1)
    assert len(spans) == 1


def test_find_child_properties_offsets():
    text = '(symbol (property "Reference" "R1") (property "Value" "10k"))'
    hits = find_child_properties(text)
    assert [(h.name, h.value) for h in hits] == [("Reference", "R1"), ("Value", "10k")]


def test_fmt_number_and_escape():
    assert fmt_number(0) == "0"
    assert fmt_number(-0.0) == "0"
    assert fmt_number(1.5) == "1.5"
    assert fmt_number(12.3456789) == "12.345679"
    assert sexpr_escape('say "hi" \\ ok') == 'say \\"hi\\" \\\\ ok'
    with pytest.raises(ValueError, match="control characters"):
        sexpr_escape("bad\x01value")


def test_server_write_tools_registered():
    import asyncio

    tools = asyncio.run(server.mcp.list_tools())
    write_tools = {
        tool.name: tool
        for tool in tools
        if tool.name in {"preview_write", "confirm_write", "rollback_snapshot", "list_snapshots", "get_write_audit"}
    }
    assert len(write_tools) == 5
    for _name, tool in write_tools.items():
        annotations = tool.annotations
        assert annotations is not None
        assert annotations.read_only_hint is False


def test_audit_jsonl_is_append_only_shape(write_workspace):
    pipeline.preview_write("demo.kicad_pro", "set_property", {"reference": "R1", "name": "Value", "value": "22k"})
    log_path = store.audit_log_path()
    lines = log_path.read_text(encoding="utf-8").strip().splitlines()
    records = [json.loads(line) for line in lines]
    assert all(isinstance(record, dict) for record in records)
    assert all("ts" in record and "stage" in record for record in records)
