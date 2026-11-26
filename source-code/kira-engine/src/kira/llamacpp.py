"""A llama.cpp server Kira can start and stop, so chat has a local tier without another app.

The Portable AI Studio shape, natively: a single-file GGUF is chosen in the UI, a `llama-server`
child process is started on loopback, and the moment it answers `/v1/models` the engine appends a
keyless `openai_compat` provider named ``local_llama``. Chat then routes to it exactly like any
remote stanza — the router does not learn a second code path — and stopping the server removes the
provider again.

No model is downloaded here. A machine with no GGUF or no `llama-server` reports what is missing;
starting one is an explicit click, and it is stopped when Kira shuts down.
"""

from __future__ import annotations

import atexit
import os
import socket
import subprocess
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path

from .config import Config, ProviderConfig
from .errors import KiraError
from .studio import Studio, find_studio

PROVIDER_NAME = "local_llama"
DEFAULT_CONTEXT = 4096
DEFAULT_START_TIMEOUT_S = 180.0
LLM_EXTENSIONS = (".gguf",)


class LlmUnavailable(KiraError):
    code = "llm_unavailable"
    status = 503


class LlmStartFailed(KiraError):
    code = "llm_start_failed"
    status = 502


@dataclass(frozen=True)
class LlmModel:
    name: str
    filename: str
    path: Path
    size_bytes: int

    def to_wire(self) -> dict:
        return {
            "name": self.name,
            "filename": self.filename,
            "size_bytes": self.size_bytes,
        }


