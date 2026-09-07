# Tool Reference

The server uses stdio MCP transport. Existing discovery tools return their
compact Phase 0 shapes documented below. The data extraction and diagnostic
tools use the shared envelope in the next section. Paths in responses are
relative to `KICAD_WORKSPACE`; internal absolute paths are used only to invoke
the native KiCad CLI.

## MCP resources

Nine project-scoped resources expose the read-tool data through stable URIs so
hosts can list and subscribe without invoking tools:

```text
codex-kicad://projects/{project}/manifest
codex-kicad://projects/{project}/raw
codex-kicad://projects/{project}/schematic
codex-kicad://projects/{project}/pcb
codex-kicad://projects/{project}/hierarchy
codex-kicad://projects/{project}/netlist
codex-kicad://projects/{project}/bom
codex-kicad://projects/{project}/stackup
codex-kicad://projects/{project}/report
```

`{project}` is the workspace-relative `.kicad_pro` path, percent-encoded
because the resource template does not match across `/`. Resources reuse the
read tools exactly: the same parsing, envelope, size limits, and workspace
boundary checks apply. Specifics:

- `manifest`, `schematic`, `pcb`, `hierarchy`, `netlist`, `bom`, `stackup`:
  identical payloads to the corresponding read tools, served as
  `application/json`.
- `raw`: the unmodified text of one artifact, served as `text/plain`. Only the
  suffixes `.kicad_pro`, `.kicad_sch`, `.kicad_pcb`, `.kicad_prl`, and
  `.kicad_sym` are served, and `KICAD_MAX_FILE_BYTES` still bounds the read so
  raw access cannot bypass the parser budget.
- `report`: normalized findings from a local ERC/DRC JSON report without
  invoking `kicad-cli`. It prefers `erc.json` (or KiCad's GUI default
  `<stem>.json`) beside the root schematic and falls back to `drc.json` (or
  `<stem>.json`) beside the board; it errors when neither exists.

## MCP prompts

Seven prompts render structured, read-only task instructions. They never
execute writes; each names the tools and resources to call and the report
format to produce.

| Prompt | Arguments | Task |
| --- | --- | --- |
| `audit_project` | `project` | Full design audit: inventory, structure, reviews, ERC/DRC, verdict |
| `generate_bom_report` | `project`, `purpose` | BOM export plus schematic/PCB consistency notes |
| `review_power_distribution` | `project`, `rails?` | Power-tree review with rail filter and classifications |
| `review_signal_integrity` | `project` | SI review grouped by net class with a routing-fix list |
| `cross_probe_issue` | `project`, `query` | Trace one item across schematic, netlist, and PCB |
| `prepare_fabrication` | `project` | Fabrication go/no-go checklist gated on ERC/DRC |
| `summarize_project_for_handoff` | `project` | Structured handoff summary under 400 words |

Prompts validate the project path through the shared boundary helpers, so an
unknown project renders as a tool error, not a generic instruction.

## Shared data envelope

`read_schematic`, `read_pcb`, `read_hierarchy`, `read_buses`,
`read_netlist`, `read_bom`, `read_board_metrics`, `read_layer_stackup`,
`read_zones`, `read_vias`, and `run_kicad_cli_check` return:

```json
{
  "schemaVersion": "1.0",
  "project": "demo.kicad_pro",
  "source": {"path": "demo.kicad_sch", "sha256": "64 hex chars", "sizeBytes": 1},
  "data": {},
  "counts": {},
  "warnings": [],
  "confidence": "parsed"
}
```

`confidence` is `parsed` for direct S-expression extraction, `cli` when the
result came from a KiCad CLI export/report, or `heuristic` when a requested
KiCad structure was absent and a conservative equivalent was derived. The
source is the design artifact consumed by the tool, not a temporary CLI output.

## Shared review envelope

The eight review tools return the same compact findings envelope. `data` is
present only for tools that also return measurements, matches, or checklists:

```json
{
  "schemaVersion": "1.0",
  "project": "demo.kicad_pro",
  "source": {"path": "demo.kicad_sch", "sha256": "64 hex chars", "sizeBytes": 1},
  "findings": [],
  "summary": {"error": 0, "warning": 0, "info": 0},
  "counts": {"findings": 0, "rules": 0},
  "warnings": [],
  "confidence": "heuristic"
}
```

Each finding has `ruleId`, `kind`, `severity`, `confidence`, `message`,
`source.path`, `objects`, and `suggestions`. `kind` is `power`,
`decoupling`, `parity`, `si`, `manufacturing`, or `layout`; severity is
`error`, `warning`, or `info`; confidence is `high`, `medium`, or `low`.
Objects always contain `kind`, `name`, and nullable `uuid`. Optional
`schematic` and `pcb` objects carry the symbol/pin/sheet-path and
footprint/pad/layer/position context. Every finding is traceable to at least
one source path, object, coordinate, or UUID.

