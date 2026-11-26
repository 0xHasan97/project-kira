# Kira unit 12 — remote reach: loopback + pairing tokens

Date: 2026-10-30. Status: design, executing as M25 (engine) and M26 (client, docs, pass).

## The rule this unit is built around

Ultron's phone access was a `0.0.0.0` bind: one socket, every interface, one bearer token
that is also the key to the provider vault. Rule 5 forbids that outright, and the reason is
not cosmetic — a LAN or public listener in Kira's own process is a second, weaker door to
`data_dir`, the workspace and the tool harness.

So **Kira never listens off loopback.** Not on the LAN, not on `0.0.0.0`, not behind a flag.
The phone reaches the desktop through a transport the user runs and owns — Tailscale Serve,
`cloudflared`, an SSH tunnel — which forwards to `127.0.0.1:8901`. That transport is the
network boundary, and it is the user's decision, not a default.

What Kira adds is the part the transport does not: **a device has to be paired, and its
token is not the engine token.**

## Two principals

| Principal | How it proves itself | What it may do |
| --- | --- | --- |
| **Owner** | the engine token printed on first run (Locker) | everything |
| **Device** | a token minted by pairing | reads, and chat turns |

The distinction is not enforced by source IP — behind a tunnel every request arrives from
`127.0.0.1`, so an address check would be a lie. It is enforced by what the two tokens can
reach:

- **Mutations already need `X-Kira-Confirm`**, a second Locker secret that is never stored
  in `localStorage` and never leaves the desktop. A device never has it, so every
  confirm-gated route — provider settings, keys, cooldowns, probes, history deletion,
  approvals, tool policies, memory writes, checkpoint restore, pairing codes, device
  revocation — is closed to a device by construction, not by a list someone has to maintain.
- Two reads are owner-only as well, because they are about the security surface itself:
  `GET /v1/kira/devices` and anything that mints a code.

Chat is allowed, and that is deliberate: a paired phone is *you*. It can start a turn, and a
turn can use `allow` tools exactly as it can from the desktop. What it cannot do is approve
an `ask` tool or change a policy — those still happen at the desk, which is the whole point
of the confirm secret.

## Pairing

1. On the desktop, `#/remote` mints a code: 8 characters, Crockford-ish base32, **120 s**,
   single use. Codes live in engine memory only — a restart invalidates them, which is the
   right failure.
2. The screen composes a link from a tunnel base the user pastes in (defaults to the
   current origin) plus `/chat/#/pair?code=…`, and offers a copy button.
3. The phone opens the link. `#/pair` renders **before** the token gate — that is the one
   page a device with no token can reach. It asks for a name, posts `{code, name}` to
   `POST /v1/kira/pair` (no bearer), and receives `{token, device}`.
4. The phone stores the token in its own `localStorage` and its base stays empty, so every
   request resolves against the tunnel origin the page was served from.
5. The desktop's device table shows name, created and last seen; revoke is confirm-gated.

Exchange rate limit: at most 10 attempts per minute per engine process, so a code cannot be
ground down by a script even at 40 bits of entropy. A **per-code attempt counter would be
the wrong defence** — guessing wrong codes never names the real one, so the only way to
attribute an attempt is to guess correctly, at which point the code is already spent. The
window is what bounds an attacker; the TTL bounds the code.

Token shape: `kd_` + 43 characters of `secrets.token_urlsafe(32)`. Only the **SHA-256** of
the token is stored; a database copy is not a key to the engine. `last_seen_at` is updated
on use.

## What the phone can and cannot do, explicitly

| Route | Device |
| --- | --- |
| `POST /v1/chat/completions`, `/v1/chat/completions/stream` | yes |
| reads: models, health, sessions, messages, overview, providers (no keys), skills, tools, memory (read), voice status | yes |
| `POST /v1/kira/pairing-code`, `GET /v1/kira/devices`, `DELETE /v1/kira/devices/{id}` | no (owner/confirm) |
| every confirm-gated mutation | no (no `X-Kira-Confirm`) |
| `POST /v1/voice` WebSocket | yes, with the device token in the same place the owner token goes |

## HTTPS, and why the phone's microphone needs it

`getUserMedia` requires a secure context. A tunnel that terminates TLS (Tailscale Serve,
Cloudflare Tunnel) gives the phone HTTPS and the call screen works. A bare
`http://192.168.1.20:8901` does **not** — and Kira will not serve that, by design. The
`#/remote` screen says this in one line rather than letting a user discover it when the
microphone silently refuses.

## API additions (contract v2, additive)

```
POST   /v1/kira/pair                 no bearer      {code, name} -> {token, device}
POST   /v1/kira/pairing-code         owner + confirm -> {code, expires_at}
GET    /v1/kira/devices              owner          -> {devices:[{id,name,created_at,last_seen_at}]}
DELETE /v1/kira/devices/{id}         owner + confirm -> {deleted:true}
```

`API_VERSION` stays 1 and `CONTRACT_VERSION` stays 2. The three existing auth errors keep
their codes; a bad pairing code is `400 pairing_refused` with a message that does not say
which of expired/used/wrong it was.

## Storage

Schema v3: a `devices` table `(id, name, token_hash, created_at, last_seen_at, revoked_at)`,
migrated in one transaction the way v2 was. A revoked row stays: "this device was paired and
then revoked" is history the user may want, and the token can never authenticate again.

## Acceptance tests

Engine: a code pairs exactly once; expiry and the third wrong attempt are refused; the token
authenticates a read and cannot confirm a write or mint a code; revoking 401s it; listings
carry no hash; the raw token appears in no row; a v2 database gains the table with its
messages intact; drift gate green.

Client: `#/remote` mints a code behind the confirm dialog and shows a link that contains it;
the device table revokes; `#/pair?code=…` works with no token, stores the returned token and
opens chat; a refused code says so; every route still renders in both shells.

## Not in this unit

- **No QR code.** The link is copyable; a QR encoder is a dependency this unit does not need.
- **No LAN listener of any kind**, no UPnP, no tunnel bundled or installed.
- **No per-device scopes.** A device is you; if you want a weaker device, do not pair one.
- **No CLI verb.** Minting a code is a desktop action while the desktop is open.
