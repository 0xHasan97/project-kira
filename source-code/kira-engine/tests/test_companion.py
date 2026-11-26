"""The companion window: a second, frameless, always-on-top card over the desktop.

These tests never import pywebview, never touch a HWND and never start an engine. Everything native
is reached through an object handed in, so the ordering that the live window caught being wrong —
inject, navigate, show — is checked here instead of on a screen.
"""

import json

import pytest

from kira import companion, desktop


# --- the URL pair, which is the whole reason the main window's boot trick exists -------------


def test_the_companion_boots_on_a_url_that_is_not_the_one_it_shows():
    boot = companion.boot_url("http://127.0.0.1:8901")
    target = companion.target_url("http://127.0.0.1:8901")
    assert boot == "http://127.0.0.1:8901/chat/?companion=1"
    assert target == "http://127.0.0.1:8901/chat/#/companion"
    # WebView2 raises no second `loaded` for a navigation to the URL already open.
    assert boot != target


def test_the_companion_window_kwargs_are_the_card_and_not_the_app():
    kwargs = companion.companion_kwargs("http://127.0.0.1:8901", desktop.Placement(x=40, y=50, width=320, height=420))
    assert kwargs["title"] == "Kira companion"
    assert kwargs["url"] == companion.boot_url("http://127.0.0.1:8901")
    assert kwargs["frameless"] is True
    assert kwargs["transparent"] is True
    assert kwargs["on_top"] is True
    assert kwargs["hidden"] is True
    assert kwargs["easy_drag"] is True
    assert (kwargs["x"], kwargs["y"]) == (40, 50)
    assert (kwargs["width"], kwargs["height"]) == (320, 420)
    assert kwargs["min_size"] == (companion.MIN_WIDTH, companion.MIN_HEIGHT)
    # The OS shadow of a frameless window is a rectangle — the shape transparency exists to remove.
    assert kwargs["shadow"] is False


#: `webview.create_window` parameters, read off the installed pywebview on 2026-11-04. The live
#: `--companion` run passed a keyword this signature does not have (`window_frame`), which raised
#: `TypeError` and read as "this toolkit refuses transparency". This list is what stops a second
#: invented keyword from ever reaching a user's desktop.
CREATE_WINDOW_PARAMS = frozenset(
    {
        "title", "url", "html", "js_api", "width", "height", "x", "y", "screen", "resizable",
        "fullscreen", "min_size", "hidden", "frameless", "easy_drag", "shadow", "focus", "minimized",
        "maximized", "on_top", "confirm_close", "background_color", "transparent", "text_select",
        "zoomable", "draggable", "vibrancy", "menu", "localization", "server", "http_port", "server_args",
    }
)


@pytest.mark.parametrize("transparent", [True, False])
def test_every_keyword_the_card_asks_for_is_one_the_toolkit_takes(transparent):
    kwargs = companion.companion_kwargs("http://127.0.0.1:8901", desktop.Placement(), transparent=transparent)
    assert set(kwargs) <= CREATE_WINDOW_PARAMS, sorted(set(kwargs) - CREATE_WINDOW_PARAMS)


def test_a_card_that_cannot_be_transparent_is_asked_for_as_an_opaque_one():
    kwargs = companion.companion_kwargs("http://127.0.0.1:8901", desktop.Placement(), transparent=False)
    assert kwargs["transparent"] is False
    assert kwargs["frameless"] is True  # still a card, still no title bar
    assert kwargs["on_top"] is True


# --- geometry lives beside the main window's, in its own key --------------------------------


def test_the_two_windows_keep_their_own_geometry_in_one_file(tmp_path):
    path = tmp_path / "desktop.json"
    desktop.Placement(x=10, y=20, width=1200, height=800).save(path)
    companion.save_placement(path, desktop.Placement(x=900, y=60, width=320, height=420))

    assert desktop.Placement.load(path) == desktop.Placement(x=10, y=20, width=1200, height=800)
    assert companion.load_placement(path) == desktop.Placement(x=900, y=60, width=320, height=420)
    assert set(json.loads(path.read_text(encoding="utf-8"))) == {desktop.MAIN_KEY, companion.COMPANION_KEY}


def test_a_file_written_before_the_companion_still_reads_as_the_main_window(tmp_path):
    # The flat shape is what every existing install has on disk; the companion must not ask for it.
    path = tmp_path / "desktop.json"
    path.write_text(json.dumps({"x": 3, "y": 4, "width": 900, "height": 700, "maximized": False}), encoding="utf-8")
    assert desktop.Placement.load(path) == desktop.Placement(x=3, y=4, width=900, height=700)
    # The card's own size, not the app window's: a 900-pixel pet is a window, and a pet is not a window.
    assert companion.load_placement(path) == desktop.Placement(
        width=companion.DEFAULT_WIDTH, height=companion.DEFAULT_HEIGHT
    )


