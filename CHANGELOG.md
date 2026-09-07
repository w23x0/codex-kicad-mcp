# Changelog

## 0.2.0 - 2026-09-07

- Calibrated review semantics against real KiCad 10.0.6 demo boards:
  `power.source_missing` now reports an assumed external input rail (a
  connector on the rail, a regulator feed driving `power_out` on another
  rail, or root-sheet-only `power_in` consumers) as a `warning` with the
  reason in the message instead of an error, and `parity.net_mismatch`
  skips KiCad's auto-generated `Net-(...)`/`unconnected-` names and the
  unnamed PCB net 0 in both directions. Verified on `complex_hierarchy`
  (0 errors), `kit-dev-coldfire-xilinx_5213` (0 errors), and
  `pic_programmer` (the passively charged VPP stays a deliberate error).
- Added real-project scan tests (`mcp/tests/test_real_projects.py`): the
  full tool surface runs against demo projects copied from the KiCad
  installation with the real `kicad-cli`, with an error-count ceiling as the
  false-positive tripwire (the drill-parse bug's 273 errors would fail it).
  Tests skip cleanly when KiCad is absent; `KICAD_DEMO_ROOT` overrides the
  demo directory.
- Added boundary tests for S-expression token/depth/file-size limits,
  unterminated quotes, unbalanced parens, symlink/NUL/empty path escapes,
  per-value `config.env_int` errors, `as_int`/`as_float` NaN/Infinity/bool
  edges, and kicad-cli timeout/missing-CLI failure modes
  (`mcp/tests/test_boundaries.py`).
- Added a real-export netlist snapshot fixture set
  (`mcp/tests/fixtures/real_projects/real_netlists.py`) so semantic
  regression tests cover the real CLI output shape without a runtime
  kicad-cli dependency.
- Fixed `artifact_file` reporting a missing artifact as a workspace escape;
  missing artifacts now raise `missing project artifact`.
- Fixed a missing `Path` import in the write pipeline type annotations.
- Removed unused variables flagged by lint in `pcb`, `hierarchy`, and
  `signal_integrity`; switched bus-pair iteration to `itertools.pairwise`.
- Added ruff (lint + format), mypy, and pytest-cov gates with explicit,
  commented per-module exemptions in `pyproject.toml`; bumped package
  metadata to v0.2.0 with URLs, keywords, classifiers, and authors.
- Extended CI: macOS single-point matrix (3.12), ruff lint job, mypy job,
  coverage job with artifact upload, CodeQL, a tag-gated PyPI release
  workflow (trusted publishing with a commented PYPI_TOKEN fallback), build
  artifact upload, Dependabot, and pre-commit.
- Added a Dockerfile (python3.12-slim + uv, stdio entrypoint) and extended
  `.gitignore` for KiCad reports and MCP host local state.
- Expanded `catalog/catalog.json`: the full 28-tool listing (kept aligned
  with the MCP listing by a drift-guard test), all 14 `KICAD_*` environment
  variables, and registration examples for Codex, Claude Desktop, VS Code,
  and Cursor in `registration.example.toml`.
- Englishized `docs/development-workflow.md`, `docs/github-research.md`, and
  `docs/maintenance.md`; documented the external-input-rail and
  auto-net-name rules in `docs/tool-reference.md`; added `docs/faq.md`,
  `docs/roadmap.md`, and `docs/architecture.svg`; refreshed the README with
  badges, the architecture diagram, and grouped tool tables; added
  `CODEOWNERS`.
- Added a `server.main()` smoke test.

## Unreleased

- Migrated to the MCP Python SDK 2.x: `mcp.server.fastmcp.FastMCP` became
  `mcp.server.mcpserver.MCPServer`, annotation fields switched to snake_case,
  resource template fields to `uri_template`/`mime_type`, and anticipated
  handler errors are now forwarded as `ToolError`/`ResourceError` so clients
  still see actionable messages instead of a generic crash string. The
  dependency bound widened to `mcp>=1.9,<3`; the full suite, lint, types,
  real-project scans, and build were re-verified on 2.x. Migration was
  forced by an accidentally merged Dependabot constraint bump (#2); the
  2.x API surface was probed before adapting the registration and tests.

- Normalized all response paths to workspace-relative forward slashes:
  `project.safe_relative`, a new `project.rel_posix` helper, and every
  remaining `relative_to` conversion now emit `as_posix()`, and one
  platform-dependent test expectation was fixed. MCP clients on another OS
  than the server now see `sub/power.kicad_sch` instead of
  `sub\power.kicad_sch` in hierarchy, resource, and inventory responses.
- Added the Step 7 MCP surface: nine project-scoped resources
  (`manifest`, suffix-allowlisted bounded `raw`, `schematic`, `pcb`,
  `hierarchy`, `netlist`, `bom`, `stackup`, and local-report `report`) under
  `codex-kicad://projects/{project}/…`, plus seven read-only prompts
  (`audit_project`, `generate_bom_report`, `review_power_distribution`,
  `review_signal_integrity`, `cross_probe_issue`, `prepare_fabrication`,
  `summarize_project_for_handoff`) that render structured task instructions.
  Resources reuse the read tools, including all size limits and workspace
  boundary checks; prompts never execute writes.
- Added the Step 8 opt-in write API: `preview_write` (dry-run diffs plus a
  plan-hash- and snapshot-bound, single-use, TTL confirm token),
  `confirm_write` (lock, snapshot, hash re-check, atomic apply,
  post-validate, audit), `rollback_snapshot`, `list_snapshots`, and
  `get_write_audit`. Writes require `KICAD_ENABLE_WRITES=1` exactly. The
  first-batch operations are `set_property`, `move_footprint`,
  `rotate_footprint`, and `auto_annotate`; every stage appends to an
  append-only JSON Lines audit log and failures roll back byte-for-byte from
  the snapshot.
- Added the Step 6 review layer with eight read-only analyzers:
  `analyze_power_rails`, `check_decoupling`, `cross_probe`,
  `compare_schematic_pcb`, `run_design_review`, `analyze_signal_integrity`,
  `analyze_board_density`, and `check_fabrication_readiness`. Findings share a
  provenance-bearing schema, severity/confidence labels, and a 17-rule first
  set covering power, decoupling, schematic/PCB parity, SI layout geometry,
  manufacturing readiness, and track width.
- Fixed KiCad netlist component references to read the nested `ref` child used
  by current CLI exports; the previous direct `comp` token produced `None`.
- Added the Step 4 data extraction layer: schematic and PCB readers now return
  the shared schema envelope, plus `read_hierarchy`, `read_buses`,
  `read_netlist`, `read_bom`, `read_board_metrics`, `read_layer_stackup`,
  `read_zones`, and `read_vias`. Netlist and BOM use bounded temporary
  `kicad-cli` exports; every response includes source path, SHA-256, byte size,
  counts, warnings, and confidence.
- Upgraded ERC/DRC to KiCad JSON reports with `--format json` and
  `--severity-all`. The normalizer handles `violations`,
  `unconnected_items`, and `schematic_parity`, normalizes severities and rule
  IDs, and preserves exit-code semantics through `--exit-code-violations`.
- Recorded the KiCad 10.0.6 ERC coordinate observation in structured warnings:
  report values labeled mm are two decimal orders smaller than schematic mm;
  DRC positions are already mm. Normalized diagnostic positions are millimetres.
- Added fixture-backed and malformed-input tests for every data tool, real
  KiCad 10 ERC/DRC golden snapshots (15 ERC findings and the controlled DRC
  track-dangling finding), and a 10-net netlist golden count.

- Added the deterministic demo fixture project (`mcp/tests/fixtures/demo`):
  a grid-aligned schematic (MCU, decoupling caps, resistor, power symbols,
  clock label, data bus with entries, hierarchical power sheet with a sheet
  pin, two intentionally dangling pins) and a 50x30 mm 2-layer board built
  through the bundled pcbnew API (real footprints, connected routes, one
  via, a GND zone, one intentionally dangling B.Cu stub). ERC/DRC run clean
  through kicad-cli against it, with a small controlled set of real
  findings. `scripts/generate_fixture.py` regenerates it (KiCad 10 bundled
  Python required); the repository ships the generated files so tests have
  no KiCad dependency.
- Split the 726-line server module into focused units: `config`
  (environment-backed limits), `sexpr` (bounded S-expression parser),
  `project` (workspace boundary and discovery), `schematic`/`pcb`
  (design-file extraction), and `kicad_cli` (subprocess adapter). The server
  module is now only the registration surface; tool behavior is unchanged.
- Fixed packaging so builds and editable installs work again: the package
  readme moved into `mcp/` and metadata now uses an SPDX license expression
  instead of paths outside the package directory.
- Unified `run_kicad_cli_check` with the shared CLI runner, bounded output,
  and a configurable `KICAD_CLI_CHECK_TIMEOUT` (default 120 s). The check now
  passes `--exit-code-violations`, so `passed` reflects ERC/DRC findings
  instead of always reporting success on a zero exit code.
- Removed unused imports from the server module.
- Merged MCP server and toolkit catalog into a single repository.
- Consolidated duplicated LICENSE, SECURITY.md, CONTRIBUTING.md, and CI into
  root-level files.
- Removed CampusCard references from the public project.

## 0.1.0 - 2026-09-06

- Initial read-only MCP server for project discovery, inventory, and ERC/DRC checks.
- Published MCP and skill inventory with catalog schema and validators.
- Added cross-platform CI for Python 3.10-3.13 on Ubuntu and Windows.
- Added deterministic tests for workspace safety, project metadata errors, and
  mocked KiCad CLI calls.
- Added the public tool reference with schemas, errors, and side-effect notes.
