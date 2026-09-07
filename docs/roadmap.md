# Roadmap

Statuses: done / in progress / planned. The milestone numbering follows
`docs/development-workflow.md` phases; version numbers follow the CHANGELOG.

## v0.1 — read-only baseline (done)

- Workspace-confined project discovery, inventory, and summary
- Schematic/PCB/hierarchy/bus parsing with the shared envelope
- ERC/DRC through `kicad-cli` with normalized JSON reports
- Deterministic demo fixture and golden tests; cross-platform CI

## v0.2 — review layer, writes, calibration (in progress)

- Eight review analyzers (power, decoupling, parity, SI, manufacturing,
  layout, density, fabrication) with a provenance-bearing findings schema
- Opt-in controlled write API: preview/confirm/rollback with snapshots,
  locks, hash re-checks, and an append-only audit log
- Semantic calibration against real KiCad demo boards: external-input rails
  downgrade to warnings with a reason; auto-generated net names filtered from
  parity
- Real-project scan tests as the "fixture-green / real-board-red" tripwire
- Tooling: ruff + mypy + coverage gates, macOS CI point, CodeQL, release
  workflow, Dockerfile, pre-commit, Dependabot
- Catalog drift guard: `catalog.json` tools list kept identical to the MCP
  listing by a test

## v0.3 — planned

- Typed data layer under the analyzers so mypy per-module exemptions can be
  removed
- More write operations reviewed case by case (candidate: `set_netclass`,
  zone deletion with confirmation); each stays snapshot-backed and audited
- Review improvements: rail-name learning from power symbols, decoupling
  voltage-aware grouping, parity pin-map checks for multi-unit symbols
- Gerber/drill read-only inspection so `check_fabrication_readiness` can gate
  on delivered outputs, not just project state

## v1.0 — planned

- KiCad IPC API integration next to the CLI adapter (live sessions without
  spawning processes per tool call)
- Packaging: PyPI publication and the macOS/Linux smoke matrix running the
  installed wheel
- Compatibility matrix verified against KiCad 10 LTS and current stable
- Localized message handling reviewed with non-English KiCad installs

## Non-goals

- Editing copper, routing, or netlists through the write API
- Impedance/crosstalk computation in the SI rules (needs stackup physics the
  parsed design cannot provide)
- Running as a network service; the server stays stdio-local by design
