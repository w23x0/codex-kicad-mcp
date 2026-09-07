"""Write pipeline: lock, snapshot, hash-check, plan, confirm, execute, audit.

Flow:
1. ``preview_write`` builds the plan in memory, returns a unified diff plus a
   ``planHash`` and ``snapshotId`` the caller must echo back (no disk
   mutation).  The full plan text is held server-side in the preview
   registry; clients never carry file content.
2. ``confirm_write`` re-verifies the input hashes, takes the project lock,
   creates the snapshot under the previewed ID, burns the confirm token
   (bound to plan hash + snapshot ID, single use, TTL), applies the edits,
   post-validates that every result parses, then atomically replaces the
   files and appends the audit record.  Any validation failure or exception
   rolls the touched files back from the snapshot before re-raising.
"""

from __future__ import annotations

import difflib
import time
from pathlib import Path
from typing import Any

from codex_kicad_mcp import project as project_module
from codex_kicad_mcp.sexpr import parse_sexpr
from codex_kicad_mcp.writes import edits, store
from codex_kicad_mcp.writes.edits import EditError, Plan


def _ts() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _artifact_paths(project: str, suffixes: tuple[str, ...]) -> list:
    pro = project_module.project_file(project)
    result = []
    for suffix in suffixes:
        path = pro.with_suffix(suffix)
        if path.is_file():
            result.append(path)
    if not result:
        raise EditError(f"project has no {suffixes[0]} artifact to edit")
    return result


def _read_artifact_text(path) -> str:
    payload = store.read_file_bytes(path)
    try:
        return payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError(f"artifact is not valid UTF-8: {path.name}") from exc


def _validate_sexpr(text: str, name: str) -> None:
    try:
        parse_sexpr(text)
    except ValueError as exc:
        raise ValueError(f"{name} is not valid KiCad S-expression: {exc}") from exc


def _diff(old: str, new: str) -> str:
    return "".join(
        difflib.unified_diff(
            old.splitlines(keepends=True),
            new.splitlines(keepends=True),
            fromfile="before",
            tofile="after",
            n=2,
        )
    )


def _build_plan(project: str, op: str, params: dict[str, Any]) -> Plan:
    params = params or {}
    if op == "set_property":
        (schematic_path,) = _artifact_paths(project, (".kicad_sch",))
        text = _read_artifact_text(schematic_path)
        _validate_sexpr(text, schematic_path.name)
        new_text, description = edits.plan_set_property(
            text,
            reference=str(params["reference"]),
            name=str(params["name"]),
            value=str(params["value"]),
        )
        return Plan(
            project=project,
            kind=op,
            edits=[
                edits.FileEdit(
                    path=(schematic_path.relative_to(project_module.workspace())).as_posix(),
                    description=description,
                    transform=new_text,
                )
            ],
        )
    if op in {"move_footprint", "rotate_footprint"}:
        (pcb_path,) = _artifact_paths(project, (".kicad_pcb",))
        text = _read_artifact_text(pcb_path)
        _validate_sexpr(text, pcb_path.name)
        if op == "move_footprint":
            new_text, description = edits.plan_move_footprint(
                text,
                reference=str(params["reference"]),
                x=float(params["x"]),
                y=float(params["y"]),
            )
        else:
            new_text, description = edits.plan_rotate_footprint(
                text, reference=str(params["reference"]), angle=float(params["angle"])
            )
        return Plan(
            project=project,
            kind=op,
            edits=[
                edits.FileEdit(
                    path=(pcb_path.relative_to(project_module.workspace())).as_posix(),
                    description=description,
                    transform=new_text,
                )
            ],
        )
    if op == "auto_annotate":
        (schematic_path,) = _artifact_paths(project, (".kicad_sch",))
        text = _read_artifact_text(schematic_path)
        _validate_sexpr(text, schematic_path.name)
        prefix_map = params.get("prefix_map") or {}
        if not isinstance(prefix_map, dict):
            raise EditError("prefix_map must be an object of substring -> prefix")
        new_text, description, count = edits.plan_auto_annotate(text, prefix_map)
        return Plan(
            project=project,
            kind=op,
            edits=[
                edits.FileEdit(
                    path=(schematic_path.relative_to(project_module.workspace())).as_posix(),
                    description=description,
                    transform=new_text,
                )
            ],
            warnings=[] if count else ["no unannotated symbols; nothing to do"],
        )
    raise EditError(f"unsupported write operation: {op}")


