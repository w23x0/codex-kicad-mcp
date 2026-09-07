# Codex KiCad MCP server image.
#
# The server is read-first: it inspects KiCad projects under KICAD_WORKSPACE
# and shells out to kicad-cli when available.  Mount a workspace read-only at
# /workspace and, for full netlist/BOM/ERC/DRC support, a KiCad installation
# that provides kicad-cli on PATH (e.g. from the kicad/kicad image base).
FROM python:3.12-slim

# uv is the supported installer for this project (fast, lockfile-aware).
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app
COPY mcp/pyproject.toml mcp/uv.lock mcp/README.md ./mcp/
COPY mcp/src ./mcp/src
WORKDIR /app/mcp

# Install without the dev extras; the lockfile pins the runtime dependency.
RUN uv sync --frozen --no-dev

ENV KICAD_WORKSPACE=/workspace
# FastMCP speaks stdio; no ports are opened.
ENTRYPOINT ["uv", "run", "--no-dev", "codex-kicad-mcp"]
