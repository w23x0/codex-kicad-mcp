"""MCP prompts: structured task instructions for KiCad workflows.

Prompts render instruction text for the calling host; they never execute
writes or run checks themselves.  Each prompt documents which read-only tools
and resources to use, in which order, and how to interpret results so a
host-side agent can drive a complete workflow deterministically.
"""

from __future__ import annotations

from codex_kicad_mcp import project as project_module


def _project_line(project: str) -> str:
    try:
        inventory = project_module.inspect_project(project)
    except ValueError as exc:
        raise ValueError(f"project must be a workspace-relative .kicad_pro path: {exc}") from exc
    return f"Project: {inventory['project']}"


def audit_project(project: str) -> str:
    """Render the full design-audit task: inventory, checks, reviews, verdict."""
    line = _project_line(project)
    return f"""Design-audit instructions for `{project}`.
{line}

1. Inventory
   - Call `inspect_project` and `project_summary` for the project.
   - Read the manifest resource for the same project URI when the host supports resources.

2. Read-only structure review
   - `read_hierarchy` to map the sheet tree; flag sheets with no symbols or no labels.
   - `read_schematic` for symbol/value/footprint assignment gaps.
   - `read_pcb` plus `read_board_metrics` and `read_layer_stackup` for physical context.

3. Reviews (run all, then triage)
   - `run_design_review` with the default checks; re-run individual analyzers
     (`analyze_power_rails`, `check_decoupling`, `compare_schematic_pcb`,
     `analyze_signal_integrity`, `check_fabrication_readiness`) only where the
     combined report lacks detail you must quote.
   - If KiCad CLI is installed, run `run_kicad_cli_check` for both ERC and DRC.

4. Report format
   - Open with a verdict line: PASS / PASS WITH WARNINGS / FAIL.
   - Group findings by severity (error, warning, info), quoting rule IDs,
     references, and coordinates exactly as reported.
   - Finish with a prioritized fix list (max 10 items) referencing the exact
     tool or check that produced each finding.

All tools and resources are read-only; do not attempt to modify any project file.
"""


def generate_bom_report(project: str, purpose: str = "review") -> str:
    """Render a BOM-generation task with consistency checks and output format."""
    line = _project_line(project)
    return f"""BOM-report instructions for `{project}`.
{line}
Purpose: {purpose or "review"}

1. Call `read_bom` for the canonical export; note the `command` provenance.
2. Cross-check with `read_schematic`:
   - Every placed symbol must appear exactly once (multi-unit parts share one
     reference; DNP parts must still appear).
   - Flag symbols with empty Value or Footprint.
3. Cross-check with `read_pcb`:
   - Footprints on the board without a BOM row are ghost parts; report them.
4. Output format: a Markdown table (Reference, Value, Footprint, Quantity, DNP)
   followed by a short "Consistency notes" section listing every mismatch with
   references.  Do not invent part numbers or reorder rows beyond sorting by
   reference designator.
"""


def review_power_distribution(project: str, rails: str | None = None) -> str:
    """Render a power-tree review task over `analyze_power_rails` output."""
    line = _project_line(project)
    rail_arg = f"rails: [{rails}]" if rails else "no rails filter (auto-detect)"
    return f"""Power-distribution review instructions for `{project}`.
{line}
Rail filter: {rail_arg}

1. Run `analyze_power_rails` with the requested rails filter.
2. For every finding, verify context with:
   - `read_netlist` (which nodes share the rail) and `read_schematic`
     (which symbols drive it).
   - `check_decoupling` for the capacitors that feed each flagged IC.
3. Classify each finding: grounding-short (blocking), source conflict
   (blocking), single-source-load (risk), or info.  Explain the failure mode
   for the blocking classes in one sentence each.
4. Finish with concrete next actions: which symbol to fix, which rail to
   rename, or which capacitor to add/move, referencing exact references.

All analysis is read-only; do not edit any project file.
"""


def review_signal_integrity(project: str) -> str:
    """Render a signal-integrity review task over PCB routing analysis."""
    line = _project_line(project)
    return f"""Signal-integrity review instructions for `{project}`.
{line}

1. Call `read_layer_stackup` first: without a controlled-impedance stackup the
   SI conclusions are heuristic; say so explicitly in your report.
2. Run `analyze_signal_integrity` and group findings by net class:
   - Clock/crystal nets: report any layer change or stub, however small.
   - High-speed buses: group by bus; report aggregate stub lengths.
   - All other nets: report only the worst offenders (top 5).
3. Use `read_vias` to quantify via counts on flagged nets and
   `read_board_metrics` for layer count context.
4. End with a routing-fix list ordered by estimated effort (track edit, via
   removal, re-route on one layer).

Analysis is read-only; do not re-route anything yourself.
"""


def cross_probe_issue(project: str, query: str) -> str:
    """Render a cross-probing task that traces one design item across views."""
    line = _project_line(project)
    return f"""Cross-probe instructions for `{project}`.
{line}
Query: {query}

1. Call `cross_probe` with the query verbatim.
2. For every hit, report: view (schematic/PCB/netlist), reference, exact
   position or pin, and net context.  Preserve positions in mm as returned.
3. Compare schematic pad/pin presence with PCB pads for the same reference;
   call out any mismatch explicitly (missing footprint pad, unconnected pin,
   net name disagreement).
4. Finish with a single verdict line: consistent / inconsistent (with the
   one-line reason).
"""


def prepare_fabrication(project: str) -> str:
    """Render a fabrication-readiness task: fab checks plus ERC/DRC gating."""
    line = _project_line(project)
    return f"""Fabrication-preparation instructions for `{project}`.
{line}

1. Run `check_fabrication_readiness` and quote every finding verbatim.
2. Run `read_board_metrics` and `read_layer_stackup`; compare board thickness
   and copper count against the fab house defaults and flag assumptions you
   cannot verify from the project alone.
3. Gate on KiCad's own checks when the CLI is available:
   - `run_kicad_cli_check` for ERC and DRC.
   - DRC must be clean (zero error-severity issues) before fabrication.
4. Produce a go/no-go checklist: outline closed, all footprints assigned,
   no unconnected nets, no drill violations, stackup documented.
   Mark each row PASS/FAIL/N-A with the evidence you used.

Read-only throughout; do not generate Gerbers or modify the board.
"""


def summarize_project_for_handoff(project: str) -> str:
    """Render a handoff-summary task covering structure, stackup, and risks."""
    line = _project_line(project)
    return f"""Handoff-summary instructions for `{project}`.
{line}

Produce a handoff document with exactly these sections:

1. Identity: project name, sheet tree from `read_hierarchy`, and total size
   from `project_summary`.
2. Structure: top-level sheet purposes, symbol/footprint counts from
   `read_schematic` and `read_pcb`.
3. Electrical: rail list and source/consumer map from `analyze_power_rails`.
4. Physical: stackup summary from `read_layer_stackup`, board size from
   `read_board_metrics`, density hot spots from `analyze_board_density`.
5. Open risks: top 5 findings across all reviews, each with severity and the
   tool that produced it.
6. Verification status: which ERC/DRC checks were run (or that kicad-cli was
   unavailable) and their outcomes.

Keep the summary under 400 words; link claims to the tool that produced them.
"""
