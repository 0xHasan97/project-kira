import json
import time

from kira import desktop


def test_bootstrap_script_writes_the_token_and_the_base_and_nothing_else():
    script = desktop.bootstrap_script("http://127.0.0.1:8901", "tok_abc")
    assert 'localStorage.setItem("kira.token", "tok_abc")' in script
    assert 'localStorage.setItem("kira.base", "http://127.0.0.1:8901")' in script
    # The confirm secret is the one thing a window must never be handed: writes re-ask for it.
    assert "confirm" not in script


def test_bootstrap_script_cannot_be_broken_out_of_by_a_quoted_token():
    # A token is Locker data, but a script built by concatenation is the classic injection site.
    # JSON-encoding keeps a quote inside the string instead of ending it.
    token = 'x");document.title="pwned";//'
    script = desktop.bootstrap_script("http://127.0.0.1:8901", token)
    assert json.dumps(token) in script
    assert script.count("document.title") == token.count("document.title")


def test_wait_until_up_returns_true_as_soon_as_the_probe_answers():
    calls: list[int] = []

    def probe() -> bool:
        calls.append(1)
        return len(calls) == 3

    assert desktop.wait_until_up(probe, timeout_s=1.0, interval_s=0.01) is True
    assert len(calls) == 3


def test_wait_until_up_gives_up_after_the_timeout():
    started = time.monotonic()
    assert desktop.wait_until_up(lambda: False, timeout_s=0.05, interval_s=0.01) is False
    assert time.monotonic() - started >= 0.05


def test_wait_until_up_treats_a_raising_probe_as_not_ready_yet():
    calls: list[int] = []

    def probe() -> bool:
        calls.append(1)
        if len(calls) < 2:
            raise ConnectionError("connection refused")
        return True

    assert desktop.wait_until_up(probe, timeout_s=1.0, interval_s=0.01) is True
    assert len(calls) == 2


def test_placement_round_trips_and_survives_a_corrupt_file(tmp_path):
    path = tmp_path / "desktop.json"
    assert desktop.Placement.load(path) == desktop.Placement()

    desktop.Placement(x=10, y=20, width=900, height=700, maximized=True).save(path)
    assert desktop.Placement.load(path) == desktop.Placement(x=10, y=20, width=900, height=700, maximized=True)

    path.write_text("{not json", encoding="utf-8")
    assert desktop.Placement.load(path) == desktop.Placement()


def test_placement_never_shrinks_below_the_window_minimum(tmp_path):
    path = tmp_path / "desktop.json"
    path.write_text(json.dumps({"width": 100, "height": 120}), encoding="utf-8")
    loaded = desktop.Placement.load(path)
    assert (loaded.width, loaded.height) == (desktop.MIN_WIDTH, desktop.MIN_HEIGHT)


def test_placement_reads_geometry_only_and_ignores_anything_else(tmp_path):
    path = tmp_path / "desktop.json"
    path.write_text(
        json.dumps({"x": 1, "y": 2, "width": 800, "height": 600, "token": "leak", "confirm": "leak"}),
        encoding="utf-8",
    )
    loaded = desktop.Placement.load(path)
    assert (loaded.x, loaded.y, loaded.width, loaded.height) == (1, 2, 800, 600)
    # The file is rewritten from the dataclass, so an injected key cannot survive a save.
    loaded.save(path)
    rewritten = json.loads(path.read_text(encoding="utf-8"))
    assert "token" not in rewritten and "confirm" not in rewritten


def test_mutex_name_is_stable_and_local_to_one_data_dir(tmp_path):
    first = desktop.mutex_name(tmp_path / "a")
    assert first == desktop.mutex_name(tmp_path / "a")
    assert first != desktop.mutex_name(tmp_path / "b")
    assert first.startswith("Local\\")
    assert len(first) < 120


def test_window_kwargs_carry_the_saved_placement_and_start_hidden():
    kwargs = desktop.window_kwargs(
        "http://127.0.0.1:8901", desktop.Placement(x=5, y=6, width=900, height=700, maximized=True)
    )
    assert kwargs["title"] == "Kira"
    # A different URL from the one it navigates to after injecting: WebView2 raises no second
    # `loaded` for a navigation to the URL already open, and a boot URL that matched would
    # leave the window hidden forever (measured in the 2026-10-30 desktop pass).
    assert kwargs["url"] == "http://127.0.0.1:8901/chat/?window=1"
    assert (kwargs["x"], kwargs["y"]) == (5, 6)
    assert (kwargs["width"], kwargs["height"]) == (900, 700)
    assert kwargs["min_size"] == (desktop.MIN_WIDTH, desktop.MIN_HEIGHT)
    # Hidden until the token is in localStorage: the connect gate must never flash.
    assert kwargs["hidden"] is True
    # Saved as maximized means it reopens maximized, not merely as large.
    assert kwargs["maximized"] is True


def test_a_window_saved_restored_comes_back_restored():
    assert desktop.window_kwargs("http://127.0.0.1:8901", desktop.Placement())["maximized"] is False


class FakeWindow:
    def __init__(self, fail_js: bool = False):
        self.calls: list[tuple] = []
        self.fail_js = fail_js

    def evaluate_js(self, script):
        self.calls.append(("js", script))
        if self.fail_js:
            raise RuntimeError("script rejected")
        return True

    def load_url(self, url):
        self.calls.append(("load", url))

    def show(self):
        self.calls.append(("show",))


def test_the_boot_injects_on_the_first_load_and_shows_on_the_second():
    window = FakeWindow()
    booter = desktop.Booter(window, "http://127.0.0.1:8901", "tok_abc")

    booter.loaded()
    assert [call[0] for call in window.calls] == ["js", "load"]
    assert window.calls[0][1] == desktop.bootstrap_script("http://127.0.0.1:8901", "tok_abc")
    assert window.calls[1][1] == "http://127.0.0.1:8901/chat/"

    booter.loaded()
    assert window.calls[-1] == ("show",)
    booter.loaded()
    assert [call[0] for call in window.calls].count("show") == 1


def test_a_rejected_injection_still_navigates_and_shows_the_gate():
    # A window stuck hidden is worse than a window showing the connect screen: the user can
    # paste a token there, and a hidden window has no way to say anything at all.
    window = FakeWindow(fail_js=True)
    booter = desktop.Booter(window, "http://127.0.0.1:8901", "tok_abc")
    booter.loaded()
    booter.loaded()
    assert window.calls[-2][0] == "load"
    assert window.calls[-1] == ("show",)


def test_a_second_start_raises_the_open_window_and_says_that_it_did(monkeypatch, capsys, tmp_path):
    # The live window showed the old message ("use the tray icon") on top of a window that had
    # just been raised: the two disagreed, and the message is the only feedback a double-click
    # gets, so it has to match what happened.
    monkeypatch.setattr(desktop, "_already_running", lambda data_dir: True)
    calls = []
    monkeypatch.setattr(desktop, "_focus_existing", lambda: calls.append("raised") or True)

    assert desktop.run(object(), host="127.0.0.1", port=1, token="tok", data_dir=tmp_path) == 0

    assert calls == ["raised"]
    out = capsys.readouterr().out
    assert "brought the window forward" in out
    assert "tray" not in out


def test_a_second_start_that_finds_no_window_still_points_at_the_tray(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(desktop, "_already_running", lambda data_dir: True)
    monkeypatch.setattr(desktop, "_focus_existing", lambda: False)

    assert desktop.run(object(), host="127.0.0.1", port=1, token="tok", data_dir=tmp_path) == 0

    out = capsys.readouterr().out
    assert "already running" in out
    assert "tray" in out
