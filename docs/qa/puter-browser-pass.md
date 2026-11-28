# Puter workspace browser pass — 2026-11-28 (UTC)

Engine: `.venv\Scripts\python.exe -m kira serve --port 8901`, serving `kira-chat/dist` with
`contract_version: 2`. Browser: the app's preview browser in an incognito profile, at 1280×800 and
390×844. Page: `http://127.0.0.1:8901/chat/?v=8#/puter`.

**No live Puter account was used, no credentials were typed, and no paid Puter capability was
started.** The signed-out gate, the SDK fetch and Puter's own sign-in popup were exercised for real.
The signed-in workspace was then rendered against a local stub `window.puter` object so its seven
tabs and responsive layout could be inspected without pretending to be a Puter account. The prices,
models and replies visible in those layout screenshots are stub values, not Puter data.

## Run order

1. Open `#/puter` with no prior SDK in the page. Inspect the gate at desktop and phone widths.
2. Press **Connect Puter** once. The SDK request to `https://js.puter.com/v2/` returns 200 and the
   button changes to **Continue to Puter**.
3. Press **Continue to Puter**. A second tab opens
   `https://puter.com/action/sign-in?embedded_in_popup=true&msg_id=…`; close it without signing in.
4. Confirm the screen shows the human-readable auth error, not a JSON body.
5. Reload, inject the stub SDK, connect, and walk all seven tabs at both widths.
6. Measure `document.documentElement.scrollWidth` against `innerWidth` on the phone.

## Checks

| # | Check | Observed | Verdict |
| --- | --- | --- | --- |
| 1 | route and nav entry | `#/puter` loads **Puter AI**; the Create group holds `Puter AI` between Images and Studio; the header still reads `/v1 · v2`. | matched |
| 2 | signed-out gate | A single card explains user-pays billing, lists chat/images/video/speech/OCR/realtime, and says Kira never asks for or stores an API key. The footer links `developer.puter.com`, `Powered by Puter`, API docs and the user-pays model. | matched |
| 3 | SDK load is explicit | Before the click, no `js.puter.com` script exists. The click fetches it; no other request leaves the page for Puter until sign-in. | matched |
| 4 | sign-in keeps the click's activation | The first click cannot open a popup after the async fetch, so it stops at **Continue to Puter**. The second, real click opens Puter's popup. Calling `signIn()` before any await is what keeps that activation. | matched after fix |
| 5 | auth failure is readable | Closing the popup produces `Authentication window was closed by the user without completing the process. (auth_window_closed)` in the card, wrapped at phone width. The raw SDK object is no longer printed. | matched after fix |
| 6 | signed-in shell | With the stub: account bar (`connected`, username, `sign out`), then `chat · images · speech · vision · video · realtime · models`. Chat shows transcript, composer, model datalist, test-mode and send/clear. | rendered with stub |
| 7 | every tab is present | Images (prompt/model/ratio/test), Speech (TTS with AWS SSML / transcribe / revoice, provider-specific fields), Vision (file or URL, OCR provider), Video (prompt/model/seconds/size/test), Realtime (text/voice, model, voice, instructions), Models (live catalogue table, search, provider filter, refresh). | rendered with stub |
| 8 | phone tabs stay usable | At 390px the tab strip no longer collapses to ~8px; the seven labels form a visible 4+3 grid (~60px high), and a 3-column grid takes over below 380px. The page itself stays at `scrollWidth = 390` with no horizontal page overflow. | matched after fix |
| 9 | desktop spacing | Gate card is readable at 1280px and the footer sits at the bottom of the screen. No console errors during load, connect or tab switching. | matched |

## Findings

- **The phone tab strip collapsed.** `.puter-tabs` is a flex item in the screen's column. Its
  `overflow-x: auto` removes the automatic minimum height, so the column shrank it to 8px and the
  labels were clipped. `flex: 0 0 auto` gives the strip its content height; on phones it becomes a
  4-column grid (3 below 380px), so all seven labels are visible without sideways scrolling or page
  overflow.
- **The first Connect click could not open the popup.** The SDK fetch is asynchronous, so a popup
  opened after it loses the click's user activation. The gate now stops at Continue after loading,
  and the second click calls `signIn()` before any await.
- **The SDK error was rendered as JSON.** The bridge only read `message`; Puter's auth rejection uses
  `msg` + `error`. `puterError` now prefers `message`, then `msg`, then `String(error)`, and appends
  `code`/`errorCode` when present.
- **TTS engine and model were conflated.** AWS Polly takes `engine` while the other providers take
  `model`; the screen now keeps them separate and resets the provider-specific catalogues when the
  provider changes. Output format and OpenAI/Gemini delivery instructions are passed through too.

## Limits

- No live `puter.ai.*` result was observed. Models, replies and prices in the signed-in render come
  from the stub, so this pass does **not** claim that Puter's live providers answer correctly.
- Realtime is beta and needs a paid Puter plan; it was rendered, never started.
- The Puter OpenAI-compatible endpoint was deliberately not wired into Kira's provider registry.
- Reviewer should repeat rows 2-8 with a real free Puter account before calling the integration
  field-verified; that run will bill that account, not Kira.

## Regression

`npm run check` in `kira-chat`: 57 files, 577 tests, typecheck and Vite build pass. The Puter chunk
is 36.79 KB raw / 9.09 KB gzip; its CSS is 4.53 KB / 1.29 KB gzip. Focused tests:
`src/puter.test.ts` (5) and `src/screens/PuterScreen.test.tsx` (10).
