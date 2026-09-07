# GitHub MCP Project Research

Research date: 2026-09-06. Star counts are approximations from query time and
change over time.

## Reference Projects

| Project | ~Stars | Practices worth adopting |
| --- | ---: | --- |
| [punkpeye/awesome-mcp-servers](https://github.com/punkpeye/awesome-mcp-servers) | 94k | Explains MCP first, then categorizes by client, tutorial, community, implementation, and framework; badges/legends lower the cost of reading a directory. |
| [modelcontextprotocol/servers](https://github.com/modelcontextprotocol/servers) | 90k | States clearly that "reference implementations" are not production solutions; lists SDKs, capability scope, and security warnings; archived entries carry migration pointers. |
| [github/github-mcp-server](https://github.com/github/github-mcp-server) | 32k | Shows use cases first; offers remote and local installation together; config examples grouped per host; policy, permissions, and authentication documented separately. |
| [PrefectHQ/fastmcp](https://github.com/PrefectHQ/fastmcp) | 27k | Minimal runnable example on the first screen; docs, versions, tests, and license entry points; emphasizes where the framework's abstraction boundary sits. |
| [mixelpixx/KiCAD-MCP-Server](https://github.com/mixelpixx/KiCAD-MCP-Server) | 2k | Organizes many tools by category; provides search; records version changes, compatibility, and migration notices; flags experimental features. |
| [lamaalrajih/kicad-mcp](https://github.com/lamaalrajih/kicad-mcp) | 500 | Directory covers prerequisites, installation, configuration, development, troubleshooting, and contribution; states KiCad, Python, and uv version requirements. |

## Common Patterns

High-quality projects usually provide:

1. A README first screen that says what problem the project solves, with a
   minimal runnable example.
2. Installation instructions with copyable config per OS or host client,
   rather than a single "configure it yourself".
3. Tools grouped by domain, with permissions, destructive operations, input
   limits, and failure behaviour documented.
4. Developer docs, troubleshooting, contribution guide, code of conduct, and
   license maintained separately.
5. CI, version badges, changelogs, or release pages as evidence of active
   maintenance.
6. An explicit distinction between "example / reference implementation" and
   "production ready", plus a recorded security-responsibility boundary.
7. A prominent replacement link at the top of the README when an upstream
   project migrates or is archived.

## Application to This Project

This repository has already adopted:

- A new-user quickstart (`docs/quickstart.md`) covering dependencies, MCP
  registration, verification, and a first KiCad task.
- A compatibility matrix under `docs/` recording Codex, KiCad, MCP, and skill
  versions.
- Per-entry tool classification, permission risk, input/output, and
  verification status in `catalog/catalog.json` — including the 28-tool
  listing that a consistency test keeps aligned with the MCP listing.
- GitHub Actions for tests (Ubuntu/Windows/macOS matrix), ruff lint, mypy,
  coverage, CodeQL, packaging, and a tag-gated PyPI release workflow.
- A changelog and release tags so catalog changes are traceable.
- SPDX license fields and links to the upstream security policy for
  third-party projects.

This research only references public GitHub READMEs and repository metadata;
stars measure popularity, not security, correctness, or production fitness.
