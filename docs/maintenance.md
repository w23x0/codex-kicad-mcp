# Maintenance Record

## Record Format

Every component change records at minimum: date, component ID, source version
or commit, entrypoint changes, verification commands, and results.  Config
problems record the symptom and recovery steps, not just "fixed".

## Boundaries

This file records reusable collaboration infrastructure.  Component choices,
antenna parameters, board outlines, and manufacturing conclusions for an
individual hardware project belong in that project's `README.md` or `docs/`,
not here.

## 2026-09-07

- Added the real-project scan suite (`mcp/tests/test_real_projects.py`): the
  full tool surface runs against copied KiCad demo projects with the real
  `kicad-cli`, skipping cleanly when KiCad is absent.  Motivated by the
  drill-parse bug that shipped 273 false errors on `complex_hierarchy` behind
  a green fixture suite.
- Calibrated Step 6 semantics against real exports: rails fed externally (via
  a connector, a regulator feed, or root-sheet power_in pins) now report
  `power.source_missing` as a warning with the reason in the message, and
  parity ignores KiCad's auto-generated `Net-(...)`/`unconnected-` net names
  and the empty PCB net 0.
- Verified on KiCad 10.0.6 with three demo projects: `complex_hierarchy`
  (0 errors, 4 warnings), `kit-dev-coldfire-xilinx_5213` (0 errors,
  3 warnings), `pic_programmer` (1 error: the VPP charge pump is a real
  heuristic blind spot and stays a reported finding on purpose).
- Fixed `artifact_file` reporting a missing artifact as a workspace escape.
- Fixed a missing `Path` import in the write pipeline (dead annotation only,
  but a real defect).

## 2026-09-06

- `codex mcp list` currently lists only `node_repl`, so
  `codexRegistration.status` stays `needs-review`.
- The KiCad MCP dist entrypoint and the LTspice MCP executable both exist;
  direct-launch testing can continue.
- Recovery steps: register `kicad` and `ltspice` in `${CODEX_HOME}/config.toml`,
  restart Codex, run the test scripts, and update `catalog.json`.
