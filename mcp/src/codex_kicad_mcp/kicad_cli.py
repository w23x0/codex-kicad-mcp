"""kicad-cli subprocess adapter.

All external KiCad invocations go through ``run_cli`` with fixed safe process
defaults and bounded output.  ERC/DRC uses KiCad's JSON report plus a shared
normalizer so callers receive stable severities, rule IDs, positions, and
provenance rather than locale-dependent text.
"""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path
from typing import Any

from codex_kicad_mcp import config, diagnostics
from codex_kicad_mcp.project import artifact_file, read_text, rel_posix, workspace
from codex_kicad_mcp.response import artifact_source, envelope

CLI_COMMAND = "kicad-cli"
DEFAULT_VERSION_TIMEOUT = 15
DEFAULT_CHECK_TIMEOUT = 120


def bounded_output(value: Any, label: str) -> str:
    """Convert subprocess output to bounded UTF-8 text for MCP responses."""
    if value is None:
        text = ""
    elif isinstance(value, bytes):
        text = value.decode("utf-8", errors="replace")
    else:
        text = str(value)
    limit = config.max_cli_output_bytes()
    encoded = text.encode("utf-8", errors="replace")
    if len(encoded) <= limit:
        return text
    clipped = encoded[:limit].decode("utf-8", errors="replace")
    marker = f"\n[truncated {label} at {limit} bytes]"
    return clipped + marker


def run_cli(command: list[str], *, timeout: int, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    """Run the fixed KiCad CLI shape with safe process defaults."""
    try:
        return subprocess.run(
            command,
            cwd=cwd,
            stdin=subprocess.DEVNULL,
            text=True,
            capture_output=True,
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError as exc:
        raise RuntimeError("kicad-cli was not found on PATH") from exc
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"kicad-cli timed out after {timeout} seconds") from exc
    except PermissionError as exc:
        raise RuntimeError("kicad-cli could not be executed (permission denied)") from exc
    except OSError as exc:
        raise RuntimeError(f"kicad-cli could not be executed: {exc.strerror or exc.__class__.__name__}") from exc


def kicad_cli_version() -> dict[str, object]:
    result = run_cli(
        [CLI_COMMAND, "--version"],
        timeout=config.cli_timeout("KICAD_CLI_VERSION_TIMEOUT", DEFAULT_VERSION_TIMEOUT, maximum=300),
    )
    stdout = bounded_output(result.stdout, "stdout")
    stderr = bounded_output(result.stderr, "stderr")
    # Some KiCad builds print the version on stderr.  Keep the historical
    # response shape while making the useful value available in either case.
    version = stdout.strip() or stderr.strip()
    return {"exitCode": result.returncode, "version": version, "stderr": stderr}


def run_kicad_cli_check(project: str, check: str = "sch") -> dict[str, object]:
    if check not in {"sch", "pcb"}:
        raise ValueError("check must be 'sch' or 'pcb'")
    suffix = ".kicad_sch" if check == "sch" else ".kicad_pcb"
    target = artifact_file(project, suffix)
    project_path = rel_posix(target.with_suffix(".kicad_pro"))
    source = artifact_source(target, read_text(target))
    report_name = "erc.json" if check == "sch" else "drc.json"
    command = (
        [CLI_COMMAND, "sch", "erc", "--format", "json", "--severity-all", "--exit-code-violations", "--output"]
        if check == "sch"
        else [CLI_COMMAND, "pcb", "drc", "--format", "json", "--severity-all", "--exit-code-violations", "--output"]
    )
    with tempfile.TemporaryDirectory(prefix="codex-kicad-check-") as temporary:
        output = Path(temporary) / report_name
        command = [*command, str(output), str(target)]
        result = run_cli(
            command,
            timeout=config.cli_timeout("KICAD_CLI_CHECK_TIMEOUT", DEFAULT_CHECK_TIMEOUT, maximum=3600),
            cwd=workspace(),
        )
        stdout = bounded_output(result.stdout, "stdout")
        stderr = bounded_output(result.stderr, "stderr")
        try:
            report_text = read_text(output) if output.is_file() else stdout
            report = diagnostics.parse_check_json(report_text)
        except (OSError, UnicodeError, ValueError) as exc:
            if isinstance(exc, ValueError):
                raise
            raise ValueError(f"could not read kicad-cli check report: {exc}") from exc
    issues, warnings, severity_counts = diagnostics.normalize_check_report(report, check=check)
    data = {
        "check": "ERC" if check == "sch" else "DRC",
        "command": command,
        "passed": result.returncode == 0,
        "exitCode": result.returncode,
        "kicadVersion": report.get("kicad_version"),
        "coordinateUnits": report.get("coordinate_units"),
        "includedSeverities": report.get("included_severities", []),
        "ignoredChecks": report.get("ignored_checks", []),
        "issues": issues,
        "raw": {"stdout": stdout, "stderr": stderr},
    }
    counts = {
        "issues": len(issues),
        **severity_counts,
    }
    return envelope(project_path, source, data, counts, warnings=warnings, confidence="cli")
