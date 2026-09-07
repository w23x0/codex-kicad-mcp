"""Bounded KiCad S-expression tokenizer, parser, and tree helpers.

KiCad files are mostly conventional S-expressions but can contain semicolon
comments and escaped quotes.  The parser is iterative and bounded so malformed
files cannot trigger unbounded recursion or memory growth in an MCP process.
"""

from __future__ import annotations

import math
from collections.abc import Iterator
from typing import Any

from codex_kicad_mcp import config


def sexpr_tokens(text: str, *, max_tokens: int | None = None) -> Iterator[str]:
    """Yield KiCad S-expression tokens, preserving quoted strings.

    KiCad files are mostly conventional S-expressions but can contain
    semicolon comments and escaped quotes.  The tokenizer rejects unterminated
    strings and enforces a token budget before a caller can build a large tree.
    """
    if not isinstance(text, str):
        raise ValueError("S-expression input must be text")
    budget = config.max_sexpr_tokens() if max_tokens is None else max_tokens
    if budget < 1:
        raise ValueError("max_tokens must be positive")
    token: list[str] = []
    quoted = False
    escaped = False
    comment = False
    emitted = 0

    def emit(value: str) -> str:
        nonlocal emitted
        emitted += 1
        if emitted > budget:
            raise ValueError(f"S-expression exceeds token limit ({budget})")
        return value

    for char in text:
        if comment:
            if char in "\r\n":
                comment = False
            continue
        if quoted:
            token.append(char)
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                quoted = False
                yield emit("".join(token))
                token.clear()
            continue
        if char == ";":
            if token:
                yield emit("".join(token))
                token.clear()
            comment = True
        elif char == '"':
            if token:
                yield emit("".join(token))
                token.clear()
            quoted = True
            token.append(char)
        elif char in "()":
            if token:
                yield emit("".join(token))
                token.clear()
            yield emit(char)
        elif char.isspace():
            if token:
                yield emit("".join(token))
                token.clear()
        else:
            token.append(char)
    if quoted:
        raise ValueError("unterminated quoted string in KiCad S-expression")
    if token:
        yield emit("".join(token))


def unquote(token: str) -> str:
    """Remove S-expression quotes and decode only KiCad's escaped delimiters."""
    if not (token.startswith('"') and token.endswith('"')):
        return token
    body = token[1:-1]
    result: list[str] = []
    escaped = False
    for char in body:
        if escaped:
            # Preserve unknown escapes verbatim; KiCad has historically used
            # a few non-JSON escapes in user text fields.
            result.append(char if char in {'"', "\\"} else "\\" + char)
            escaped = False
        elif char == "\\":
            escaped = True
        else:
            result.append(char)
    if escaped:  # defensive; tokenizer normally makes this impossible
        result.append("\\")
    return "".join(result)


def parse_sexpr(
    text: str,
    *,
    max_depth: int | None = None,
    max_tokens: int | None = None,
) -> list[Any]:
    """Parse KiCad's parenthesized format into nested Python lists.

    The parser is iterative and bounded so malformed files cannot trigger
    unbounded recursion or memory growth in an MCP process.
    """
    depth_limit = config.max_sexpr_depth() if max_depth is None else max_depth
    if depth_limit < 1:
        raise ValueError("max_depth must be positive")
    root: list[Any] = []
    stack: list[list[Any]] = [root]
    depth = 0
    for token in sexpr_tokens(text, max_tokens=max_tokens):
        if token == "(":
            depth += 1
            if depth > depth_limit:
                raise ValueError(f"S-expression exceeds depth limit ({depth_limit})")
            node: list[Any] = []
            stack[-1].append(node)
            stack.append(node)
        elif token == ")":
            if len(stack) == 1:
                raise ValueError("unbalanced KiCad S-expression")
            stack.pop()
            depth -= 1
        else:
            stack[-1].append(unquote(token))
    if len(stack) != 1:
        raise ValueError("unbalanced KiCad S-expression")
    return root


def children(node: Any, name: str) -> list[list[Any]]:
    if not isinstance(node, list):
        return []
    return [child for child in node[1:] if isinstance(child, list) and child and child[0] == name]


def first_child(node: Any, name: str) -> list[Any] | None:
    matches = children(node, name)
    return matches[0] if matches else None


def scalar_child(node: Any, name: str) -> Any:
    child = first_child(node, name)
    return child[1] if child and len(child) > 1 else None


def as_float(value: Any) -> float | None:
    try:
        parsed = float(value)
        return parsed if math.isfinite(parsed) else None
    except (TypeError, ValueError):
        return None


def as_int(value: Any) -> int | None:
    """Parse KiCad integer fields without accepting malformed suffixes."""
    if isinstance(value, bool):
        return None
    try:
        text = str(value)
        if not text or text in {"+", "-"}:
            return None
        signless = text[1:] if text[:1] in {"+", "-"} else text
        if not signless.isdigit():
            return None
        return int(text, 10)
    except (TypeError, ValueError):
        return None
