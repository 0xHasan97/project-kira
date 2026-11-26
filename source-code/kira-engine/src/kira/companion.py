"""The companion window: the same Kira, as a card that sits on the desktop.

`kira-engine desktop --companion` opens this second window next to the app window. Nothing about the
engine changes — same loopback port, same bearer token, same memory-only boot path — and the confirm
secret is as absent here as it is in the app window. What changes is the chrome: no title bar, always on
top, an optional transparent client area, and a click-through switch the page can ask for so the card
stops intercepting the desktop underneath it. This pywebview has no keyword that suppresses a taskbar or
Alt-Tab entry, so the card is listed there.

Two things keep this testable. The window kwargs, the URL pair and the geometry file are pure, and the
Win32 calls are reached through a `user32` handed in, so no test ever needs an HWND or a running GUI.
"""

from __future__ import annotations

import platform
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from . import desktop
from .desktop import Placement

#: This window's section in `desktop.json` — see `desktop.MAIN_KEY` for the other one.
COMPANION_KEY = "companion"
TITLE = "Kira companion"
DEFAULT_WIDTH = 320
DEFAULT_HEIGHT = 420
MIN_WIDTH = 200
MIN_HEIGHT = 240
#: The boot page is the app with a query string; the target is the companion route. They must differ
#: for the same reason the main window's pair does: WebView2 raises no `loaded` for a navigation to the
#: document that is already open, and a card that never shows is a card that does not exist.
BOOT_QUERY = "?companion=1"
TARGET_HASH = "#/companion"
#: What the user is told when the toolkit cannot make the client area transparent.
TRANSPARENCY_NOTE = "transparency is not available here - the companion is an opaque card"

# The two extended-style bits Windows checks before it lets a window be click-through: the layered
# window is what makes the hit-test skip it, so setting one without the other is decoration.
WS_EX_TRANSPARENT = 0x00000020
WS_EX_LAYERED = 0x00080000
#: Not part of the toggle. The tests set it on a fake window to prove the bits this code does not own survive.
WS_EX_TOOLWINDOW = 0x00000080


def boot_url(base: str) -> str:
    return f"{base}/chat/{BOOT_QUERY}"


def target_url(base: str) -> str:
    return f"{base}/chat/{TARGET_HASH}"


def load_placement(path: Path) -> Placement:
    return desktop.read_placement(path, COMPANION_KEY, (DEFAULT_WIDTH, DEFAULT_HEIGHT), (MIN_WIDTH, MIN_HEIGHT))


def save_placement(path: Path, placement: Placement) -> None:
    desktop.write_placement(path, COMPANION_KEY, placement)


def native_user32() -> Any:
    """The Win32 handle table, or None where there is none — a non-Windows box has no ex-style to set."""
    if platform.system() != "Windows":
        return None
    try:
        import ctypes

        return ctypes.windll.user32
    except (AttributeError, OSError):  # pragma: no cover - only a non-Windows `ctypes` gets here
        return None


def find_hwnd(title: str = TITLE) -> int | None:
    """The card's handle, looked up when the page asks rather than when the window was made.

    pywebview gives no window handle on its `Window`, and the second `loaded` can arrive before any
    GUI thread has published one, so this is a by-title lookup — the same trick `desktop._focus_existing`
    uses. A frameless window keeps its title; only its border is gone.
    """
    user32 = native_user32()
    if user32 is None:
        return None
    return user32.FindWindowW(None, title) or None


def apply_click_through(hwnd: int | None, enabled: Any, *, user32: Any = None) -> bool | None:
    """Set or clear the click-through bits, leaving every other bit of the style alone.

    Returns None when there is no window to change — no handle, or no Win32 — which the caller reports
    as "unsupported" rather than as a failure of what the user asked for.
    """
    if not hwnd or user32 is None:
        return None
    style = user32.GetWindowLongW(hwnd, desktop.GWL_EXSTYLE)
    bits = WS_EX_TRANSPARENT | WS_EX_LAYERED
    wanted = (style & ~bits) | bits if enabled is True else style & ~bits
    user32.SetWindowLongW(hwnd, desktop.GWL_EXSTYLE, wanted)
    return bool(enabled)


