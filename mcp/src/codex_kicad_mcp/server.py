"""Codex KiCad MCP server.

This module is only the registration surface: it declares the MCP server
instance, the shared read-only tool annotations, and the registered tools.
Tool logic lives in focused modules for project discovery, S-expression
extractors, PCB analysis, CLI exports, and ERC/DRC normalization.
"""

from __future__ import annotations

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ResourceError, ToolError
from mcp.types import ToolAnnotations

from codex_kicad_mcp import (
    analysis,
    board,
    bom,
    hierarchy,
    kicad_cli,
    netlist,
    pcb,
    prompts,
    resources,
    schematic,
)
from codex_kicad_mcp import project as project_module
from codex_kicad_mcp.writes import pipeline as writes_pipeline

# Keep the public server deliberately read-only.  These annotations are exposed
# through MCP's ``tools/list`` response and let hosts make safer confirmation
# decisions without having to infer intent from a docstring.
_READ_ONLY = ToolAnnotations(
    read_only_hint=True,
    destructive_hint=False,
    idempotent_hint=True,
    open_world_hint=False,
)
_CLI_READ_ONLY = ToolAnnotations(
    read_only_hint=True,
    destructive_hint=False,
    idempotent_hint=True,
    open_world_hint=True,
)
_WRITE_MUTATING = ToolAnnotations(
    read_only_hint=False,
    destructive_hint=False,
    idempotent_hint=False,
    open_world_hint=False,
)


def _expected(tool_fn):
    """Wrap a handler so anticipated errors surface as MCP protocol errors.

    The SDK treats a bare ``ValueError``/``RuntimeError`` as a crash: the
    client sees only a generic "error executing tool" message.  Every error
    our tool functions raise on purpose carries an actionable message, so the
    adapters forward it verbatim through ``ToolError``/``ResourceError``
    (both supported on mcp 2.x; harmless wrappers on 1.x semantics).
    Unexpected exceptions (bugs) still crash loudly by design.
    """

    def tool_adapter(*args, **kwargs):
        try:
            return tool_fn(*args, **kwargs)
        except (ValueError, RuntimeError) as exc:
            raise ToolError(str(exc)) from exc

    return tool_adapter


def _expected_resource(resource_fn):
    # The parameter name must match the URI template's {project}; a generic
    # *args/**kwargs signature would break the SDK's URI-parameter binding.
    def resource_adapter(project: str):
        try:
            return resource_fn(project)
        except (ValueError, RuntimeError) as exc:
            raise ResourceError(str(exc)) from exc

    return resource_adapter


mcp = MCPServer(
    "Codex KiCad",
    instructions=(
        "Read-only KiCad project inspection and ERC/DRC checks. All project paths are confined to KICAD_WORKSPACE."
    ),
)

# Resources reuse the read-tool implementations behind stable project URIs.
# The project parameter is percent-encoded in ``resources.encode_project``
# because the SDK template matcher does not match across ``/``.
_URI_SCHEME = "codex-kicad"
_PROJECT = "{project}"
_RESOURCE_TEMPLATES = {
    "manifest": (_expected_resource(resources.manifest_resource), None, "Project manifest and file inventory."),
    "raw": (
        _expected_resource(resources.raw_artifact),
        None,
        "Raw bytes of a project artifact (bounded, suffix allowlist).",
    ),
    "schematic": (
        _expected_resource(resources.schematic_resource),
        None,
        "Parsed schematic symbols, labels, wires, and sheets.",
    ),
    "pcb": (
        _expected_resource(resources.pcb_resource),
        None,
        "Parsed PCB layers, nets, footprints, tracks, and outline.",
    ),
    "hierarchy": (_expected_resource(resources.hierarchy_resource), None, "Parsed schematic sheet hierarchy."),
    "netlist": (
        _expected_resource(resources.netlist_resource),
        None,
        "Freshly exported KiCad netlist (requires kicad-cli).",
    ),
    "bom": (_expected_resource(resources.bom_resource), None, "Freshly exported BOM rows (requires kicad-cli)."),
    "stackup": (_expected_resource(resources.stackup_resource), None, "Parsed or derived board layer stackup."),
    "report": (_expected_resource(resources.report_resource), None, "Normalized local ERC/DRC report findings."),
}


def _register_resources() -> None:
    for name, (fn, _, description) in _RESOURCE_TEMPLATES.items():
        mime_type = resources.TEXT_MIME if name == "raw" else resources.SCHEMA_MIME
        mcp.resource(
            f"{_URI_SCHEME}://projects/{_PROJECT}/{name}",
            name=f"project_{name}",
            description=description,
            mime_type=mime_type,
        )(fn)


