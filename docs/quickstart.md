# Quick Start

This guide takes a clean machine from the Toolkit catalog to a verified,
read-only KiCad MCP session. The Toolkit itself is metadata and documentation;
the executable server is maintained in the sibling `Codex-KiCad/mcp` checkout or
in the upstream distribution you select.

## Prerequisites

- Codex with MCP support and the `codex` command available on `PATH`.
- Python 3.10 or newer and [`uv`](https://docs.astral.sh/uv/) (recommended).
- KiCad 8 or newer when invoking ERC/DRC; `kicad-cli` must be on `PATH`.
- A disposable or version-controlled directory containing at least one
  `.kicad_pro` project.

Confirm the host before changing files:

```powershell
codex mcp list
python --version
kicad-cli --version
```

`kicad-cli` is not needed for package installation or read-only parsing, but it
is required for the KiCad version and ERC/DRC tools.

## Install the local KiCad MCP

From the workspace that contains both directories:

```powershell
uv run --directory .\Codex-KiCad/mcp pytest -q
uv run --directory .\Codex-KiCad/mcp Codex-KiCad/mcp
```

The second command stays attached to stdio. Stop it with `Ctrl+C`; Codex normally
owns the process lifecycle. Set the workspace boundary before registering it:

```powershell
$env:KICAD_WORKSPACE = "C:/path/to/eda-workspace"
```

For macOS/Linux, use `./Codex-KiCad/mcp` and `export KICAD_WORKSPACE=...`.

## Register with Codex

Copy the KiCad block from [`../catalog/registration.example.toml`](../catalog/registration.example.toml)
into `${CODEX_HOME}/config.toml`, replacing both paths:

```toml
[mcp_servers.kicad]
command = "uv"
args = ["run", "--directory", "C:/path/to/Codex-KiCad/mcp", "Codex-KiCad/mcp"]
env = { KICAD_WORKSPACE = "C:/path/to/eda-workspace" }
```

Restart Codex and run:

```powershell
codex mcp list
```

The server must appear as `kicad` before asking Codex to invoke tools. If it does
not, check the config path, executable path, and inherited environment; do not
label the catalog entry `registered` until the host lists it.

## First safe task

Use a copy of a project and ask Codex to perform this sequence:

1. Discover `.kicad_pro` files below `KICAD_WORKSPACE`.
2. Inspect one project and summarize its schematic, PCB, and metadata files.
3. Run schematic ERC and PCB DRC separately.
4. Report exit codes, issue lines, and any report files created by KiCad.

The current server is read-first. It does not expose routing, library editing,
or arbitrary file writes. KiCad may still create a report during a check, so keep
the first run on a disposable copy and review the diff afterward.

## Record the result

From the Toolkit root, run:

```powershell
python scripts/validate_catalog.py
python scripts/check_links.py
```

Update [`../catalog/catalog.json`](../catalog/catalog.json) and [`CONTRIBUTING.md`](../CONTRIBUTING.md) with the date, versions, exact commands, and
observed result. A stale or failed registration is recorded as `needs-review`,
not silently treated as available.

## Troubleshooting

| Symptom | Check |
| --- | --- |
| `kicad` is absent from `codex mcp list` | Confirm `${CODEX_HOME}/config.toml`, restart Codex, and run the command from a clean shell. |
| No projects are discovered | `KICAD_WORKSPACE` must be an existing directory containing `.kicad_pro`; use paths relative to it. |
| `kicad-cli` cannot be found | Install KiCad and add its CLI directory to `PATH`, then restart Codex. |
| ERC/DRC creates unexpected files | Use a disposable copy, inspect the diff, and document the KiCad version and report path. |
| A command works manually but not in Codex | Compare the environment inherited by Codex with the shell (`PATH`, `KICAD_WORKSPACE`, and `uv` location). |

