"""kicad-cli BOM export and CSV extraction."""

from __future__ import annotations

import csv
import io
import tempfile
from pathlib import Path

from codex_kicad_mcp import config, kicad_cli
from codex_kicad_mcp.project import artifact_file, read_text, rel_posix
from codex_kicad_mcp.response import artifact_source, envelope

DEFAULT_FIELDS = "Reference,Value,Footprint,QUANTITY,DNP"
DEFAULT_LABELS = "Reference,Value,Footprint,Quantity,DNP"


def _export_bom(schematic_path: Path, fields: str, labels: str) -> tuple[str, list[str], list[str], list[str]]:
    with tempfile.TemporaryDirectory(prefix="codex-kicad-bom-") as temporary:
        output = Path(temporary) / "bom.csv"
        command = [
            kicad_cli.CLI_COMMAND,
            "sch",
            "export",
            "bom",
            "--fields",
            fields,
            "--labels",
            labels,
            "--output",
            str(output),
            str(schematic_path),
        ]
        result = kicad_cli.run_cli(
            command,
            timeout=config.cli_timeout("KICAD_EXPORT_TIMEOUT", kicad_cli.DEFAULT_CHECK_TIMEOUT, maximum=3600),
            cwd=schematic_path.parent,
        )
        stdout = kicad_cli.bounded_output(result.stdout, "stdout")
        stderr = kicad_cli.bounded_output(result.stderr, "stderr")
        if result.returncode != 0:
            raise RuntimeError(f"kicad-cli BOM export failed with exit code {result.returncode}: {stderr or stdout}")
        if not output.is_file():
            raise RuntimeError("kicad-cli did not create the requested BOM export")
        try:
            text = read_text(output)
        except (OSError, UnicodeError) as exc:
            raise ValueError(f"invalid BOM export: {exc}") from exc
        warnings = [line.strip() for line in stderr.splitlines() if line.strip()]
        info = [line.strip() for line in stdout.splitlines() if line.strip()]
        return text, warnings, info, command


def read_bom(
    project: str,
    *,
    fields: str = DEFAULT_FIELDS,
    labels: str = DEFAULT_LABELS,
) -> dict[str, object]:
    schematic_path = artifact_file(project, ".kicad_sch")
    project_path = rel_posix(schematic_path.with_suffix(".kicad_pro"))
    source = artifact_source(schematic_path, read_text(schematic_path))
    text, warnings, info, command = _export_bom(schematic_path, fields, labels)
    try:
        rows = list(csv.reader(io.StringIO(text), strict=True))
    except csv.Error as exc:
        raise ValueError(f"kicad-cli BOM export is not valid CSV: {exc}") from exc
    if not rows or not any(cell.strip() for cell in rows[0]):
        raise ValueError("kicad-cli BOM export has no header row")
    columns = rows[0]
    if len(set(columns)) != len(columns):
        warnings.append("BOM export contains duplicate column names; later values replace earlier values")
    records = [dict(zip(columns, row, strict=False)) for row in rows[1:] if any(cell.strip() for cell in row)]
    data = {
        "command": command,
        "columns": columns,
        "rows": records,
        "exportMessages": info,
    }
    counts = {"columns": len(columns), "rows": len(records)}
    return envelope(project_path, source, data, counts, warnings=warnings, confidence="cli")
