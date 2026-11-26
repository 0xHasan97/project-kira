# Kira unit 8 — web + mobile surfaces

Date: 2026-10-30. Status: design, executed as M31 (installable bundle), M32 (phone layout) and
M33 (pass, docs, gates).

Decisions in this file were taken in autonomous mode: the user's standing instruction was "do the
full project step by step as you fit or recommended" and they were unavailable to approve, so the
recommended option is recorded here rather than asked about.

## What "unit 8" is, given what already exists

The roadmap's one-line entry is "Web + mobile surfaces". It has to be read against reality: unit 12
already made the same React bundle reachable from a phone through the user's own tunnel, behind
pairing, with `#/pair` rendering before the token gate. So there is **no new surface to invent**.
What is missing is that the bundle is not *installable* and was never *laid out* for a phone — at
390 px it is a desktop grid with a 10-item rail wrapped over the top of the screen.

Unit 8 is therefore: **make the existing one bundle installable, and make it usable at phone
width** — without a second UI, a second build, or a second auth path.

| Option | Why not / why |
| --- | --- |
| **PWA of the existing bundle + a real phone layout** | **chosen** — one build, one contract, one test suite; `#/pair` and the device token already work; no store, no signing, no second toolchain |
| React Native / Capacitor wrapper | a second toolchain and a native build pipeline for a UI that is already HTML; the wrapper adds a WebView and nothing else, and the phone still needs the tunnel to reach a loopback engine |
| A separate server-rendered mobile site | a second surface to keep in step with contract v2; every future screen lands twice, and the 30-file client suite would not cover the copy |
| Do nothing, phone users pinch-zoom | honest but wrong: the rail, the composer and the settings panel are the three things a phone user touches first, and all three misbehave at 390 px |

The PWA is not "another product". It is the same `dist/` the desktop window renders.

## Shape

### M31 — the installable half

1. **Manifest.** `kira-chat/public/manifest.webmanifest` (copied into `dist/` by Vite):
   `name`/`short_name` "Kira", `start_url: "/chat/#/chat"`, `scope: "/chat/"`,
   `display: "standalone"`, `background_color` and `theme_color` `#0f1113`, `lang: "en"`,
   `orientation` unset (a chat app in landscape is a valid choice), icons 192/512 plus a
   maskable 512. Linked from `index.html`; no query string, no secret in it.
2. **Icons, generated not committed.** `kira-chat/scripts/make-icons.mjs` writes PNGs from code —
   Node's `zlib` and a ~40-line PNG encoder, no dependency — into `public/icons/`: a rounded
   square in `--ink` with the accent dot and ring the favicon already draws. Same decision the tray
   icon took in unit 3: an icon is code, not a binary in the repo. `npm run build` runs it before
   Vite; the generated files stay out of git.
3. **Service worker.** `kira-chat/public/sw.js`, plain JS, no build step, register scope `/chat/`.
   Its only jobs:
   - cache the built shell (`index.html`, hashed `assets/*`, icons, manifest, fonts) under a cache
     name derived from the build stamp, so a rebuild never leaves an old bundle reachable;
   - answer a **navigation** network-first, falling back to a self-contained offline card that
     says the engine is unreachable. A chat product with no engine has nothing useful to cache,
     and pretending otherwise would be a lie the first time a turn was typed into it;
   - never touch anything else. `/v1/*`, `/healthz` and every non-GET request miss the cache.
4. **Registration** in `main.tsx` via a small `src/sw.ts`: only when `serviceWorker` exists and the
   context is secure; a failure is silent (a browser without it, or a plain-HTTP tunnel, still gets
   a working app). New worker `skipWaiting()` + `clients.claim()` so no tab quietly runs yesterday's
   bundle — the contract check in `App.refresh()` is the backstop, not the only defence.
5. **Engine.** Two things the static mount does not do by itself: `manifest.webmanifest` has to be
   served as `application/manifest+json`, and `sw.js` must not be cached by the browser. A tiny
   `ChatBundle(StaticFiles)` sets `Cache-Control: no-cache` on `sw.js` and `index.html`, and leaves
   the hashed assets alone. No new API route, no contract change, `CONTRACT_VERSION` stays 2.

### M32 — the phone layout

Breakpoint at **48rem (768 px)**, separate from the existing 60rem compaction rule, so a small
desktop window keeps the desktop arrangement.

- **`viewport-fit=cover`** + `theme-color` + the three `apple-mobile-web-app-*` metas and an
  `apple-touch-icon`: iOS installs from the share sheet and ignores most of the manifest.