def test_saving_the_card_cannot_keep_a_secret_that_was_put_in_the_file(tmp_path):
    # The file is rewritten from the two dataclasses, so a key nobody put there cannot survive.
    path = tmp_path / "desktop.json"
    path.write_text(json.dumps({"x": 1, "token": "leak", "confirm": "leak"}), encoding="utf-8")
    companion.save_placement(path, desktop.Placement(x=5, y=6, width=320, height=420))
    written = json.loads(path.read_text(encoding="utf-8"))
    assert "token" not in json.dumps(written)
    assert "confirm" not in json.dumps(written)
    assert written[companion.COMPANION_KEY]["width"] == 320


def test_the_card_has_its_own_minimum_and_never_shrinks_below_it(tmp_path):
    path = tmp_path / "desktop.json"
    companion.save_placement(path, desktop.Placement(width=40, height=60))
    loaded = companion.load_placement(path)
    assert (loaded.width, loaded.height) == (companion.MIN_WIDTH, companion.MIN_HEIGHT)


# --- the token path is the main window's, and so is its limit ---------------------------------


def test_the_companion_is_booted_by_the_same_injection_and_no_more():
    script = desktop.bootstrap_script("http://127.0.0.1:8901", "tok_abc")
    assert "kira.token" in script and "kira.base" in script
    assert "confirm" not in script
    # The companion reuses `Booter`, so this is the only script either window ever runs.
    assert companion.boot_script is desktop.bootstrap_script


# --- click-through: one ex-style bit, behind a function with no window in it ------------------


class FakeUser32:
    def __init__(self, ex_style=0):
        self.ex_style = ex_style
        self.writes: list[tuple[int, int]] = []

    def GetWindowLongW(self, hwnd, index):
        assert index == desktop.GWL_EXSTYLE if hasattr(desktop, "GWL_EXSTYLE") else True
        return self.ex_style

    def SetWindowLongW(self, hwnd, index, value):
        self.writes.append((index, value))
        self.ex_style = value
        return 0


def test_click_through_sets_the_two_bits_windows_needs_and_clears_both_again():
    user32 = FakeUser32()
    assert companion.apply_click_through(1234, True, user32=user32) is True
    style = user32.writes[-1][1]
    assert style & companion.WS_EX_TRANSPARENT
    assert style & companion.WS_EX_LAYERED  # without it, WS_EX_TRANSPARENT is decoration

    assert companion.apply_click_through(1234, False, user32=user32) is False
    style = user32.writes[-1][1]
    assert not style & companion.WS_EX_TRANSPARENT
    assert not style & companion.WS_EX_LAYERED


def test_click_through_keeps_a_bit_it_was_not_asked_about():
    user32 = FakeUser32(ex_style=companion.WS_EX_TOOLWINDOW)
    companion.apply_click_through(1234, True, user32=user32)
    assert user32.writes[-1][1] & companion.WS_EX_TOOLWINDOW


def test_a_window_without_a_handle_reports_click_through_as_unavailable():
    assert companion.apply_click_through(None, True, user32=FakeUser32()) is None
    assert companion.apply_click_through(1234, True, user32=None) is None


def test_the_api_the_page_calls_answers_in_plain_data():
    user32 = FakeUser32()
    api = companion.CompanionApi(hwnd=lambda: 1234, user32=user32)
    assert api.set_click_through(True) == {"ok": True, "click_through": True}
    assert api.set_click_through(False) == {"ok": True, "click_through": False}
    assert api.set_click_through("yes please") == {"ok": False, "error": "click_through must be true or false"}
    assert api.get_state() == {"click_through": False, "supported": True}


def test_the_api_says_no_rather_than_crashing_when_there_is_no_handle():
    api = companion.CompanionApi(hwnd=lambda: None, user32=FakeUser32())
    assert api.set_click_through(True) == {"ok": False, "error": "no window handle"}
    assert api.get_state() == {"click_through": False, "supported": False}


def test_the_js_api_is_handed_to_the_window_that_needs_it():
    kwargs = companion.companion_kwargs("http://127.0.0.1:8901", desktop.Placement())
    assert kwargs["js_api"] is not None


# --- opening it, and the honest fallback ------------------------------------------------------


class FakeEvent:
    """pywebview's event object: `window.events.loaded += handler` is how a handler arrives."""

    def __init__(self):
        self.handlers = []

    def __iadd__(self, handler):
        self.handlers.append(handler)
        return self


class FakeWebview:
    def __init__(self, reject_transparent=False):
        self.windows = []
        self.reject_transparent = reject_transparent

    def create_window(self, **kwargs):
        class W:
            def __init__(self, kwargs):
                self.kwargs = kwargs
                self.events = type("E", (), {"loaded": FakeEvent(), "closing": FakeEvent(), "closed": FakeEvent()})()
                self.shown = 0
                self.hidden = 0
                self.x, self.y, self.width, self.height = 700, 80, 300, 400

            def show(self):
                self.shown += 1

            def hide(self):
                self.hidden += 1

            def evaluate_js(self, script):
                self.kwargs.setdefault("ran", []).append(script)

            def load_url(self, url):
                self.kwargs.setdefault("navigated", []).append(url)

        window = W(kwargs)
        # Recorded before the refusal, so a test can see the attempt the toolkit rejected, not only
        # the window that came out of it.
        self.windows.append(window)
        if self.reject_transparent and kwargs.get("transparent"):
            raise TypeError("create_window() got an unexpected keyword argument 'transparent'")
        return window


