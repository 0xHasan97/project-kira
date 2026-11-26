# Skills — browser pass, 2026-10-30

Unit 7's client half, driven in a real Chromium against the built bundle. The engine was
`tools/kira_lab.py` (throwaway data dir, `mock_openai` on loopback, both secrets disposable),
the pack was the four builtin files, and nothing here touched the user's Locker or a real
provider.

## What was opened

`http://127.0.0.1:8912/chat/#/skills` after storing the lab's token in `localStorage` — the
same gate a user sees.

## What the screen said

| Row | kind | source | size | control |
| --- | --- | --- | --- | --- |
| `concise` — "Answer in the fewest words that are still true." | persona | builtin | 244 B | `use concise` |
| `debug` — "Reproduce, observe, narrow, fix, prove …" | method | builtin | 726 B | `the model loads it` |
| `research` — "Decompose a question, search narrowly …" | method | builtin | 663 B | `the model loads it` |
| `reviewer` — "Review code for defects first, style second …" | persona | builtin | 352 B | `use reviewer` |

`files` listed all four as `loaded`. The rail names **Skills** between Tools and Memory in
both shells, and `GET /v1/kira/skills` is the single read behind the screen (network log:
`[GET] /v1/kira/skills => 200`).

## What the button did

1. `use reviewer` → hash became `#/chat` and the composer showed
   `skill: reviewer · clear` next to the model/mode line.
2. A turn was sent ("say hi in five words"). The request body, read from the browser's own
   network record, was:
   ```json
   {"messages":[{"role":"user","content":"say hi in five words"}],"model":"mini","mode":"AUTO","session_id":null,"skill":"reviewer","stream":true}
   ```
   and the response was `200 text/event-stream`; the stored turn came back `complete`,
   `mini`, `100↑ / 50↓`, `1 served · 0 failed` — so the engine accepted the persona name
   (an unknown name is a `400 config_error`, and pinning a **method** is a `400` whose
   message names `use_skill`; both are engine tests, not defects of this pass).
3. Clicking the chip cleared it: the button disappeared and
   `sessionStorage.getItem("kira.skill")` was `null`.

## What this pass does not claim

- **The mock provider cannot echo its prompt**, so this pass does not show the persona text
  arriving at a model. What it shows is the browser's wire truth (`skill` in the body, a
  `200`, a completed turn) and the engine's assembly rule is proved where it can be:
  `tests/test_skills.py` asserts the persona is the **first** system message and the memory
  block follows it.
- **`use_skill` was not exercised by a model here.** The tool exists only because methods
  loaded (the fixture shows the two methods), and its enum/semantics are engine tests.
- The pack is the four shipped starter files, not a user pack: shadowing and a skipped file
  are unit- and engine-tested, not browser-driven.
- No live provider was called; this pass spends nothing.