def _plan_fingerprint(plan: Plan, pre_hashes: dict[str, str]) -> str:
    payload = json_dumps(
        {
            "project": plan.project,
            "kind": plan.kind,
            "edits": [edit.path for edit in plan.edits],
            "descriptions": [edit.description for edit in plan.edits],
            "pre": pre_hashes,
        }
    )
    return store.sha256_text(payload)


def json_dumps(value: Any) -> str:
    import json

    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def preview_write(project: str, op: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    """Dry-run a write: build the plan, hash inputs, return diffs. No writes."""
    store.require_writes_enabled()
    plan = _build_plan(project, op, params or {})
    pre_hashes: dict[str, str] = {}
    diffs: dict[str, str] = {}
    for edit in plan.edits:
        path = project_module.workspace() / edit.path
        current = _read_artifact_text(path)
        pre_hashes[edit.path] = store.sha256_text(current)
        diffs[edit.path] = _diff(current, edit.transform)
    plan_hash = _plan_fingerprint(plan, pre_hashes)
    # The snapshot ID is derived deterministically from the plan hash so the
    # confirm token can bind to the exact snapshot that will be created.
    snapshot_id = f"staged-{plan_hash[:16]}"
    store.register_preview(
        plan_hash,
        store.PreviewEntry(
            plan=plan,
            pre_hashes=pre_hashes,
            diffs=diffs,
            expires_at=time.monotonic()
            + store.config_int("KICAD_WRITE_PREVIEW_TTL", store.PREVIEW_TTL_SECONDS, maximum=86400),
        ),
    )
    token = store.issue_confirm_token(plan_hash, snapshot_id)
    store.audit_append(
        {
            "stage": "preview",
            "ts": _ts(),
            "project": plan.project,
            "kind": plan.kind,
            "planHash": plan_hash,
            "touched": plan.touched,
            "ok": True,
        }
    )
    return {
        "schemaVersion": "1.0",
        "project": plan.project,
        "kind": plan.kind,
        "edits": [{"path": edit.path, "description": edit.description} for edit in plan.edits],
        "diffs": diffs,
        "touched": plan.touched,
        "planHash": plan_hash,
        "snapshotId": snapshot_id,
        "preHashes": pre_hashes,
        "warnings": plan.warnings,
        "confirmToken": token,
        "confirmRequired": True,
    }


def confirm_write(project: str, plan_hash: str, snapshot_id: str, confirm_token: str) -> dict[str, Any]:
    """Execute a previewed write under lock + snapshot + post-validate."""
    store.require_writes_enabled()
    if not plan_hash or not snapshot_id or not confirm_token:
        raise EditError("confirm_write requires planHash, snapshotId, and confirmToken")
    entry = store.take_preview(plan_hash)
    plan = entry.plan
    pre_hashes = entry.pre_hashes
    if plan.project != project:
        raise EditError("preview belongs to a different project")

    # Bind the token to this plan and snapshot before touching anything.
    store.consume_confirm_token(confirm_token, plan_hash, snapshot_id)
    expected_snapshot_id = f"staged-{plan_hash[:16]}"
    if snapshot_id != expected_snapshot_id:
        raise EditError("snapshotId does not match this plan hash")

    workspace = project_module.workspace()
    targets: dict[str, Path] = {}
    for name in plan.touched:
        if name not in pre_hashes:
            raise EditError(f"preview did not hash file: {name}")
        path = workspace / name
        if not path.is_file():
            raise EditError(f"touched artifact disappeared: {name}")
        targets[name] = path

    lock = store.project_lock(project)
    lock.acquire()
    committed = False
    try:
        # Hash check under the lock: every file must still match the preview.
        for name, expected in pre_hashes.items():
            current = store.sha256_text(_read_artifact_text(targets[name]))
            if current != expected:
                raise EditError(f"source hash changed for {name}; the preview is stale, re-run preview_write")

        # Snapshot the pre-write bytes under the previewed deterministic ID.
        snapshot_files = {name: store.read_file_bytes(path) for name, path in targets.items()}
        store.create_snapshot(project, snapshot_files, snapshot_id=snapshot_id)

        try:
            new_payloads: dict[str, bytes] = {}
            for edit in plan.edits:
                _validate_sexpr(edit.transform, targets[edit.path].name)
                new_payloads[edit.path] = edit.transform.encode("utf-8")
            for name, payload in new_payloads.items():
                store.atomic_write_bytes(targets[name], payload)
            committed = True

            # Post-write validate: reread from disk and confirm bytes match.
            for name, payload in new_payloads.items():
                written = store.read_file_bytes(targets[name])
                if store.sha256_bytes(written) != store.sha256_bytes(payload):
                    raise RuntimeError(f"post-write hash mismatch: {name}")
        except BaseException:
            if committed:
                store.restore_snapshot_files(snapshot_id, targets)
            raise

        file_hashes = {
            name: {"sha256": store.sha256_bytes(payload), "sizeBytes": len(payload)}
            for name, payload in new_payloads.items()
        }
        store.audit_append(
            {
                "stage": "execute",
                "ts": _ts(),
                "project": project,
                "kind": plan.kind,
                "planHash": plan_hash,
                "snapshotId": snapshot_id,
                "tokenHash": store.token_fingerprint(confirm_token),
                "preHashes": pre_hashes,
                "files": {name: item["sha256"] for name, item in file_hashes.items()},
                "ok": True,
            }
        )
        return {
            "schemaVersion": "1.0",
            "project": project,
            "kind": plan.kind,
            "applied": True,
            "snapshotId": snapshot_id,
            "files": file_hashes,
        }
    except BaseException as exc:
        rollback: list[str] = []
        if committed:
            try:
                rollback = store.restore_snapshot_files(snapshot_id, targets)
            except ValueError:
                rollback = []
        store.audit_append(
            {
                "stage": "execute",
                "ts": _ts(),
                "project": project,
                "kind": plan.kind,
                "planHash": plan_hash,
                "snapshotId": snapshot_id,
                "tokenHash": store.token_fingerprint(confirm_token),
                "ok": False,
                "error": f"{type(exc).__name__}: {exc}",
                "rolledBack": rollback,
            }
        )
        raise
    finally:
        lock.release()


def rollback_snapshot(project: str, snapshot_id: str) -> dict[str, Any]:
    """Restore every file recorded in a snapshot; require writes + lock."""
    store.require_writes_enabled()
    manifest = store.load_snapshot_manifest(snapshot_id)
    if manifest.get("project") != project:
        raise EditError(f"snapshot {snapshot_id} belongs to a different project")
    pro = project_module.project_file(project)
    targets: dict[str, Path] = {}
    for name in manifest["files"]:
        targets[name] = pro.with_name(name)
    lock = store.project_lock(project)
    lock.acquire()
    try:
        restored = store.restore_snapshot_files(snapshot_id, targets)
    finally:
        lock.release()
    store.audit_append(
        {
            "stage": "rollback",
            "ts": _ts(),
            "project": project,
            "snapshotId": snapshot_id,
            "files": restored,
            "ok": True,
        }
    )
    return {
        "schemaVersion": "1.0",
        "project": project,
        "snapshotId": snapshot_id,
        "restored": restored,
        "rolledBack": True,
    }


def list_snapshots(project: str | None = None) -> dict[str, Any]:
    store.require_writes_enabled()
    resolved = None
    if project is not None:
        pro = project_module.project_file(project)
        resolved = (pro.relative_to(project_module.workspace())).as_posix()
    return {"schemaVersion": "1.0", "snapshots": store.list_snapshots(resolved)}


def get_write_audit(project: str | None = None, limit: int = 100) -> dict[str, Any]:
    store.require_writes_enabled()
    resolved = None
    if project is not None:
        pro = project_module.project_file(project)
        resolved = (pro.relative_to(project_module.workspace())).as_posix()
    return {"schemaVersion": "1.0", "records": store.audit_records(resolved, limit=limit)}
