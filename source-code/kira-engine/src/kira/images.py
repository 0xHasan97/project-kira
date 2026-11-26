"""Local image generation: stable-diffusion.cpp on this machine, nothing in the cloud.

Kira already speaks to text providers and to two local voice engines. This module is the fourth
door from the Portable AI Studio idea: a folder-backed image workspace. A user drops a
stable-diffusion.cpp executable into ``<data>/images/engines`` and a single-file checkpoint into
``<data>/images/models``; every generation is a child process writing a real PNG and a JSON sidecar
next to it, so the gallery survives a restart and a failed run leaves no half-record.

Nothing here downloads anything. A machine with no executable and no model is not broken — the
status route says exactly what is missing, and a generation attempt refuses with the same sentence
instead of pretending a made-up model exists.
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import re
import secrets
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .config import Config
from .errors import KiraError
from .studio import Studio, find_studio

IMAGE_EXTENSIONS = (".safetensors", ".ckpt", ".gguf")
DEFAULT_SAMPLER = "euler_a"
MAX_PROMPT_CHARS = 4_000
MAX_NEGATIVE_CHARS = 2_000
MIN_SIDE = 64
MAX_SIDE = 2_048
MIN_STEPS = 1
MAX_STEPS = 150
MAX_CFG = 30.0
MAX_GALLERY = 100
DEFAULT_TIMEOUT_S = 600.0
SAMPLER_RE = re.compile(r"^[a-z0-9_]{1,32}$")
NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,120}$")
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


class ImageBackendMissing(KiraError):
    code = "image_backend_missing"
    status = 503


class ImageModelMissing(KiraError):
    code = "model_not_found"
    status = 400


class ImageNotFound(KiraError):
    code = "image_not_found"
    status = 404


class ImageRequestInvalid(KiraError):
    code = "image_request_invalid"
    status = 400


class ImageGenerationFailed(KiraError):
    code = "image_generation_failed"
    status = 502


@dataclass(frozen=True)
class ImageModel:
    name: str
    filename: str
    path: Path
    size_bytes: int

    def to_wire(self) -> dict:
        return {
            "name": self.name,
            "filename": self.filename,
            "size_bytes": self.size_bytes,
            "kind": self.path.suffix.lstrip(".").lower(),
        }


@dataclass(frozen=True)
class ImageOutput:
    name: str
    prompt: str
    negative_prompt: str
    model: str
    steps: int
    cfg_scale: float
    width: int
    height: int
    seed: int
    sampler: str
    created_at: str
    duration_ms: int
    backend: str

    def to_wire(self) -> dict:
        return {
            "name": self.name,
            "url": f"/v1/kira/images/file/{self.name}",
            "prompt": self.prompt,
            "negative_prompt": self.negative_prompt,
            "model": self.model,
            "steps": self.steps,
            "cfg_scale": self.cfg_scale,
            "width": self.width,
            "height": self.height,
            "seed": self.seed,
            "sampler": self.sampler,
            "created_at": self.created_at,
            "duration_ms": self.duration_ms,
            "backend": self.backend,
        }


def _env_path(name: str) -> Path | None:
    raw = os.environ.get(name, "").strip()
    return Path(raw).expanduser() if raw else None


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _as_int(value: object) -> int:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0


def _as_float(value: object) -> float:
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0.0


def _is_executable(path: Path) -> bool:
    if not path.is_file():
        return False
    if os.name == "nt":
        return path.suffix.lower() in (".exe", ".bat", ".cmd")
    return os.access(path, os.X_OK)


def _find_engine(engine_dir: Path, studio: Studio | None = None) -> Path | None:
    """The explicit env path wins, then Kira's engine folder, then a Portable AI Studio backend."""
    explicit = _env_path("KIRA_SD_BACKEND")
    if explicit is not None:
        return explicit if _is_executable(explicit) else None
    if engine_dir.is_dir():
        candidates = [
            path
            for path in engine_dir.rglob("*")
            if _is_executable(path) and path.stem.lower().startswith("sd")
        ]
        # `sd-<backend>.exe` is the HTTP server build; `sd-cli` is the one that takes `-o`.
        candidates.sort(
            key=lambda path: (not path.stem.lower().startswith("sd-cli"), str(path))
        )
        if candidates:
            return candidates[0]
    if studio is not None:
        engines = studio.image_engines()
        if engines:
            return engines[0]
    return None


