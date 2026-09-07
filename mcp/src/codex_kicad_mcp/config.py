"""Environment-backed configuration for the MCP server.

Every limit is read from the environment at call time so hosts can configure a
long-lived MCP process between requests; invalid values raise ``ValueError``
instead of being clamped silently.
"""

from __future__ import annotations

import os
from typing import Any

_DEFAULT_MAX_FILE_BYTES = 32 * 1024 * 1024
_DEFAULT_MAX_SEXPR_TOKENS = 1_000_000
_DEFAULT_MAX_SEXPR_DEPTH = 512
_DEFAULT_MAX_RESULT_ITEMS = 100_000
_DEFAULT_MAX_CLI_OUTPUT_BYTES = 1 * 1024 * 1024


def env_int(
    name: str,
    default: int,
    *,
    minimum: int = 1,
    maximum: int | None = None,
) -> int:
    """Read a bounded positive integer from the environment.

    Configuration errors are reported as ``ValueError`` instead of silently
    accepting an unsafe value.  The helper is intentionally evaluated at call
    time so hosts can configure a long-lived MCP process before each request.
    """
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = int(raw, 10)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if value < minimum or (maximum is not None and value > maximum):
        bound = f" between {minimum} and {maximum}" if maximum is not None else f" >= {minimum}"
        raise ValueError(f"{name} must be{bound}")
    return value


def cli_timeout(name: str, default: int, *, maximum: int) -> int:
    return env_int(name, default, maximum=maximum)


def max_file_bytes() -> int:
    return env_int("KICAD_MAX_FILE_BYTES", _DEFAULT_MAX_FILE_BYTES, maximum=512 * 1024 * 1024)


def max_sexpr_tokens() -> int:
    return env_int("KICAD_MAX_SEXPR_TOKENS", _DEFAULT_MAX_SEXPR_TOKENS, maximum=10_000_000)


def max_sexpr_depth() -> int:
    return env_int("KICAD_MAX_SEXPR_DEPTH", _DEFAULT_MAX_SEXPR_DEPTH, maximum=10_000)


def max_result_items() -> int:
    return env_int("KICAD_MAX_RESULT_ITEMS", _DEFAULT_MAX_RESULT_ITEMS, maximum=1_000_000)


def max_cli_output_bytes() -> int:
    return env_int("KICAD_MAX_CLI_OUTPUT_BYTES", _DEFAULT_MAX_CLI_OUTPUT_BYTES, maximum=64 * 1024 * 1024)


def bounded_append(items: list[Any], item: Any, label: str) -> None:
    """Append an extracted item while enforcing a response-size guardrail."""
    if len(items) >= max_result_items():
        raise ValueError(f"{label} exceeds the configured item limit")
    items.append(item)
