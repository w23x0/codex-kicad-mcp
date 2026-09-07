# Contributing

Keep tools small, explicit, and safe by default.

## Rules

1. New tools must validate all user paths against `KICAD_WORKSPACE`.
2. Document side effects and include a focused test.
3. Do not commit KiCad projects containing private designs or credentials.
4. Update `catalog/catalog.json` for new MCP or skill entries.
5. Record maintenance results in `docs/` with dates and commands.

## Process

1. Write the user task and safety boundary.
2. Implement against a fixture before touching a real design.
3. Run focused tests, then the workspace validator and build.
4. Update the catalog and changelog only after behavior is verified.

See [`docs/development-workflow.md`](docs/development-workflow.md) for the
staged delivery process.
