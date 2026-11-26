# Desktop shell — design, 2026-10-30

Unit 3 of the roadmap: a window, a tray, and a packaged launcher. It is also the prerequisite
for unit 11's click-through avatar overlay, because a browser tab cannot be transparent and
cannot keep a tray icon.

## The fork, and the choice

| Option | Why not / why | Cost on this machine |
| --- | --- | --- |
| **pywebview 6 + WebView2** | **chosen** — the WebView2 runtime is already installed (`156.0.4314.50`, HKLM), pywebview 6.2.1 installs into the engine venv, and a window is one `create_window` call | ~12 MB of wheels, no Chromium download |
| Electron | the donor stack, and the only one that does `setIgnoreMouseEvents` natively — but it means a second toolchain, a `node_modules` with a Chromium build, and a JS side that has to supervise a Python engine | ~200 MB download, a build step the repo does not have |
| Tauri | needs the Rust toolchain, which this machine does not have | new system dependency |

Electron stays a valid future swap: the window only ever renders `/chat/`, so the shell is
replaceable without touching the UI. pywebview wins because it adds no second build system
and no downloaded browser; click-through for unit 11 is a Win32 style bit
(`WS_EX_LAYERED | WS_EX_TRANSPARENT`) on the same window.

## Shape

`kira-engine desktop` — a new CLI verb beside `serve`, `token`, `doctor`:

1. **Engine in the same process, on a thread.** `uvicorn.Server` runs in a daemon thread;
   the window runs on the main thread (pywebview owns it). Loopback only, same `Vault`, same
   config, same `create_app`. No subprocess to orphan.
2. **Window.** `webview.create_window("Kira", base + "/chat/", 1280×860, min 720×520)`, hidden
   until the token is in place. `private_mode` stays on: the token lives in the window's
   memory, not in a WebView2 profile on disk — the Credential Locker rule is not weakened by
   this unit.
3. **The token.** On first `loaded`, the shell runs one `localStorage.setItem("kira.token", …)`
   with a JSON-encoded value, then loads `/chat/` a second time and shows the window. The
   connect gate therefore never appears in the desktop shell. **The confirm secret is never
   injected** — writes still ask, exactly as in a browser.
4. **Tray.** `pystray` icon generated in code (a 64 px rounded square with a "K" — no binary
   asset in the repo): *Show Kira*, *Open in browser*, *Quit*. Closing the window hides to the
   tray; Quit is the only exit.
5. **Single instance.** A named mutex derived from the data directory; the second launch says
   "Kira is already running — use the tray to show it" and exits 0.
6. **Window placement.** `desktop.json` in the data dir remembers x/y/w/h and whether the
   window was maximised. It holds geometry only — no token, no secret.

`run-kira.bat` gains `--window` (and only that flag changes): it installs the `desktop` extra
when the import is missing, then runs `kira-engine desktop` in the same venv. Without the flag
the launcher behaves exactly as it does today.

## Packaging

A PyInstaller onedir build (`kira-engine/packaging/kira.spec`) named `Kira.exe` that bundles
the engine, `kira-chat/dist` and the desktop modules. The build script is
`kira-engine/packaging/build.ps1`; output `kira-engine/packaging/dist/Kira/`. It is a launcher
artefact, not the development path: `run-kira.bat --window` stays the way to run from source.

## Testing

- Unit-testable, headless: the placement store, the bootstrap script's escaping, the health
  wait, the mutex name, and the CLI wiring behind a fake window.
- The real window cannot be asserted from pytest in this environment; it gets a desktop pass
  with OS screenshots (`docs/qa/desktop-shell-pass.md`), the same way voice needed a real
  audio device.

## What this unit does not do

- No hotkeys / push-to-talk (the spine spec mentions them under this unit; a global hotkey
  needs a policy about a hot mic, so it belongs with unit 6/11).
- No click-through, transparency or overlay: the window is an ordinary rectangular app until
  unit 11 asks for a character.
- No installer (MSI/NSIS), no code signing. The artefact is a folder with `Kira.exe`.
- No auto-update and no start-with-Windows option.
