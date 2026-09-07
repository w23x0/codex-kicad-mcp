"""Boundary and malformed-input tests for the parsing and config layers.

These cover the Step 9 checklist: S-expression limits (token/depth/file-bytes),
unterminated quotes and unbalanced parens, project-path escapes (symlink, NUL,
empty), ``config.env_int`` per-item validation, ``as_int``/``as_float`` edge
values, and ``kicad_cli`` failure modes (missing target, timeout, missing CLI).
"""

from __future__ import annotations

import subprocess

import pytest
from mcp.server.mcpserver.exceptions import ResourceError, ToolError

from codex_kicad_mcp import config, kicad_cli, project, server
from codex_kicad_mcp.sexpr import as_float, as_int, parse_sexpr, sexpr_tokens
from test_server import workspace  # noqa: F401 - fixture

EXPECTED_ERRORS = (ValueError, RuntimeError, ToolError, ResourceError)

# ---------------------------------------------------------------------------
# S-expression parser limits
# ---------------------------------------------------------------------------


def test_tokens_exceed_budget():
    with pytest.raises(ValueError, match="token limit"):
        list(sexpr_tokens("(a b)", max_tokens=2))


def test_depth_exceeds_limit():
    text = "(" * 10 + ")" * 10
    with pytest.raises(ValueError, match="depth limit"):
        parse_sexpr(text, max_depth=5)


def test_file_over_max_bytes_is_rejected(workspace, monkeypatch):
    monkeypatch.setenv("KICAD_MAX_FILE_BYTES", "10")
    (workspace / "demo.kicad_sch").write_text("(kicad_sch (version 20231120))", encoding="utf-8")
    with pytest.raises(EXPECTED_ERRORS, match="KICAD_MAX_FILE_BYTES"):
        server.read_schematic("demo.kicad_pro")


def test_unterminated_quote_rejected():
    with pytest.raises(ValueError, match="unterminated quoted string"):
        parse_sexpr('(label "open)')


def test_unbalanced_parens_rejected():
    with pytest.raises(ValueError, match="unbalanced"):
        parse_sexpr("(a (b c)")
    with pytest.raises(ValueError, match="unbalanced"):
        parse_sexpr("(a))")


# ---------------------------------------------------------------------------
# Project path boundaries
# ---------------------------------------------------------------------------


def test_symlink_escape_rejected(workspace):
    outside = workspace.parent / "outside-target.kicad_pro"
    outside.write_text("{}", encoding="utf-8")
    link = workspace / "link.kicad_pro"
    try:
        link.symlink_to(outside)
    except OSError:
        pytest.skip("symlinks are not available on this filesystem")
    with pytest.raises(ValueError, match="inside KICAD_WORKSPACE"):
        project.project_file("link.kicad_pro")


def test_nul_in_path_rejected(workspace):
    with pytest.raises(ValueError, match="NUL"):
        project.inside_workspace("demo\x00.kicad_pro")


def test_empty_path_rejected():
    with pytest.raises(ValueError, match="must not be empty"):
        project.inside_workspace("   ")


def test_env_int_rejects_each_bad_value(monkeypatch):
    cases = {
        "abc": "must be an integer",
        "1.5": "must be an integer",
        "0x10": "must be an integer",
        "-3": "must be",
        "0": "must be",
        " ": None,  # blank falls back to default, not an error
    }
    for raw, expected in cases.items():
        monkeypatch.setenv("KICAD_TEST_LIMIT", raw)
        if expected is None:
            assert config.env_int("KICAD_TEST_LIMIT", 7) == 7
        else:
            with pytest.raises(ValueError, match=expected):
                config.env_int("KICAD_TEST_LIMIT", 7)
    monkeypatch.setenv("KICAD_TEST_LIMIT", "5")
    assert config.env_int("KICAD_TEST_LIMIT", 7) == 5


def test_as_int_and_as_float_edges():
    assert as_int(True) is None
    assert as_int(False) is None
    assert as_int("12abc") is None
    assert as_int("++1") is None
    assert as_int("42") == 42
    assert as_int("-7") == -7
    assert as_float(float("nan")) is None
    assert as_float(float("inf")) is None
    assert as_float(float("-inf")) is None
    assert as_float(None) is None
    assert as_float("2.5") == 2.5


# ---------------------------------------------------------------------------
# kicad-cli failure modes
# ---------------------------------------------------------------------------


def test_check_target_missing_fails(workspace):
    (workspace / "demo.kicad_sch").unlink()
    with pytest.raises(EXPECTED_ERRORS, match=r"missing project artifact|must be an existing"):
        server.run_kicad_cli_check("demo.kicad_pro", "sch")


def test_cli_timeout_maps_to_runtime_error(monkeypatch):
    def slow_run(command, **kwargs):
        raise subprocess.TimeoutExpired(command, 5)

    monkeypatch.setattr(kicad_cli.subprocess, "run", slow_run)
    with pytest.raises(RuntimeError, match="timed out"):
        kicad_cli.kicad_cli_version()


def test_cli_missing_from_path(monkeypatch):
    def missing(command, **kwargs):
        raise FileNotFoundError("kicad-cli")

    monkeypatch.setattr(kicad_cli.subprocess, "run", missing)
    with pytest.raises(RuntimeError, match="not found on PATH"):
        kicad_cli.kicad_cli_version()
