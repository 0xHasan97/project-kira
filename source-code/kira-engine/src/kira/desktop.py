"""The desktop shell: the engine on a thread, a WebView2 window, a tray.

`kira-engine desktop` is the same engine and the same vault as `serve`, with a native window
instead of a browser tab. The window is the built chat bundle at `/chat/`, so the UI is not a
second copy of anything; what this module adds is the window, the tray, the single-instance
lock, and the one thing a browser tab cannot do: hand the window its token without a paste.

The token is written into the window's `localStorage` on the first load, and pywebview runs
with `private_mode` (its default), so that copy lives in memory for the life of the window and
never in a WebView2 profile on disk. The confirm secret is never handed over: writes re-ask.
"""

from __future__ import annotations

import hashlib
import json
import threading
import time
import urllib.error
import urllib.request
import webbrowser
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable

DEFAULT_WIDTH = 1280
DEFAULT_HEIGHT = 860
MIN_WIDTH = 720
MIN_HEIGHT = 520
PLACEMENT_FILE = "desktop.json"
#: How long the window may stay hidden if the second `loaded` never arrives.
SHOW_FALLBACK_S = 8.0
#: The window boots here and then navigates to `/chat/`. The two must differ: WebView2 raises no
#: second `loaded` for a navigation to the URL already open, and the window would stay hidden.
BOOT_QUERY = "?window=1"
#: The main window's section in `desktop.json`. The companion keeps its own beside it, because two
#: windows that share a file but not a shape cannot share one set of coordinates.
MAIN_KEY = "main"
#: `GetWindowLongW`/`SetWindowLongW` index for the extended style word.
GWL_EXSTYLE = -20
#: The only fields the geometry file may hold. Anything else a third party writes into it is dropped
#: on the next save, which is how this file stays free of secrets without anyone having to remember to
#: keep it that way.
GEOMETRY_FIELDS = ("x", "y", "width", "height", "maximized")


def _read_sections(path: Path) -> dict[str, dict]:
    """The geometry sections in `desktop.json`, one per window.

    A file from before the companion carries the main window's fields at the top level. That shape is
    read as the main section, so an existing install keeps the window it had — and is rewritten in
    sections the next time either window closes.
    """
    try:
        read = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(read, dict):
        return {}
    sections = {key: value for key, value in read.items() if isinstance(value, dict)}
    if sections:
        return sections
    return {MAIN_KEY: read} if read else {}


def read_placement(path: Path, key: str, default: tuple[int, int], minimum: tuple[int, int]) -> Placement:
    """One window's geometry, with its own size on disk and its own floor."""
    read = _read_sections(path).get(key, {})

    def number(field: str, fallback: int) -> int:
        value = read.get(field)
        if not isinstance(value, int) or isinstance(value, bool):
            return fallback
        return max(value, minimum[0] if field == "width" else minimum[1])

    def coordinate(field: str) -> int | None:
        value = read.get(field)
        return value if isinstance(value, int) and not isinstance(value, bool) else None

    return Placement(
        x=coordinate("x"),
        y=coordinate("y"),
        width=number("width", default[0]),
        height=number("height", default[1]),
        maximized=bool(read.get("maximized")),
    )