The first rule set is:

| Rule | Severity | Heuristic boundary |
| --- | --- | --- |
| `power.source_missing` | error/warning | Recognized rail has consumers but no `power_out`-style source. Downgraded to a warning when the rail looks externally fed — a connector on the rail, a component on the rail that drives `power_out` on a different rail (regulator input pattern), or all component `power_in` pins on the root sheet — and the message states the assumption (`assumed external input rail: …`) |
| `power.consumer_missing_rail` | warning | Supply-style pin is on an unrecognized net |
| `power.multiple_sources_same_rail` | warning | More than one source pin is on one rail |
| `power.rail_short_to_ground` | error | A GND-valued power symbol node appears on a supply net |
| `decoupling.cap_missing` | warning | A capacitor has fewer than two connected nets |
| `decoupling.cap_not_near_pin` | warning | Bypass capacitor is farther than `near_pin_mm` from an IC supply pad |
| `decoupling.shared_capacitor` | warning | One bypass-cap rail feeds more than one IC supply |
| `decoupling.missing_bulk_capacitor` | warning | Bypassed rail has consumers but no capacitor above 1 uF |
| `parity.footprint_mismatch` | error/warning | Missing, extra, or differing footprint references |
| `parity.pin_missing` | error | Netlist pin has no matching PCB pad number |
| `parity.net_mismatch` | warning | Schematic net is absent from PCB or PCB net is extra. KiCad auto-generated names (`Net-(…)`, `unconnected-…`) and the unnamed PCB net 0 are skipped in both directions — they are per-view identifiers, not user labels |
| `si.stub_detected` | warning | Copper endpoint has one segment and no pad/via within 0.01 mm |
| `si.uncontrolled_layer_change` | error | Same-point layers change without a covering via |
| `manufacturing.unusual_drill` | warning/error | Missing, non-finite, or out-of-range drill |
| `manufacturing.board_outline_not_closed` | error | Edge.Cuts is not a single closed vertex cycle |
| `manufacturing.missing_courtyard` | warning | Placed footprint has no `.CrtYd` geometry |
| `layout.track_width_below_target` | warning/error | Segment width is below the project, request, or 0.2 mm default |

Power source classification depends on netlist pin types, not textual rail
names alone. SI rules are geometric and do not infer stackup impedance,
return paths, or signal rise times. They complement ERC/DRC and are not
substitutes for KiCad validation.

## `kicad_cli_version`

No arguments. Returns `exitCode`, `version`, and `stderr` from
`kicad-cli --version`. Raises a tool error when `kicad-cli` cannot be found.

## `list_kicad_projects`

No arguments. Recursively lists `.kicad_pro` files below `KICAD_WORKSPACE`.
Each item has `path` and `name`. `.git` and `node_modules` trees are skipped.

## `inspect_project`

```json
{"project": "relative/path/design.kicad_pro"}
```

Returns the selected project path and related `.kicad_pro`, `.kicad_sch`,
`.kicad_pcb`, and `.kicad_prl` files with their relative paths and byte sizes.

## `project_summary`

```json
{"project": "relative/path/design.kicad_pro"}
```

Returns file count/bytes, sorted project JSON `metaKeys`, and
`boardPresent`/`schematicPresent`. Invalid project JSON is a tool error.

## `read_schematic`

```json
{"project": "relative/path/design.kicad_pro"}
```

Parses the root schematic. `data` contains metadata, `symbols` with properties
and placed-pin UUIDs, labels, wires, and `sheets` with their file references and
sheet pins. Embedded `lib_symbols` definitions are intentionally omitted.

## `read_hierarchy`

```json
{"project": "relative/path/design.kicad_pro"}
```

Follows `Sheetfile` references inside the workspace and returns root-first
`nodes`, hierarchical labels, sheet pins, path names, and UUID paths. Missing
or invalid child sheets are surfaced as warnings instead of being treated as a
complete hierarchy. Cycles are detected and skipped; nesting is bounded.

## `read_buses`

```json
{"project": "relative/path/design.kicad_pro"}
```

Returns bus polylines, matched range labels such as `D[1..0]`, and bus-entry
geometry. `busPoint` is the bus-side endpoint stored in `bus_entry.at`;
`wirePoint` is derived by adding the `size` vector. The fixture expectation is
that an entry endpoint must land exactly on a wire connection point.

## `read_netlist`

```json
{"project": "relative/path/design.kicad_pro"}
```

Runs
`kicad-cli sch export netlist --format kicadsexpr` into a private temporary
directory, parses the export, and deletes the directory. `data` contains the
fixed command, design sheets, components and fields, libraries, nets, and node
references. Requires KiCad 10-compatible CLI export flags. The source design is
not modified.

