from __future__ import annotations

import asyncio
import json
import os
import shutil
import time
from pathlib import Path

from .limits import (
    MAX_ARG_CHARS,
    MAX_ARGV,
    MAX_LIST_ENTRIES,
    MAX_OUTPUT_BYTES,
    MAX_READ_BYTES,
    MAX_SEARCH_BYTES,
    MAX_SEARCH_FILES,
    MAX_SEARCH_HITS,
    MAX_TIMEOUT_S,
    MAX_WRITE_BYTES,
    MIN_TIMEOUT_S,
)

SHELLS = {
    "cmd", "cmd.exe", "powershell", "powershell.exe", "pwsh", "pwsh.exe",
    "bash", "bash.exe", "sh", "zsh", "wsl", "wsl.exe",
}
ENV_ALLOW = (
    "PATH", "PATHEXT", "SYSTEMROOT", "SYSTEMDRIVE", "WINDIR", "TEMP", "TMP",
    "USERPROFILE", "HOME", "LANG", "LC_ALL", "TERM",
)


class WorkspaceError(ValueError):
    pass


class Workspace:
    """Every tool path resolves here. Symlinks are followed *before* the containment check."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def safe_path(self, raw: str) -> Path:
        if not isinstance(raw, str) or not raw or "\x00" in raw:
            raise WorkspaceError("path must be a non-empty string")
        candidate = Path(raw)
        resolved = (candidate if candidate.is_absolute() else self.root / candidate).resolve()
        if resolved != self.root and self.root not in resolved.parents:
            raise WorkspaceError(f"path escapes the workspace: {raw}")
        return resolved

    @staticmethod
    def _read_head(path: Path, limit: int) -> tuple[bytes, bool]:
        """At most `limit + 1` bytes, and whether there was more. The cap is enforced *before* the read.

        `read_bytes()` and then slice read the whole file in order to throw most of it away: a 50 MB file
        in the workspace cost a 50 MB allocation to return 128 KB, and the agent can ask as often as it
        likes. One byte over the limit is all this needs to know that the file was longer.
        """
        with path.open("rb") as handle:
            data = handle.read(limit + 1)
        return data[:limit], len(data) > limit

    def read_text(self, raw: str) -> str:
        path = self.safe_path(raw)
        if not path.exists():
            raise WorkspaceError(f"file does not exist: {raw}")
        if not path.is_file():
            raise WorkspaceError(f"not a file: {raw}")
        data, truncated = self._read_head(path, MAX_READ_BYTES)
        if b"\x00" in data:
            raise WorkspaceError(f"file looks binary: {raw}")
        text = data.decode("utf-8", "replace")
        if truncated:
            text += f"\n[truncated at {MAX_READ_BYTES} bytes]"
        return text

    def list_dir(self, raw: str) -> str:
        path = self.safe_path(raw)
        if not path.is_dir():
            raise WorkspaceError(f"not a directory: {raw}")
        entries = []
        for child in sorted(path.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))[:MAX_LIST_ENTRIES]:
            try:
                size = child.stat().st_size if child.is_file() else 0
            except OSError:
                size = 0
            entries.append({"name": child.name, "type": "dir" if child.is_dir() else "file", "size": size})
        return json.dumps({"path": raw, "entries": entries, "count": len(entries)}, ensure_ascii=False)

    def search_text(self, query: str, raw: str) -> str:
        if not query:
            raise WorkspaceError("query must not be empty")
        root = self.safe_path(raw)
        if not root.is_dir():
            raise WorkspaceError(f"not a directory: {raw}")
        hits: list[dict] = []
        scanned = 0
        budget = MAX_SEARCH_BYTES
        for path in sorted(root.rglob("*")):
            if len(hits) >= MAX_SEARCH_HITS or scanned >= MAX_SEARCH_FILES or budget <= 0:
                break
            if not path.is_file() or ".git" in path.parts:
                continue
            scanned += 1
            try:
                # The same pre-read cap as `read_text`: the search budget decides how much of the file is
                # looked at, and the file is never fully materialised to find that out.
                limit = min(budget, MAX_READ_BYTES)
                if limit <= 0:
                    break
                data, _ = self._read_head(path, limit)
            except OSError:
                continue
            budget -= len(data)
            if b"\x00" in data:
                continue
            for number, line in enumerate(data.decode("utf-8", "replace").splitlines(), start=1):
                if query in line:
                    hits.append({"path": path.relative_to(self.root).as_posix(), "line": number, "text": line[:300]})
                    if len(hits) >= MAX_SEARCH_HITS:
                        break
        return json.dumps({"query": query, "hits": hits, "scanned_files": scanned}, ensure_ascii=False)

    def write_text(self, raw: str, content: str) -> int:
        if not isinstance(content, str):
            raise WorkspaceError("content must be a string")
        data = content.encode("utf-8")
        if len(data) > MAX_WRITE_BYTES:
            raise WorkspaceError(f"content is too large (max {MAX_WRITE_BYTES} bytes)")
        path = self.safe_path(raw)
        if path == self.root:
            raise WorkspaceError("cannot write the workspace root")
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(path.name + ".kira-tmp")
        temporary.write_bytes(data)
        os.replace(temporary, path)
        return len(data)

    def _command_env(self) -> dict[str, str]:
        env = {key: value for key in ENV_ALLOW if (value := os.environ.get(key)) is not None}
        # Windows needs these even with a stripped environment; without SYSTEMROOT some runtimes fail to start.
        env.setdefault("PATH", os.defpath)
        return env

    async def run_command(self, argv: list[str], cwd: str = ".", timeout_s: int = 30) -> dict:
        if not isinstance(argv, list) or not argv or len(argv) > MAX_ARGV:
            raise WorkspaceError(f"argv must be a list of 1-{MAX_ARGV} strings")
        if not all(isinstance(item, str) and item and len(item) <= MAX_ARG_CHARS for item in argv):
            raise WorkspaceError("every argv entry must be a non-empty string under 4096 characters")
        name = Path(argv[0]).name.lower()
        if name in SHELLS:
            raise WorkspaceError(f"refusing to run a shell ({name}); pass the program directly")
        if not (MIN_TIMEOUT_S <= timeout_s <= MAX_TIMEOUT_S):
            raise WorkspaceError(f"timeout must be {MIN_TIMEOUT_S}-{MAX_TIMEOUT_S} seconds")
        resolved_cwd = self.safe_path(cwd)
        if not resolved_cwd.is_dir():
            raise WorkspaceError(f"not a directory: {cwd}")
        executable = argv[0]
        if not Path(executable).is_absolute() and "/" not in executable and "\\" not in executable:
            executable = shutil.which(executable, path=self._command_env().get("PATH")) or executable
        started = time.perf_counter()
        process = await asyncio.create_subprocess_exec(
            executable,
            *argv[1:],
            cwd=str(resolved_cwd),
            env=self._command_env(),
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        timed_out = False
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout_s)
        except asyncio.TimeoutError:
            timed_out = True
            process.kill()
            stdout, stderr = await process.communicate()
        duration_ms = int((time.perf_counter() - started) * 1000)
        out = stdout[:MAX_OUTPUT_BYTES].decode("utf-8", "replace")
        err = stderr[:MAX_OUTPUT_BYTES].decode("utf-8", "replace")
        truncated = len(stdout) > MAX_OUTPUT_BYTES or len(stderr) > MAX_OUTPUT_BYTES
        return {
            "exit_code": 124 if timed_out else int(process.returncode or 0),
            "stdout": out,
            "stderr": err,
            "duration_ms": duration_ms,
            "truncated": truncated,
        }
