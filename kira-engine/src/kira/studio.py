"""Portable AI Studio as a local component source for Kira.

Portable AI Studio ships four runtimes in one folder: stable-diffusion.cpp, llama.cpp,
whisper.cpp, and a Kokoro TTS runner, each with the model folders beside it. Kira already had
its own voice stack and image workspace; this module lets those features reuse the studio's
binaries and checkpoints without copying tens of gigabytes or making the engine depend on the
folder being there.

Discovery is intentionally conservative: a candidate is a studio only when it has the server
marker and the four ``app`` folders. Nothing is downloaded, nothing is written into the studio
folder, and a machine without one still serves chat.
"""

from __future__ import annotations

import json
import os
import shutil
from dataclasses import dataclass
from pathlib import Path

STUDIO_DIR_ENV = "KIRA_STUDIO_DIR"
STUDIO_MARKER = Path("scripts") / "server" / "serve.cjs"
IMAGE_EXTENSIONS = (".safetensors", ".ckpt", ".gguf")
LLM_EXTENSIONS = (".gguf",)
STT_EXTENSIONS = (".bin",)

IMAGE_BACKEND_DIRS = ("vulkan", "cuda", "cpu")
LLM_BACKEND_DIRS = ("vulkan", "cuda", "hip", "cpu")
SPEECH_BACKEND_DIRS = ("vulkan", "cpu")

PLATFORM_DIRS = {"win32": "win", "linux": "linux", "darwin": "mac"}


def _platform() -> str:
    return PLATFORM_DIRS.get(os.sys.platform, "linux")


# `llama-server*` also matches the shared library and its import library. Those are not launchable, and
# a status that offered `llama-server-impl.dll` as the engine would make the start button fail on click.
NOT_EXECUTABLE = (".dll", ".so", ".dylib", ".lib", ".exp", ".pdb")
WINDOWS_EXECUTABLE = (".exe", ".bat", ".cmd")


def _executables(directory: Path, stems: tuple[str, ...]) -> list[Path]:
    """Executables in preference order: the first matching stem in ``stems``, then its siblings."""
    found: list[Path] = []
    if not directory.is_dir():
        return found
    for stem in stems:
        for candidate in sorted(directory.glob(f"{stem}*")):
            if not candidate.is_file() or candidate.suffix.lower() in NOT_EXECUTABLE:
                continue
            if os.name == "nt":
                if candidate.suffix.lower() not in WINDOWS_EXECUTABLE:
                    continue
            elif not os.access(candidate, os.X_OK):
                continue
            found.append(candidate)
            break
    return found


def _models(directory: Path, extensions: tuple[str, ...]) -> list[Path]:
    if not directory.is_dir():
        return []
    return sorted(
        path
        for path in directory.iterdir()
        if path.is_file() and path.suffix.lower() in extensions
    )


def candidate_roots(data_dir: Path, *, cwd: Path | None = None) -> list[Path]:
    """Everywhere a studio may sit, in priority order: explicit env, data dir, repo parent, cwd."""
    roots: list[Path] = []
    explicit = os.environ.get(STUDIO_DIR_ENV, "").strip()
    if explicit:
        roots.append(Path(explicit).expanduser())
    roots.append(data_dir / "studio")
    for base in (data_dir, *data_dir.parents):
        roots.append(base / "Portable-Local-Studio-main")
        roots.append(base / "Portable-AI-Studio")
    if cwd is not None:
        roots.append(cwd / "Portable-Local-Studio-main")
    seen: set[Path] = set()
    unique: list[Path] = []
    for root in roots:
        try:
            resolved = root.resolve()
        except OSError:
            continue
        if resolved in seen:
            continue
        seen.add(resolved)
        unique.append(resolved)
    return unique


def _looks_like_studio(root: Path) -> bool:
    return (root / STUDIO_MARKER).is_file() and (root / "app").is_dir()