def write_placement(path: Path, key: str, placement: Placement) -> None:
    """Set one window's section, keeping the others' geometry and nothing that is not geometry."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    sections = {name: {field: value for field, value in section.items() if field in GEOMETRY_FIELDS} for name, section in _read_sections(path).items()}
    sections[key] = asdict(placement)
    path.write_text(json.dumps(sections), encoding="utf-8")


def bootstrap_script(base: str, token: str) -> str:
    """The one line of JS that spares the user the connect gate — and nothing more."""
    return (
        f"localStorage.setItem(\"kira.token\", {json.dumps(token)});"
        f"localStorage.setItem(\"kira.base\", {json.dumps(base)});"
    )


def wait_until_up(probe: Callable[[], bool], timeout_s: float, interval_s: float = 0.25) -> bool:
    """Poll `probe` until it is true or the deadline passes. A refused connection is 'not yet'."""
    deadline = time.monotonic() + timeout_s
    while True:
        try:
            if probe():
                return True
        except Exception:  # noqa: BLE001 - every failure before the engine listens is "not yet"
            pass
        if time.monotonic() >= deadline:
            return False
        time.sleep(interval_s)


def healthz(base: str) -> Callable[[], bool]:
    def probe() -> bool:
        with urllib.request.urlopen(f"{base}/healthz", timeout=1.0) as response:
            return response.status == 200

    return probe


@dataclass
class Placement:
    """Where a window was, in the data dir. Geometry only — never a secret."""

    x: int | None = None
    y: int | None = None
    width: int = DEFAULT_WIDTH
    height: int = DEFAULT_HEIGHT
    maximized: bool = False

    @classmethod
    def load(cls, path: Path, key: str = MAIN_KEY) -> "Placement":
        return read_placement(path, key, (DEFAULT_WIDTH, DEFAULT_HEIGHT), (MIN_WIDTH, MIN_HEIGHT))

    def save(self, path: Path, key: str = MAIN_KEY) -> None:
        write_placement(path, key, self)


def mutex_name(data_dir: Path) -> str:
    digest = hashlib.sha256(str(Path(data_dir).resolve()).lower().encode("utf-8")).hexdigest()[:16]
    return f"Local\\Kira.Desktop.{digest}"


def window_kwargs(base: str, placement: Placement) -> dict[str, Any]:
    return {
        "title": "Kira",
        "url": f"{base}/chat/{BOOT_QUERY}",
        "width": placement.width,
        "height": placement.height,
        "x": placement.x,
        "y": placement.y,
        "min_size": (MIN_WIDTH, MIN_HEIGHT),
        "hidden": True,
        "resizable": True,
        "maximized": placement.maximized,
    }


class Booter:
    """Two loads: inject the token on the first, show the window on the second.

    Kept apart from `run` because this ordering is what the live window caught being wrong —
    the first build reloaded the same URL from the handler, raised no second `loaded`, and left
    the window hidden for good. A boot URL that differs from the navigated one is the fix.
    """

    def __init__(self, window: Any, base: str, token: str, target: str | None = None):
        self.window = window
        self.base = base
        self.token = token
        #: Where this window goes once the token is in. The companion overrides it with its own route.
        self.target = target or f"{base}/chat/"
        self._injected = False
        self._shown = False

    def loaded(self) -> None:
        if self._shown:
            return
        if self._injected:
            self.show()
            return
        self._injected = True
        try:
            self.window.evaluate_js(bootstrap_script(self.base, self.token))
        except Exception as exc:  # noqa: BLE001 - a visible gate that asks for the token beats a hidden window
            print(f"[kira] could not inject the token ({exc}) - the connect screen will ask for it", flush=True)
        self.window.load_url(self.target)

    def show(self) -> None:
        if self._shown:
            return
        self._shown = True
        self.window.show()


def _already_running(data_dir: Path) -> bool:
    """One window per data dir; a second double-click must not start a second engine."""
    import ctypes

    mutex = ctypes.windll.kernel32.CreateMutexW(None, False, mutex_name(data_dir))
    already = ctypes.windll.kernel32.GetLastError() == 183  # ERROR_ALREADY_EXISTS
    # The handle is deliberately never closed: the OS releases it with this process.
    return bool(already and mutex)


def _focus_existing(title: str = "Kira") -> bool:
    """Raise the window the mutex says is already open; False when there is no window to raise.

    FindWindowW returns hidden windows too, so a window parked in the tray is shown again. The
    caller prints what actually happened rather than always pointing at the tray.
    """
    import ctypes

    user32 = ctypes.windll.user32
    hwnd = user32.FindWindowW(None, title)
    if not hwnd:
        return False
    user32.ShowWindow(hwnd, 9)  # SW_RESTORE
    user32.SetForegroundWindow(hwnd)
    return True


def _tray_image():
    from PIL import Image, ImageDraw

    image = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((2, 2, 62, 62), radius=14, fill=(23, 23, 27, 255))
    # A K drawn from three strokes: no font file, no binary asset in the repo.
    draw.line((22, 16, 22, 48), fill=(240, 240, 245, 255), width=6)
    draw.line((22, 33, 42, 16), fill=(240, 240, 245, 255), width=6)
    draw.line((22, 33, 43, 49), fill=(240, 240, 245, 255), width=6)
    return image


def _start_companion(webview: Any, base: str, token: str, data_dir: Path, state: dict) -> Any:
    """The card window, wired the way the app window is: boot, hide on close, remember the geometry.

    Separate from `run` because everything in it is the second window's own life cycle; the ordering
    that bit the first desktop build — inject, navigate, show — is the main window's `Booter`, reused.
    """
    from . import companion

    try:
        opened = companion.open_window(webview, base, token, companion.load_placement(data_dir / PLACEMENT_FILE))
    except Exception as exc:  # noqa: BLE001 - measured on 2026-11-04: a card that cannot be made must not take the app with it
        print(f"[kira] no companion window ({exc}) - the app is unaffected, and `--companion` is the extra", flush=True)
        return None
    if opened.note:
        print(f"[kira] {opened.note}", flush=True)
    card = opened.window

    def remember_card() -> None:
        try:
            companion.save_placement(data_dir / PLACEMENT_FILE, Placement(x=card.x, y=card.y, width=card.width, height=card.height))
        except Exception:  # noqa: BLE001 - a card that will not remember where it was is not a reason to fail a quit
            pass

    def closing() -> bool:
        if state["quitting"]:
            return True
        # The tray is the only door back, which is why the tray menu grows a "Show companion" row.
        remember_card()
        card.hide()
        return False

    card.events.loaded += opened.booter.loaded
    card.events.closing += closing
    card.events.closed += remember_card

    fallback = threading.Timer(SHOW_FALLBACK_S, opened.booter.show)
    fallback.daemon = True
    fallback.start()
    return card


def run(app: Any, *, host: str, port: int, token: str, data_dir: Path, timeout_s: float = 20.0, companion: bool = False) -> int:
    """Start the engine, show the window, keep the tray. Returns the process exit code.

    `companion=True` adds the card window beside the app window: same engine, same token, no chrome.
    """
    if _already_running(data_dir):
        if _focus_existing():
            print("[kira] Kira is already running - brought the window forward", flush=True)
        else:
            print("[kira] Kira is already running - use the tray icon to show it", flush=True)
        return 0

    import uvicorn

    base = f"http://{host}:{port}"
    server = uvicorn.Server(uvicorn.Config(app, host=host, port=port, log_level="warning"))
    engine = threading.Thread(target=server.run, name="kira-engine", daemon=True)
    engine.start()
    if not wait_until_up(healthz(base), timeout_s):
        print(f"[kira] the engine did not answer {base}/healthz within {timeout_s:.0f}s", flush=True)
        server.should_exit = True
        return 1

    import webview

    placement = Placement.load(data_dir / PLACEMENT_FILE)
    window = webview.create_window(**window_kwargs(base, placement))
    booter = Booter(window, base, token)
    state = {"quitting": False}

    def closing() -> bool:
        if state["quitting"]:
            return True
        window.hide()
        return False

    def quit_app() -> None:
        state["quitting"] = True
        try:
            icon.stop()
        finally:
            window.destroy()

    def remember() -> None:
        # pywebview's window object answers on any thread once the GUI is up; a failed read
        # after quit is not worth a dialog.
        try:
            Placement(
                x=window.x,
                y=window.y,
                width=window.width,
                height=window.height,
                maximized=window.state.value == "maximized",
            ).save(data_dir / PLACEMENT_FILE)
        except Exception:  # noqa: BLE001 - geometry is nice to have, never a reason to fail a quit
            pass

    window.events.loaded += booter.loaded
    window.events.closing += closing
    window.events.closed += remember

    # A hidden window is the one failure with no way out from inside the app, so a late load
    # still shows the gate rather than nothing at all.
    fallback = threading.Timer(SHOW_FALLBACK_S, booter.show)
    fallback.daemon = True
    fallback.start()

    card = _start_companion(webview, base, token, data_dir, state) if companion else None

    import pystray

    menu = [
        pystray.MenuItem("Show Kira", lambda: window.show(), default=True),
        pystray.MenuItem("Open in browser", lambda: webbrowser.open(f"{base}/chat/")),
        pystray.MenuItem("Quit", quit_app),
    ]
    if card is not None:
        # The card hides instead of closing, so the tray is the only way back to it.
        menu.insert(1, pystray.MenuItem("Show companion", lambda: card.show()))
    icon = pystray.Icon("kira", _tray_image(), "Kira", pystray.Menu(*menu))
    threading.Thread(target=icon.run, name="kira-tray", daemon=True).start()

    try:
        webview.start()
    finally:
        state["quitting"] = True
        try:
            icon.stop()
        except Exception:  # noqa: BLE001 - a tray that already stopped is not an error
            pass
        server.should_exit = True
        engine.join(5)
    return 0
