"""Validate the toolkit catalog with only Python's standard library.

The toolkit is intentionally metadata-only, so CI should not require a third-party
JSON-schema package or any EDA installation.  This validator checks the stable
contract that contributors need to preserve and gives actionable errors for
portable-path and verification mistakes.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date
from pathlib import Path
from typing import Any


ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
STATUSES = {"registered", "direct-verified", "available", "installed", "needs-review", "planned"}
RESULTS = {"pass", "partial", "not-registered", "not-run", "fail"}
FORBIDDEN_PATH_RE = re.compile(
    r"(?:^|[\\/])(?:\.env(?:\.|$)|auth[^\\/]*\.json$)|(?:token|secret|password|private[_-]?key)",
    re.IGNORECASE,
)
ABSOLUTE_PATH_RE = re.compile(r"^(?:[A-Za-z]:[\\/]|[\\/]{1,2}|~(?:[\\/]|$))")


class CatalogError(ValueError):
    """A user-facing catalog validation error."""


def _require(mapping: dict[str, Any], key: str, context: str) -> Any:
    if key not in mapping:
        raise CatalogError(f"{context}: missing required field '{key}'")
    return mapping[key]


def _string(value: Any, context: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise CatalogError(f"{context}: expected a non-empty string")
    return value


def _date(value: Any, context: str) -> str:
    text = _string(value, context)
    if not DATE_RE.fullmatch(text):
        raise CatalogError(f"{context}: expected YYYY-MM-DD, got {text!r}")
    try:
        date.fromisoformat(text)
    except ValueError as exc:
        raise CatalogError(f"{context}: invalid calendar date {text!r}") from exc
    return text


def _id(value: Any, context: str) -> str:
    text = _string(value, context)
    if not ID_RE.fullmatch(text):
        raise CatalogError(f"{context}: id must match {ID_RE.pattern!r}")
    return text


def _list(value: Any, context: str, *, non_empty: bool = False) -> list[Any]:
    if not isinstance(value, list) or (non_empty and not value):
        suffix = " and contain at least one item" if non_empty else ""
        raise CatalogError(f"{context}: expected a list{suffix}")
    return value


def _portable_path(value: Any, context: str) -> None:
    text = _string(value, context)
    if ABSOLUTE_PATH_RE.search(text):
        raise CatalogError(f"{context}: absolute paths are not portable: {text!r}")
    if FORBIDDEN_PATH_RE.search(text):
        raise CatalogError(f"{context}: path appears to reference a secret or local credential: {text!r}")


def _verification(value: Any, context: str) -> None:
    if not isinstance(value, dict):
        raise CatalogError(f"{context}: expected an object")
    _date(_require(value, "lastChecked", context), f"{context}.lastChecked")
    result = _string(_require(value, "result", context), f"{context}.result")
    if result not in RESULTS:
        raise CatalogError(f"{context}.result: unsupported result {result!r}")
    commands = _list(_require(value, "commands", context), f"{context}.commands", non_empty=True)
    for index, command in enumerate(commands):
        _string(command, f"{context}.commands[{index}]")
    _string(_require(value, "observed", context), f"{context}.observed")


def _permissions(value: Any, context: str) -> None:
    if not isinstance(value, dict):
        raise CatalogError(f"{context}: expected an object")
    for key in ("read", "write", "network", "subprocess"):
        item = _require(value, key, context)
        if not isinstance(item, bool):
            raise CatalogError(f"{context}.{key}: expected true or false")


def _entry(value: Any, context: str, *, mcp: bool) -> str:
    if not isinstance(value, dict):
        raise CatalogError(f"{context}: expected an object")
    entry_id = _id(_require(value, "id", context), f"{context}.id")
    for key in ("displayName", "purpose", "source"):
        _string(_require(value, key, context), f"{context}.{key}")
    _portable_path(value["source"], f"{context}.source")
    status = _string(_require(value, "status", context), f"{context}.status")
    if status not in STATUSES:
        raise CatalogError(f"{context}.status: unsupported status {status!r}")
    _verification(_require(value, "verification", context), f"{context}.verification")
    if mcp:
        for key in ("entrypoint", "config", "transport", "capabilities", "permissions", "risk"):
            _require(value, key, context)
        _portable_path(value["entrypoint"], f"{context}.entrypoint")
        _portable_path(value["config"], f"{context}.config")
        transport = _string(value["transport"], f"{context}.transport")
        if transport not in {"stdio", "http", "unknown"}:
            raise CatalogError(f"{context}.transport: unsupported transport {transport!r}")
        capabilities = _list(value["capabilities"], f"{context}.capabilities")
        for index, capability in enumerate(capabilities):
            _string(capability, f"{context}.capabilities[{index}]")
        if "tools" in value:
            tool_re = re.compile(r"^[a-z][a-z0-9_]*$")
            for index, name in enumerate(_list(value["tools"], f"{context}.tools")):
                if not isinstance(name, str) or not tool_re.fullmatch(name):
                    raise CatalogError(f"{context}.tools[{index}]: expected a snake_case tool name")
            if len(set(value["tools"])) != len(value["tools"]):
                raise CatalogError(f"{context}.tools: duplicate tool name")
        if "environment" in value:
            env_re = re.compile(r"^KICAD_[A-Z_]+$")
            for index, name in enumerate(_list(value["environment"], f"{context}.environment")):
                if not isinstance(name, str) or not env_re.fullmatch(name):
                    raise CatalogError(f"{context}.environment[{index}]: expected a KICAD_* variable name")
            if len(set(value["environment"])) != len(value["environment"]):
                raise CatalogError(f"{context}.environment: duplicate variable name")
        _permissions(value["permissions"], f"{context}.permissions")
        risk = _string(value["risk"], f"{context}.risk")
        if risk not in {"low", "moderate", "high", "unknown"}:
            raise CatalogError(f"{context}.risk: unsupported risk {risk!r}")
    else:
        _string(_require(value, "scope", context), f"{context}.scope")
    return entry_id


def validate_catalog(catalog_path: Path, schema_path: Path) -> None:
    try:
        catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise CatalogError(f"catalog not found: {catalog_path}") from exc
    except json.JSONDecodeError as exc:
        raise CatalogError(f"invalid JSON in {catalog_path}: {exc}") from exc
    try:
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise CatalogError(f"schema not found: {schema_path}") from exc
    except json.JSONDecodeError as exc:
        raise CatalogError(f"invalid JSON in {schema_path}: {exc}") from exc

    if not isinstance(catalog, dict):
        raise CatalogError("catalog root must be an object")
    if not isinstance(schema, dict) or schema.get("$schema") is None:
        raise CatalogError("catalog schema must be a JSON Schema document")
    if _require(catalog, "$schema", "catalog") != "./catalog.schema.json":
        raise CatalogError("catalog.$schema must point to ./catalog.schema.json")
    if _require(catalog, "schemaVersion", "catalog") != 1:
        raise CatalogError("catalog.schemaVersion must be 1")
    for key in ("project", "purpose", "pathNote"):
        _string(_require(catalog, key, "catalog"), f"catalog.{key}")
    _date(_require(catalog, "updated", "catalog"), "catalog.updated")

    registration = _require(catalog, "codexRegistration", "catalog")
    if not isinstance(registration, dict):
        raise CatalogError("catalog.codexRegistration must be an object")
    _portable_path(_require(registration, "config", "catalog.codexRegistration"), "catalog.codexRegistration.config")
    registration_status = _string(_require(registration, "status", "catalog.codexRegistration"), "catalog.codexRegistration.status")
    if registration_status not in {"registered", "needs-review", "not-configured"}:
        raise CatalogError(f"catalog.codexRegistration.status: unsupported status {registration_status!r}")
    _date(_require(registration, "lastChecked", "catalog.codexRegistration"), "catalog.codexRegistration.lastChecked")
    listed = _list(_require(registration, "listedServers", "catalog.codexRegistration"), "catalog.codexRegistration.listedServers")
    expected = _list(_require(registration, "expectedServers", "catalog.codexRegistration"), "catalog.codexRegistration.expectedServers")
    for name in [*listed, *expected]:
        _id(name, "catalog.codexRegistration server")
    _string(_require(registration, "note", "catalog.codexRegistration"), "catalog.codexRegistration.note")
    if registration_status == "registered" and not set(expected).issubset(set(listed)):
        raise CatalogError("catalog.codexRegistration.status is registered but expected servers are missing")

    for key, is_mcp in (("mcps", True), ("skills", False)):
        entries = _list(_require(catalog, key, "catalog"), f"catalog.{key}", non_empty=True)
        ids: set[str] = set()
        for index, entry in enumerate(entries):
            entry_id = _entry(entry, f"catalog.{key}[{index}]", mcp=is_mcp)
            if entry_id in ids:
                raise CatalogError(f"duplicate {key} entry id: {entry_id}")
            ids.add(entry_id)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", type=Path, help="catalog JSON path (default: repository catalog.json)")
    parser.add_argument("--schema", type=Path, help="schema JSON path (default: repository catalog.schema.json)")
    args = parser.parse_args()
    repository = Path(__file__).resolve().parents[1]
    catalog_path = (args.catalog or repository / "catalog" / "catalog.json").resolve()
    schema_path = (args.schema or repository / "catalog" / "catalog.schema.json").resolve()
    try:
        validate_catalog(catalog_path, schema_path)
    except CatalogError as exc:
        print(f"catalog validation failed: {exc}", file=sys.stderr)
        return 1
    print(f"catalog validation passed: {catalog_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

