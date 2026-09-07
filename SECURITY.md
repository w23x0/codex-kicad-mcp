# Security Policy

Report vulnerabilities privately to the repository maintainers rather than
publishing exploit details.

## Trust boundaries

The MCP server restricts filesystem paths to `KICAD_WORKSPACE`, invokes a
fixed `kicad-cli` command shape, and does not read credentials. The public
tool set is read-only.

| Boundary | What crosses it | Control |
| --- | --- | --- |
| Codex host -> MCP process | Tool requests and JSON over stdio | Register only trusted local commands |
| MCP process -> workspace | Project paths and generated reports | Resolve below workspace root; use disposable copies |
| MCP process -> KiCad CLI | Subprocess arguments and output | Fixed command shape, no shell interpolation |

## Reporting

Do not open a public issue containing a credential, private schematic, or an
exploit that can escape the configured workspace. Include a minimal
reproduction using synthetic files where possible.

## Scope

This does not protect against a compromised KiCad installation or a user who
grants the process a workspace containing sensitive files.