## `read_bom`

```json
{"project": "relative/path/design.kicad_pro"}
```

Runs `kicad-cli sch export bom` with the default fields
`Reference,Value,Footprint,QUANTITY,DNP` into a private temporary directory and
returns normalized CSV columns and rows. Strict CSV parsing is used; a malformed
CLI export is a tool error.

## `read_pcb`

```json
{"project": "relative/path/design.kicad_pro"}
```

Parses the PCB. `data` contains metadata, the layer table, declared nets,
footprints and pads, tracks, vias, zones, and Edge.Cuts geometry. Footprint pad
positions are the local positions stored in the footprint node; board metrics
use global routing and outline geometry for extents.

## `read_board_metrics`

```json
{"project": "relative/path/design.kicad_pro"}
```

Returns board size from Edge.Cuts when available, overall parsed geometry
extents, copper-layer count, total and per-layer track length, zone polygon
area, board thickness, and object/pad counts. Units are millimetres.

## `read_layer_stackup`

```json
{"project": "relative/path/design.kicad_pro"}
```

Reads `setup.stackup` when present. If no stackup is embedded, it derives an
ordered layer list from the PCB layer table, sets `confidence` to `heuristic`,
and emits a warning. Callers should not treat the derived list as physical
dielectric/copper thickness data.

## `read_zones`

```json
{"project": "relative/path/design.kicad_pro"}
```

Returns zone layer(s), net, UUID, polygons, bounding boxes, and polygon areas in
square millimetres. Zone fill geometry is not calculated.

## `read_vias`

```json
{"project": "relative/path/design.kicad_pro"}
```

Returns via position, size, drill, layer pair, net, UUID, and type, plus counts
grouped by type, net, and layer pair. When no explicit type is stored, the
default is `through`.

## `run_kicad_cli_check`

```json
{"project": "relative/path/design.kicad_pro", "check": "sch"}
```

`check` must be `sch` (ERC) or `pcb` (DRC), defaulting to `sch`. The command
includes `--format json`, `--severity-all`, and `--exit-code-violations`.
KiCad writes the report to a private temporary file, which is parsed and deleted.

`data.issues` normalizes three report families: sheet-scoped `violations`, and
board-level `unconnected_items` / `schematic_parity`. Each issue has a normalized
severity (`error`, `warning`, `info`, or `excluded`), the original KiCad type as
`ruleId` when present, a stable hash fallback, a message, items, and context.
`passed` is true only for CLI exit code 0; a nonzero
`--exit-code-violations` exit means findings were emitted.

Position values in issues are millimetres. DRC positions are used as emitted.
KiCad 10.0.6 ERC positions labeled mm are observed to be two decimal orders
smaller than schematic mm and are normalized; the result emits a warning so this
compatibility behaviour remains explicit.

The timeout is configurable through `KICAD_CLI_CHECK_TIMEOUT` (default 120
seconds, hard maximum 3600). Bounded raw stdout/stderr remain in `data.raw`.
The source design is not edited, although KiCad may create or update project
metadata according to its installed version and configuration.

## `analyze_power_rails`

```json
{"project": "relative/path/design.kicad_pro", "rails": ["VCC"]}
```

`rails` is optional. Omit it to review recognized positive supply names;
ground-only nets are treated as return paths rather than powered rails.
Requires a netlist export. Returns rail names, source/consumer objects, and
power findings.

## `check_decoupling`

```json
{"project": "relative/path/design.kicad_pro", "near_pin_mm": 5.0}
```

Requires a netlist export and PCB. Capacitance is parsed from the value field;
capacitors above 1 uF are bulk storage, while smaller capacitors are checked
for IC locality and sharing. `near_pin_mm` must be greater than 0 and at most
100.

## `cross_probe`

```json
{"project": "relative/path/design.kicad_pro", "query": "CLK"}
```

`query` is one case-insensitive reference, value, net, or label. The result
groups exact matches by `schematic`, `netlist`, and `pcb`; an empty result is
not an error. Requires a netlist export.

## `compare_schematic_pcb`

```json
{"project": "relative/path/design.kicad_pro"}
```

Requires a netlist export and PCB. Footprint libraries are compared without
their `Library:` prefix, netlist pins are compared with pad numbers, and named
nets are compared with nets declared or referenced by PCB copper.

## `run_design_review`

```json
{
  "project": "relative/path/design.kicad_pro",
  "checks": ["power", "decoupling", "parity", "si", "manufacturing", "layout"],
  "rails": null,
  "near_pin_mm": 5.0,
  "minimum_track_width_mm": null
}
```

