"""Offset-aware S-expression text surgery for the write API.

The write API performs minimal, reviewable edits: it locates balanced node
spans with the same lexing rules as the bounded parser and rewrites only those
spans, so every byte outside an edit stays identical.  All helpers work on
decoded text without newline translation; callers own byte hashing and atomic
writes.
"""

from __future__ import annotations

import math
from collections.abc import Iterator
from typing import NamedTuple

from codex_kicad_mcp.sexpr import unquote


class Token(NamedTuple):
    kind: str  # "open", "close", "string", "atom"
    start: int
    end: int

    def slice(self, text: str) -> str:
        return text[self.start : self.end]


def iter_tokens(text: str, start: int = 0) -> Iterator[Token]:
    """Yield offset tokens using the same lexing rules as ``sexpr_tokens``.

    Comments (``;`` to end of line) are skipped without being yielded.  An
    unterminated quoted string raises ``ValueError`` like the parser does.
    """
    i = start
    n = len(text)
    while i < n:
        char = text[i]
        if char == ";":
            while i < n and text[i] not in "\r\n":
                i += 1
            continue
        if char.isspace():
            i += 1
            continue
        if char == "(":
            yield Token("open", i, i + 1)
            i += 1
            continue
        if char == ")":
            yield Token("close", i, i + 1)
            i += 1
            continue
        if char == '"':
            j = i + 1
            escaped = False
            while j < n:
                c = text[j]
                if escaped:
                    escaped = False
                elif c == "\\":
                    escaped = True
                elif c == '"':
                    break
                j += 1
            if j >= n:
                raise ValueError("unterminated quoted string in KiCad S-expression")
            yield Token("string", i, j + 1)
            i = j + 1
            continue
        j = i
        while j < n and not text[j].isspace() and text[j] not in '();"':
            j += 1
        yield Token("atom", i, j)
        i = j


def matching_paren(text: str, open_index: int) -> int:
    """Return the index just past the ``)`` that closes ``open_index``."""
    depth = 0
    for token in iter_tokens(text, open_index):
        if token.kind == "open":
            depth += 1
        elif token.kind == "close":
            depth -= 1
            if depth == 0:
                return token.end
    raise ValueError("unbalanced KiCad S-expression")


def find_named_blocks(text: str, name: str, *, parent_depth: int = 1) -> list[tuple[int, int]]:
    """Spans of balanced ``(name ...)`` blocks opened at ``parent_depth``.

    Depth counts open parens, so the file root opens at depth 0 and its direct
    children open at depth 1.  Nested same-name blocks (for example symbols
    inside ``lib_symbols``) sit deeper and are not matched.
    """
    results: list[tuple[int, int]] = []
    tokens = list(iter_tokens(text))
    depth = 0
    i = 0
    while i < len(tokens):
        token = tokens[i]
        if token.kind == "open":
            named = (
                depth == parent_depth
                and i + 1 < len(tokens)
                and tokens[i + 1].kind in {"atom", "string"}
                and unquote(tokens[i + 1].slice(text)) == name
            )
            if named:
                balance = 1
                j = i + 1
                while j < len(tokens) and balance:
                    if tokens[j].kind == "open":
                        balance += 1
                    elif tokens[j].kind == "close":
                        balance -= 1
                    j += 1
                if balance == 0:
                    results.append((token.start, tokens[j - 1].end))
                    # Skip past the consumed block; its open/close cancel out,
                    # so the enclosing depth is unchanged for the next sibling.
                    i = j
                    continue
            depth += 1
        elif token.kind == "close":
            depth -= 1
        i += 1
    return results


class PropertyHit(NamedTuple):
    """A direct-child ``(property "name" "value" ...)`` node inside a block."""

    name: str
    value: str | None
    node_start: int
    node_end: int
    value_start: int
    value_end: int


