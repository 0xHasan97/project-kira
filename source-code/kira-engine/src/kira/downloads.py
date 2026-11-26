"""Fetch one model file from Hugging Face into the folder Kira already reads.

Portable AI Studio's model manager is a paste-a-URL downloader. This is the same door with the
brakes on: only the model kinds Kira can actually load, only a filename that matches the URL's
last segment, only Hugging Face (or loopback for tests), a hard byte ceiling, and a `.part` file
that is renamed only after the last chunk. Nothing is unpacked and no archive is accepted.
"""

from __future__ import annotations

import os
import re
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from .errors import KiraError

DOWNLOAD_KINDS = ("llm", "image", "stt")
KIND_EXTENSIONS = {
    "llm": (".gguf",),
    "image": (".safetensors", ".ckpt", ".gguf"),
    "stt": (".bin",),
}
ALLOWED_HOSTS = {"huggingface.co", "hf.co", "huggingface.com"}
LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}
DEFAULT_MAX_BYTES = 20 * 1024 * 1024 * 1024
FILENAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,180}$")
CHUNK = 1024 * 1024


class DownloadRefused(KiraError):
    code = "download_refused"
    status = 400


class DownloadFailed(KiraError):
    code = "download_failed"
    status = 502


def target_dir(data_dir: Path, kind: str) -> Path:
    if kind == "llm":
        return data_dir / "llm" / "models"
    if kind == "image":
        return data_dir / "images" / "models"
    if kind == "stt":
        return data_dir / "voice" / "models"
    raise DownloadRefused(f"kind must be one of {list(DOWNLOAD_KINDS)}")


def _max_bytes() -> int:
    raw = os.environ.get("KIRA_DOWNLOAD_MAX_BYTES", "").strip()
    if not raw:
        return DEFAULT_MAX_BYTES
    try:
        value = int(raw)
    except ValueError as exc:
        raise DownloadRefused("KIRA_DOWNLOAD_MAX_BYTES must be an integer") from exc
    return value if value > 0 else DEFAULT_MAX_BYTES


def check_url(kind: str, url: str, filename: str | None = None) -> tuple[str, str]:
    """Return (name, filename) after every refusal this door makes, before a socket is opened."""
    if kind not in DOWNLOAD_KINDS:
        raise DownloadRefused(f"kind must be one of {list(DOWNLOAD_KINDS)}")
    parsed = urllib.parse.urlparse(url.strip())
    if parsed.scheme not in ("http", "https"):
        raise DownloadRefused("url must be http(s)")
    host = (parsed.hostname or "").lower()
    loopback = host in LOOPBACK_HOSTS
    if host not in ALLOWED_HOSTS and not loopback:
        raise DownloadRefused(
            "only huggingface.co links are accepted (or a loopback URL for a local mirror)"
        )
    if parsed.scheme != "https" and not loopback:
        raise DownloadRefused("a remote model must be downloaded over https")
    name = (filename or "").strip() or Path(urllib.parse.unquote(parsed.path)).name
    if not FILENAME_RE.match(name):
        raise DownloadRefused(
            "filename must be a plain file name: letters, digits, dot, dash and underscore only"
        )
    suffix = Path(name).suffix.lower()
    if suffix not in KIND_EXTENSIONS[kind]:
        raise DownloadRefused(
            f"{kind} needs one of {list(KIND_EXTENSIONS[kind])}, not '{suffix or 'no extension'}'"
        )
    url_name = Path(urllib.parse.unquote(parsed.path)).name
    if filename and url_name != name:
        raise DownloadRefused(
            f"filename '{name}' does not match the URL's last segment '{url_name}'"
        )
    return name, name


def download_model(
    data_dir: Path, kind: str, url: str, filename: str | None = None
) -> dict:
    saved_name = check_url(kind, url, filename)[1]
    directory = target_dir(data_dir, kind)
    directory.mkdir(parents=True, exist_ok=True)
    final = directory / saved_name
    part = directory / f"{saved_name}.part"
    limit = _max_bytes()
    request = urllib.request.Request(
        url.strip(),
        headers={"User-Agent": "kira-engine/model-downloader"},
    )
    written = 0
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            expected = int(response.headers.get("content-length") or 0)
            if expected and expected > limit:
                raise DownloadRefused(
                    f"the server says {expected} bytes; the ceiling is {limit} (KIRA_DOWNLOAD_MAX_BYTES)"
                )
            with part.open("wb") as out:
                while True:
                    chunk = response.read(CHUNK)
                    if not chunk:
                        break
                    written += len(chunk)
                    if written > limit:
                        raise DownloadRefused(
                            f"download passed the ceiling of {limit} bytes (KIRA_DOWNLOAD_MAX_BYTES)"
                        )
                    out.write(chunk)
    except DownloadRefused:
        part.unlink(missing_ok=True)
        raise
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        part.unlink(missing_ok=True)
        raise DownloadFailed(f"the download did not finish: {exc}") from exc
    if written == 0:
        part.unlink(missing_ok=True)
        raise DownloadFailed("the server returned an empty file")
    part.replace(final)
    return {
        "name": Path(saved_name).stem,
        "filename": saved_name,
        "kind": kind,
        "bytes": written,
        "path": str(final),
    }
