# Development Workflow

This project provides a KiCad MCP that is dependable inside Codex: clear
installation, discoverable tools, verifiable outputs, controlled writes, and
traceable version changes.

## Product Boundaries

### Target Users

- Hardware engineers using Codex to assist schematic and PCB design
- KiCad users who need automated checks, analysis, and report generation
- Developers who run an MCP locally and keep control of their design files

### Core Principles

1. Reads come first; every write must be explicitly confirmed and support
   snapshots or rollback.
2. Tools return structured results while preserving KiCad's raw output and
   exit codes.
3. Every tool has documented inputs, outputs, preconditions, permissions, and
   failure behaviour.
4. Version compatibility, example projects, and automated tests ship with the
   code.
5. The MCP owns tool connectivity; the Codex skill owns workflow and
   engineering judgement.

## Phased Delivery

### Phase 0: Baseline (done)

Deliverables: installable Python package, stdio launch, workspace confinement,
project discovery, project inventory, ERC/DRC invocation, unit tests, CI.

Exit criteria: a new user can install per the README and see the server in
`codex mcp list`; CI passes on Python 3.10-3.13.

### Phase 1: Read-only project understanding (done)

Deliverables: KiCad version detection, project summary, schematic symbol/net
reading, PCB layer/footprint/net/outline reading, structured ERC/DRC reports.

Exit criteria: every tool has schema documentation and test fixtures; at least
one public example project completes the "discover -> summarize -> check ->
report" flow.

### Phase 2: Design review (done)

Deliverables: read-only review tools for power-integrity heuristics,
unconnected pins, missing footprints, net gaps, outline, and rule anomalies;
results carry severity and location.

Exit criteria: review results trace to files, objects, and line/coordinates;
known false-positive boundaries are documented; heuristic conclusions are
never presented as ERC/DRC results.

### Phase 3: Controlled writes (done)

Deliverables: snapshot creation, property/annotation edits, small-granularity
placement and movement; dry-run by default; explicit confirm before apply.

Exit criteria: before/after snapshots are comparable, failures recover
automatically, every operation has an audit log and rollback test, and nothing
lands on disk without confirmation.

### Phase 4: Manufacturing and release (in progress)

Deliverables: BOM, Gerber, drill, and assembly outputs; pre-fabrication
reports; versioned examples; cross-platform installers or a stable launch
command.

Exit criteria: the example project reproduces from checks to manufacturing
outputs; release packages install in a clean environment; CHANGELOG and the
compatibility matrix stay in sync.

## Delivery Loop per Feature

1. Write the requirement: user task, KiCad version, input files, output
   schema, and side effects.
2. Design the interface: MCP tool name, parameters, error types, permission
   level.
3. Build fixtures: a minimal KiCad project or sanitized fixture; never depend
   on files from a developer's machine.
4. Implement the adapter: prefer KiCad IPC or the official CLI; never
   hand-modify KiCad S-expressions outside the audited write pipeline.
5. Test: unit tests, tests without KiCad installed, and real-KiCad integration
   tests are marked separately. The real-project scan tests
   (`test_real_projects.py`) are the regression insurance against
   "fixtures green, real board red" failures such as the drill-parse bug that
   produced 273 false errors.
6. Document and release: update README, tool reference, compatibility matrix,
   and CHANGELOG.
7. Merge gate: CI green, no secrets, no path escapes, write operations carry
   rollback proof.

## Release Gate

All of the following must hold before a release:

- `pytest`, package install, and JSON validation pass
- KiCad integration tests on supported versions have explicit results
- The README executes cleanly on a fresh machine
- Every tool's documentation includes side effects and error handling
- Security policy, license, changelog, and compatibility matrix are updated
- The release version matches `pyproject.toml`, CHANGELOG, and docs
