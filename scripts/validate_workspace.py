"""Validate the publishable metadata in the Codex-KiCad repository.

The default mode is dependency-free so it can run in a fresh Git checkout.
Use ``--full`` to run the MCP package tests as well.
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
MCP = ROOT / "mcp"
CATALOG = ROOT / "catalog"


class Validation:
    def __init__(self) -> None:
        self.errors: list[str] = []
        self.warnings: list[str] = []

    def error(self, message: str) -> None:
        self.errors.append(message)

    def warning(self, message: str) -> None:
        self.warnings.append(message)


def load_json(path: Path, result: Validation) -> dict[str, Any] | list[Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        result.error(f"{path.relative_to(ROOT)}: invalid JSON ({exc})")
        return None
    if not isinstance(value, (dict, list)):
        result.error(f"{path.relative_to(ROOT)}: top-level JSON value must be an object or array")
        return None
    return value


def decorated_tools(path: Path, result: Validation) -> set[str]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (OSError, SyntaxError) as exc:
        result.error(f"{path.relative_to(ROOT)}: cannot parse Python ({exc})")
        return set()
    names: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for decorator in node.decorator_list:
            if isinstance(decorator, ast.Call):
                decorator = decorator.func
            if isinstance(decorator, ast.Attribute) and decorator.attr == "tool":
                names.add(node.name)
    return names


def check_structure(result: Validation) -> None:
    required_root = ["README.md", "LICENSE", "SECURITY.md", "CONTRIBUTING.md", "CHANGELOG.md"]
    for name in required_root:
        if not (ROOT / name).is_file():
            result.error(f"{name} is missing")

    required_mcp = ["pyproject.toml", "src/codex_kicad_mcp/server.py"]
    for name in required_mcp:
        if not (MCP / name).is_file():
            result.error(f"mcp/{name} is missing")

    required_catalog = ["catalog.json", "catalog.schema.json", "registration.example.toml"]
    for name in required_catalog:
        if not (CATALOG / name).is_file():
            result.error(f"catalog/{name} is missing")


def check_catalog(result: Validation) -> None:
    catalog = load_json(CATALOG / "catalog.json", result)
    if not isinstance(catalog, dict):
        return
    if catalog.get("schemaVersion") != 1:
        result.error("catalog.json: unsupported schemaVersion")
    for key in ("mcps", "skills"):
        entries = catalog.get(key)
        if not isinstance(entries, list):
            result.error(f"catalog.json: {key} must be a list")
            continue
        ids = [item.get("id") for item in entries if isinstance(item, dict)]
        if len(ids) != len(set(ids)):
            result.error(f"catalog.json: duplicate {key} id")

    source_tools = decorated_tools(MCP / "src" / "codex_kicad_mcp" / "server.py", result)
    mcp_entries = catalog.get("mcps") or []
    for entry in mcp_entries:
        if not isinstance(entry, dict):
            continue
        tool_list = entry.get("tools")
        if isinstance(tool_list, list):
            for name in sorted(source_tools - set(tool_list)):
                result.error(f"MCP tool {name!r} is missing from catalog entry {entry.get('id', '?')}")


def check_sensitive_metadata(result: Validation) -> None:
    candidates = [
        CATALOG / "catalog.json",
        CATALOG / "registration.example.toml",
    ]
    machine_path = re.compile(r"(?:[A-Za-z]:[\\/](?:Users|ホーム|home)[\\/]|/home/|/Users/)", re.IGNORECASE)
    secret_key = re.compile(r"(?:api[_-]?key|api[_-]?secret|access[_-]?token|private[_-]?key)", re.IGNORECASE)
    for path in candidates:
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        if machine_path.search(text):
            result.error(f"{path.relative_to(ROOT)} contains a machine-specific absolute path")
        if secret_key.search(text):
            result.error(f"{path.relative_to(ROOT)} contains a credential-like key name")


def run_full_tests(result: Validation) -> None:
    env = os.environ.copy()
    if shutil.which("uv"):
        command = ["uv", "run", "--project", str(MCP), "pytest", "-q"]
    else:
        src = str(MCP / "src")
        env["PYTHONPATH"] = src + os.pathsep + env.get("PYTHONPATH", "")
        command = [sys.executable, "-m", "pytest", "-q"]
    completed = subprocess.run(
        command,
        cwd=MCP,
        env=env,
        text=True,
        capture_output=True,
        check=False,
        timeout=180,
    )
    if completed.returncode:
        result.error("MCP test suite failed:\n" + (completed.stdout + completed.stderr).strip())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--full", action="store_true", help="also run the MCP pytest suite")
    args = parser.parse_args()
    result = Validation()
    check_structure(result)
    check_catalog(result)
    check_sensitive_metadata(result)
    if args.full:
        run_full_tests(result)
    for warning in result.warnings:
        print(f"warning: {warning}")
    for error in result.errors:
        print(f"error: {error}")
    if result.errors:
        print(f"workspace validation failed ({len(result.errors)} error(s))")
        return 1
    print("workspace validation passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
