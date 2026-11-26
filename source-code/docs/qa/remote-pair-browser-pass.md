# Remote reach — browser pass, 2026-10-30

Unit 12's two screens and both principals, driven in a real Chromium against the built
bundle. The engine was `tools/kira_lab.py` (throwaway data dir, in-process memory vault,
`mock_openai` on 8999, engine on 8912). Nothing here touched the user's Locker, a real
provider, or a real tunnel.

## The phone, in this pass

There is no second machine here, and the engine must not listen off loopback. So the phone
is a **second browser context on a second origin**: `http://127.0.0.1:8913`, a throwaway
Starlette/httpx streaming proxy that forwards to 8912 byte-for-byte (it drops
`content-length`/`accept-encoding` and streams `aiter_raw`). LocalStorage is per-origin, so
8913 really does start with no token — which is the one property of a phone that matters to
this pass. The proxy is a stand-in for the user's tunnel, **not** a tunnel: it is plain
HTTP, on loopback, with no certificate.

## What pairing did

1. `http://127.0.0.1:8913/chat/#/pair` rendered the pairing form with `localStorage` empty —
   `#/pair` sits before the token gate on purpose, because the code is the only credential a
   phone arrives with.
2. The desktop minted `31FRMYKT` (then `NRA83HNN` for "pixel"), each with a
   `good until 2026-10-30 16:20` line and a link of the shape
   `http://127.0.0.1:8913/chat/#/pair?code=NRA83HNN`.
3. Entering the code on 8913 stored a token of **46 characters** starting `kd_`, and
   `localStorage["kira.base"]` stayed empty (the phone talks to the origin it was paired on).
4. The phone sent "say hi" and got a completed turn: `mock_one · complete · mini · 100↑ / 50↓ ·
   1 served · 0 failed · 0 skipped · 0 tool runs`.

## The device table, and one defect it found

On a fresh load, `#/remote` listed both devices with paired/last-seen stamps and a
`revoke <name>` button each.

The defect: **the rail's refresh did not re-read the screen on show.** It re-read `healthz`
and the model catalogue, so after a phone paired the table kept saying "no device has paired
yet" with no control that could change that short of a route change or reload. This is a real
user story — the phone pairs while the desktop sits on Remote. Fixed test-first:
`src/App.test.tsx` → "re-reads the screen on show, not only the engine-wide reads" reads red
against the old deps and green once every data screen takes a `pull` counter that `refresh()`
increments (`useAsync` deps gained it: Overview, Models, Providers, Sessions, Tools, Skills,
Memory, Remote).

Proved live through the same defect's exit: a third device ("tablet") was paired out of band
with `curl`, the rail's refresh was pressed, the browser's own resource timings showed the
third `/v1/kira/devices` read, and the `tablet` row appeared without a reload.

An earlier symptom of the same pass was an engine-side defect, not a UI one: the phone's
first screen fired two reads in parallel and sqlite answered one of them with
`InterfaceError: bad parameter or other API misuse`, surfacing as `health => 500` and
`sessions => 401`. One shared `sqlite3.Connection` across FastAPI's threadpool was the cause;
the store now keeps one connection per thread (WAL, `busy_timeout=5000`). Test:
`tests/test_store.py::test_one_store_serves_four_threads_without_colliding` — red with three
distinct sqlite errors under a 4-thread storm, green after. The engine suite is 499 passed,
1 skipped.

## Revoking

`revoke pixel` opened the confirm dialog ("its token stops authenticating on the next
request"), the confirm secret went out once in `X-Kira-Confirm`, and the row disappeared from
the table. The revoked token then answered:

```
GET /v1/kira/health -> 401 {"error":{"code":"unauthorized","message":"missing or invalid bearer token","status":401,"retryable":false}}
```

Opening a fresh tab on 8913 with that token in `localStorage` landed on **Connect to Kira**
and the token was removed — the unit-13 rule that a refused token returns to the gate, seen
here for a device token rather than the owner's.

## The battery, verbatim

Two principals on one engine, one token each. `$D` is the paired device's `kd_…` token, `$O`
the owner's, all through 8912:

| Request | Status | Body |
| --- | --- | --- |
| `GET /v1/kira/devices` as `$D` | 401 | `this endpoint needs the engine token from the desktop, not a device token` |
| `POST /v1/kira/pairing-code` as `$D` | 401 | same message |
| `GET /v1/kira/memory` as `$D` | 200 | `{"memories":[],"total":0,"settings":{…}}` |
| `POST /v1/kira/memory` as `$D`, no confirm | 401 | `this write needs the confirm secret in X-Kira-Confirm - re-enter it in the dialog` |
| `GET /v1/kira/health` as `$O` | 200 | providers and configured stanzas |
| `POST /v1/chat/completions` as `$D` | 200 | `"status":"complete"`, `provider_chain` `attempt` → `served` |

The confirm message is the boundary by construction: a device token can read and chat, and
the secret that unlocks every write never leaves the desktop, so there is nothing on the phone
to steal that would let it change a key, a memory, a policy or a deletion.

## Observations that are not Kira defects

- `sessions?limit=30` took 4.7 s once through the proxy. Eight parallel `curl`s straight at
  8912 answered in ~2 ms each, so engine-side contention is disproved; the slow path is the
  browser/proxy keep-alive stand-in, which no shipped code contains.
- A desktop tab opened before a rebuild kept its pre-fix bundle after a same-hash navigation;
  only `location.reload()` picked up the new one. That is how a stale tab looks, not a cache
  bug in the bundle (the assets are content-hashed).

## What this pass does not claim

- No physical phone, no TLS, no microphone permission: `getUserMedia` needs HTTPS and the
  call screen stays desktop-only until the user's tunnel provides it.
- The proxy is not Tailscale Serve or `cloudflared`; certificate handling and DNS are the
  user's tunnel's job and untested here.
- No QR code, no LAN listener, no per-device scopes, no CLI verb for pairing — each is listed
  as out of unit 12 in the design and the roadmap.
- The pairing-code rate limit (10 attempts / 60 s, single use, 120 s TTL) was exercised by
  engine tests, not by hammering the lab by hand.
- No live provider was called; the lab's providers are the mock and its keys are disposable.
