# Security Model

The Toolkit is a catalog and set of operating instructions. It does not run an
MCP server itself, store credentials, or upload design files. The security
properties below describe the servers it indexes and the checks maintainers
expect before calling an entry safe enough for a local workflow.

## Trust boundaries

| Boundary | What crosses it | Required control |
| --- | --- | --- |
| Codex host -> MCP process | Tool requests and JSON results over stdio | Register only trusted local commands; inspect the command and environment. |
| MCP process -> workspace | Project paths and generated reports | Resolve paths below an explicit workspace root; use a disposable copy for checks. |
| MCP process -> EDA CLI | KiCad/LTspice subprocess arguments and output | Use fixed command shapes, avoid shell interpolation, and retain exit code plus raw diagnostics. |
| Repository -> contributor machine | TOML snippets, scripts, and catalog metadata | Replace placeholders, keep credentials out of source control, and review diffs. |

## Data handling

- KiCad projects, schematics, board files, simulations, and reports can contain
  proprietary designs. Treat MCP transcripts and generated artifacts as
  confidential unless the project owner says otherwise.
- The catalog uses `${CODEX_HOME}` and `<path-to>` placeholders so local user
  names and drive letters are not committed.
- Do not add API keys, OAuth tokens, cookies, `auth*.json`, `.env` files, or
  private model data to this repository.
- Network access is not needed for the indexed KiCad workflow. If an upstream
  MCP requires network access, document the host, endpoints, and least-privilege
  credentials before changing its risk rating.

## Side effects and write policy

The indexed KiCad MCP is read-first. ERC/DRC may create or update a report file
according to the installed KiCad release, so checks are not strictly side-effect
free. The planned LTspice entry may write simulation artifacts. Before invoking
any write-capable server:

1. Use a versioned or disposable project copy.
2. Record the exact command, input paths, and output directory.
3. Review the file diff and simulator/CLI diagnostics.
4. Never treat a zero exit code as proof that a design is electrically correct.

## Reporting a vulnerability

Do not publish exploit details in an issue. Follow the private reporting process
in [`../SECURITY.md`](../SECURITY.md), including the affected entry, host/OS,
exact command, and a minimal reproduction that does not contain design secrets.

