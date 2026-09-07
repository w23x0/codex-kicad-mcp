# Release Process

Toolkit releases are metadata snapshots. They make the catalog, installation
examples, and compatibility claims reproducible; they do not bundle KiCad,
LTspice, or third-party MCP source code.

## Before tagging

Run from the repository root in a clean checkout:

```powershell
python scripts/validate_catalog.py
python scripts/check_links.py
python -c "import json, pathlib; json.loads(pathlib.Path('catalog.json').read_text(encoding='utf-8')); print('JSON OK')"
```

Then confirm:

- `catalog.json` status and verification dates match the latest `codex mcp list`;
- `docs/compatibility.md` names the tested host, OS, Python, KiCad, and MCP
  versions;
- `CHANGELOG.md` and the tag use the same version;
- no absolute user paths, credentials, generated reports, or private designs are
  included;
- the sibling MCP package's own tests and build pass.

## Tag and archive

Use a semantic version tag such as `v0.1.0`. The GitHub Actions release workflow
creates a source archive from the tagged tree and generates release notes. The
archive contains only this metadata repository; users still install the selected
MCP server from its own trusted source.

## After release

1. Open the generated release and verify the archive contents.
2. Check that links in the rendered README and docs resolve.
3. Record any host-registration or integration result in the next maintenance
   entry rather than editing an old release retroactively.
4. If an upstream MCP is withdrawn or compromised, mark its catalog status
   `needs-review` and publish a migration note before the next tag.

