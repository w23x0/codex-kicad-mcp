"""First-batch controlled edits: plan/execute pairs for low-risk operations.

Each edit type provides ``plan_*`` (pure text-in/text-out) functions that the
pipeline hashes and applies; nothing here touches the filesystem.  Supported
operations are deliberately limited to:

- ``set_property``     change or add a symbol property (Reference/Value/fields)
- ``move_footprint``   set a footprint's ``(at x y)`` position
- ``rotate_footprint`` set a footprint's ``(at x y angle)`` rotation
- ``auto_annotate``    fill in missing reference designators in sheet order
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from codex_kicad_mcp.sexpr import unquote
from codex_kicad_mcp.writes import textops

MAX_ANNOTATE_DESIGNATORS = 5000
_ANNOTATE_SKIP = re.compile(r"^(#\w*|.*\?.*)$")


class EditError(ValueError):
    """A user-facing error describing why an edit plan is not executable."""


@dataclass(frozen=True)
class FileEdit:
    path: str  # workspace-relative artifact path
    description: str
    transform: str  # full post-edit artifact text (hashed by the pipeline)


@dataclass
class Plan:
    project: str
    kind: str
    edits: list[FileEdit]
    warnings: list[str] = field(default_factory=list)

    @property
    def touched(self) -> list[str]:
        return sorted({edit.path for edit in self.edits})


def _symbol_reference(block: str) -> str | None:
    for hit in textops.find_child_properties(block):
        if hit.name == "Reference":
            return hit.value
    return None


# ---------------------------------------------------------------------------
# set_property
# ---------------------------------------------------------------------------


def plan_set_property(schematic_text: str, reference: str, name: str, value: str) -> tuple[str, str]:
    """Return (new_text, description) changing one symbol property by reference."""
    if not reference or not reference.strip():
        raise EditError("reference must not be empty")
    if not name or not name.strip():
        raise EditError("property name must not be empty")
    for start, end in textops.find_named_blocks(schematic_text, "symbol", parent_depth=1):
        block = schematic_text[start:end]
        if _symbol_reference(block) != reference:
            continue
        hits = textops.find_child_properties(block)
        hit = next((h for h in hits if h.name == name), None)
        if hit is None:
            new_block = textops.insert_property_line(block, name, value)
            description = f"add property {name}={value!r} to {reference}"
        else:
            new_block = textops.replace_property_value(block, hit, value)
            description = f"set property {name}={value!r} on {reference} (was {hit.value!r})"
        return schematic_text[:start] + new_block + schematic_text[end:], description
    raise EditError(f"symbol with Reference {reference!r} not found")


# ---------------------------------------------------------------------------
# move / rotate footprint
# ---------------------------------------------------------------------------


def _plan_footprint_at(
    pcb_text: str,
    reference: str,
    x: float | None,
    y: float | None,
    angle: float | None,
) -> tuple[str, str]:
    if not reference or not reference.strip():
        raise EditError("reference must not be empty")
    for start, end in textops.find_named_blocks(pcb_text, "footprint", parent_depth=1):
        block = pcb_text[start:end]
        if _symbol_reference(block) != reference:
            continue
        at = textops.at_node_atoms(block)
        if at is None:
            raise EditError(f"footprint {reference} has no (at ...) node")
        span, atoms = at
        current = [block[a:b] for a, b in atoms]
        if len(current) < 2:
            raise EditError(f"footprint {reference} (at ...) is missing coordinates")
        was_angle = current[2] if len(current) > 2 else "0"
        if angle is None:
            assert x is not None and y is not None
            values = [textops.fmt_number(x), textops.fmt_number(y)]
            if len(current) > 2:
                values.append(current[2])
            description = f"move {reference} from ({current[0]}, {current[1]}) to ({values[0]}, {values[1]})"
        else:
            values = [current[0], current[1], textops.fmt_number(angle)]
            description = f"rotate {reference} from {was_angle} to {values[2]} degrees"
        new_block = textops.replace_at_atoms(block, span, atoms, values)
        return pcb_text[:start] + new_block + pcb_text[end:], description
    raise EditError(f"footprint with Reference {reference!r} not found")


def plan_move_footprint(pcb_text: str, reference: str, x: float, y: float) -> tuple[str, str]:
    for value in (x, y):
        textops.fmt_number(value)  # validate finiteness/type up front
    return _plan_footprint_at(pcb_text, reference, x, y, None)


def plan_rotate_footprint(pcb_text: str, reference: str, angle: float) -> tuple[str, str]:
    if not -360.0 <= angle <= 360.0:
        raise EditError("angle must be within [-360, 360] degrees")
    return _plan_footprint_at(pcb_text, reference, None, None, angle)


# ---------------------------------------------------------------------------
# auto_annotate
# ---------------------------------------------------------------------------


@dataclass
class _AnnotateTarget:
    span: tuple[int, int]  # absolute schematic-text offsets of the symbol block
    value_start: int  # absolute offsets of the Reference value token
    value_end: int
    prefix: str


def _lib_id_of(block: str) -> str:
    # KiCad schematics carry the library id as a direct child node:
    # (symbol (lib_id "Device:R") ...).  Fall back to the first quoted token.
    for node_start, _node_end in textops.find_named_blocks(block, "lib_id", parent_depth=1):
        # Skip the opening paren; the value is the first string token after it.
        for token in textops.iter_tokens(block, node_start + 1):
            if token.kind == "string":
                return unquote(token.slice(block))
            if token.kind in {"open", "close"}:
                break
    tokens = [t for t in textops.iter_tokens(block) if t.kind in {"atom", "string"}]
    if len(tokens) >= 2 and tokens[1].kind == "string":
        return unquote(tokens[1].slice(block))
    return ""


def _prefix_for(lib_id: str, prefix_map: dict[str, str]) -> str:
    for key, prefix in prefix_map.items():
        if key and lib_id.startswith(key):
            return prefix if prefix.strip() else "REF"
    base = lib_id.rsplit(":", 1)[-1]
    prefix = re.sub(r"[^A-Za-z]", "", base)[:4]
    return prefix or "REF"


def plan_auto_annotate(
    schematic_text: str,
    prefix_map: dict[str, str] | None = None,
) -> tuple[str, str, int]:
    """Assign missing Reference designators in top-to-bottom sheet order.

    Returns (new_text, description, assigned_count).  Only symbols whose
    Reference is empty or contains ``?`` (KiCad's unassigned marker) are
    annotated; existing references are never rewritten.  Numeric suffixes
    continue from the highest number already used for each prefix.
    """
    targets: list[_AnnotateTarget] = []
    used: set[str] = set()
    highest: dict[str, int] = {}
    for start, end in textops.find_named_blocks(schematic_text, "symbol", parent_depth=1):
        block = schematic_text[start:end]
        ref_hit = None
        for hit in textops.find_child_properties(block):
            if hit.name == "Reference":
                ref_hit = hit
                break
        ref = ref_hit.value if ref_hit is not None else None
        if ref and not _ANNOTATE_SKIP.match(ref):
            used.add(ref)
            match = re.fullmatch(r"([A-Za-z]+)(\d+)", ref)
            if match:
                prefix = match.group(1)
                highest[prefix] = max(highest.get(prefix, 0), int(match.group(2)))
            continue
        if ref_hit is None:
            raise EditError("symbol without a Reference property; annotate manually")
        prefix = _prefix_for(_lib_id_of(block), prefix_map or {})
        # find_child_properties offsets are relative to the block slice; the
        # annotation pass rewrites the full text, so translate to absolute.
        targets.append(_AnnotateTarget((start, end), start + ref_hit.value_start, start + ref_hit.value_end, prefix))
    if not targets:
        return schematic_text, "no unannotated symbols found", 0
    if len(targets) > MAX_ANNOTATE_DESIGNATORS:
        raise EditError(f"too many unannotated symbols ({len(targets)}); annotate manually")
    assigned = 0
    result = schematic_text
    # Edit back-to-front so earlier offsets stay valid.
    for target in sorted(targets, key=lambda item: -item.span[0]):
        number = max(highest.get(target.prefix, 0), _next_counter(used, target.prefix)) + 1
        candidate = f"{target.prefix}{number}"
        while candidate in used:
            number += 1
            candidate = f"{target.prefix}{number}"
        used.add(candidate)
        highest[target.prefix] = number
        replacement = f'"{textops.sexpr_escape(candidate)}"'
        result = textops.replace_span(result, target.value_start, target.value_end, replacement)
        assigned += 1
    return result, f"assigned {assigned} reference designator(s)", assigned


def _next_counter(used: set[str], prefix: str) -> int:
    number = 0
    while f"{prefix}{number + 1}" in used:
        number += 1
    return number
