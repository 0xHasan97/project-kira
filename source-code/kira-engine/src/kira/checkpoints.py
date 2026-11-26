from __future__ import annotations

import difflib
import hashlib
import json
import os
import shutil
from pathlib import Path

from .limits import MAX_CHECKPOINT_BYTES
from .store import Store
from .workspace import Workspace


class CheckpointConflict(Exception):
    def __init__(self, conflicts: list[dict]) -> None:
        super().__init__(f"{len(conflicts)} file(s) changed since the checkpoint")
        self.conflicts = conflicts


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class CheckpointManager:
    """Captures a file's bytes before a write, so the dashboard can diff and undo it.

    A checkpoint is opened before the tool runs and finalized after, because only then are both
    hashes known. Restore refuses when the file moved on since `sha256_after` - unless forced -
    and always takes a safety checkpoint first, so an undo is itself undoable.
    """

    def __init__(self, workspace: Workspace, directory: Path, store: Store, retention: int = 50) -> None:
        self.workspace = workspace
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.store = store
        self.retention = retention

    def take(self, *, session_id: str | None, tool: str, call_id: str, paths: list[str]) -> dict:
        files = []
        for index, raw in enumerate(paths):
            resolved = self.workspace.safe_path(raw)
            relative = resolved.relative_to(self.workspace.root).as_posix()
            entry = {"path": relative, "existed": False, "sha256_before": None, "sha256_after": None, "size": 0, "blob": None}
            if resolved.exists():
                if not resolved.is_file():
                    raise ValueError(f"not a file: {raw}")
                data = resolved.read_bytes()
                if len(data) > MAX_CHECKPOINT_BYTES:
                    raise ValueError(f"file too large to checkpoint: {relative}")
                entry.update(existed=True, sha256_before=_sha256(data), size=len(data), blob=f"{index}.blob")
            files.append(entry)
        row = self.store.add_checkpoint(session_id=session_id, tool=tool, call_id=call_id, scope="files", files=files)
        target = self.directory / row["id"]
        target.mkdir(parents=True, exist_ok=True)
        for index, entry in enumerate(files):
            if entry["existed"]:
                (target / f"{index}.blob").write_bytes((self.workspace.root / entry["path"]).read_bytes())
        (target / "manifest.json").write_text(json.dumps(row, indent=2), encoding="utf-8")
        return row

    def finalize(self, checkpoint_id: str) -> dict:
        row = self.store.get_checkpoint(checkpoint_id)
        if row is None:
            raise KeyError(checkpoint_id)
        files = []
        for entry in row["files"]:
            current = self.workspace.root / entry["path"]
            after = _sha256(current.read_bytes()) if current.is_file() else None
            files.append({**entry, "sha256_after": after})
        updated = self.store.finalize_checkpoint(checkpoint_id, files)
        self.prune()
        return updated

    def get(self, checkpoint_id: str) -> dict | None:
        return self.store.get_checkpoint(checkpoint_id)

    def list(self, limit: int = 20, session_id: str | None = None) -> list[dict]:
        return self.store.list_checkpoints(limit=limit, session_id=session_id)

    def prune(self) -> int:
        removed = self.store.prune_checkpoints(self.retention)
        for checkpoint_id in removed:
            shutil.rmtree(self.directory / checkpoint_id, ignore_errors=True)
        return len(removed)

    def _blob_path(self, checkpoint_id: str, entry: dict) -> Path:
        return self.directory / checkpoint_id / str(entry["blob"])

    def diff(self, checkpoint_id: str) -> dict:
        row = self.store.get_checkpoint(checkpoint_id)
        if row is None:
            raise KeyError(checkpoint_id)
        files = []
        for entry in row["files"]:
            current = self.workspace.root / entry["path"]
            before = self._blob_path(checkpoint_id, entry).read_bytes() if entry["existed"] else b""
            after = current.read_bytes() if current.is_file() else b""
            if b"\x00" in before or b"\x00" in after:
                body, changed = "binary differs", before != after
            else:
                old = before.decode("utf-8", "replace").splitlines(keepends=True)
                new = after.decode("utf-8", "replace").splitlines(keepends=True)
                patch = list(difflib.unified_diff(old, new, fromfile=f"a/{entry['path']}", tofile=f"b/{entry['path']}"))
                body = "".join(patch[:200])
                changed = bool(patch)
            files.append({"path": entry["path"], "existed": entry["existed"], "changed": changed, "diff": body})
        return {"checkpoint": row, "files": files}

    def restore(self, checkpoint_id: str, *, force: bool = False) -> dict:
        row = self.store.get_checkpoint(checkpoint_id)
        if row is None:
            raise KeyError(checkpoint_id)
        conflicts = []
        for entry in row["files"]:
            current = self.workspace.root / entry["path"]
            actual = _sha256(current.read_bytes()) if current.is_file() else None
            if actual != entry["sha256_after"]:
                conflicts.append({"path": entry["path"], "expected_after": entry["sha256_after"], "actual": actual})
        if conflicts and not force:
            raise CheckpointConflict(conflicts)
        safety = self.take(
            session_id=row["session_id"],
            tool="restore",
            call_id=row["id"],
            paths=[entry["path"] for entry in row["files"]],
        )
        self.finalize(safety["id"])
        for entry in row["files"]:
            target = self.workspace.root / entry["path"]
            if entry["existed"]:
                data = self._blob_path(checkpoint_id, entry).read_bytes()
                target.parent.mkdir(parents=True, exist_ok=True)
                temporary = target.with_name(target.name + ".kira-tmp")
                temporary.write_bytes(data)
                os.replace(temporary, target)
            elif target.exists():
                target.unlink()
        self.store.mark_checkpoint_restored(checkpoint_id)
        return {
            "restored": [entry["path"] for entry in row["files"]],
            "conflicts": conflicts,
            "checkpoint_id": safety["id"],
        }
