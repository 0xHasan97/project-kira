# Unit 13 — findings closeout: design addendum — 2026-10-30

Source findings: [`docs/qa/dashboard-browser-pass.md`](../qa/dashboard-browser-pass.md) §Findings.
That pass was run on 2026-10-29 against a mock provider and left twelve findings. Two were fixed
inside the units that owned the code (the spend ledger stopped delete-all from re-arming caps; an
omitted `usage` is now estimated and labelled). This addendum records the decisions for the other
ten, so a later reader can tell a deliberate choice from an oversight.

Nothing here changes `API_VERSION` (1) or `CONTRACT_VERSION` (2): every wire change is additive.

## F1 — a plan-time refusal has no row to live in

`Router.plan()` raises before `create_session()`, which is exactly what "refused" means — no session,
no user row, no spend. The consequence was that the engine could not report the refusal at all, and
the Overview could not answer "how often did this month hit the ceiling?".

Decision: a `refusals` table outside `messages` (`code`, `message`, `mode`, `model`, `created_at`),
written by `build_run()` for `BudgetExhausted` and `AllProvidersExhausted` only. A `ConfigError` is
the caller's mistake and already answers 400 with the reason; counting typos as refusals would make
the ledger noise. `GET /v1/kira/overview` grows `refusals: {count, by_code, recent}` and the screen
renders it **outside** the `turns === 0` branch — a month that spent nothing is the month a refusal
produces, so hiding the block there would hide the finding.

Refusals survive `delete every session` on purpose: they are not history, they are the record that
history was never written. The Overview's spend meter still re-arms on history deletion, which stays
a known, documented asymmetry (data model section of the dashboard spec).

## F2 — plan notes belong to the turn, not to each agent step

`Router.events()` re-yielded `plan.notes` on every step, so a two-step agent turn showed the same
`over budget` chip twice and stored the note twice in the chain. `AttemptState` now carries
`notes_emitted`; the first `events()` call speaks the notes, later steps do not. The stored chain is
what the screen replays, so fixing the yield fixes both.

## F6 — a refused token returns to the gate

Only `unauthorized` on the first read clears `kira.token` and re-renders the connect form. Every
other failure keeps the shell, the token and the engine URL, because those are failures the screens
already show and asking for the token again would be busywork. The distinction lives in `App.tsx`'s
refresh handler; `useChat` still reads the same boolean the ledger uses.

## F7 — an override equal to the baseline is not stored

`matches_baseline()` compares an override to `config.yaml` **by effect** (`_effective`), not by raw
value: `monthly_cap: 0` means "no cap", so it matches a YAML `cap: null` and stores nothing. A write
that lands on the baseline clears the row instead of storing `on — was on`, which used to leave a
`clear override` button that cleared nothing.

## F8 — a sitting is a tab, not a page load

The session id moved from React state alone to `sessionStorage["kira.session"]`:
`sessionStorage` because two tabs are two sittings and a browser restart is a new one, but a reload
or a route change is the same conversation. The stored id is adopted on mount, the transcript is
re-read, and a session the engine no longer holds is forgotten rather than replayed as an error.
This is a conversation id, not a secret; the `localStorage` secret claim is untouched, and the README
says which key lives where.

## F9 — the model picker groups by id and names every provider

The API takes a model id and the router chooses the provider by mode → priority → key → budget →
cooldown. The option value therefore stays the bare id, but duplicate ids collapse into one option
labelled with every provider that serves it, and `no key` appears only when **none** of them can
answer. The chain chips still name who actually served the turn.

## F10 — Providers says `at cap` where the router acts

The row now carries the router's own test (`effective cap is not null and spend >= cap`, with `0`
already folded to null by `overrides.py`). It is the same moment the provider stops being a
candidate, not an estimate.

## F11 — `never` stays as defensive display

`last_used_at` is `MAX(messages.created_at)`, and the only way to have a session with no message is
to create one and never answer — which the refusal path does not do, because it raises before
`create_session`. Every row the UI can produce has a timestamp, so `never` describes a state the
product cannot reach. Decision: keep the fallback (the store type allows it, and a wiped message
table would produce it), and record here that it is unreachable by a user. No code change.

## F12 — a user row shows only what a user row has

Status and token columns are assistant vocabulary. The transcript now prints them only on assistant
rows; a user row keeps its role and its text.

## Not changed in this unit

- History deletion still resets the derived spend meter while the settings overrides survive. The
  meter counts what is stored; that is self-consistent and recorded in the dashboard spec's data
  model. A refusal ledger does not change it.
- A provider that omits `usage` on a step is already estimated and labelled; nothing further.

## Proof

`docs/qa/unit-13-findings-pass.md` lists, per finding, the test that would fail without the fix and
the gates that were run. No second browser pass was claimed: the fixes are covered by engine and
client tests, and the browser behaviours they change (refresh, 401, cap badge, refusal block) are
each asserted at the component or API boundary.
