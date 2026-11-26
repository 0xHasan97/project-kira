"""One-click Kira launcher.

Double-click run-kira.bat, or run `python run_kira.py` from anywhere. It is plain
stdlib so any Python 3.9+ can run it; it creates the engine venv, builds the chat
UI if needed (or if the bundle on disk speaks a different API revision than this
engine), starts the engine, and opens your browser once the engine answers
/healthz. Provider API keys are entered in the app's Providers screen, never at
this console.

Flags: --port N  --no-browser  --rebuild  --window  --companion
On first run it prints the browser token and the dashboard confirm secret once
each; both come from the Windows Credential Locker (service `kira`), and
`kira-engine token` reprints them. The browser opens already connected using the
token, which is consumed from the URL fragment and removed from history. With
KIRA_VAULT=memory they are never stored, so the engine prints each one on its own
stderr instead and both die with it.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parent
ENGINE = ROOT / "kira-engine"
CHAT = ROOT / "kira-chat"
BOOTSTRAP_FLAG = "KIRA_LAUNCHER_BOOTSTRAPPED"
HEALTH_TIMEOUT_S = 30.0

# Honour an explicit KIRA_DATA_DIR, otherwise keep Kira's own .kira-data next to this
# script; it is exported below so the engine resolves the same directory from any cwd.
DATA_DIR = Path(os.environ.get("KIRA_DATA_DIR") or ROOT / ".kira-data")


def venv_python() -> Path:
    if os.name == "nt":
        return ENGINE / ".venv" / "Scripts" / "python.exe"
    return ENGINE / ".venv" / "bin" / "python"


def say(msg: str) -> None:
    print(f"[kira] {msg}", flush=True)


def fail(msg: str, code: int = 1) -> int:
    say(f"ERROR: {msg}")
    if os.name == "nt" and sys.stdin is not None and sys.stdin.isatty():
        input("Press Enter to close this window...")
    return code


def run_stream(cmd: list[str], cwd: Path) -> int:
    """Run a build step with its output visible; a silent failure looks like a hang."""
    say("$ " + " ".join(str(part) for part in cmd))
    return subprocess.call(cmd, cwd=str(cwd))


# ---------------------------------------------------------------- venv


def ensure_venv() -> tuple[bool, str | None]:
    """Return (ready, python). Builds the venv and installs the engine when absent."""
    py = venv_python()
    if py.exists():
        return True, str(py)

    say("first run: creating the engine virtualenv (about a minute)...")
    if subprocess.call([sys.executable, "-m", "venv", str(ENGINE / ".venv")]) != 0:
        return False, None
    if not py.exists():
        return False, None
    if run_stream([str(py), "-m", "pip", "install", "-e", ".[dev]"], ENGINE) != 0:
        return False, None
    return True, str(py)


def reexec_under_venv(py: str, argv: list[str]) -> int:
    env = dict(os.environ, **{BOOTSTRAP_FLAG: "1"})
    return subprocess.call([py, str(Path(__file__).resolve()), *argv], env=env)


# ---------------------------------------------------------------- config + keys


def engine_import_root() -> None:
    """The engine lives in src/; installed editable, but keep the launcher usable raw."""
    src = ENGINE / "src"
    if src.exists() and str(src) not in sys.path:
        sys.path.insert(0, str(src))


# ---------------------------------------------------------------- chat bundle


def engine_versions() -> dict:
    """What the engine will serve, read from its source.

    Returns {} when the engine cannot be imported: the version check must never block a launch, and
    an unreadable engine is a warning the user will see in the engine log anyway.
    """
    try:
        engine_import_root()
        from kira.contracts import API_PREFIX, API_VERSION, CONTRACT_VERSION
    except Exception as exc:  # noqa: BLE001 - any import failure means "carry on with the bundle we have"
        say(f"WARNING: cannot read the engine's API version ({type(exc).__name__}: {exc}); serving the bundle as built")
        return {}
    return {"api_prefix": API_PREFIX, "api_version": API_VERSION, "contract_version": CONTRACT_VERSION}


def bundle_stamp(path: Path) -> str:
    """The versions the bundle on disk was built for, or why there is nothing to compare."""
    if not path.exists():
        return "no kira-build.json stamp"
    try:
        read = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return f"unreadable stamp ({exc})"
    return f"api /v{read.get('api_version')}, contract v{read.get('contract_version')}"


def _stamp_matches(path: Path, want: dict) -> bool:
    try:
        read = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return all(read.get(key) == value for key, value in want.items())


def _healthz_versions(body: bytes) -> str:
    """The versions a live engine reports, phrased for the console. A body that is not the contract's
    is still a live engine, so this degrades to '' rather than turning a good start into a traceback."""
    try:
        read = json.loads(body.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return ""
    if not isinstance(read, dict) or "api_version" not in read or "contract_version" not in read:
        return ""
    return f" (api /v{read['api_version']}, contract v{read['contract_version']})"


def ensure_chat_bundle(rebuild: bool) -> None:
    index = CHAT / "dist" / "index.html"
    stamp = CHAT / "dist" / "kira-build.json"
    want = engine_versions()
    if index.exists() and not rebuild:
        # A bundle older than the engine is the failure a double-click used to hide: the launcher served
        # it forever and the UI broke with no explanation. The build step writes the stamp it was built to.
        if not want or _stamp_matches(stamp, want):
            return
        say(f"chat bundle is stale ({bundle_stamp(stamp)}; this engine is {want['api_prefix']} contract v{want['contract_version']}) - rebuilding")
    npm = shutil.which("npm.cmd" if os.name == "nt" else "npm")
    if not npm:
        say("WARNING: npm not found, so /chat/ will not be served - the API still works")
        return
    if not (CHAT / "node_modules").exists() and run_stream([npm, "install"], CHAT) != 0:
        say("WARNING: npm install failed; /chat/ unavailable, the API still works")
        return
    if run_stream([npm, "run", "build"], CHAT) != 0:
        say("WARNING: chat build failed; /chat/ unavailable, the API still works")


# ---------------------------------------------------------------- serve


def connect_url(base: str, token: str = "") -> str:
    """The browser URL, carrying the bearer token in the fragment.

    A fragment never reaches the engine or its access log. The UI consumes it before
    React mounts, stores it next to the other preferences, and replaces the history
    entry, so the token is not left in the address bar.
    """
    url = f"{base}/chat/"
    if token:
        url += f"#/chat?token={quote(token, safe='')}"
    return url


def open_when_ready(base: str, browse: bool, token: str = "") -> None:
    chat = f"{base}/chat/"
    deadline = time.time() + HEALTH_TIMEOUT_S
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f"{base}/healthz", timeout=1.0) as resp:
                if resp.status == 200:
                    say(f"engine is up at {base}{_healthz_versions(resp.read())}")
                    if browse:
                        webbrowser.open(connect_url(base, token))
                        say(f"opened {chat} - connected")
                    else:
                        say(f"chat UI: {chat}")
                    # One line for both branches: the dashboard is why most people start Kira now, and
                    # a route the launcher never mentions is a route nobody finds.
                    say("screens: #/overview #/providers #/models #/sessions - each write re-asks for the confirm secret")
                    return
        except (urllib.error.URLError, OSError):
            time.sleep(0.3)
    say(f"WARNING: /healthz did not answer within {HEALTH_TIMEOUT_S:.0f}s - check the engine log above")


def ensure_desktop_extras() -> bool:
    """`--window` needs three packages the plain launcher install never asked for."""
    import importlib.util

    if all(importlib.util.find_spec(name) for name in ("webview", "pystray", "PIL")):
        return True
    say("installing the desktop-window extras (gui packages, one time)...")
    return run_stream([sys.executable, "-m", "pip", "install", "-e", ".[desktop]"], ENGINE) == 0


def serve(args: argparse.Namespace) -> int:
    ok, py = ensure_venv()
    if not ok:
        return fail("could not create kira-engine/.venv - install Python 3.12 and retry")
    if py and os.environ.get(BOOTSTRAP_FLAG) != "1":
        return reexec_under_venv(py, sys.argv[1:])

    # Inside the venv interpreter from here on.
    os.environ.setdefault("KIRA_DATA_DIR", str(DATA_DIR))
    # The engine finds the UI relative to the data dir, so a relocated .kira-data must
    # still point it back at this checkout's bundle.
    os.environ.setdefault("KIRA_CHAT_DIST", str(CHAT / "dist"))
    engine_import_root()
    from kira.config import load_config, write_sample_config
    from kira.vault import Vault

    config_path = DATA_DIR / "config.yaml"
    if not config_path.exists():
        write_sample_config(DATA_DIR)
        say(f"wrote starter config to {config_path}")

    config = load_config(DATA_DIR)
    say(f"providers: {', '.join(p.name for p in config.providers) or 'none'}")
    vault = Vault()
    say(f"secrets come from the {vault.location}; engine data dir {DATA_DIR}")

    token = ""
    if vault.backend == "keyring":
        # Shared store: the token minted here is the same one the engine will read.
        token, created = vault.get_or_create_engine_token()
        say(f"connect-token for the browser ({'created now' if created else 'already stored'}): {token}")
        confirm, confirm_created = vault.get_or_create_confirm()
        say(f"confirm secret for dashboard writes ({'created now' if confirm_created else 'already stored'}): {confirm}")
    else:
        say("secrets: copy the 'engine token' and 'confirm secret' lines below (a memory vault is per-process)")

    ensure_chat_bundle(args.rebuild)

    port = args.port or config.port
    base = f"http://{config.host}:{port}"
    # Without this the engine's em-dashes turn into mojibake on a cp1252 Windows console.
    child_env = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8")

    if args.window:
        # The window command runs the engine itself; opening a tab as well would show the same page twice.
        if not ensure_desktop_extras():
            return fail('could not install the desktop extras - run: pip install -e ".[desktop]" inside kira-engine')
        say(f"starting the Kira window on {base} - closing it to the tray keeps the engine running")
        command = [sys.executable, "-X", "utf8", "-m", "kira", "desktop", "--port", str(port)]
        if args.companion:
            command.append("--companion")
        child = subprocess.Popen(command, cwd=str(ENGINE), env=child_env)
        try:
            return child.wait()
        except KeyboardInterrupt:
            say("stopping engine...")
            child.terminate()
            try:
                child.wait(10)
            except subprocess.TimeoutExpired:
                child.kill()
            return 0

    say(f"serving {base} (loopback only) - Ctrl+C stops")
    child = subprocess.Popen(
        [sys.executable, "-X", "utf8", "-m", "kira", "serve", "--port", str(port)], cwd=str(ENGINE), env=child_env
    )
    try:
        open_when_ready(base, browse=not args.no_browser, token=token)
        return child.wait()
    except KeyboardInterrupt:
        say("stopping engine...")
        child.terminate()
        try:
            child.wait(10)
        except subprocess.TimeoutExpired:
            child.kill()
        return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="One-click Kira launcher")
    parser.add_argument("--port", type=int)
    parser.add_argument("--no-browser", action="store_true", help="start the engine without opening a tab")
    parser.add_argument("--rebuild", action="store_true", help="force npm run build for the chat UI")
    parser.add_argument("--window", action="store_true", help="run inside a native desktop window instead of a browser tab")
    parser.add_argument(
        "--companion",
        action="store_true",
        help="with --window, also open the always-on-top desktop card",
    )
    args = parser.parse_args()
    if args.companion:
        # The card is a second window, not a replacement for the first: asking for one asks for the desktop.
        args.window = True
    try:
        return serve(args)
    except Exception as exc:  # noqa: BLE001 - a double-click needs a readable error, not a traceback
        return fail(f"{type(exc).__name__}: {exc}")


if __name__ == "__main__":
    raise SystemExit(main())
