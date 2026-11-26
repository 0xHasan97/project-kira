# Desktop shell — live pass, 2026-10-30

Unit 3 of the roadmap. The spec says the window itself cannot be asserted from pytest in this
environment, so it gets the same treatment the voice unit got: run it on the real machine, look
at it, and write down what was seen and what was not. This pass covers the source run
(`python -m kira desktop`) and the packaged run (`packaging\dist\Kira\Kira.exe`).

## Lab

| Thing | Value |
| --- | --- |
| Machine | Windows 11 26200, WebView2 runtime 156.0.4314.50, pywebview 6.2.1 |
| Engine | `kira-engine/.venv`, `-m kira desktop --backend memory --port 8916` |
| Data dir | a temp directory outside the repo, holding one keyless provider |
| Provider | `mock_one` (`openai_compat` at `http://127.0.0.1:8999/v1`, models `mini`/`small`) served by `kira-engine/tools/mock_openai.py` |
| Keys | none. Nothing in this pass talks to a paid provider |

Captures are `PrintWindow(hwnd, hdc, PW_RENDERFULLCONTENT)` of the Kira window only. Nothing
outside the application appears in `docs/qa/desktop-shell/`, because nothing outside it was
captured — full-screen grabs of a personal desktop do not belong in a repo.

## What was seen

| # | Check | Evidence |
| --- | --- | --- |
| 1 | The window shows the Chat shell, not the connect gate | [01](desktop-shell/01-chat-on-first-show.png): provider line `mock_one — no key needed · idle`, no token field. The hidden boot injected the token and showed on the second load |
| 2 | Chat → Agent switch changes the whole shell | [02](desktop-shell/02-agent-shell.png): left rail (Chat/Call/Overview/…/Remote), session column, and the work panel with Changes · Terminal · Tests · Problems · Agents · Checkpoints · Context · Developer |
| 3 | A turn runs from the window | [03](desktop-shell/03-agent-turn.png): typed in the composer, Ctrl+Enter; session `e9e7d2ad`, `YOU` line, `MOCK_ONE` bubble, two step chips, `1 served · 0 failed` |
| 4 | Agent → Chat keeps the sitting | [04](desktop-shell/04-back-to-chat.png): same session selected, full transcript still there |
| 5 | Closing the window hides it to the tray | `WM_CLOSE` → `IsWindowVisible=False`, process alive, `GET /healthz` still 200 |
| 6 | A second launch raises the open window | second process exits 0 and prints `Kira is already running - brought the window forward`; the window is visible again with the transcript intact |
| 7 | Placement is restored | hand-written `desktop.json` `{x:300,y:200,width:1100,height:700}` → window rect `300,200 1100x700` ([05](desktop-shell/05-placement-restored.png)); the rail reflows at that width instead of clipping |
| 8 | The tray icon is registered | two `...SystemTrayIcon` windows own the process (pystray's icon + its message window) |
| 9 | The packaged build does the same | `packaging/dist/Kira/Kira.exe`, 55 MB folder, `console=False`; Chat renders ([06](desktop-shell/06-packaged-chat.png)), a turn is answered ([07](desktop-shell/07-packaged-turn.png)), `WM_CLOSE` hides to tray, and a second `Kira.exe` launch also exits 0 after raising the first |
| 10 | The frozen build keeps its data out of the install folder | `%LOCALAPPDATA%\Kira` unless `KIRA_DATA_DIR`/`--data-dir`; the packaged run above used the explicit data dir |

## Defects this pass found, each fixed test-first

1. **The window could stay hidden forever.** The first live run never appeared: pywebview raises
   `loaded` for a navigation to a *different* URL, and the original boot reloaded the same
   `/chat/` URL from inside the handler, so the second `loaded` never came and `show()` never
   ran. Fixed with a boot URL that differs (`/chat/?window=1`), a `Booter` class that injects on
   the first load and shows on the second, an 8 s fallback timer, and a caught injection error
   that still shows the gate. Tests: `test_the_boot_injects_on_the_first_load_and_shows_on_the_second`,
   `test_a_rejected_injection_still_navigates_and_shows_the_gate`.
2. **The second launch said the wrong thing.** It printed "use the tray icon to show it" on top
   of a window it had just raised. `_focus_existing()` now reports whether it found a window, and
   the two outcomes get two messages. Tests:
   `test_a_second_start_raises_the_open_window_and_says_that_it_did`,
   `test_a_second_start_that_finds_no_window_still_points_at_the_tray`.
3. **Both frozen paths were wrong.** In a frozen app `Path(__file__).parents[3]` lands inside
   `_internal`: the chat bundle was not found, and the data dir would have resolved into the
   install folder. `_chat_dist()` and `resolve_data_dir()` now have frozen branches
   (`sys._MEIPASS/kira-chat/dist`, `%LOCALAPPDATA%\Kira`). Tests: `test_packaging.py`,
   `test_a_frozen_build_keeps_its_data_under_local_appdata`,
   `test_from_a_source_checkout_the_bundle_is_the_sibling_directory`.

Also worth recording, because it cost the most time: on this machine a *script* calling
`SetForegroundWindow` is refused until an Alt tap clears the foreground lock, and a maximised
browser keeps a normal window behind it even when `IsWindowVisible` says true. `SetWindowPos`
with `HWND_TOPMOST` was only ever a QA aid; the shell itself raises the window with
`ShowWindow(SW_RESTORE)` + `SetForegroundWindow` and does not fight the foreground lock.

## What this pass does not claim

- **Tray menu items were not clicked by automation.** Registration and the callbacks' code are
  all this pass shows; the menu itself was not driven (the two `SystemTrayIcon` windows are the
  evidence that the icon exists).
- **`Quit` and the geometry *write* were not exercised live.** Killing the process does not run
  the `closed` handler, so `remember()` was not observed writing `desktop.json`; the write is
  unit-tested (`test_a_window_saved_restored_comes_back_restored`) and the *read* is proven by
  #7 above.
- **Writes still ask for the confirm secret.** Only the token is injected; that the confirm
  dialog appears in the window was not driven in this pass (the browser passes cover the dialog
  itself, and the injection script provably contains no confirm value — the bootstrap test
  asserts it).
- **Only the memory vault was used.** The lab runs `--backend memory`; the Locker path is the
  same `Vault` the `serve` passes used.
- **One machine.** No clean Windows without the WebView2 runtime, no second display, no
  high-DPI monitor.
- Out of scope by design: no global hotkeys / push-to-talk, no click-through or transparent
  overlay (unit 11), no installer, no code signing, no auto-update, no start-with-Windows.

## Gates at the end of the unit

- engine: `pytest -q` → **528 passed, 1 skipped**
- client: `npm run check` (tsc + vitest + vite build + stamp) → **30 files, 254 tests**, build OK
- contract drift gate: version 2, 77 schemas, 6 chunk types, 16 chain events — inside the
  engine suite
- docs test (`test_every_cli_verb_is_documented`) — inside the engine suite
