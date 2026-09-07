# codex-kicad-mcp

A safe, read-first [Model Context Protocol](https://modelcontextprotocol.io/)
server for KiCad workflows. It discovers KiCad projects, parses schematics and
PCBs into structured data, and runs ERC/DRC checks through `kicad-cli` without
editing design files. MCP resources expose the same data through stable URIs,
prompts provide structured task instructions, and an opt-in write API performs
snapshot-backed, audited minimal edits.

## Install

```powershell
uv pip install codex-kicad-mcp
```

Or from a source checkout:

```powershell
cd mcp
uv pip install -e ".[dev]"
```

## Run

Set `KICAD_WORKSPACE` to the directory that contains your `.kicad_pro`
projects, then start the stdio server:

```powershell
$env:KICAD_WORKSPACE = "C:/path/to/eda-workspace"
codex-kicad-mcp
```

Every tool resolves paths below `KICAD_WORKSPACE`; attempts to escape fail
before any file access or command runs. See
[`docs/security-model.md`](../docs/security-model.md) for the full trust
boundaries.

## Tools

| Tool | Reads | KiCad required |
| --- | --- | --- |
| `kicad_cli_version` | CLI version | Yes |
| `list_kicad_projects` | Workspace tree | No |
| `inspect_project` | Project file inventory | No |
| `project_summary` | Project JSON and inventory | No |
| `read_schematic` | Schematic S-expression | No |
| `read_pcb` | PCB S-expression | No |
| `read_hierarchy` | Sheet hierarchy and pins | No |
| `read_buses` | Bus geometry and entries | No |
| `read_netlist` | Netlist CLI export | Yes |
| `read_bom` | BOM CLI export | Yes |
| `read_board_metrics` | Board size and copper totals | No |
| `read_layer_stackup` | Stackup or layer table | No |
| `read_zones` | Copper zones and polygons | No |
| `read_vias` | Vias and layer pairs | No |
| `run_kicad_cli_check` | Structured ERC/DRC JSON | Yes |
| `analyze_power_rails` | Netlist power topology | Yes |
| `check_decoupling` | Netlist and PCB capacitor placement | Yes |
| `cross_probe` | Schematic, netlist, and PCB matches | Yes |
| `compare_schematic_pcb` | Netlist-to-PCB parity | Yes |
| `run_design_review` | Unified review findings | Yes |
| `analyze_signal_integrity` | PCB routing geometry | No |
| `analyze_board_density` | PCB occupancy metrics | No |
| `check_fabrication_readiness` | PCB manufacturing readiness | No |
| `preview_write` | Dry-run edit plan (opt-in) | No |
| `confirm_write` | Execute previewed edit (opt-in) | No |
| `rollback_snapshot` | Restore snapshot files (opt-in) | No |
| `list_snapshots` | Write snapshot inventory (opt-in) | No |
| `get_write_audit` | Append-only audit log (opt-in) | No |

Write tools are inert unless `KICAD_ENABLE_WRITES=1` is set exactly; see
[`docs/tool-reference.md`](../docs/tool-reference.md) for the preview →
confirm pipeline, token binding, and audit record shape.

## Resources

Nine resources under `codex-kicad://projects/{project}/…` mirror the read
tools: `manifest`, `raw` (suffix allowlist, size-bounded), `schematic`, `pcb`,
`hierarchy`, `netlist`, `bom`, `stackup`, and `report` (normalized local
ERC/DRC JSON). The `{project}` parameter is the percent-encoded
workspace-relative `.kicad_pro` path.

## Prompts

Seven prompts render structured task instructions (never writes):
`audit_project`, `generate_bom_report`, `review_power_distribution`,
`review_signal_integrity`, `cross_probe_issue`, `prepare_fabrication`, and
`summarize_project_for_handoff`.

## Configuration

All limits are read at call time; invalid values raise a tool error instead of
being clamped.

| Variable | Default | Purpose |
| --- | --- | --- |
| `KICAD_WORKSPACE` | — (required) | Root directory for all project paths |
| `KICAD_MAX_FILE_BYTES` | 33554432 | Largest artifact accepted for parsing |
| `KICAD_MAX_SEXPR_TOKENS` | 1000000 | S-expression token budget |
| `KICAD_MAX_SEXPR_DEPTH` | 512 | S-expression nesting budget |
| `KICAD_MAX_RESULT_ITEMS` | 100000 | Item cap per response |
| `KICAD_MAX_CLI_OUTPUT_BYTES` | 1048576 | CLI stdout/stderr cap per response |
| `KICAD_CLI_VERSION_TIMEOUT` | 15 | Seconds for `kicad-cli --version` |
| `KICAD_CLI_CHECK_TIMEOUT` | 120 | Seconds for an ERC/DRC check |
| `KICAD_EXPORT_TIMEOUT` | 120 | Seconds for a netlist or BOM export |
| `KICAD_ENABLE_WRITES` | unset (writes off) | Set exactly `1` to enable the write API |
| `KICAD_SNAPSHOT_ROOT` | `<workspace>/.kicad-mcp-snapshots` | Directory for write snapshots and audit log |
| `KICAD_WRITE_TOKEN_TTL` | 900 | Confirm-token lifetime in seconds |
| `KICAD_WRITE_PREVIEW_TTL` | 1800 | Preview plan lifetime in seconds |
| `KICAD_MAX_SNAPSHOTS_LISTED` | 50 | Cap on `list_snapshots` results |

The complete tool contract lives in
[`docs/tool-reference.md`](../docs/tool-reference.md).
