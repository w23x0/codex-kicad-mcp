# Catalog

This directory contains the MCP and skill registry. The structured source of
truth is [`catalog.json`](catalog.json), validated by
[`../scripts/validate_catalog.py`](../scripts/validate_catalog.py).

## Registration

Copy the relevant block from
[`registration.example.toml`](registration.example.toml) into
`${CODEX_HOME}/config.toml`, replacing paths. Restart Codex, then confirm with
`codex mcp list`.

Status conventions:

- `registered`: the current `codex mcp list` contains the server.
- `direct-verified`: the entrypoint started or passed its smoke test.
- `needs-review`: registration, version, or integration check must be repeated.
- `planned`: no verified entrypoint is available.