@dataclass(frozen=True)
class Studio:
    root: Path

    # ---------------------------------------------------------------- app directories

    @property
    def app(self) -> Path:
        return self.root / "app"

    @property
    def image_models_dir(self) -> Path:
        return self.app / "models"

    @property
    def llm_models_dir(self) -> Path:
        return self.app / "llm-models"

    @property
    def speech_models_dir(self) -> Path:
        return self.app / "speech-models"

    @property
    def tts_models_dir(self) -> Path:
        return self.app / "tts-models"

    @property
    def tts_cache_dir(self) -> Path:
        return self.app / "tts-cache"

    # ---------------------------------------------------------------- binaries

    def image_engines(self) -> list[Path]:
        base = self.app / "backend" / _platform()
        found: list[Path] = []
        for backend in IMAGE_BACKEND_DIRS:
            directory = base / backend
            if not directory.is_dir():
                continue
            # The studio ships both `sd-vulkan.exe` (HTTP server only) and `sd-cli.exe` (writes
            # `-o`). Kira drives the CLI, so the CLI comes first; a build with only the server
            # binary is still reported and the refusal names the missing output flag at start.
            found += _executables(directory, ("sd-cli", "sd"))
        return found

    def llama_engines(self) -> list[Path]:
        base = self.app / "llm-backend" / _platform()
        found: list[Path] = []
        for backend in LLM_BACKEND_DIRS:
            found += _executables(base / backend, ("llama-server",))
        return found

    def whisper_engines(self) -> list[Path]:
        base = self.app / "speech-backend" / _platform()
        found: list[Path] = []
        for backend in SPEECH_BACKEND_DIRS:
            found += _executables(base / backend, ("whisper-cli",))
        # The top-level fallback some studio builds use.
        found += _executables(base, ("whisper-cli",))
        return found

    def kokoro_worker(self) -> Path:
        return self.root / "scripts" / "workers" / "tts-kokoro-worker.mjs"

    def tts_runtime(self) -> Path:
        return self.app / "tts-runtime"

    def node(self) -> Path | None:
        local = (
            self.app
            / "tools"
            / f"node-{_platform()}"
            / ("node.exe" if os.name == "nt" else "node")
        )
        if local.is_file():
            return local
        found = shutil.which("node")
        return Path(found) if found else None

    def kokoro_config(self) -> dict:
        manifest = self.tts_models_dir / "kokoro-onnx-q8.json"
        if manifest.is_file():
            try:
                parsed = json.loads(manifest.read_text(encoding="utf-8"))
                return parsed if isinstance(parsed, dict) else {}
            except (OSError, ValueError):
                return {}
        return {}

    # ---------------------------------------------------------------- models

    def image_models(self) -> list[Path]:
        return _models(self.image_models_dir, IMAGE_EXTENSIONS)

    def llm_models(self) -> list[Path]:
        return _models(self.llm_models_dir, LLM_EXTENSIONS)

    def speech_models(self) -> list[Path]:
        return _models(self.speech_models_dir, STT_EXTENSIONS)

    # ---------------------------------------------------------------- status

    def status(self) -> dict:
        image_engines = self.image_engines()
        llama_engines = self.llama_engines()
        whisper_engines = self.whisper_engines()
        node = self.node()
        kokoro = (
            self.kokoro_worker().is_file()
            and (self.tts_runtime() / "node_modules" / "kokoro-js").is_dir()
        )
        return {
            "root": str(self.root),
            "image": {
                "available": bool(image_engines and self.image_models()),
                "engine": str(image_engines[0]) if image_engines else None,
                "detail": (
                    f"{len(self.image_models())} checkpoints · stable-diffusion.cpp"
                    if image_engines
                    else "no stable-diffusion.cpp executable in app/backend"
                ),
                "models": [_model_wire(path, "image") for path in self.image_models()],
            },
            "llm": {
                "available": bool(llama_engines and self.llm_models()),
                "engine": str(llama_engines[0]) if llama_engines else None,
                "detail": (
                    f"{len(self.llm_models())} GGUF models · llama.cpp"
                    if llama_engines
                    else "no llama-server executable in app/llm-backend"
                ),
                "models": [_model_wire(path, "llm") for path in self.llm_models()],
            },
            "stt": {
                "available": bool(whisper_engines and self.speech_models()),
                "engine": str(whisper_engines[0]) if whisper_engines else None,
                "detail": (
                    f"{len(self.speech_models())} whisper.cpp models"
                    if whisper_engines
                    else "no whisper-cli executable in app/speech-backend"
                ),
                "models": [_model_wire(path, "stt") for path in self.speech_models()],
            },
            "tts": {
                "available": bool(node and kokoro),
                "engine": str(node) if node else None,
                "detail": (
                    "Kokoro ONNX runtime is installed; the model downloads on first use"
                    if kokoro and node
                    else "Kokoro runtime or node is missing in app/tts-runtime"
                ),
                "models": [
                    _model_wire(path, "tts")
                    for path in _models(self.tts_models_dir, (".json",))
                ],
            },
        }


def _model_wire(path: Path, kind: str) -> dict:
    try:
        size = path.stat().st_size
    except OSError:
        size = 0
    return {
        "name": path.stem,
        "filename": path.name,
        "path": str(path),
        "size_bytes": size,
        "kind": kind,
    }


def find_studio(data_dir: Path, *, cwd: Path | None = None) -> Studio | None:
    """The first candidate that is really a studio, or None. Never raises on an unreadable folder."""
    for root in candidate_roots(Path(data_dir), cwd=cwd):
        try:
            if _looks_like_studio(root):
                return Studio(root)
        except OSError:
            continue
    return None
