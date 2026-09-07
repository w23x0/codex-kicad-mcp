# Compatibility

| Component | Supported baseline |
| --- | --- |
| Python | 3.10-3.13 |
| KiCad | 8.x-10.x with `kicad-cli` on PATH; patch-level output may differ. The Step 4/5 fixture and JSON diagnostics were verified against KiCad 10.0.6 |
| Codex | Current MCP-capable releases |
| MCP Python SDK | 1.9.x (`<2`) |

Command output can vary by KiCad patch release. The server is read-first;
ERC/DRC may create reports according to KiCad behavior but do not edit design
source files. Before reporting a project as clean, inspect both `exitCode` and
the returned issue lines. A zero exit code alone is not a substitute for
reviewing KiCad's report.

## Integration checklist

1. Run `kicad_cli_version` and record the reported version.
2. Run the schematic and board checks against a disposable copy of a project.
3. Confirm report files and source files are unchanged except for documented
   KiCad report side effects.
4. Record the result in the release notes when adding a new KiCad major.