class CompanionApi:
    """The object the card's page talks to: `window.pywebview.api.set_click_through(true)`.

    Answers are plain dicts, because a page cannot see a Python exception and a string is the one thing
    it can show. Nothing here can reach the vault, the filesystem or the engine — it changes one style
    word on one window of this process.
    """

    def __init__(self, hwnd: Callable[[], int | None] | None = None, *, user32: Any = None):
        self._hwnd = hwnd if callable(hwnd) else find_hwnd
        self._user32 = user32

    def _user32_now(self) -> Any:
        return self._user32 if self._user32 is not None else native_user32()

    def set_click_through(self, enabled: Any) -> dict:
        if not isinstance(enabled, bool):
            return {"ok": False, "error": "click_through must be true or false"}
        handle = self._hwnd()
        if not handle:
            return {"ok": False, "error": "no window handle"}
        applied = apply_click_through(handle, enabled, user32=self._user32_now())
        if applied is None:
            return {"ok": False, "error": "no window handle"}
        return {"ok": True, "click_through": applied}

    def get_state(self) -> dict:
        handle = self._hwnd()
        user32 = self._user32_now()
        if not handle or user32 is None:
            return {"click_through": False, "supported": False}
        style = user32.GetWindowLongW(handle, desktop.GWL_EXSTYLE)
        return {"click_through": bool(style & WS_EX_TRANSPARENT), "supported": True}


def companion_kwargs(base: str, placement: Placement, *, transparent: bool = True) -> dict[str, Any]:
    return {
        "title": TITLE,
        "url": boot_url(base),
        "width": max(placement.width, MIN_WIDTH),
        "height": max(placement.height, MIN_HEIGHT),
        "x": placement.x,
        "y": placement.y,
        "min_size": (MIN_WIDTH, MIN_HEIGHT),
        "frameless": True,
        "transparent": transparent,
        "on_top": True,
        "hidden": True,
        "easy_drag": True,
        # A frameless window still gets an OS shadow unless told otherwise, and a shadow is a rectangle —
        # exactly the shape a transparent client area is trying not to have.
        "shadow": False,
        "js_api": CompanionApi(),
    }


@dataclass
class Opened:
    """The card, how it was booted, and the one thing the caller has to say about it."""

    window: Any
    booter: desktop.Booter
    note: str | None = None


def _refuses_transparency(error: TypeError) -> bool:
    """Only a refusal that names `transparent` is this toolkit's limit.

    Any other `TypeError` is a keyword that does not exist; retrying it opaque raises the same error a
    second time and, on the live run, took the whole desktop down with the card.
    """
    return "transparent" in str(error)


def open_window(webview: Any, base: str, token: str, placement: Placement) -> Opened:
    """Create the card, then retry it opaque if this toolkit does not know `transparent`.

    Every other failure propagates: the desktop shell would otherwise run with a companion the user
    asked for and never got, and the console is the only place that can say so.
    """
    try:
        window = webview.create_window(**companion_kwargs(base, placement))
        return Opened(window, desktop.Booter(window, base, token, target=target_url(base)))
    except TypeError as refused:
        if not _refuses_transparency(refused):
            raise
        print(f"[kira] the card asked for transparency and was refused ({refused})", flush=True)
    window = webview.create_window(**companion_kwargs(base, placement, transparent=False))
    return Opened(
        window,
        desktop.Booter(window, base, token, target=target_url(base)),
        note=TRANSPARENCY_NOTE,
    )


#: The injection is the app window's, unchanged: one token, one base URL, and never the confirm secret.
boot_script = desktop.bootstrap_script
