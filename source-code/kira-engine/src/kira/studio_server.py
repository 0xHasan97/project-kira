"""Run Portable AI Studio's own server as a Kira child and forward its API.

Kira already loads the studio's binaries and checkpoints, but the studio is more than binaries:
whisper transcription, Kokoro speech, the four model folders, download progress and the hardware
report are all thin HTTP clients over one Node process ('scripts/server/serve.cjs'). Rebuilding
those endpoints here would fork behaviour the studio updates; forwarding them through Kira's token
gives one door, one audit point and every function without copying the implementation.

The server binds loopback only, is started on demand, and is stopped with the process tree Kira
created. A studio the user started themselves is reported as running and is never killed.
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import time
from pathlib import Path
from typing import Any

import httpx

from .config import Config
from .errors import KiraError
from .studio import Studio

DEFAULT_PORT = 1420
START_TIMEOUT_S = 40.0
#: Paths the proxy will forward. The studio's whole API lives under '/api'; the other three are the
#: files its own answers point at (generated images, transcripts, spoken audio).
ALLOWED_PREFIXES = ("/api/", "/tts-outputs/", "/transcriptions/", "/outputs/")
#: The chat route is deliberately absent: Kira's own /chat/completions already owns conversation,
#: memory and tools, and a second stream here would be a different product on the same screen.
ALLOWED_METHODS = ("GET", "POST")
MAX_PATH_CHARS = 512


class StudioError(KiraError):
    code = "studio_unavailable"
    status = 503


class StudioRefused(StudioError):
    """A request this door will not forward. The refusal is the caller's, not the studio's."""

    code = "studio_refused"
    status = 400


def _port() -> int:
    raw = os.environ.get("KIRA_STUDIO_PORT", "").strip()
    if not raw:
        return DEFAULT_PORT
    try:
        value = int(raw)
    except ValueError as exc:
        raise StudioError("KIRA_STUDIO_PORT must be an integer") from exc
    if not 1 <= value <= 65535:
        raise StudioError("KIRA_STUDIO_PORT must be a TCP port")
    return value


class StudioServer:
    """The studio's Node server: start, stop, and one forwarded request at a time."""

    def __init__(
        self,
        config: Config,
        studio: Studio | None,
        *,
        client: httpx.Client | None = None,
    ) -> None:
        self.config = config
        self.studio = studio
        self.port = _port()
        explicit = os.environ.get("KIRA_STUDIO_URL", "").strip().rstrip("/")
        self.url = explicit or f"http://127.0.0.1:{self.port}"
        self.external = bool(explicit)
        self.client = client or httpx.Client(timeout=2.0)
        self._process: subprocess.Popen | None = None
        self._log: Any = None
        self._error: str | None = None
        self._async: httpx.AsyncClient | None = None
        self._loop: Any = None

    # ------------------------------------------------------------------ health

    def _health(self) -> dict | None:
        """The studio's own health answer, or None. Never raises: a dead port is a state, not an error."""
        try:
            response = self.client.get(f"{self.url}/api/health")
        except httpx.HTTPError:
            return None
        if response.status_code >= 400:
            return None
        try:
            body = response.json()
        except ValueError:
            return None
        return body if isinstance(body, dict) else None

    # ------------------------------------------------------------------ lifecycle

    def status(self) -> dict:
        health = self._health()
        process = self._process
        managed = process is not None and process.poll() is None
        return {
            "found": self.studio is not None,
            "running": health is not None,
            "managed": managed,
            "external": self.external,
            "url": self.url if health is not None else None,
            "root": str(self.studio.root) if self.studio is not None else None,
            "pid": process.pid if managed else None,
            "error": self._error,
            "health": (
                {"build": health.get("build"), "issues": health.get("issues") or []}
                if health is not None
                else None
            ),
        }

    def start(self) -> dict:
        # A server already answering is the user's own studio or a previous start: attach, do not spawn.
        if self._health() is not None:
            self._error = None
            return self.status()
        if self.external:
            raise StudioError(
                f"KIRA_STUDIO_URL is set to {self.url}, which is not answering; start that studio yourself"
            )
        if self.studio is None:
            raise StudioError(
                "no Portable AI Studio folder was found; set KIRA_STUDIO_DIR to the folder that "
                "contains scripts/server/serve.cjs"
            )
        node = self.studio.node()
        if node is None:
            raise StudioError("the studio has no Node runtime; run its windows.bat / linux.sh once")
        script = self.studio.root / "scripts" / "server" / "serve.cjs"
        if not script.is_file():
            raise StudioError(f"the studio server is missing: {script}")
        logs = self.config.data_dir / "logs"
        logs.mkdir(parents=True, exist_ok=True)
        self._log = (logs / "studio.log").open("ab")
        env = {**os.environ, "PORT": str(self.port), "FRONTEND_PORT": str(self.port)}
        options: dict[str, Any] = {
            "cwd": str(self.studio.root),
            "env": env,
            "stdout": self._log,
            "stderr": subprocess.STDOUT,
        }
        if os.name == "nt":
            options["creationflags"] = subprocess.CREATE_NO_WINDOW
        self._error = None
        try:
            self._process = subprocess.Popen([str(node), str(script)], **options)
        except OSError as exc:
            self._close_log()
            self._error = f"the studio server did not start: {exc}"
            raise StudioError(self._error) from exc

        deadline = time.monotonic() + START_TIMEOUT_S
        while time.monotonic() < deadline:
            if self._health() is not None:
                self._error = None
                return self.status()
            if self._process.poll() is not None:
                break
            time.sleep(0.25)
        detail = "the studio server exited before answering /api/health"
        if self._process.poll() is None:
            detail = f"the studio server did not answer /api/health within {int(START_TIMEOUT_S)} s"
        self._error = f"{detail} (log: {logs / 'studio.log'})"
        self._kill()
        raise StudioError(self._error)

    def stop(self) -> dict:
        if not self.status()["managed"]:
            # Nothing of ours to stop. An external studio belongs to whoever started it.
            return self.status()
        self._kill()
        self._error = None
        return self.status()

    def _kill(self) -> None:
        process = self._process
        self._process = None
        if process is not None and process.poll() is None:
            if os.name == "nt":
                subprocess.run(
                    ["taskkill", "/F", "/T", "/PID", str(process.pid)],
                    capture_output=True,
                    check=False,
                )
            else:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
        self._close_log()

    def _close_log(self) -> None:
        if self._log is not None:
            try:
                self._log.close()
            except OSError:
                pass
            self._log = None

    # ------------------------------------------------------------------ proxy

    @staticmethod
    def _split(target: str) -> tuple[str, str]:
        path, _, query = target.partition("?")
        if not path or len(target) > MAX_PATH_CHARS:
            raise StudioRefused("the studio path is missing or too long")
        # A forwarded path may only reach the API surface the studio publishes. '..' in any segment
        # is refused before a socket opens: the studio parses paths too, but this door does not pass
        # something the caller could have meant as a file walk.
        if ".." in path.replace(chr(92), "/").split("/"):
            raise StudioRefused("the studio path may not leave the API")
        if not any(path.startswith(prefix) for prefix in ALLOWED_PREFIXES):
            raise StudioRefused("that path is not part of the studio API")
        return path, query

    async def proxy(
        self, method: str, target: str, *, content_type: str | None = None, body: bytes = b""
    ) -> tuple[int, str, bytes]:
        method = method.upper()
        if method not in ALLOWED_METHODS:
            raise StudioRefused(f"the studio proxy forwards {', '.join(ALLOWED_METHODS)} only")
        path, query = self._split(target)
        if self._health() is None:
            raise StudioError("the studio server is not running; start it from the Studio screen")
        # One pooled client per event loop. A test harness or a restarted engine can hand this object a
        # second loop; a client created on the first one cannot open a socket on the second (asyncio
        # transports are loop-bound), so the pool is rebuilt rather than failing the request.
        loop = asyncio.get_running_loop()
        if self._async is None or (self._loop is not None and self._loop is not loop):
            self._async = httpx.AsyncClient(timeout=httpx.Timeout(180.0, connect=5.0))
            self._loop = loop
        headers = {"content-type": content_type} if content_type else {}
        try:
            response = await self._async.request(
                method,
                f"{self.url}{path}" + (f"?{query}" if query else ""),
                content=body or None,
                headers=headers,
            )
        except httpx.HTTPError as exc:
            raise StudioError(f"the studio did not answer: {type(exc).__name__}") from exc
        return (
            response.status_code,
            response.headers.get("content-type", "application/json"),
            response.content,
        )

    async def aclose(self) -> None:
        """Stop the child and close the pool on the loop that owns it."""
        self._kill()
        if self._async is not None:
            await self._async.aclose()
            self._async = None
        self.client.close()

    def close(self) -> None:
        """The synchronous half: stop the child. A pool whose loop is gone closes with the loop."""
        self._kill()
        self._async = None
        self.client.close()
