"""Snapshot store, project lock, audit log, tokens, and preview registry.

Snapshots are full copies of the touched artifacts stored under
``KICAD_SNAPSHOT_ROOT`` (default ``<workspace>/.kicad-mcp-snapshots``) so a
failed or cancelled write can be rolled back byte-for-byte.  Locks use atomic
file creation with a stale timeout instead of blocking forever.  The audit log
is append-only JSON Lines; every pipeline stage appends one record.  Confirm
tokens are random, bound to the plan hash and snapshot ID, single-use, and
expire after a short TTL.  Preview plans live server-side in a bounded,
expiring registry keyed by plan hash; the client never carries file content.
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from codex_kicad_mcp import project as project_module
from codex_kicad_mcp.writes.edits import Plan

ENABLE_WRITES_ENV = "KICAD_ENABLE_WRITES"
SNAPSHOT_ROOT_ENV = "KICAD_SNAPSHOT_ROOT"
DEFAULT_SNAPSHOT_DIR = ".kicad-mcp-snapshots"
LOCK_STALE_SECONDS = 300
TOKEN_TTL_SECONDS = 900
PREVIEW_TTL_SECONDS = 1800
MAX_PREVIEWS = 32


def writes_enabled() -> bool:
    """True only when ``KICAD_ENABLE_WRITES=1`` is set exactly."""
    return os.environ.get(ENABLE_WRITES_ENV, "") == "1"


def require_writes_enabled() -> None:
    if not writes_enabled():
        raise ValueError(f"writes are disabled; set {ENABLE_WRITES_ENV}=1 to enable the write API")


def snapshot_root() -> Path:
    raw = os.environ.get(SNAPSHOT_ROOT_ENV)
    root = Path(raw).expanduser() if raw and raw.strip() else project_module.workspace() / DEFAULT_SNAPSHOT_DIR
    root.mkdir(parents=True, exist_ok=True)
    return root


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_text(text: str) -> str:
    return sha256_bytes(text.encode("utf-8"))


def config_int(name: str, default: int, maximum: int) -> int:
    from codex_kicad_mcp import config

    return config.env_int(name, default, maximum=maximum)


# ---------------------------------------------------------------------------
# Atomic file replacement
# ---------------------------------------------------------------------------


def atomic_write_bytes(path: Path, payload: bytes) -> None:
    """Replace a file atomically via a temp file + ``os.replace``."""
    fd, temp_name = tempfile_pair(path)
    temp_path = Path(temp_name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
    except BaseException:
        temp_path.unlink(missing_ok=True)
        raise
    try:
        dir_fd = os.open(path.parent, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(dir_fd)
    except OSError:
        pass
    finally:
        os.close(dir_fd)


def tempfile_pair(path: Path) -> tuple[int, str]:
    import tempfile

    return tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)


def read_file_bytes(path: Path) -> bytes:
    try:
        return path.read_bytes()
    except OSError as exc:
        raise ValueError(f"could not read artifact: {path.name}") from exc


# ---------------------------------------------------------------------------
# Locking
# ---------------------------------------------------------------------------


@dataclass
class ProjectLock:
    """An exclusive advisory lock for one project's write operations.

    Uses ``os.O_CREAT | os.O_EXCL`` for atomic creation and a stale timeout so
    a crashed process cannot wedge the workspace forever.
    """

    path: Path
    acquired_at: float = 0.0

    def acquire(self, *, wait_seconds: float = 30.0) -> None:
        deadline = time.monotonic() + wait_seconds
        while True:
            try:
                fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            except FileExistsError:
                if time.monotonic() >= deadline:
                    try:
                        age = time.time() - self.path.stat().st_mtime
                    except OSError:
                        age = LOCK_STALE_SECONDS + 1
                    if age <= LOCK_STALE_SECONDS:
                        raise ValueError(f"another write operation holds the lock: {self.path.name}") from None
                    self.path.unlink(missing_ok=True)
                    continue
                time.sleep(0.05)
            except OSError as exc:
                raise ValueError(f"could not create write lock: {exc.strerror or exc}") from exc
            else:
                with os.fdopen(fd, "w", encoding="utf-8") as handle:
                    handle.write(f"pid={os.getpid()} acquired={time.time():.3f}\n")
                self.acquired_at = time.time()
                return

    def release(self) -> None:
        self.path.unlink(missing_ok=True)


def project_lock(project: str) -> ProjectLock:
    pro = project_module.project_file(project)
    return ProjectLock(path=snapshot_root() / f"{pro.stem}.lock")


# ---------------------------------------------------------------------------
# Snapshots
# ---------------------------------------------------------------------------


def create_snapshot(project: str, files: dict[str, bytes], snapshot_id: str | None = None) -> dict[str, Any]:
    """Persist the pre-write content of every file an edit may touch."""
    pro = project_module.project_file(project)
    if snapshot_id is None:
        stamp = time.strftime("%Y%m%dT%H%M%S", time.gmtime())
        snapshot_id = f"{pro.stem}-{stamp}-{secrets.token_hex(4)}"
    if not _valid_snapshot_id(snapshot_id):
        raise ValueError("invalid snapshot id")
    directory = snapshot_root() / snapshot_id
    if directory.exists():
        raise ValueError(f"snapshot already exists: {snapshot_id}")
    directory.mkdir(parents=True)
    manifest: dict[str, Any] = {
        "snapshotId": snapshot_id,
        "project": (pro.relative_to(project_module.workspace())).as_posix(),
        "createdAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "files": {},
    }
    for name, payload in files.items():
        target = directory / Path(name).name
        target.write_bytes(payload)
        manifest["files"][name] = {
            "sha256": sha256_bytes(payload),
            "sizeBytes": len(payload),
        }
    (directory / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


def _valid_snapshot_id(snapshot_id: str) -> bool:
    if not snapshot_id or len(snapshot_id) > 200:
        return False
    if "/" in snapshot_id or "\\" in snapshot_id or snapshot_id in {".", ".."}:
        return False
    return all(char.isalnum() or char in "-_." for char in snapshot_id)


def snapshot_dir(snapshot_id: str) -> Path:
    if not _valid_snapshot_id(snapshot_id):
        raise ValueError("invalid snapshot id")
    directory = snapshot_root() / snapshot_id
    if not directory.is_dir():
        raise ValueError(f"snapshot does not exist: {snapshot_id}")
    return directory


def load_snapshot_manifest(snapshot_id: str) -> dict[str, Any]:
    directory = snapshot_dir(snapshot_id)
    manifest_path = directory / "manifest.json"
    if not manifest_path.is_file():
        raise ValueError(f"snapshot manifest is missing: {snapshot_id}")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        raise ValueError(f"snapshot manifest is not valid JSON: {snapshot_id}") from exc
    if not isinstance(manifest, dict) or not isinstance(manifest.get("files"), dict):
        raise ValueError(f"snapshot manifest is malformed: {snapshot_id}")
    return manifest


def restore_snapshot_files(snapshot_id: str, files: dict[str, Path]) -> list[str]:
    """Copy snapshot payloads back over the live files; return restored names."""
    directory = snapshot_dir(snapshot_id)
    manifest = load_snapshot_manifest(snapshot_id)
    restored: list[str] = []
    for name, target in files.items():
        entry = manifest["files"].get(name)
        if entry is None:
            raise ValueError(f"snapshot does not contain file: {name}")
        source = directory / Path(name).name
        payload = source.read_bytes()
        if sha256_bytes(payload) != entry["sha256"]:
            raise ValueError(f"snapshot payload hash mismatch: {name}")
        atomic_write_bytes(target, payload)
        restored.append(name)
    return restored


def list_snapshots(project: str | None = None) -> list[dict[str, Any]]:
    """List snapshot manifests, newest first, optionally filtered by project."""
    root = snapshot_root()
    results: list[dict[str, Any]] = []
    limit = config_int("KICAD_MAX_SNAPSHOTS_LISTED", 50, maximum=1000)
    for directory in sorted(root.iterdir(), reverse=True):
        if not directory.is_dir():
            continue
        manifest_path = directory / "manifest.json"
        if not manifest_path.is_file():
            continue
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if not isinstance(manifest, dict):
            continue
        if project is not None and manifest.get("project") != project:
            continue
        results.append(
            {
                "snapshotId": manifest.get("snapshotId"),
                "project": manifest.get("project"),
                "createdAt": manifest.get("createdAt"),
                "files": sorted(manifest.get("files", {})),
            }
        )
        if len(results) >= limit:
            break
    return results


def prune_snapshots(project: str, keep: int = 20) -> int:
    """Delete oldest snapshots for one project beyond ``keep``; return count."""
    manifests = list_snapshots(project)
    removed = 0
    for entry in manifests[keep:]:
        snapshot_id = entry.get("snapshotId")
        if snapshot_id and _valid_snapshot_id(str(snapshot_id)):
            directory = snapshot_root() / str(snapshot_id)
            if directory.is_dir():
                for child in directory.iterdir():
                    child.unlink(missing_ok=True)
                directory.rmdir()
                removed += 1
    return removed


# ---------------------------------------------------------------------------
# Audit log
# ---------------------------------------------------------------------------


def audit_log_path() -> Path:
    return snapshot_root() / "audit.jsonl"


def audit_append(record: dict[str, Any]) -> None:
    path = audit_log_path()
    line = json.dumps(record, sort_keys=True, separators=(",", ":"))
    with path.open("a", encoding="utf-8") as handle:
        handle.write(line + "\n")


def audit_records(project: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
    """Read audit records, oldest last, filtered by project when given."""
    path = audit_log_path()
    if not path.is_file():
        return []
    records: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if project is None or record.get("project") == project:
                records.append(record)
    return records[-limit:]


# ---------------------------------------------------------------------------
# Confirm tokens
# ---------------------------------------------------------------------------


@dataclass
class ConfirmToken:
    value: str
    plan_hash: str
    snapshot_id: str
    expires_at: float


_TOKENS: dict[str, ConfirmToken] = {}


def token_fingerprint(token_value: str) -> str:
    """Stable audit-safe hash of a token value (never log the raw token)."""
    return sha256_text(token_value)[:16]


def issue_confirm_token(plan_hash: str, snapshot_id: str) -> str:
    ttl = config_int("KICAD_WRITE_TOKEN_TTL", TOKEN_TTL_SECONDS, maximum=86400)
    value = secrets.token_urlsafe(24)
    _TOKENS[value] = ConfirmToken(
        value=value,
        plan_hash=plan_hash,
        snapshot_id=snapshot_id,
        expires_at=time.monotonic() + ttl,
    )
    _sweep_expired()
    return value


def consume_confirm_token(token_value: str, plan_hash: str, snapshot_id: str) -> None:
    """Validate and burn a confirm token bound to this plan and snapshot."""
    token = _TOKENS.get(token_value)
    _TOKENS.pop(token_value, None)
    if token is None:
        raise ValueError("confirm token is unknown, already used, or expired")
    if token.expires_at < time.monotonic():
        raise ValueError("confirm token has expired")
    if not secrets.compare_digest(token.plan_hash, plan_hash):
        raise ValueError("confirm token does not match this plan hash")
    if token.snapshot_id != snapshot_id:
        raise ValueError("confirm token does not match this snapshot id")


def _sweep_expired() -> None:
    now = time.monotonic()
    for key in [key for key, item in _TOKENS.items() if item.expires_at < now]:
        _TOKENS.pop(key, None)


def reset_tokens() -> None:
    """Test hook: forget every outstanding confirm token."""
    _TOKENS.clear()


# ---------------------------------------------------------------------------
# Preview registry (server-side plan memory)
# ---------------------------------------------------------------------------


@dataclass
class PreviewEntry:
    plan: Plan
    pre_hashes: dict[str, str]
    diffs: dict[str, str]
    expires_at: float


_PREVIEWS: dict[str, PreviewEntry] = {}


def register_preview(plan_hash: str, entry: PreviewEntry) -> None:
    ttl = config_int("KICAD_WRITE_PREVIEW_TTL", PREVIEW_TTL_SECONDS, maximum=86400)
    _PREVIEWS[plan_hash] = entry
    now = time.monotonic()
    for key in [key for key, item in _PREVIEWS.items() if item.expires_at < now]:
        _PREVIEWS.pop(key, None)
    while len(_PREVIEWS) > MAX_PREVIEWS:
        oldest = min(_PREVIEWS, key=lambda key: _PREVIEWS[key].expires_at)
        _PREVIEWS.pop(oldest, None)
    del ttl


def take_preview(plan_hash: str) -> PreviewEntry:
    """Fetch and burn the preview entry bound to a plan hash."""
    entry = _PREVIEWS.pop(plan_hash, None)
    if entry is None:
        raise ValueError("no active preview for this plan hash; run preview_write first")
    if entry.expires_at < time.monotonic():
        raise ValueError("preview has expired; run preview_write again")
    return entry


def reset_previews() -> None:
    """Test hook: drop every outstanding preview."""
    _PREVIEWS.clear()