class LocalLlm:
    """One child server at a time. The lock is the serialiser: two starts cannot race a port."""

    def __init__(
        self,
        config: Config,
        *,
        studio: Studio | None = None,
        spawn: Callable[[list[str], dict[str, str], Path], subprocess.Popen]
        | None = None,
        probe: Callable[[str, float], bool] | None = None,
        free_port: Callable[[], int] | None = None,
    ) -> None:
        self.config = config
        self.studio = studio if studio is not None else find_studio(config.data_dir)
        self.engine_dir = config.data_dir / "llm" / "engines"
        self.model_dir = config.data_dir / "llm" / "models"
        self.log_path = config.data_dir / "logs" / "llama-server.log"
        self._spawn = spawn or self._spawn_process
        self._probe = probe or self._probe_http
        self._free_port = free_port or _free_loopback_port
        self._lock = threading.Lock()
        self._proc: subprocess.Popen | None = None
        self._model: LlmModel | None = None
        self._url: str | None = None
        self._baseline: ProviderConfig | None = None
        # A child server must not outlive the engine on a normal exit; `shutdown()` also runs from the
        # Studio screen's stop button. Kill-only exits cannot be caught, which is why stop is explicit.
        atexit.register(self.shutdown)

    # ------------------------------------------------------------- discovery

    def _engine(self) -> Path | None:
        explicit = os.environ.get("KIRA_LLAMA_BACKEND", "").strip()
        if explicit:
            path = Path(explicit).expanduser()
            return path if path.is_file() else None
        if self.engine_dir.is_dir():
            for path in sorted(self.engine_dir.rglob("llama-server*")):
                if not path.is_file() or path.suffix.lower() in (".dll", ".so", ".dylib", ".lib"):
                    continue
                if os.name == "nt" and path.suffix.lower() not in (".exe", ".bat", ".cmd"):
                    continue
                return path
        if self.studio is not None:
            engines = self.studio.llama_engines()
            if engines:
                return engines[0]
        return None

    def models(self) -> list[LlmModel]:
        paths: list[Path] = []
        explicit = os.environ.get("KIRA_LLAMA_MODEL", "").strip()
        if explicit:
            candidate = Path(explicit).expanduser()
            if candidate.is_file() and candidate.suffix.lower() in LLM_EXTENSIONS:
                paths.append(candidate)
        if self.model_dir.is_dir():
            paths += sorted(
                p
                for p in self.model_dir.iterdir()
                if p.is_file() and p.suffix.lower() in LLM_EXTENSIONS
            )
        if self.studio is not None:
            paths += self.studio.llm_models()
        rows: list[LlmModel] = []
        seen: set[Path] = set()
        for path in paths:
            if path in seen:
                continue
            seen.add(path)
            try:
                size = path.stat().st_size
            except OSError:
                size = 0
            rows.append(
                LlmModel(name=path.stem, filename=path.name, path=path, size_bytes=size)
            )
        return rows

    def status(self) -> dict:
        engine = self._engine()
        running = self._proc is not None and self._proc.poll() is None
        if not running and self._proc is not None:
            # It died between requests. Keep the truth instead of a stale "running".
            self._forget_provider()
            self._proc = None
            self._model = None
            self._url = None
        return {
            "running": running,
            "model": self._model.name if running and self._model else None,
            "url": self._url if running else None,
            "engine": str(engine) if engine else None,
            "model_dir": str(self.model_dir),
            "engine_dir": str(self.engine_dir),
            "models": [model.to_wire() for model in self.models()],
            "reason": None
            if engine and self.models()
            else (
                "no llama-server executable: put one in "
                f"{self.engine_dir}, set KIRA_LLAMA_BACKEND, or install Portable AI Studio beside the project"
                if not engine
                else "no GGUF model: put one in "
                f"{self.model_dir}, set KIRA_LLAMA_MODEL, or use a studio's app/llm-models folder"
            ),
        }

    # ---------------------------------------------------------------- control

    def start(self, model_name: str | None = None) -> dict:
        with self._lock:
            models = self.models()
            if not models:
                raise LlmUnavailable(
                    "no GGUF model: put one in "
                    f"{self.model_dir}, set KIRA_LLAMA_MODEL, or use a studio's app/llm-models folder"
                )
            wanted = model_name or models[0].name
            chosen = next((m for m in models if wanted in (m.name, m.filename)), None)
            if chosen is None:
                raise LlmUnavailable(
                    f"no GGUF model named '{wanted}'; see {self.model_dir}"
                )
            if self._proc is not None and self._proc.poll() is None:
                if self._model is not None and self._model.path == chosen.path:
                    return self.status()
                self._stop_locked()
            engine = self._engine()
            if engine is None:
                raise LlmUnavailable(
                    self.status()["reason"] or "no llama-server executable"
                )
            port = self._free_port()
            url = f"http://127.0.0.1:{port}/v1"
            argv = self._argv(engine, chosen, port)
            args, env = argv, self._env(engine)
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
            log = self.log_path.open("ab")
            try:
                proc = self._spawn(args, env, self.log_path)
            except OSError as exc:
                log.close()
                raise LlmStartFailed(
                    f"llama-server could not be started: {exc}"
                ) from exc
            self._proc = proc
            self._model = chosen
            self._url = url
            ready = self._wait_ready(proc, url, log)
            log.close()
            if not ready:
                detail = self._log_tail()
                self._stop_locked()
                raise LlmStartFailed(
                    f"llama-server did not become ready{': ' + detail if detail else ''}"
                )
            self._install_provider(url, chosen)
            return self.status()

    def stop(self) -> dict:
        with self._lock:
            self._stop_locked()
            return self.status()

    def shutdown(self) -> None:
        try:
            self.stop()
        except Exception:  # noqa: BLE001, S110 - shutdown must not raise on the way out
            pass

    # ---------------------------------------------------------------- internals

    def _argv(self, engine: Path, model: LlmModel, port: int) -> list[str]:
        argv = [
            str(engine),
            "-m",
            str(model.path),
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--alias",
            model.name,
            "--ctx-size",
            str(DEFAULT_CONTEXT),
        ]
        # Offload is opt-in, not guessed. `-ngl 99` on a 4 GB card and a 13 GB GGUF is an
        # allocation failure after a long load, and Kira cannot see the VRAM budget. `KIRA_LLAMA_NGL`
        # is the one place to say how many layers the machine can hold; everything else stays on CPU.
        explicit = os.environ.get("KIRA_LLAMA_NGL", "").strip()
        if explicit:
            try:
                layers = max(0, int(explicit))
            except ValueError:
                layers = 0
        else:
            layers = 0
        argv += ["-ngl", str(layers)]
        return argv

    @staticmethod
    def _env(engine: Path) -> dict[str, str]:
        env = dict(os.environ)
        directory = str(engine.parent)
        if os.name == "nt":
            env["PATH"] = directory + os.pathsep + env.get("PATH", "")
        elif os.sys.platform == "darwin":
            env["DYLD_LIBRARY_PATH"] = (
                directory + os.pathsep + env.get("DYLD_LIBRARY_PATH", "")
            )
        else:
            env["LD_LIBRARY_PATH"] = (
                directory + os.pathsep + env.get("LD_LIBRARY_PATH", "")
            )
        return env

    def _spawn_process(
        self, argv: list[str], env: dict[str, str], log_path: Path
    ) -> subprocess.Popen:
        log = log_path.open("ab")
        try:
            return subprocess.Popen(
                argv,
                stdout=log,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                env=env,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
        finally:
            log.close()

    def _wait_ready(self, proc: subprocess.Popen, url: str, log) -> bool:
        deadline = time.monotonic() + DEFAULT_START_TIMEOUT_S
        while time.monotonic() < deadline:
            if proc.poll() is not None:
                return False
            if self._probe(url, 1.0):
                return True
            time.sleep(0.5)
        return False

    @staticmethod
    def _probe_http(url: str, timeout: float) -> bool:
        try:
            with urllib.request.urlopen(f"{url}/models", timeout=timeout) as response:
                return 200 <= response.status < 500
        except (urllib.error.URLError, TimeoutError, OSError):
            return False

    def _log_tail(self, limit: int = 600) -> str:
        try:
            text = self.log_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return ""
        return text.strip()[-limit:]

    def _install_provider(self, url: str, model: LlmModel) -> None:
        existing = self.config.by_name.get(PROVIDER_NAME)
        if existing is None:
            self.config.providers.append(
                ProviderConfig(
                    name=PROVIDER_NAME,
                    kind="openai_compat",
                    base_url=url,
                    models=[model.name],
                    tier="fast",
                    priority=140,
                )
            )
            self._baseline = None
            return
        if self._baseline is None:
            self._baseline = replace(existing)
        existing.base_url = url
        existing.models = [model.name]

    def _forget_provider(self) -> None:
        existing = self.config.by_name.get(PROVIDER_NAME)
        if existing is None:
            return
        if self._baseline is None:
            self.config.providers = [
                p for p in self.config.providers if p.name != PROVIDER_NAME
            ]
        else:
            existing.base_url = self._baseline.base_url
            existing.models = list(self._baseline.models)

    def _stop_locked(self) -> None:
        proc = self._proc
        if proc is not None:
            try:
                if proc.poll() is None:
                    proc.terminate()
                    try:
                        proc.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                        proc.wait(timeout=5)
            except OSError:
                pass
        self._proc = None
        self._model = None
        self._url = None
        self._forget_provider()


def _free_loopback_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])