_register_resources()


@mcp.prompt(name="audit_project")
def audit_project_prompt(project: str) -> str:
    """Structured instructions for a full read-only design audit."""
    return prompts.audit_project(project)


@mcp.prompt(name="generate_bom_report")
def generate_bom_report_prompt(project: str, purpose: str = "review") -> str:
    """Structured instructions for a BOM export and consistency report."""
    return prompts.generate_bom_report(project, purpose)


@mcp.prompt(name="review_power_distribution")
def review_power_distribution_prompt(project: str, rails: str | None = None) -> str:
    """Structured instructions for a power-tree review."""
    return prompts.review_power_distribution(project, rails)


@mcp.prompt(name="review_signal_integrity")
def review_signal_integrity_prompt(project: str) -> str:
    """Structured instructions for a PCB signal-integrity review."""
    return prompts.review_signal_integrity(project)


@mcp.prompt(name="cross_probe_issue")
def cross_probe_issue_prompt(project: str, query: str) -> str:
    """Structured instructions for tracing one design item across views."""
    return prompts.cross_probe_issue(project, query)


@mcp.prompt(name="prepare_fabrication")
def prepare_fabrication_prompt(project: str) -> str:
    """Structured instructions for a fabrication go/no-go review."""
    return prompts.prepare_fabrication(project)


@mcp.prompt(name="summarize_project_for_handoff")
def summarize_project_for_handoff_prompt(project: str) -> str:
    """Structured instructions for a concise handoff summary."""
    return prompts.summarize_project_for_handoff(project)


@mcp.tool(annotations=_CLI_READ_ONLY)
def kicad_cli_version() -> dict[str, object]:
    """Return the installed kicad-cli version without touching project files."""
    return _expected(kicad_cli.kicad_cli_version)()


@mcp.tool(annotations=_READ_ONLY)
def list_kicad_projects() -> list[dict[str, str]]:
    """List KiCad project files under the configured workspace."""
    return _expected(project_module.list_kicad_projects)()


@mcp.tool(annotations=_READ_ONLY)
def inspect_project(project: str) -> dict[str, object]:
    """Return a read-only inventory of a KiCad project's related files."""
    return _expected(project_module.inspect_project)(project)


@mcp.tool(annotations=_READ_ONLY)
def project_summary(project: str) -> dict[str, object]:
    """Return safe metadata from a KiCad project JSON and related files."""
    return _expected(project_module.project_summary)(project)


@mcp.tool(annotations=_READ_ONLY)
def read_schematic(project: str) -> dict[str, object]:
    """Read schematic symbol instances, labels, wires, and sheet metadata."""
    return _expected(schematic.read_schematic)(project)


@mcp.tool(annotations=_READ_ONLY)
def read_hierarchy(project: str) -> dict[str, object]:
    """Read the schematic sheet hierarchy, sheet pins, and labels."""
    return _expected(hierarchy.read_hierarchy)(project)


@mcp.tool(annotations=_READ_ONLY)
def read_buses(project: str) -> dict[str, object]:
    """Read bus geometry, range labels, and bus entry endpoints."""
    return _expected(hierarchy.read_buses)(project)


@mcp.tool(annotations=_CLI_READ_ONLY)
def read_netlist(project: str) -> dict[str, object]:
    """Export a structured KiCad netlist through kicad-cli and parse it."""
    return _expected(netlist.read_netlist)(project)


@mcp.tool(annotations=_CLI_READ_ONLY)
def read_bom(project: str) -> dict[str, object]:
    """Export a BOM through kicad-cli and return normalized rows."""
    return _expected(bom.read_bom)(project)


@mcp.tool(annotations=_READ_ONLY)
def read_pcb(project: str) -> dict[str, object]:
    """Read PCB layers, nets, footprints, tracks, and board outline metadata."""
    return _expected(pcb.read_pcb)(project)


@mcp.tool(annotations=_READ_ONLY)
def read_board_metrics(project: str) -> dict[str, object]:
    """Read board size, copper totals, and object counts from the PCB."""
    return _expected(board.read_board_metrics)(project)


@mcp.tool(annotations=_READ_ONLY)
def read_layer_stackup(project: str) -> dict[str, object]:
    """Read the embedded stackup or derive a layer list when absent."""
    return _expected(board.read_layer_stackup)(project)


@mcp.tool(annotations=_READ_ONLY)
def read_zones(project: str) -> dict[str, object]:
    """Read copper zones, their polygons, areas, and nets."""
    return _expected(board.read_zones)(project)


@mcp.tool(annotations=_READ_ONLY)
def read_vias(project: str) -> dict[str, object]:
    """Read vias with position, drill, layers, and net metadata."""
    return _expected(board.read_vias)(project)


