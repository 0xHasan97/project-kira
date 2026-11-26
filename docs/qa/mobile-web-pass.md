# Web + mobile surfaces — live pass, 2026-10-31

Unit 8 of the roadmap (M31 manifest/worker/icons, M32 phone layout, M33 this pass). One bundle, one
engine, no second codebase: the phone gets a layout, not an app. Driven in a real Chromium against
the built bundle, served by the engine itself at `/chat/`.

## Lab

| Thing | Value |
| --- | --- |
| Engine | `kira-engine/.venv`, `tools/kira_lab.py --port 8901 --mock-port 8999` |
| Data dir | a temp directory outside the repo; memory vault; the token and confirm printed to stdout and thrown away with the directory |
| Providers | `mock_one` / `mock_two` through `tools/mock_openai.py` on loopback. No paid provider was contacted |
| Device | Chromium emulating iPhone-class viewport `390x844x3, mobile, touch` with an iOS Safari user agent |

The emulation note matters: `resize_page` bottoms out near 500 px because the OS window has a minimum
width, so the phone numbers below come from `Emulation.setDeviceMetricsOverride`, not from a narrow
window. `take_screenshot` with a `filePath` was refused — that MCP server's workspace root is
`C:\Users\Administrator`, not this repo — so the evidence here is the readings themselves. Nothing
was saved into `docs/qa/` as a picture, and no full-screen capture was taken at any point.

## Installability

`GET /chat/manifest.webmanifest` → 200, and the manifest the browser actually parsed:

| Field | Value |
| --- | --- |
| `name` / `short_name` | `Kira` / `Kira` |
| `display` | `standalone` |
| `start_url` / `scope` | `/chat/#/chat` / `/chat/` |
| `theme_color` / `background_color` | `#0f1113` / `#0f1113` |
| `icons` | 192×192 `any`, 512×512 `any`, 512×512 `maskable` (all `image/png`) |

The document carries `<meta name="theme-color" content="#0f1113">`, an `apple-touch-icon` link, and an
inline-SVG favicon — all three generated from the same `draw_icon` code as the PNGs, so the icon
cannot drift from the brand. The manifest's `scope` matches the engine's mount point, which is what
makes a launched app stay inside Kira instead of opening the browser tab.

## Offline

With the service worker registered (`scope: http://127.0.0.1:8901/chat/`, `navigator.serviceWorker.controller`
non-null) the shell cached under **`kira-shell-1c7xpw6`** — the cache name is a hash of `index.html`, so
a new build is a new cache and no stale bundle can survive a reload.

What the cache holds, read back with `cache.keys()`: 5 entries — `/chat/`, the manifest, one `.js`,
one `.css`, one `.png`. **Zero entries under `/v1/`.** The worker's rule is that the API is never
cached, and the cache contents are the proof.

Then network → Offline, reload:

| Observation | Reading |
| --- | --- |
| The shell mounts, not the connect gate | `gated: false`, `data-shell="agent"` still there, composer present |
| The token survived | `localStorage.getItem("kira.token")` non-null |
| The page says why it is useless | `[role=alert]` = `no answer from the engine at http://127.0.0.1:8901 (Failed to fetch)` |
| Nothing pretends to be data | model picker reads `no models configured`, footer reads `Enter sends · 0 models · AUTO` |

Back online, reload: `alert: null`, footer `Enter sends · 2 models · AUTO`, six picker options. The
offline banner is the fix that came out of this pass — before it, the same state showed a red dot and
"no models configured" with no reason, which reads as a broken app rather than an unreachable one
(`docs/qa/agent-shell-pass.md` §3).

## The phone layout at 390×844

| Check | Reading |
| --- | --- |
| The document never scrolls; the app owns the scroll | `documentElement.scrollHeight` 844 = `innerHeight` 844 |
| Bottom bar inside a thumb, above the home indicator | `.phone-bar` top 799, bottom 844 (Chat · Call · Sessions · Overview · Menu) |
| Composer clears the bar | `.composer` bottom 656, send row fully on screen |
| The thread is the scroller | `thread.scrollHeight > thread.clientHeight` |
| The session/provider strip is a strip, not a wall | `.side` height 287 px = 34 dvh, `overflow-y: auto` |
| The header wraps instead of clipping | model picker on its own line at full width: `mini · mock_one, mock_two · fast` |
| Type iOS will not zoom on focus | composer/gate/select computed `font-size: 16px` |
| Safe areas are wired | `padding-bottom: calc(0.75rem + env(safe-area-inset-bottom))` on the composer, `env(safe-area-inset-top)` on the bar |

## What this pass did **not** prove

- **No real phone.** Chromium's mobile emulation, not iOS Safari or Android Chrome on hardware. Touch
  targets, `dvh` and safe-area insets were read from the emulated metrics, not felt.
- **No install was clicked.** Chrome's install prompt, the standalone window it opens, iOS's
  Add-to-Home-Screen and its status-bar colour all need a real device and, on iOS, a user gesture in
  Safari. What is proved here is that the manifest, the icons, the worker and the meta tags are
  served and parsed.
- **No TLS.** The engine binds loopback and this pass used plain `http://127.0.0.1:8901`, which
  Chromium treats as a secure context, so the worker registered. A phone on the other side of a
  tunnel is *not* loopback: installability and the service worker both require HTTPS there, so unit
  8's install path depends on the user's own tunnel terminating TLS (Tailscale Serve does; a bare
  `cloudflared http` does not). This is a documented dependency, not a defect in the shell.
- **No Lighthouse/PWA audit** and no throttled-performance measurement.

## Gates at the end of the unit

`npx tsc --noEmit` clean · vitest **327 passed / 37 files** · `npm run build` stamped
`{"api_version":1,"contract_version":2,"api_prefix":"/v1"}` · engine **536 passed, 1 skipped** ·
`node kira-contracts/check-drift.mjs` → `kira-contracts OK — v2, 77 schemas, 6 chunk types,
16 chain events`.