- **Bottom bar, not a wrapped rail.** In both shells below 48rem the rail leaves the top and becomes
  a fixed bottom bar: Chat, Call, Sessions, Overview, and **Menu**. Menu opens the same `<nav>`
  as a sheet — every route stays reachable, no second list of routes to keep in step, and the
  primary four are thumb-height. Safe-area padding under the bar; 44 px minimum target.
- **Height.** `.shell` moves to `100dvh` with a `100vh` fallback, so mobile browser chrome does not
  clip the composer, and the composer's padding carries `env(safe-area-inset-bottom)`.
- **Typing.** Inputs and the composer get `font-size: 16px` at phone width, which is what stops iOS
  from zooming on focus; `-webkit-text-size-adjust: 100%` on `body`.
- **Density.** Screen padding and the options sheet's clamped padding shrink; `.screen` already has
  `overflow-x: auto`, which stays the answer for the eight-column provider table.
- **Agent shell on a phone** keeps the existing ≤60rem stacking (transcript, then the work panel
  below it). No phone-only work panel: the phone's home is the Chat shell, and Agent is reachable
  through the same switch.

## Security, and what this unit does not weaken

- **No new listener.** The engine binds loopback, as unit 12 established; the phone still arrives
  through the user's tunnel. A service worker is not a network surface.
- **No API caching.** The SW's fetch handler returns early for anything but same-origin GETs inside
  `/chat/`. No response carrying `Authorization` is ever stored, because no API response is stored.
- **No new secret.** No push notifications (that needs a VAPID key pair and a subscription store —
  a second key material for no capability this unit promises). No QR code (unit 12's non-goal
  stands). Token handling is exactly as before: `localStorage` on the device, Locker on the desktop.
- **Installability does not require HTTPS on loopback** (127.0.0.1 is a secure context), but
  **service workers do require a secure context**. Over a plain-HTTP tunnel the app runs with no
  offline card; over Tailscale Serve or Cloudflare Tunnel it installs fully. The `#/remote` screen
  already says the microphone needs TLS; the README says the same for installation.

## Files

| Area | File | Change |
| --- | --- | --- |
| client | `kira-chat/index.html` | manifest link, theme colour, apple metas, `viewport-fit` |
| client | `kira-chat/public/manifest.webmanifest` | new |
| client | `kira-chat/public/sw.js` | new — shell cache, offline card, network-first navigation |
| client | `kira-chat/scripts/make-icons.mjs` | new — PNGs from code |
| client | `kira-chat/src/sw.ts` | new — guarded registration |
| client | `kira-chat/src/main.tsx` | call the registration |
| client | `kira-chat/src/App.tsx` | Menu button + sheet state at phone width |
| client | `kira-chat/src/styles.css` | 48rem block: bottom bar, sheet, dvh, safe areas, 16px inputs |
| client | `kira-chat/package.json` | `prebuild` runs the icon script |
| engine | `kira-engine/src/kira/app.py` | `ChatBundle` mount with the two cache exceptions |
| engine | `kira-engine/tests/test_chat_bundle.py` | new |
| docs | `README.md`, `docs/ROADMAP.md`, `docs/qa/mobile-web-pass.md` | the three honest pages |

## Acceptance tests

Engine: the manifest is served with `application/manifest+json`; `sw.js` and `index.html` come back
`no-cache` while a hashed asset keeps its long cache; a dist without a manifest still mounts; no
route outside `/chat/` is affected.

Client: the registration module registers once, does nothing without `navigator.serviceWorker`, does
nothing in an insecure context, and swallows a rejected registration; the manifest declares the
scope, start URL and three icons; the icon script produces four valid PNGs (checked by signature and
size, and by re-running it — byte-identical); a CSS guard asserts the 48rem block keeps `100dvh`, a
`100vh` fallback, `env(safe-area-inset-bottom)`, 44 px targets and 16 px inputs.

Pass (M33): Chrome DevTools device emulation at **390×844** (iPhone 12/13/14) against the real
engine and the real bundle — both shells, all eleven routes, the Menu sheet, a streamed chat turn,
`#/pair` before the gate, the SW registered and its cache populated, and the offline card with the
engine stopped. Screenshots into `docs/qa/mobile-web-pass.md`, window content only.

## Not in this unit

- No native app, no store listing, no signing, no Capacitor/Electron Mobile.
- No push notifications, no background sync, no share target, no `beforeinstallprompt` banner.
- No offline chat and no queued turns: a turn needs a provider, and a provider needs a key on the
  desktop.
- No QR pairing, no LAN listener, no bundled tunnel, no per-device scopes.
- No second UI, no phone-only screen, no rewrite of the desktop arrangement.
- No changes to the contract, the API version, or any engine route outside `/chat/`.