def test_opening_the_card_creates_it_hidden_and_boots_it_like_the_main_window():
    webview = FakeWebview()
    opened = companion.open_window(webview, "http://127.0.0.1:8901", "tok_abc", desktop.Placement())
    assert opened.note is None
    assert len(webview.windows) == 1
    window = webview.windows[0]
    assert window.kwargs["on_top"] is True
    opened.booter.loaded()  # inject + navigate
    opened.booter.loaded()  # show
    assert window.shown == 1
    assert window.kwargs["navigated"] == [companion.target_url("http://127.0.0.1:8901")]


def test_a_toolkit_that_refuses_transparency_says_so_and_shows_an_opaque_card():
    webview = FakeWebview(reject_transparent=True)
    opened = companion.open_window(webview, "http://127.0.0.1:8901", "tok_abc", desktop.Placement())
    assert opened.note == "transparency is not available here - the companion is an opaque card"
    assert len(webview.windows) == 2  # the refused attempt, then the card that works
    assert webview.windows[1].kwargs["transparent"] is False
    assert webview.windows[1].kwargs["on_top"] is True


def test_a_card_that_cannot_be_created_at_all_is_reported_rather_than_swallowed():
    class Broken:
        def create_window(self, **kwargs):
            raise RuntimeError("no webview2 runtime")

    with pytest.raises(RuntimeError, match="webview2"):
        companion.open_window(Broken(), "http://127.0.0.1:8901", "tok_abc", desktop.Placement())


# --- what the desktop shell does with it, which is the only part unique to a second window -----


def test_the_card_is_wired_to_boot_hide_and_remember_like_the_app_window(tmp_path):
    webview = FakeWebview()
    state = {"quitting": False}
    card = desktop._start_companion(webview, "http://127.0.0.1:8901", "tok_abc", tmp_path, state)

    window = webview.windows[0]
    assert window.events.loaded.handlers and window.events.closing.handlers and window.events.closed.handlers

    # Closing the card hides it: the tray item is how it comes back, and killing it would leave the
    # user with a companion they asked for and no way to reopen.
    assert window.events.closing.handlers[0]() is False
    assert window.hidden == 1

    state["quitting"] = True
    assert window.events.closing.handlers[0]() is True

    window.events.closed.handlers[0]()
    saved = companion.load_placement(tmp_path / desktop.PLACEMENT_FILE)
    assert (saved.x, saved.y, saved.width, saved.height) == (700, 80, 300, 400)


def test_the_main_windows_geometry_survives_the_card_being_closed(tmp_path):
    path = tmp_path / desktop.PLACEMENT_FILE
    desktop.Placement(x=10, y=20, width=1200, height=800).save(path)
    webview = FakeWebview()
    card = desktop._start_companion(webview, "http://127.0.0.1:8901", "tok_abc", tmp_path, {"quitting": False})
    card.events.closed.handlers[0]()

    assert desktop.Placement.load(path) == desktop.Placement(x=10, y=20, width=1200, height=800)


def test_a_refused_transparency_is_said_out_loud_on_the_console(tmp_path, capsys):
    webview = FakeWebview(reject_transparent=True)
    desktop._start_companion(webview, "http://127.0.0.1:8901", "tok_abc", tmp_path, {"quitting": False})
    assert "opaque card" in capsys.readouterr().out


def test_a_keyword_the_toolkit_does_not_take_is_not_mistaken_for_a_transparency_refusal(capsys):
    # Measured on 2026-11-04: the card asked with a keyword this pywebview does not have, and the shell
    # read that TypeError as "no transparency here", retried the same bad keyword, and raised again.
    # Only a refusal that names `transparent` is a toolkit limitation; the rest is a bug to show.
    class BadKwarg:
        def create_window(self, **kwargs):
            raise TypeError("create_window() got an unexpected keyword argument 'window_frame'")

    with pytest.raises(TypeError, match="window_frame"):
        companion.open_window(BadKwarg(), "http://127.0.0.1:8901", "tok_abc", desktop.Placement())
    assert "transparency" not in capsys.readouterr().out


def test_a_card_that_cannot_be_created_leaves_the_app_window_running(tmp_path, capsys):
    # The same run put a traceback in `run()` before the main loop, so a user got neither the card nor
    # the app. The companion is an extra; an extra that takes the application down is a defect twice over.
    class Broken:
        def create_window(self, **kwargs):
            raise TypeError("create_window() got an unexpected keyword argument 'window_frame'")

    assert desktop._start_companion(Broken(), "http://127.0.0.1:8901", "tok_abc", tmp_path, {"quitting": False}) is None
    assert "companion" in capsys.readouterr().out
