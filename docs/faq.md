# FAQ

## How do I point the server at my KiCad projects?

Every tool resolves project paths against the `KICAD_WORKSPACE` environment
variable. Set it to the directory that contains your `.kicad_pro` files (any
depth below it is fine) in your host's MCP config:

```json
{ "command": "uv", "args": ["run", "--directory", "C:/path/to/Codex-KiCad/mcp", "codex-kicad-mcp"],
  "env": { "KICAD_WORKSPACE": "C:/path/to/eda-workspace" } }
```

Paths you pass to tools can be relative to the workspace (`boards/sensor/
sensor.kicad_pro`) or absolute inside it. Anything that resolves outside the
workspace is rejected, including symlinks that point elsewhere.

## Which tools work without KiCad installed?

The parser-based tools never shell out and work on any machine:

- `list_kicad_projects`, `inspect_project`, `project_summary`
- `read_schematic`, `read_hierarchy`, `read_buses`, `read_pcb`,
  `read_board_metrics`, `read_layer_stackup`, `read_zones`, `read_vias`
- `analyze_signal_integrity`, `analyze_board_density`,
  `check_fabrication_readiness` (partial: checklist items that need a netlist
  report gaps), and the write API

Tools that require `kicad-cli` on PATH: `read_netlist`, `read_bom`,
`run_kicad_cli_check` (ERC/DRC), and the review tools that consume a netlist
(`analyze_power_rails`, `check_decoupling`, `cross_probe`,
`compare_schematic_pcb`, `run_design_review`). They raise a tool error that
names the missing CLI rather than returning partial data.

Check which one is available with `kicad_cli_version`.

## Why do review findings differ from KiCad's ERC/DRC?

They are different check families. ERC/DRC are KiCad's own validators, run
through `kicad-cli` with JSON reports. The review tools are heuristics over
the parsed design; they find things ERC/DRC do not (external-input power
rails, decoupling placement, parity gaps) and deliberately never report
heuristic conclusions as ERC/DRC results. Treat review findings as review
input, not as a substitute for a clean DRC.

Known heuristic boundaries, kept as findings on purpose:

- A rail charged passively (for example the PIC programmer VPP charge pump)
  has no recognizable source pin and is reported as an error.
- Rail names that do not look like supplies (the `HT` net in
  `complex_hierarchy`) are not auto-detected as rails; pass them explicitly
  via the `rails` argument of `analyze_power_rails`.

## My system language is Chinese — anything to watch?

KiCad report JSON may carry localized text in `description` fields; the
normalizer preserves it verbatim and reports severities by KiCad's structured
fields, not by parsing English prose, so severity counts are locale-safe.
`kicad-cli` exit codes are locale-independent. One KiCad 10.0.6 quirk the
server compensates for: ERC coordinates labeled `mm` are emitted two decimal
orders smaller than real millimetres; normalized positions are millimetres
and the result carries a warning explaining the scaling.

## How do I enable the write API?

Writes are inert by default. Set `KICAD_ENABLE_WRITES=1` exactly (any other
value keeps every write tool raising). Recommended additions in the same
config block:

```json
"env": {
  "KICAD_ENABLE_WRITES": "1",
  "KICAD_SNAPSHOT_ROOT": "C:/path/to/eda-snapshots"
}
```

`KICAD_SNAPSHOT_ROOT` outside the workspace keeps snapshots from ever being
confused with design artifacts. Every write is a three-step cycle —
`preview_write` (diff + one-time token), `confirm_write` (lock, snapshot,
apply, validate), `rollback_snapshot` — and every stage appends to an
append-only audit log.

## How do the tests handle a machine without KiCad?

The suite always runs the fixture-backed tests. The real-project scan tests
(`mcp/tests/test_real_projects.py`) copy small demo projects out of a KiCad
installation and skip when KiCad or the demos are absent, so CI stays green
without KiCad while your workstation runs the full coverage. Set
`KICAD_DEMO_ROOT` to point at a custom demo directory.

## Where should I report a false-positive review finding?

Open a GitHub issue with the rule ID, the message, and the smallest possible
project (or describe the rail/net structure). The
[rules table](tool-reference.md#shared-review-envelope) documents each rule's
heuristic boundary; the `power` rules include their external-input reason in
the message text.