Omit `checks` to run all six analyzers. Values are validated before any
analysis runs. One shared parse/netlist context is used for all selected
checks; findings are sorted by severity, kind, rule ID, and message. ERC and
DRC remain separate tools by default so KiCad findings are not silently mixed
with heuristic review findings.

## `analyze_signal_integrity`

```json
{"project": "relative/path/design.kicad_pro"}
```

Parses tracks, vias, and pad geometry without KiCad CLI. A pad position is
matched within 0.01 mm to accommodate KiCad rotation/rounding. This tool does
not compute impedance or crosstalk.

## `analyze_board_density`

```json
{
  "project": "relative/path/design.kicad_pro",
  "cell_size_mm": 2.0,
  "high_density_ratio": 0.8
}
```

Returns board/grid metrics and occupied-cell counts. It emits no findings or
heuristic confidence because density is deterministic parsed geometry.
`cell_size_mm` is 0<value<=100; `high_density_ratio` is 0<value<=1.

## `check_fabrication_readiness`

```json
{"project": "relative/path/design.kicad_pro"}
```

Correct project spelling is `design.kicad_pro`. Runs manufacturing rules with a
netlist export and returns a checklist for board presence, outline closure,
footprint assignment, courtyards, and drill range. It does not inspect Gerber
or drill output files in this step.

## Write API

Five tools provide minimal, audited design edits. They are inert unless the
environment sets `KICAD_ENABLE_WRITES=1` exactly; any other value (or the
variable absent) makes every write tool raise immediately. The pipeline is:
lock, snapshot, source-hash check, plan, confirm token, execute,
post-validate, audit.

Supported operations (`op` in `preview_write`) are deliberately limited to
low-risk edits: `set_property` (symbol Reference/Value/field text),
`move_footprint`, `rotate_footprint`, and `auto_annotate` (fill unassigned
references; accepts an optional `params.prefix_map` object). Bulk
re-annotation of existing references, netlist edits, and re-routing are out of
scope.

### `preview_write`

```json
{"project": "demo.kicad_pro", "op": "set_property",
 "params": {"reference": "R1", "name": "Value", "value": "22k"}}
```

Dry-run only: no disk mutation. Returns per-file unified diffs under
`diffs` (keyed by workspace-relative path), the `touched` file list,
`preHashes`, `planHash`, `snapshotId` (deterministically `staged-<planHash
prefix>`), and a one-time `confirmToken`. The token is bound to the plan hash
and snapshot ID, expires after `KICAD_WRITE_TOKEN_TTL` seconds (default 900),
and is burned on use. The server holds the plan in memory; clients never
carry file content. Every preview appends a `preview` record to the audit log.

### `confirm_write`

```json
{"project": "demo.kicad_pro", "plan_hash": "...", "snapshot_id": "...",
 "confirm_token": "..."}
```

Executes the previewed plan. Under an exclusive per-project lock it verifies
the snapshot ID against the plan hash, re-verifies every input SHA-256,
snapshots the touched files, burns the token, validates the edited text
parses as S-expression, writes each file atomically, rereads to confirm
bytes, and appends the audit record. On any failure the touched files are
rolled back from the snapshot before the error is raised. A stale preview
(input changed after preview) is rejected as `source hash changed`; re-run
`preview_write`. Returns `applied: true`, the `snapshotId`, and per-file
`sha256`/`sizeBytes`.

### `rollback_snapshot`

```json
{"project": "demo.kicad_pro", "snapshot_id": "..."}
```

Restores every file captured in a snapshot byte-for-byte and appends a
`rollback` audit record. Returns the `restored` file list. Snapshots live
under `KICAD_SNAPSHOT_ROOT` (default `<workspace>/.kicad-mcp-snapshots`) so
they are never confused with design artifacts. The snapshot ID is validated
against traversal before any path is touched.

### `list_snapshots`

```json
{"project": "demo.kicad_pro"}
```

Lists snapshot manifests, newest first, optionally filtered by project.
`KICAD_MAX_SNAPSHOTS_LISTED` bounds the result (default 50).

### `get_write_audit`

```json
{"project": "demo.kicad_pro", "limit": 100}
```

Reads the append-only `audit.jsonl` log. Every record carries `stage`
(`preview`, `execute`, `rollback`), timestamp, project, plan hash, snapshot
ID, token fingerprint (never the raw token), per-file hashes, success flag,
and, on failure, the error and which files were rolled back.

## Path and data handling

The workspace root is read from `KICAD_WORKSPACE` at call time. Relative and
absolute user-supplied paths are resolved and checked before file access or
subprocess execution. Netlist and BOM exports use a private OS temporary
directory. Secrets are not read intentionally, but project files, exports, and
command output can contain proprietary design information; treat MCP transcripts
as sensitive.