def find_child_properties(block: str) -> list[PropertyHit]:
    """Find direct-child property nodes of a block slice (parent_depth=1)."""
    hits: list[PropertyHit] = []
    for block_start, block_end in find_named_blocks(block, "property", parent_depth=1):
        # header: open, node name ("property"), key string, optional value
        header = list(iter_tokens(block, block_start))[:5]
        if len(header) < 3 or header[1].kind != "atom" or header[2].kind != "string":
            continue
        name = unquote(header[2].slice(block))
        value: str | None = None
        value_start = value_end = -1
        if len(header) > 3 and header[3].kind == "string":
            value = unquote(header[3].slice(block))
            value_start, value_end = header[3].start, header[3].end
        hits.append(PropertyHit(name, value, block_start, block_end, value_start, value_end))
    return hits


def find_child_node(block: str, name: str) -> tuple[int, int] | None:
    """Span of the first direct-child ``(name ...)`` node in a block slice."""
    spans = find_named_blocks(block, name, parent_depth=1)
    return spans[0] if spans else None


def at_node_atoms(block: str) -> tuple[tuple[int, int], list[tuple[int, int]]] | None:
    """Span and atom spans of the first direct-child ``(at ...)`` node.

    The returned atom spans exclude the node name itself, so callers replace
    exactly the coordinate values.
    """
    span = find_child_node(block, "at")
    if span is None:
        return None
    atoms: list[tuple[int, int]] = []
    name_seen = False
    for token in iter_tokens(block, span[0] + 1):
        if token.kind == "atom":
            if not name_seen:
                name_seen = True  # the node name ("at") is an atom too; skip it
                continue
            atoms.append((token.start, token.end))
        elif token.kind in {"open", "close"}:
            break
    return span, atoms


def _line_ending_after(text: str, index: int) -> str:
    if text.startswith("\r\n", index):
        return "\r\n"
    if index < len(text) and text[index] == "\n":
        return "\n"
    return "\n"


def _indent_of(text: str, node_start: int) -> str:
    line_start = text.rfind("\n", 0, node_start) + 1
    indent = text[line_start:node_start]
    return indent if indent.strip() == "" else ""


def replace_span(text: str, start: int, end: int, replacement: str) -> str:
    return text[:start] + replacement + text[end:]


def replace_property_value(block: str, hit: PropertyHit, new_value: str) -> str:
    """Rewrite only the value token of a property node inside a block slice."""
    replacement = f'"{sexpr_escape(new_value)}"'
    return replace_span(block, hit.value_start, hit.value_end, replacement)


def insert_property_line(block: str, new_name: str, new_value: str) -> str:
    """Insert a new direct-child property line after the last property node."""
    hits = find_child_properties(block)
    if not hits:
        raise ValueError("block has no existing property to anchor the insertion")
    last = hits[-1]
    insert_at = last.node_end
    while insert_at < len(block) and block[insert_at] not in "\r\n":
        insert_at += 1
    if insert_at < len(block) and block[insert_at] == "\r":
        insert_at += 1
    if insert_at < len(block) and block[insert_at] == "\n":
        insert_at += 1
    ending = _line_ending_after(block, last.node_end)
    indent = _indent_of(block, last.node_start)
    line = f'{indent}(property "{sexpr_escape(new_name)}" "{sexpr_escape(new_value)}")'
    return block[:insert_at] + line + ending + block[insert_at:]


def replace_at_atoms(block: str, span: tuple[int, int], atoms: list[tuple[int, int]], values: list[str]) -> str:
    """Rewrite the atom list of an ``(at ...)`` node, keeping other children."""
    if not atoms:
        replacement = "(" + " ".join(values) + ")"
        return replace_span(block, span[0], span[1], replacement)
    start, end = atoms[0][0], atoms[-1][1]
    return replace_span(block, start, end, " ".join(values))


def fmt_number(value: float) -> str:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ValueError("number must be a float")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("number must be finite")
    text = f"{number:.6f}".rstrip("0").rstrip(".") if "." in f"{number:.6f}" else f"{number:.6f}"
    if text in {"-0", ""}:
        text = "0"
    return text


def sexpr_escape(value: str) -> str:
    """Escape a Python string for a KiCad S-expression quoted token."""
    if not isinstance(value, str):
        raise ValueError("property text must be a string")
    if any(ord(char) < 0x20 for char in value):
        raise ValueError("control characters are not allowed in property text")
    return value.replace("\\", "\\\\").replace('"', '\\"')