class ImageStudio:
    """Folder-backed image workspace. No model is bundled, and no request leaves this machine."""

    def __init__(
        self,
        config: Config,
        *,
        runner: Callable[[list[str], float], bytes] | None = None,
    ) -> None:
        self.root = config.data_dir / "images"
        self.engine_dir = self.root / "engines"
        self.model_dir = self.root / "models"
        self.output_dir = self.root / "outputs"
        self.timeout_s = DEFAULT_TIMEOUT_S
        # Kira's own folder is checked first; a Portable AI Studio beside the project supplies the
        # missing half when one exists, without copying a multi-gigabyte checkpoint into `.kira-data`.
        self.studio = find_studio(config.data_dir)
        # One seam for tests: the default runner spawns stable-diffusion.cpp; a test can hand back
        # real PNG bytes without a multi-gigabyte checkpoint on disk.
        self._runner = runner or self._run_cli

    # ---------------------------------------------------------------- status

    def _models(self) -> list[ImageModel]:
        models: list[ImageModel] = []
        default = _env_path("KIRA_SD_MODEL")
        if (
            default is not None
            and default.is_file()
            and default.suffix.lower() in IMAGE_EXTENSIONS
        ):
            models.append(
                ImageModel(
                    name=default.stem,
                    filename=default.name,
                    path=default,
                    size_bytes=default.stat().st_size,
                )
            )
        if self.model_dir.is_dir():
            for path in sorted(self.model_dir.iterdir()):
                if not path.is_file() or path.suffix.lower() not in IMAGE_EXTENSIONS:
                    continue
                if any(item.path == path for item in models):
                    continue
                models.append(
                    ImageModel(
                        name=path.stem,
                        filename=path.name,
                        path=path,
                        size_bytes=path.stat().st_size,
                    )
                )
        if self.studio is not None:
            for path in self.studio.image_models():
                if any(item.path == path for item in models):
                    continue
                try:
                    size = path.stat().st_size
                except OSError:
                    size = 0
                models.append(
                    ImageModel(
                        name=path.stem, filename=path.name, path=path, size_bytes=size
                    )
                )
        return models

    def _engine(self) -> Path | None:
        return _find_engine(self.engine_dir, self.studio)

    def _remote_url(self) -> str | None:
        raw = os.environ.get("KIRA_SD_URL", "").strip().rstrip("/")
        return raw or None

    def _outputs(self) -> list[ImageOutput]:
        if not self.output_dir.is_dir():
            return []
        rows: list[ImageOutput] = []
        pngs = [p for p in self.output_dir.glob("*.png") if p.is_file()]
        pngs.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        for path in pngs[:MAX_GALLERY]:
            sidecar = path.with_suffix(".json")
            data: dict = {}
            if sidecar.is_file():
                try:
                    parsed = json.loads(sidecar.read_text(encoding="utf-8"))
                    data = parsed if isinstance(parsed, dict) else {}
                except (OSError, ValueError):
                    data = {}
            rows.append(
                ImageOutput(
                    name=path.name,
                    prompt=str(data.get("prompt", "")),
                    negative_prompt=str(data.get("negative_prompt", "")),
                    model=str(data.get("model", "")),
                    steps=_as_int(data.get("steps")),
                    cfg_scale=_as_float(data.get("cfg_scale")),
                    width=_as_int(data.get("width")),
                    height=_as_int(data.get("height")),
                    seed=_as_int(data.get("seed")),
                    sampler=str(data.get("sampler", "")),
                    created_at=str(data.get("created_at", "")),
                    duration_ms=_as_int(data.get("duration_ms")),
                    backend=str(data.get("backend", "")),
                )
            )
        return rows

    def status(self) -> dict:
        engine = self._engine()
        remote = self._remote_url()
        models = self._models()
        if remote:
            reason = None
        elif engine is None:
            reason = (
                "no image engine: put stable-diffusion.cpp's executable in "
                f"{self.engine_dir} (sd.exe on Windows), or set KIRA_SD_URL to a running server"
            )
        elif not models:
            reason = (
                "no image model: put a .safetensors, .ckpt or .gguf checkpoint in "
                f"{self.model_dir}, or set KIRA_SD_MODEL to one"
            )
        else:
            reason = None
        return {
            "ready": reason is None,
            "reason": reason,
            "backend": "remote" if remote else ("local" if engine else None),
            "backend_path": None if remote else (str(engine) if engine else None),
            "remote_url": remote,
            "engine_dir": str(self.engine_dir),
            "model_dir": str(self.model_dir),
            "output_dir": str(self.output_dir),
            "models": [model.to_wire() for model in models],
            "outputs": [output.to_wire() for output in self._outputs()],
        }

    # ------------------------------------------------------------ validation

    def _pick_model(self, requested: str | None) -> ImageModel:
        models = self._models()
        if not models:
            raise ImageModelMissing(
                "no image model: put a .safetensors, .ckpt or .gguf checkpoint in "
                f"{self.model_dir}, or set KIRA_SD_MODEL to one"
            )
        if not requested:
            return models[0]
        for model in models:
            if requested in (model.name, model.filename):
                return model
        raise ImageModelMissing(
            f"no image model named '{requested}'; see {self.model_dir}"
        )

    def _require_backend(self) -> tuple[str, str | None, Path | None]:
        remote = self._remote_url()
        if remote:
            return "remote", remote, None
        engine = self._engine()
        if engine is None:
            raise ImageBackendMissing(
                "no image engine: put stable-diffusion.cpp's executable in "
                f"{self.engine_dir} (sd.exe on Windows), or set KIRA_SD_URL to a running server"
            )
        return "local", None, engine

    # ---------------------------------------------------------- generation

    async def generate_async(self, **request: object) -> ImageOutput:
        return await asyncio.to_thread(self.generate, **request)

    def generate(
        self,
        *,
        prompt: object,
        negative_prompt: object = "",
        model: object = None,
        steps: object = 24,
        cfg_scale: object = 7.0,
        width: object = 512,
        height: object = 512,
        seed: object = -1,
        sampler: object = DEFAULT_SAMPLER,
    ) -> ImageOutput:
        text = self._text(prompt, "prompt", MAX_PROMPT_CHARS, required=True)
        negative = self._text(negative_prompt, "negative_prompt", MAX_NEGATIVE_CHARS)
        count = self._int(steps, "steps", MIN_STEPS, MAX_STEPS)
        cfg = self._float(cfg_scale, "cfg_scale", 0.0, MAX_CFG)
        w = self._dimension(width, "width")
        h = self._dimension(height, "height")
        chosen_seed = self._int(seed, "seed", -1, 2**31 - 1)
        method = str(sampler or DEFAULT_SAMPLER)
        if not SAMPLER_RE.match(method):
            raise ImageRequestInvalid(
                f"sampler '{method}' is not a stable-diffusion.cpp method name"
            )
        model_name = None if model in (None, "") else str(model)
        backend_kind, remote, engine = self._require_backend()
        # A remote server owns its own weights, so a local checkpoint is only required for the
        # managed CLI. Both branches still record a model name in the sidecar.
        chosen = None if backend_kind == "remote" else self._pick_model(model_name)
        if chosen_seed < 0:
            chosen_seed = secrets.randbelow(2**31 - 1)

        self.output_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        name = f"img-{stamp}-{secrets.token_hex(3)}.png"
        target = self.output_dir / name
        started = time.monotonic()
        if backend_kind == "remote":
            assert remote is not None
            png = self._generate_remote(
                remote=remote,
                prompt=text,
                negative=negative,
                steps=count,
                cfg=cfg,
                width=w,
                height=h,
                seed=chosen_seed,
                sampler=method,
            )
        else:
            assert engine is not None and chosen is not None
            argv = self._argv(
                engine=engine,
                model=chosen.path,
                output=target,
                prompt=text,
                negative=negative,
                steps=count,
                cfg=cfg,
                width=w,
                height=h,
                seed=chosen_seed,
                sampler=method,
            )
            png = self._runner(argv, self.timeout_s)
        if not png.startswith(PNG_MAGIC):
            raise ImageGenerationFailed(
                "the image engine returned bytes that are not a PNG"
            )
        target.write_bytes(png)
        record = ImageOutput(
            name=name,
            prompt=text,
            negative_prompt=negative,
            model=chosen.filename if chosen is not None else (model_name or "remote"),
            steps=count,
            cfg_scale=cfg,
            width=w,
            height=h,
            seed=chosen_seed,
            sampler=method,
            created_at=_utc_now(),
            duration_ms=int((time.monotonic() - started) * 1000),
            backend=backend_kind,
        )
        sidecar = target.with_suffix(".json")
        sidecar.write_text(
            json.dumps(
                {
                    "prompt": record.prompt,
                    "negative_prompt": record.negative_prompt,
                    "model": record.model,
                    "steps": record.steps,
                    "cfg_scale": record.cfg_scale,
                    "width": record.width,
                    "height": record.height,
                    "seed": record.seed,
                    "sampler": record.sampler,
                    "created_at": record.created_at,
                    "duration_ms": record.duration_ms,
                    "backend": record.backend,
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        return record

    @staticmethod
    def _text(value: object, field: str, limit: int, *, required: bool = False) -> str:
        if value is None:
            value = ""
        if not isinstance(value, str):
            raise ImageRequestInvalid(f"{field} must be a string")
        text = value.strip()
        if required and not text:
            raise ImageRequestInvalid("prompt must not be empty")
        if len(text) > limit:
            raise ImageRequestInvalid(f"{field} must be at most {limit} characters")
        return text

    @staticmethod
    def _int(value: object, field: str, low: int, high: int) -> int:
        if isinstance(value, bool) or not isinstance(value, int):
            raise ImageRequestInvalid(f"{field} must be an integer")
        if not (low <= value <= high):
            raise ImageRequestInvalid(f"{field} must be between {low} and {high}")
        return value

    @staticmethod
    def _float(value: object, field: str, low: float, high: float) -> float:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ImageRequestInvalid(f"{field} must be a number")
        number = float(value)
        if not (low <= number <= high):
            raise ImageRequestInvalid(f"{field} must be between {low} and {high}")
        return number

    @staticmethod
    def _dimension(value: object, field: str) -> int:
        if isinstance(value, bool) or not isinstance(value, int):
            raise ImageRequestInvalid(f"{field} must be an integer")
        if not (MIN_SIDE <= value <= MAX_SIDE) or value % 8:
            raise ImageRequestInvalid(
                f"{field} must be a multiple of 8 between {MIN_SIDE} and {MAX_SIDE}"
            )
        return value

    @staticmethod
    def _argv(
        *,
        engine: Path,
        model: Path,
        output: Path,
        prompt: str,
        negative: str,
        steps: int,
        cfg: float,
        width: int,
        height: int,
        seed: int,
        sampler: str,
    ) -> list[str]:
        argv = [
            str(engine),
            "-m",
            str(model),
            "-p",
            prompt,
            "--steps",
            str(steps),
            "--cfg-scale",
            f"{cfg:g}",
            "-W",
            str(width),
            "-H",
            str(height),
            "-s",
            str(seed),
            "--sampling-method",
            sampler,
            "-o",
            str(output),
        ]
        if negative:
            argv[argv.index("--steps") : argv.index("--steps")] = ["-n", negative]
        return argv

    def _run_cli(self, argv: list[str], timeout_s: float) -> bytes:
        try:
            completed = subprocess.run(  # noqa: S603 - argv is built here, never a shell string
                argv,
                capture_output=True,
                timeout=timeout_s,
                check=False,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
        except FileNotFoundError as exc:
            raise ImageBackendMissing(
                f"the image engine could not be started: {exc}"
            ) from exc
        except subprocess.TimeoutExpired as exc:
            raise ImageGenerationFailed(
                f"the image engine did not finish within {int(timeout_s)} seconds"
            ) from exc
        if completed.returncode != 0:
            detail = (
                (completed.stderr or completed.stdout or b"")
                .decode("utf-8", "replace")
                .strip()
            )
            detail = detail[-800:] if detail else f"exit code {completed.returncode}"
            raise ImageGenerationFailed(f"the image engine failed: {detail}")
        output = Path(argv[-1])
        try:
            return output.read_bytes()
        except OSError as exc:
            raise ImageGenerationFailed(
                f"the image engine wrote no image: {exc}"
            ) from exc

    def _generate_remote(
        self,
        *,
        remote: str,
        prompt: str,
        negative: str,
        steps: int,
        cfg: float,
        width: int,
        height: int,
        seed: int,
        sampler: str,
    ) -> bytes:
        payload = json.dumps(
            {
                "prompt": prompt,
                "negative_prompt": negative,
                "width": width,
                "height": height,
                "steps": steps,
                "cfg_scale": cfg,
                "seed": seed,
                "sampler_name": sampler,
                "batch_size": 1,
            }
        ).encode("utf-8")
        request = urllib.request.Request(
            f"{remote}/sdapi/v1/txt2img",
            data=payload,
            headers={"content-type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_s) as response:  # noqa: S310 - loopback URL only
                raw = response.read()
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise ImageGenerationFailed(
                f"the image server at {remote} did not answer: {exc}"
            ) from exc
        try:
            body = json.loads(raw)
            item = (body.get("data") or [{}])[0]
            encoded = item.get("b64_json")
        except (ValueError, AttributeError, IndexError) as exc:
            raise ImageGenerationFailed(
                "the image server returned an unrecognised body"
            ) from exc
        if not isinstance(encoded, str) or not encoded:
            raise ImageGenerationFailed("the image server returned no image")
        try:
            return base64.b64decode(encoded.split(",", 1)[-1], validate=True)
        except (ValueError, TypeError) as exc:
            raise ImageGenerationFailed(
                "the image server returned invalid base64"
            ) from exc

    # -------------------------------------------------------------- gallery

    def file_path(self, name: str) -> Path:
        if not NAME_RE.match(name):
            raise ImageNotFound("image name is not one this workspace wrote")
        path = self.output_dir / name
        if not path.is_file():
            raise ImageNotFound(f"no generated image named '{name}'")
        return path

    def delete(self, name: str) -> None:
        path = self.file_path(name)
        try:
            path.unlink()
        except OSError as exc:
            raise ImageGenerationFailed(f"could not delete '{name}': {exc}") from exc
        sidecar = path.with_suffix(".json")
        if sidecar.is_file():
            try:
                sidecar.unlink()
            except OSError:
                # The PNG is gone, which is what delete promised. A stale sidecar is unreachable
                # from the gallery anyway, and turning that into a failed delete would be a lie.
                pass


def register_image_tool(registry, studio: ImageStudio) -> None:
    """Give the agent the same workspace the Images screen uses, as one approval-gated tool."""

    async def image_generate(args: dict) -> str:
        record = await studio.generate_async(
            prompt=args.get("prompt"),
            negative_prompt=args.get("negative_prompt", ""),
            model=args.get("model"),
            steps=args.get("steps", 24),
            cfg_scale=args.get("cfg_scale", 7.0),
            width=args.get("width", 512),
            height=args.get("height", 512),
            seed=args.get("seed", -1),
            sampler=args.get("sampler", DEFAULT_SAMPLER),
        )
        return json.dumps(record.to_wire(), ensure_ascii=False)

    from .tools import ToolDef

    registry.register(
        ToolDef(
            name="image_generate",
            description=(
                "Generate one image locally with stable-diffusion.cpp and save it in the Images "
                "gallery. Returns the file name and the settings that made it."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "prompt": {"type": "string", "description": "what to draw"},
                    "negative_prompt": {
                        "type": "string",
                        "description": "what to avoid",
                    },
                    "model": {
                        "type": "string",
                        "description": "a checkpoint name from the images status",
                    },
                    "steps": {"type": "integer", "default": 24},
                    "cfg_scale": {"type": "number", "default": 7.0},
                    "width": {"type": "integer", "default": 512},
                    "height": {"type": "integer", "default": 512},
                    "seed": {
                        "type": "integer",
                        "default": -1,
                        "description": "-1 picks one",
                    },
                    "sampler": {"type": "string", "default": DEFAULT_SAMPLER},
                },
                "required": ["prompt"],
            },
            handler=image_generate,
            risk="write",
            summary=lambda a: str(a.get("prompt", ""))[:80],
        )
    )


def default_engine_name() -> str:
    """What the install hint should call the executable on this machine."""
    return "sd.exe" if sys.platform == "win32" else "sd"