@mcp.tool(annotations=_CLI_READ_ONLY)
def run_kicad_cli_check(project: str, check: str = "sch") -> dict[str, object]:
    """Run a read-only KiCad CLI ERC/DRC check for a project."""
    return _expected(kicad_cli.run_kicad_cli_check)(project, check)


@mcp.tool(annotations=_CLI_READ_ONLY)
def analyze_power_rails(project: str, rails: list[str] | None = None) -> dict[str, object]:
    """Analyze supply-rail source, consumer, conflict, and ground-short risks."""
    return analysis.power.analyze_power_rails(project, rails)


@mcp.tool(annotations=_CLI_READ_ONLY)
def check_decoupling(project: str, near_pin_mm: float = 5.0) -> dict[str, object]:
    """Check capacitor connectivity, placement, sharing, and bulk coverage."""
    return analysis.decoupling.check_decoupling(project, near_pin_mm)


@mcp.tool(annotations=_CLI_READ_ONLY)
def cross_probe(project: str, query: str) -> dict[str, object]:
    """Correlate one reference, value, net, or label across schematic and PCB."""
    return analysis.cross_probe.cross_probe(project, query)


@mcp.tool(annotations=_CLI_READ_ONLY)
def compare_schematic_pcb(project: str) -> dict[str, object]:
    """Compare netlist components, pins, and nets with the PCB."""
    return analysis.parity.compare_schematic_pcb(project)


@mcp.tool(annotations=_CLI_READ_ONLY)
def run_design_review(
    project: str,
    checks: list[str] | None = None,
    rails: list[str] | None = None,
    near_pin_mm: float = 5.0,
    minimum_track_width_mm: float | None = None,
) -> dict[str, object]:
    """Run the selected power, parity, SI, manufacturing, and layout reviews."""
    return analysis.review.run_design_review(
        project,
        checks=checks,
        rails=rails,
        near_pin_mm=near_pin_mm,
        minimum_track_width_mm=minimum_track_width_mm,
    )


@mcp.tool(annotations=_READ_ONLY)
def analyze_signal_integrity(project: str) -> dict[str, object]:
    """Analyze PCB routes for uncontrolled layer changes and dangling stubs."""
    return analysis.signal_integrity.analyze_signal_integrity(project)


@mcp.tool(annotations=_READ_ONLY)
def analyze_board_density(
    project: str,
    cell_size_mm: float = 2.0,
    high_density_ratio: float = 0.8,
) -> dict[str, object]:
    """Measure object occupancy on a caller-configurable board grid."""
    return analysis.layout.analyze_board_density(project, cell_size_mm, high_density_ratio)


@mcp.tool(annotations=_READ_ONLY)
def check_fabrication_readiness(project: str) -> dict[str, object]:
    """Check board geometry, courtyards, drills, and footprint assignments."""
    return analysis.manufacturing.check_fabrication_readiness(project)


# Write API: explicit opt-in via KICAD_ENABLE_WRITES=1; every tool below is a
# thin shell over the snapshot-backed pipeline and fails fast when the opt-in
# flag is missing.


@mcp.tool(annotations=_WRITE_MUTATING)
def preview_write(project: str, op: str, params: dict[str, object] | None = None) -> dict[str, object]:
    """Dry-run a controlled edit and return diffs plus a confirm token."""
    return _expected(writes_pipeline.preview_write)(project, op, params)


@mcp.tool(annotations=_WRITE_MUTATING)
def confirm_write(project: str, plan_hash: str, snapshot_id: str, confirm_token: str) -> dict[str, object]:
    """Execute a previewed write under lock, snapshot, and validation."""
    return _expected(writes_pipeline.confirm_write)(project, plan_hash, snapshot_id, confirm_token)


@mcp.tool(annotations=_WRITE_MUTATING)
def rollback_snapshot(project: str, snapshot_id: str) -> dict[str, object]:
    """Restore every file captured in a write snapshot."""
    return _expected(writes_pipeline.rollback_snapshot)(project, snapshot_id)


@mcp.tool(annotations=_WRITE_MUTATING)
def list_snapshots(project: str | None = None) -> dict[str, object]:
    """List write snapshots, newest first, optionally per project."""
    return _expected(writes_pipeline.list_snapshots)(project)


@mcp.tool(annotations=_WRITE_MUTATING)
def get_write_audit(project: str | None = None, limit: int = 100) -> dict[str, object]:
    """Read the append-only write audit log (optionally per project)."""
    return _expected(writes_pipeline.get_write_audit)(project, limit=limit)


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
