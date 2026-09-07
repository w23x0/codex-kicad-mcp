"""kicad-cli netlist export and structured extraction."""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

from codex_kicad_mcp import config, kicad_cli
from codex_kicad_mcp.project import artifact_file, read_text, rel_posix
from codex_kicad_mcp.response import artifact_source, envelope
from codex_kicad_mcp.sexpr import children, first_child, parse_sexpr, scalar_child


def _export_netlist(schematic_path: Path) -> tuple[str, list[str], list[str], list[str]]:
    with tempfile.TemporaryDirectory(prefix="codex-kicad-netlist-") as temporary:
        output = Path(temporary) / "netlist.kicad_sexpr"
        command = [
            kicad_cli.CLI_COMMAND,
            "sch",
            "export",
            "netlist",
            "--format",
            "kicadsexpr",
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
            raise RuntimeError(
                f"kicad-cli netlist export failed with exit code {result.returncode}: {stderr or stdout}"
            )
        if not output.is_file():
            raise RuntimeError("kicad-cli did not create the requested netlist export")
        try:
            text = read_text(output)
        except (OSError, UnicodeError) as exc:
            raise ValueError(f"invalid netlist export: {exc}") from exc
        warnings = [line.strip() for line in stderr.splitlines() if line.strip()]
        info = [line.strip() for line in stdout.splitlines() if line.strip()]
        return text, warnings, info, command


def _properties(node: list[Any]) -> dict[str, str | None]:
    result: dict[str, str | None] = {}
    for child in children(node, "property"):
        if len(child) >= 2:
            name = str(child[1])
            result[name] = str(child[2]) if len(child) > 2 else None
    return result


def _fields(node: list[Any]) -> dict[str, str | None]:
    result: dict[str, str | None] = {}
    for child in children(node, "field"):
        if len(child) >= 2:
            name = str(child[1])
            result[name] = str(child[2]) if len(child) > 2 else None
    return result


def read_netlist(project: str) -> dict[str, object]:
    schematic_path = artifact_file(project, ".kicad_sch")
    project_path = rel_posix(schematic_path.with_suffix(".kicad_pro"))
    source = artifact_source(schematic_path, read_text(schematic_path))
    text, warnings, info, command = _export_netlist(schematic_path)
    try:
        root = parse_sexpr(text)
    except ValueError as exc:
        raise ValueError(f"kicad-cli netlist export is not valid S-expression: {exc}") from exc
    top = next((node for node in root if isinstance(node, list) and node and node[0] == "export"), None)
    if top is None:
        raise ValueError("kicad-cli netlist export does not contain an export root")
    components_node = first_child(top, "components")
    nets_node = first_child(top, "nets")
    design_node = first_child(top, "design")
    libraries_node = first_child(top, "libraries")
    if components_node is None or nets_node is None:
        raise ValueError("kicad-cli netlist export is missing components or nets")

    components: list[dict[str, object]] = []
    pins = 0
    for component in children(components_node, "comp"):
        ref = scalar_child(component, "ref")
        units: list[dict[str, object]] = []
        for unit in children(component, "unit"):
            unit_pins = [child[1] for child in children(unit, "pin") if len(child) > 1]
            pins += len(unit_pins)
            config.bounded_append(
                units,
                {
                    "name": child[1] if (child := first_child(unit, "name")) and len(child) > 1 else None,
                    "pins": unit_pins,
                },
                "netlist component units",
            )
        libsource = first_child(component, "libsource")
        sheetpath = first_child(component, "sheetpath")
        config.bounded_append(
            components,
            {
                "reference": ref,
                "value": scalar_child(component, "value"),
                "footprint": scalar_child(component, "footprint"),
                "fields": _fields(component),
                "properties": _properties(component),
                "library": scalar_child(libsource, "lib") if libsource else None,
                "part": scalar_child(libsource, "part") if libsource else None,
                "description": scalar_child(libsource, "description") if libsource else None,
                "sheetPath": scalar_child(sheetpath, "names") if sheetpath else None,
                "sheetUuidPath": scalar_child(sheetpath, "tstamps") if sheetpath else None,
                "uuid": scalar_child(component, "tstamps"),
                "units": units,
            },
            "netlist components",
        )

    nets: list[dict[str, object]] = []
    nodes = 0
    for net in children(nets_node, "net"):
        net_nodes: list[dict[str, object]] = []
        for node in children(net, "node"):
            nodes += 1
            config.bounded_append(
                net_nodes,
                {
                    "reference": scalar_child(node, "ref"),
                    "pin": scalar_child(node, "pin"),
                    "pinFunction": scalar_child(node, "pinfunction"),
                    "pinType": scalar_child(node, "pintype"),
                },
                "netlist nodes",
            )
        config.bounded_append(
            nets,
            {
                "code": scalar_child(net, "code"),
                "name": scalar_child(net, "name"),
                "class": scalar_child(net, "class"),
                "nodes": net_nodes,
            },
            "netlist nets",
        )

    sheets: list[dict[str, object]] = []
    for sheet in children(design_node, "sheet") if design_node else []:
        title = first_child(sheet, "title_block")
        config.bounded_append(
            sheets,
            {
                "number": scalar_child(sheet, "number"),
                "name": scalar_child(sheet, "name"),
                "uuidPath": scalar_child(sheet, "tstamps"),
                "title": scalar_child(title, "title") if title else None,
                "source": scalar_child(title, "source") if title else None,
            },
            "netlist sheets",
        )
    libraries: list[dict[str, object]] = []
    for library in children(libraries_node, "library") if libraries_node else []:
        config.bounded_append(
            libraries,
            {
                "logical": scalar_child(library, "logical"),
                "uri": scalar_child(library, "uri"),
            },
            "netlist libraries",
        )
    data = {
        "command": command,
        "sheets": sheets,
        "components": components,
        "libraries": libraries,
        "nets": nets,
        "exportMessages": info,
    }
    counts = {
        "sheets": len(sheets),
        "components": len(components),
        "pins": pins,
        "nets": len(nets),
        "nodes": nodes,
        "libraries": len(libraries),
    }
    return envelope(
        project_path,
        source,
        data,
        counts,
        warnings=warnings,
        confidence="cli",
    )
