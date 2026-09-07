---
name: codex-kicad
description: Safe workflow for inspecting KiCad projects and running ERC/DRC through Codex KiCad MCP.
---

# Codex KiCad Workflow

1. Confirm `codex mcp list` shows the `kicad` server.
2. Confirm design intent and workspace.
3. Start with `kicad_cli_version`, `list_kicad_projects`, and `inspect_project`.
4. Use `project_summary`; use `read_schematic`, `read_pcb`, or focused data
   tools before reasoning about connectivity, hierarchy, or board geometry.
5. Run `run_kicad_cli_check` before suggesting changes; use `read_netlist`
   and `read_bom` when the review depends on connectivity or component data.
6. Report warnings and failures; never claim a check passed without tool
   output.

The current server is read-first. Do not invent write operations.
