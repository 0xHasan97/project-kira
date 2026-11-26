import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import App from "./App.tsx";
import { API_PREFIX, API_VERSION, CONTRACT_VERSION } from "./contracts.ts";
import type { ChainRecord } from "./contracts.ts";
import { chain, delta, done, fakeEngine } from "./fake-engine.ts";
import { setLook } from "./look.ts";
import { navigateShell } from "./shell.ts";
import { navigateTheme } from "./theme.ts";

const MODELS = [
  {
    id: "llama-3.3-70b-versatile",
    object: "model",
    owned_by: "groq",
    provider: "groq",
    tier: "fast",
    key_present: true,
    needs_key: true,
    context_window: 131072,
  },
  {
    id: "claude-sonnet-4-5",
    object: "model",
    owned_by: "anthropic",
    provider: "anthropic",
    tier: "powerful",
    key_present: true,
    needs_key: true,
    context_window: 200000,
  },
];

// What this machine actually looked like on 2026-10-29: the catalogue is priority-ordered, and the
// lowest-priority provider is the one with no key.
const UNKEYED_FIRST = [
  {
    id: "llama-3.3-70b-versatile",
    object: "model",
    owned_by: "groq",
    provider: "groq",
    tier: "fast",
    key_present: false,
    needs_key: true,
    context_window: 131072,
  },
  {
    id: "gemini-3.5-flash",
    object: "model",
    owned_by: "gemini",
    provider: "gemini",
    tier: "fast",
    key_present: true,
    needs_key: true,
    context_window: 1048576,
  },
];

// A loopback provider needs no credential. Measured against the sandbox engine: the row read "no key",
// which points the user at the Providers screen to store something the endpoint never asks for.
const KEYLESS_FIRST = [
  {
    id: "llama3",
    object: "model",
    owned_by: "local",
    provider: "local",
    tier: "fast",
    key_present: false,
    needs_key: false,
    context_window: 8192,
  },
  {
    id: "llama-3.3-70b-versatile",
    object: "model",
    owned_by: "groq",
    provider: "groq",
    tier: "fast",
    key_present: false,
    needs_key: true,
    context_window: 131072,
  },
];

const HEALTH = {
  providers: {
    openrouter: {
      failures: 1,
      successes: 0,
      cooling_s: 4.2,
      last_reason: "rate limited",
    },
  },
  configured: [
    {
      name: "groq",
      kind: "openai_compat",
      tier: "fast",
      priority: 50,
      models: ["llama-3.3-70b-versatile"],
      key_present: true,
      needs_key: true,
    },
    {
      name: "openrouter",
      kind: "openai_compat",
      tier: "powerful",
      priority: 100,
      models: ["claude-sonnet-4-5"],
      key_present: false,
      needs_key: true,
    },
  ],
};

function connectedTo(engine: ReturnType<typeof fakeEngine>) {
  vi.stubGlobal("fetch", engine.fetch);
  localStorage.setItem("kira.token", "sekret");
  localStorage.setItem("kira.base", "http://127.0.0.1:8901");
}

function modelSelect(): HTMLSelectElement {
  return screen.getByLabelText("model") as HTMLSelectElement;
}

/**
 * The catalogue lands asynchronously and the picker's option list is the cheapest thing to watch that
 * says it arrived. `Auto` is always the first entry; the model ids follow in catalogue order.
 */
async function pickerOffers(...ids: string[]) {
  await waitFor(() =>
    expect([...modelSelect().options].map((option) => option.value)).toEqual([
      "",
      ...ids,
    ]),
  );
}

beforeEach(() => {
  localStorage.clear();
  // A sitting outlives a route change, so the hook keeps the session and the skill in sessionStorage.
  // Between tests it must not, or one test's turn becomes the next one's restored conversation.
  sessionStorage.clear();
  // jsdom keeps window.location across tests, and the route tests below write it. The query too: the
  // desktop card is chosen by `?companion=1`, and a stale one would make every later test a card.
  window.history.replaceState(null, "", "/chat/");
});

describe("App", () => {
  it("asks for the token when none is stored, and connects once it is typed", async () => {
    const engine = fakeEngine({ models: MODELS, health: HEALTH });
    vi.stubGlobal("fetch", engine.fetch);
    render(<App />);
    // A fresh browser tab has no way to authenticate until the launcher's token is typed here.
    expect(
      screen.getByRole("heading", { name: "Connect to Kira" }),
    ).toBeTruthy();
    expect(engine.calls).toEqual([]);

    fireEvent.change(screen.getByLabelText("Bearer token"), {
      target: { value: "sekret" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Connect" }));

    await waitFor(() => expect(screen.getByLabelText("model")).toBeTruthy());
    expect(localStorage.getItem("kira.token")).toBe("sekret");
    expect(
      engine.calls.some((call) => call.url === `${API_PREFIX}/models`),
    ).toBe(true);
  });

  it("names a revision disagreement after connect, where the gate can no longer show it", async () => {
    // The mismatch message used to exist only inside the connect gate. A bundle left in an open tab
    // against a restarted engine therefore went quiet: dot off, send disabled, no reason anywhere.
    const engine = fakeEngine({
      models: MODELS,
      health: HEALTH,
      healthz: {
        ok: true,
        api_version: API_VERSION,
        contract_version: CONTRACT_VERSION + 1,
        providers_configured: 2,
        default_mode: "AUTO",
      },
    });
    connectedTo(engine);
    render(<App />);

    const banner = await screen.findByRole("alert");
    expect(banner.textContent).toContain(
      `${API_PREFIX} contract v${CONTRACT_VERSION}`,
    );
    expect(banner.textContent).toContain(`contract v${CONTRACT_VERSION + 1}`);
    expect(banner.textContent).toContain("--rebuild");
    expect(screen.getByLabelText("model")).toBeTruthy();
    // It refuses to speak the wrong revision, so nothing but the probe left the page.
    expect(engine.calls.map((call) => call.url)).toEqual(["/healthz"]);
  });

  it("names a namespace disagreement too, not only a revision one", async () => {
    const engine = fakeEngine({
      healthz: {
        ok: true,
        api_version: API_VERSION + 1,
        contract_version: CONTRACT_VERSION,
        providers_configured: 2,
        default_mode: "AUTO",
      },
    });
    connectedTo(engine);
    render(<App />);
    expect((await screen.findByRole("alert")).textContent).toContain(
      `/v${API_VERSION + 1}`,
    );
  });

  it("says why the ledger is empty rather than showing an idle engine", async () => {
    // A rejected token used to be swallowed by the catch that wrapped both side-panel reads, so the chat
    // looked like an engine that had never served a turn instead of one that refuses to answer.
    const engine = fakeEngine({
      models: MODELS,
      healthError: {
        code: "unauthorized",
        message: "token does not match",
        status: 401,
        retryable: false,
      },
    });
    connectedTo(engine);
    render(<App />);
    expect((await screen.findByRole("alert")).textContent).toContain(
      "unauthorized",
    );
  });

  it("says the engine did not answer when the shell is mounted without an engine", async () => {
    // Measured on a phone at 390x844 with the network off: the service worker served the shell, the
    // bearer token was still in localStorage, and the app sat there reading "no models configured"
    // with a red dot and no reason. A cached copy that will not say it is cached reads as broken.
    connectedTo(fakeEngine({ models: MODELS }));
    vi.stubGlobal("fetch", () =>
      Promise.reject(new TypeError("Failed to fetch")),
    );
    render(<App />);

    const banner = await screen.findByRole("alert");
    expect(banner.textContent).toContain("no answer from the engine");
    expect(banner.textContent).toContain("http://127.0.0.1:8901");
    // The token survives: this is a connection to wait on, not a credential to replace.
    expect(localStorage.getItem("kira.token")).toBe("sekret");
  });

  it("sends the user back to the gate after a 401 and shows the refusal", async () => {
    // A token goes stale when the engine is rebuilt with a new one. The shell cannot replace it,
    // so the gate returns with the engine's own sentence; only the token was refused.
    const engine = fakeEngine({
      models: MODELS,
      health: HEALTH,
      modelsError: {
        code: "unauthorized",
        message: "that token does not match this engine",
        status: 401,
        retryable: false,
      },
    });
    connectedTo(engine);
    render(<App />);

    expect(
      await screen.findByRole("heading", { name: "Connect to Kira" }),
    ).toBeTruthy();
    expect(
      await screen.findByText(/that token does not match this engine/),
    ).toBeTruthy();
    expect(localStorage.getItem("kira.token")).toBeNull();
    // The URL is what the user should not have to retype; only the token was refused.
    expect(localStorage.getItem("kira.base")).toBe("http://127.0.0.1:8901");
  });

  it("keeps the shell for a failure that is not about the token", async () => {
    // A stopped engine or a revision mismatch is not a reason to throw away a good token.
    const engine = fakeEngine({
      models: MODELS,
      health: HEALTH,
      modelsError: {
        code: "internal_error",
        message: "the catalogue is not open",
        status: 500,
        retryable: true,
      },
    });
    connectedTo(engine);
    render(<App />);
    expect(await screen.findByLabelText("model")).toBeTruthy();
    expect(localStorage.getItem("kira.token")).toBe("sekret");
  });

  it("streams an answer and shows which provider served it", async () => {
    const chainRecords: ChainRecord[] = [
      {
        provider: "openrouter",
        event: "skipped_missing_key",
        reason: "vault ref 'provider/openrouter' empty",
      },
      { provider: "groq", event: "attempt", model: "llama-3.3-70b-versatile" },
      { provider: "groq", event: "served", model: "llama-3.3-70b-versatile" },
    ];
    const engine = fakeEngine({
      models: MODELS,
      health: HEALTH,
      chunks: [
        chain(chainRecords[0]),
        chain(chainRecords[1]),
        delta("Hello"),
        delta(" there"),
        done({ provider_chain: chainRecords }),
      ],
    });
    connectedTo(engine);
    render(<App />);

    await pickerOffers("llama-3.3-70b-versatile", "claude-sonnet-4-5");

    fireEvent.change(screen.getByLabelText("message"), {
      target: { value: "hi Kira" },
    });
    fireEvent.click(screen.getByRole("button", { name: "send" }));

    expect(await screen.findByText("Hello there")).toBeTruthy();
    const trace = screen.getByLabelText("provider chain");
    expect(within(trace).getByText("trying")).toBeTruthy();
    expect(within(trace).getByText("answered")).toBeTruthy();
    expect(within(trace).getByText("no key")).toBeTruthy();
    // The counters moved behind the routing disclosure; the thread keeps the readable facts.
    expect(screen.getByText("How this answer was routed")).toBeTruthy();
    expect(
      screen.queryByText("1 served · 0 failed · 1 skipped · 0 tool runs"),
    ).toBeNull();
    expect(screen.getByText("0✓ 1✗ 4.2s")).toBeTruthy();
  });

  it("folds the chain into a sentence in the agent shell", async () => {
    localStorage.setItem("kira.shell", "agent");
    const records: ChainRecord[] = [
      { provider: "groq", event: "attempt", model: "llama-3.3-70b-versatile" },
      { provider: "groq", event: "served", model: "llama-3.3-70b-versatile" },
    ];
    const engine = fakeEngine({
      models: MODELS,
      health: HEALTH,
      chunks: [
        chain(records[0]!),
        delta("ok"),
        done({ provider_chain: records }),
      ],
    });
    connectedTo(engine);
    render(<App />);
    fireEvent.change(await screen.findByLabelText("message"), {
      target: { value: "go" },
    });
    fireEvent.click(screen.getByRole("button", { name: "send" }));
    expect(await screen.findByText("ok")).toBeTruthy();
    expect(screen.getByText("Answered by groq")).toBeTruthy();
    expect(screen.getByText("served by groq · 12↑ 7↓")).toBeTruthy();
    // The chat shell's pill list is not the agent shell's transcript.
    expect(screen.queryByLabelText("provider chain")).toBeNull();
  });

  it("keeps the partial answer visible when the turn is interrupted", async () => {
    const engine = fakeEngine({
      models: MODELS,
      health: HEALTH,
      chunks: [
        delta("half an"),
        delta("swer"),
        {
          type: "error",
          error: {
            code: "providers_exhausted",
            message: "every provider was filtered out",
            status: 503,
            retryable: true,
          },
          provider_chain: [
            {
              provider: "groq",
              event: "aborted_mid_stream",
              reason: "client already saw text",
            },
          ],
        },
      ],
    });
    connectedTo(engine);
    render(<App />);

    fireEvent.change(await screen.findByLabelText("message"), {
      target: { value: "go" },
    });
    fireEvent.click(screen.getByRole("button", { name: "send" }));

    expect(await screen.findByText("half answer")).toBeTruthy();
    expect(screen.getByText("cut off mid-stream")).toBeTruthy();
    expect(screen.getByText(/providers_exhausted/)).toBeTruthy();
  });

  it("keeps the streamed text when the shell changes mid-turn", async () => {
    const engine = fakeEngine({
      models: MODELS,
      health: HEALTH,
      holdOpen: true,
      chunks: [delta("still"), delta(" here"), done()],
    });
    connectedTo(engine);
    const view = render(<App />);
    await pickerOffers("llama-3.3-70b-versatile", "claude-sonnet-4-5");

    fireEvent.change(screen.getByLabelText("message"), {
      target: { value: "go" },
    });
    fireEvent.click(screen.getByRole("button", { name: "send" }));
    expect(await screen.findByText("still here")).toBeTruthy();

    fireEvent.click(
      within(screen.getByRole("group", { name: "surface" })).getByRole(
        "button",
        { name: "Agent" },
      ),
    );
    expect(
      view.container.querySelector(".app")?.getAttribute("data-shell"),
    ).toBe("agent");
    expect(screen.getByText("still here")).toBeTruthy();

    engine.releaseStream();
    await waitFor(() =>
      expect(
        (screen.getByRole("button", { name: "send" }) as HTMLButtonElement)
          .disabled,
      ).toBe(false),
    );
    expect(screen.getByText("still here")).toBeTruthy();
  });

  it("sends on Enter and leaves the text alone on Shift+Enter", async () => {
    const engine = fakeEngine({
      models: MODELS,
      health: HEALTH,
      holdOpen: true,
      chunks: [delta("ok"), done()],
    });
    connectedTo(engine);
    render(<App />);
    await pickerOffers("llama-3.3-70b-versatile", "claude-sonnet-4-5");

    const box = screen.getByLabelText("message") as HTMLTextAreaElement;
    fireEvent.change(box, { target: { value: "first line" } });
    fireEvent.keyDown(box, { key: "Enter", shiftKey: true });
    expect(
      engine.calls.some(
        (call) => call.url === `${API_PREFIX}/chat/completions`,
      ),
    ).toBe(false);
    expect(box.value).toBe("first line");

    fireEvent.change(box, { target: { value: "go" } });
    fireEvent.keyDown(box, { key: "Enter" });
    await waitFor(() =>
      expect(
        engine.calls.some(
          (call) => call.url === `${API_PREFIX}/chat/completions`,
        ),
      ).toBe(true),
    );
    // The draft is gone into the turn, and the tile that was "send" is now the way out of it.
    expect(box.value).toBe("");
    expect(screen.getByRole("button", { name: "stop" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "send" })).toBeNull();

    engine.releaseStream();
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "send" })).toBeTruthy(),
    );
  });

  it("counts the working turn in the composer footer", async () => {
    const engine = fakeEngine({
      models: MODELS,
      health: HEALTH,
      holdOpen: true,
      chunks: [delta("ok"), done()],
    });
    connectedTo(engine);
    render(<App />);
    await pickerOffers("llama-3.3-70b-versatile", "claude-sonnet-4-5");

    // Chat has no idle footer: the pickers already say model and routing. Only a working turn
    // gets a line, because the header cannot show elapsed time.
    expect(screen.queryByText(/Enter sends/)).toBeNull();
    fireEvent.change(screen.getByLabelText("message"), {
      target: { value: "go" },
    });
    fireEvent.keyDown(screen.getByLabelText("message"), { key: "Enter" });

    expect(await screen.findByText(/^Working for 0s · 0 steps$/)).toBeTruthy();
    engine.releaseStream();
    await waitFor(() => expect(screen.queryByText(/^Working for/)).toBeNull());
  });

  it("holds the turn open on an approval and posts the decision with the typed secret", async () => {
    const engine = fakeEngine({
      models: MODELS,
      health: HEALTH,
      holdOpen: true,
      confirm: "right",
      chunks: [
        {
          type: "approval",
          id: "ap1",
          tool: "write_file",
          risk: "write",
          arguments: { path: "a.txt" },
        },
        done(),
      ],
    });
    connectedTo(engine);
    render(<App />);
    await pickerOffers("llama-3.3-70b-versatile", "claude-sonnet-4-5");

    fireEvent.change(screen.getByLabelText("message"), {
      target: { value: "write it" },
    });
    fireEvent.click(screen.getByRole("button", { name: "send" }));

    const card = await screen.findByRole("group", {
      name: "approval for write_file",
    });
    expect(within(card).getByText(/a\.txt/)).toBeTruthy();
    fireEvent.change(screen.getByLabelText("approval secret"), {
      target: { value: "right" },
    });
    fireEvent.click(within(card).getByRole("button", { name: "allow" }));

    await waitFor(() =>
      expect(screen.getByText("write_file: allowed")).toBeTruthy(),
    );
    const decision = engine.calls.find(
      (call) => call.url === `${API_PREFIX}/kira/approvals/ap1`,
    );
    expect(decision?.method).toBe("POST");
    expect(decision?.headers["X-Kira-Confirm"]).toBe("right");
    expect(JSON.parse(decision?.body ?? "{}")).toEqual({ decision: "allow" });
    engine.releaseStream();
  });

  it("replays a stored session from the engine instead of keeping its own copy", async () => {
    const engine = fakeEngine({
      models: MODELS,
      health: HEALTH,
      sessions: [{ id: "sess-42", mode: "AUTO", created_at: 1 }],
      messages: {
        "sess-42": [
          {
            id: 1,
            session_id: "sess-42",
            role: "user",
            content: "earlier question",
            provider: null,
            model: null,
            finish_reason: null,
            status: "complete",
            created_at: 1,
            tool_calls: [],
            usage: {},
            chain: [],
          },
          {
            id: 2,
            session_id: "sess-42",
            role: "assistant",
            content: "earlier answer",
            provider: "groq",
            model: "llama",
            finish_reason: "stop",
            status: "complete",
            created_at: 2,
            tool_calls: [],
            usage: { input_tokens: 3, output_tokens: 4 },
            chain: [{ provider: "groq", event: "served" }],
          },
        ],
      },
    });
    connectedTo(engine);
    render(<App />);

    fireEvent.click(await screen.findByRole("button", { name: /sess-42/i }));
    expect(await screen.findByText("earlier answer")).toBeTruthy();
    expect(screen.getByText("3 in · 4 out")).toBeTruthy();
    expect(
      engine.calls.some(
        (call) => call.url === `${API_PREFIX}/kira/sessions/sess-42/messages`,
      ),
    ).toBe(true);
  });

  it("renders every route for real in both shells and a placeholder for none", async () => {
    for (const shell of ["chat", "agent"] as const) {
      localStorage.setItem("kira.shell", shell);
      const engine = fakeEngine({
        models: MODELS,
        health: HEALTH,
        sessions: [
          {
            id: "sess-1",
            mode: "AUTO",
            created_at: 1,
            message_count: 2,
            tokens: 10,
            last_used_at: 2,
          },
        ],
      });
      connectedTo(engine);
      for (const route of [
        "chat",
        "call",
        "overview",
        "providers",
        "models",
        "sessions",
        "tools",
        "skills",
        "memory",
        "avatar",
        "remote",
      ] as const) {
        window.location.hash = `#/${route}`;
        const view = render(<App />);
        expect(await screen.findByText("Kira")).toBeTruthy();
        expect(
          view.container.querySelector(".app")?.getAttribute("data-shell"),
        ).toBe(shell);
        if (route === "tools")
          expect(
            await screen.findByRole("heading", { name: "Tools" }),
          ).toBeTruthy();
        if (route === "skills")
          expect(
            await screen.findByRole("heading", { name: "Skills" }),
          ).toBeTruthy();
        if (route === "memory")
          expect(
            await screen.findByRole("heading", { name: "Memory" }),
          ).toBeTruthy();
        if (route === "avatar")
          expect(
            await screen.findByRole("heading", { name: "Avatar" }),
          ).toBeTruthy();
        if (route === "call")
          expect(
            await screen.findByRole("heading", { name: "Call" }),
          ).toBeTruthy();
        if (route === "remote")
          expect(
            await screen.findByRole("heading", { name: "Remote" }),
          ).toBeTruthy();
        expect(screen.queryByText(/arrives in M12/)).toBeNull();
        // The banner is the one thing a stale bundle can still show, so both shells must carry it.
        expect(
          screen.getByText(`${API_PREFIX} · v${CONTRACT_VERSION}`),
        ).toBeTruthy();
        view.unmount();
      }
    }
  });

  it("opens the command palette from the keyboard and follows a route", async () => {
    const engine = fakeEngine({ models: MODELS, health: HEALTH });
    connectedTo(engine);
    window.location.hash = "#/chat";
    render(<App />);

    fireEvent.keyDown(window, { key: "k", ctrlKey: true });
    const search = await screen.findByLabelText("Search commands");
    fireEvent.change(search, { target: { value: "prompts" } });
    fireEvent.keyDown(search, { key: "Enter" });
    expect(await screen.findByRole("heading", { name: "Prompts" })).toBeTruthy();
  });

  it("hangs the stage on the screen that escaped the reading cap", async () => {
    // `.screen` caps a dashboard at 72rem and styles.css lifts that only for `.screen.avatar-screen`,
    // in both shells. A section that lost one of the two classes would keep the pane and lose the room.
    const engine = fakeEngine({ models: MODELS, health: HEALTH });
    connectedTo(engine);
    window.location.hash = "#/avatar";
    const view = render(<App />);
    await screen.findByRole("heading", { name: "Avatar" });
    expect(
      view.container.querySelector(".pane > .screen.avatar-screen .stage-pane"),
    ).not.toBeNull();
    // The table is the library read's own, so it lands a tick after the heading.
    await screen.findByText("ellen");
    expect(
      view.container.querySelector(".pane > .screen.avatar-screen table.grid"),
    ).not.toBeNull();
  });

  it("asks the engine what a call can do before anyone speaks", async () => {
    const engine = fakeEngine({ models: MODELS, health: HEALTH });
    connectedTo(engine);
    window.location.hash = "#/call";
    render(<App />);
    expect(await screen.findByText("not connected")).toBeTruthy();
    // The screen shows the engine's own install sentence, verbatim, rather than a vague "unavailable".
    expect(
      await screen.findByText(/faster-whisper is not installed/),
    ).toBeTruthy();
    expect(screen.getByText(/piper is not installed/)).toBeTruthy();
    expect(screen.getByText("frames stay on this device")).toBeTruthy();
    expect(
      engine.calls.some((call) => call.url === `${API_PREFIX}/kira/voice`),
    ).toBe(true);
  });

  it("mounts the agent shell once a token is stored", () => {
    localStorage.setItem("kira.shell", "agent");
    const engine = fakeEngine({ models: MODELS, health: HEALTH });
    connectedTo(engine);
    render(<App />);
    expect(
      screen.queryByRole("heading", { name: "Connect to Kira" }),
    ).toBeNull();
    expect(screen.getByRole("group", { name: "surface" })).toBeTruthy();
  });

  it("opens the pairing screen before the token gate and lands in chat once paired", async () => {
    const engine = fakeEngine({ models: MODELS, health: HEALTH });
    vi.stubGlobal("fetch", engine.fetch);
    window.location.hash = "#/pair?code=abcd-1234";
    render(<App />);

    expect(
      screen.getByRole("heading", { name: "Pair this device" }),
    ).toBeTruthy();
    expect(
      screen.queryByRole("heading", { name: "Connect to Kira" }),
    ).toBeNull();

    fireEvent.change(screen.getByLabelText("device name"), {
      target: { value: "phone" },
    });
    fireEvent.click(screen.getByRole("button", { name: "pair" }));

    expect(await screen.findByLabelText("model")).toBeTruthy();
    expect(localStorage.getItem("kira.token")).toBe("kd_test_token");
    expect(window.location.hash).toBe("#/chat");
    const sent = engine.calls.find((call) => call.url === "/v1/kira/pair");
    expect(JSON.parse(String(sent?.body))).toEqual({
      code: "ABCD1234",
      name: "phone",
    });
  });

  it("opens the desktop card in place of the app, with no rail and no picker", async () => {
    const engine = fakeEngine({ models: MODELS, health: HEALTH });
    connectedTo(engine);
    window.location.hash = "#/companion";
    const view = render(<App />);

    expect(await screen.findByText("ellen")).toBeTruthy();
    expect(view.container.querySelector(".companion")).toBeTruthy();
    // The card is a pet, not a second copy of the app: the rail, the mode/model bar and the options
    // button all live in the other window, and one of each is what keeps a 320-pixel window readable.
    expect(view.container.querySelector(".rail")).toBeNull();
    expect(view.container.querySelector(".bar")).toBeNull();
    expect(screen.queryByLabelText("model")).toBeNull();
  });

  it("opens the card from the query the window was created with, before its hash exists", async () => {
    const engine = fakeEngine({ models: MODELS, health: HEALTH });
    connectedTo(engine);
    // The real order: create the window on `/chat/?companion=1`, inject the token, then navigate to
    // `#/companion`. If the injection is slow or fails, this is the frame that would otherwise paint
    // the whole app — rail, picker, gate — inside a frameless 320-pixel window.
    window.history.replaceState(null, "", "/chat/?companion=1");
    const view = render(<App />);

    expect(await screen.findByText("ellen")).toBeTruthy();
    expect(view.container.querySelector(".rail")).toBeNull();
  });

  it("points at the other window when there is no token, instead of showing the gate", async () => {
    const engine = fakeEngine({ models: MODELS, health: HEALTH });
    vi.stubGlobal("fetch", engine.fetch);
    window.location.hash = "#/companion";
    render(<App />);

    // A second token field would be a second place to type the same secret, and the card cannot reach
    // the engine until the app window has it anyway.
    expect(screen.getByText(/connect in the Kira window/)).toBeTruthy();
    expect(
      screen.queryByRole("heading", { name: "Connect to Kira" }),
    ).toBeNull();
    expect(engine.calls).toEqual([]);
  });

  it("writes no secret to storage when the shell and look change", () => {
    localStorage.clear();
    navigateShell("agent");
    navigateTheme("violet");
    setLook({ glass: false });
    const keys = Object.keys(localStorage).sort();
    expect(keys).toEqual(["kira.look", "kira.shell", "kira.theme"]);
    const dump = keys.map((k) => localStorage.getItem(k)).join("|");
    expect(dump).not.toMatch(/confirm|token|secret|key/i);
  });

  it("paints light and dark on the document, and the top-bar control cycles the choice", async () => {
    const engine = fakeEngine({ models: MODELS, health: HEALTH });
    connectedTo(engine);
    localStorage.setItem("kira.appearance", "light");
    window.location.hash = "#/providers";
    const view = render(<App />);

    await screen.findByRole("heading", { name: "Providers" });
    expect(document.documentElement.dataset.mode).toBe("light");
    expect(
      view.container.querySelector(".app")?.getAttribute("data-mode"),
    ).toBe("light");

    fireEvent.click(screen.getByRole("button", { name: /change appearance/ }));
    expect(localStorage.getItem("kira.appearance")).toBe("dark");
    expect(document.documentElement.dataset.mode).toBe("dark");
    expect(
      view.container.querySelector(".app")?.getAttribute("data-mode"),
    ).toBe("dark");
  });

  it("opens the transcript an Overview trouble row points at", async () => {
    const engine = fakeEngine({
      models: MODELS,
      health: HEALTH,
      sessions: [
        {
          id: "sess-9",
          mode: "AUTO",
          created_at: 1,
          message_count: 2,
          tokens: 10,
          last_used_at: 2,
        },
      ],
      messages: {
        "sess-9": [
          {
            id: 1,
            session_id: "sess-9",
            role: "assistant",
            content: "the answer that broke",
            provider: "openrouter",
            model: null,
            finish_reason: null,
            status: "failed",
            created_at: 2,
            tool_calls: [],
            usage: {},
            chain: [
              {
                provider: "openrouter",
                event: "failed",
                reason: "503",
                cooldown_s: 5,
              },
            ],
          },
        ],
      },
    });
    connectedTo(engine);
    window.location.hash = "#/overview";
    render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: "sess-9" }));
    expect(await screen.findByText("the answer that broke")).toBeTruthy();
    expect(window.location.hash).toBe("#/sessions");
  });

  it("reads the provider table from the merged view", async () => {
    const engine = fakeEngine({ models: MODELS, health: HEALTH });
    connectedTo(engine);
    window.location.hash = "#/providers";
    render(<App />);
    expect(await screen.findByText("no key")).toBeTruthy();
    expect(screen.getByText("openrouter")).toBeTruthy();
    // Which provider a call could show the camera to, read from the same row: openrouter declares
    // vision in the fixture, groq does not.
    expect(screen.getByText("vision")).toBeTruthy();
    expect(screen.getByText("text")).toBeTruthy();
    // Only overridden fields get a `was …` line: groq's priority was tuned (base 50, now 5) and
    // openrouter's enabled was (base on, now off). Untuned bases like its priority 100 stay silent.
    expect(screen.getByText(/was 50/)).toBeTruthy();
    expect(screen.getByText(/was on/)).toBeTruthy();
    expect(screen.queryByText(/was 100/)).toBeNull();
    expect(screen.getByText(/settings rows nothing uses/)).toBeTruthy();
    expect(
      engine.calls.some((call) => call.url === `${API_PREFIX}/kira/providers`),
    ).toBe(true);
  });

  it("shows the month's spend, budgets and the honest empty state", async () => {
    const engine = fakeEngine({ models: MODELS, health: HEALTH });
    connectedTo(engine);
    window.location.hash = "#/overview";
    const view = render(<App />);
    expect(await screen.findByText("40")).toBeTruthy();
    expect(screen.getByText(/16,800/)).toBeTruthy();
    expect(screen.getByText(/250,000 \/ 1,000,000/)).toBeTruthy();
    expect(screen.getByText(/no cap/)).toBeTruthy();
    expect(screen.getByText("92.5%")).toBeTruthy();
    // A failed turn has no model to name, but it still counts in `turns` — so the row is here,
    // named, rather than the table quietly adding up to less than the card above it.
    expect(screen.getByText("no model reached")).toBeTruthy();
    expect(screen.getByText(/2 providers served this month/)).toBeTruthy();

    const empty = fakeEngine({
      models: MODELS,
      health: HEALTH,
      overview: {
        month: "2026-11",
        turns: 0,
        tokens: { input: 0, output: 0 },
        success_rate: null,
        interrupted: 0,
        failed: 0,
        by_provider: [],
        by_model: [],
        daily: [],
        budgets: [],
        recent_issues: [],
        refusals: { count: 0, by_code: [], recent: [] },
      },
    });
    // The mounted client bound the fetch it was built with, so a second connectedTo() only
    // reaches the app through a fresh mount — which is also what a month rollover looks like
    // to a user who reloads the page.
    view.unmount();
    connectedTo(empty);
    render(<App />);
    expect(await screen.findByText(/nothing spent in 2026-11/)).toBeTruthy();
  });

  it("keeps chat as the default route", async () => {
    const engine = fakeEngine({ models: MODELS, health: HEALTH });
    connectedTo(engine);
    render(<App />);
    expect(window.location.hash).toBe("");
    expect(await screen.findByLabelText("message")).toBeTruthy();
  });

  describe("the model a fresh turn sends", () => {
    it("sends no model until the user names one", async () => {
      // Measured live 2026-10-29 with four providers configured and one keyed: the picker defaulted to a
      // row that could not answer, so every fresh browser turn came back `503 providers_exhausted`.
      // Defaulting to a row that *can* answer is still a pin, and a pin makes the other providers
      // unreachable from the chat bar. `model: null` is the client saying "the router decides".
      const engine = fakeEngine({ models: UNKEYED_FIRST, health: HEALTH });
      connectedTo(engine);
      render(<App />);

      await pickerOffers("llama-3.3-70b-versatile", "gemini-3.5-flash");
      expect(modelSelect().value).toBe("");
      expect(modelSelect().options[0]?.textContent).toContain("router picks");

      fireEvent.change(screen.getByLabelText("message"), {
        target: { value: "go" },
      });
      fireEvent.click(screen.getByRole("button", { name: "send" }));
      await waitFor(() =>
        expect(
          engine.calls.some(
            (call) => call.url === `${API_PREFIX}/chat/completions`,
          ),
        ).toBe(true),
      );
      const post = engine.calls.find(
        (call) => call.url === `${API_PREFIX}/chat/completions`,
      )!;
      expect(JSON.parse(post.body ?? "{}").model).toBeNull();
    });

    it("says which rows have no key, so the one left behind is explained", async () => {
      const engine = fakeEngine({ models: UNKEYED_FIRST, health: HEALTH });
      connectedTo(engine);
      render(<App />);

      await pickerOffers("llama-3.3-70b-versatile", "gemini-3.5-flash");
      const text = (id: string) =>
        [...modelSelect().options].find((option) => option.value === id)
          ?.textContent ?? "";
      expect(text("llama-3.3-70b-versatile")).toContain("no key");
      expect(text("gemini-3.5-flash")).not.toContain("no key");
    });

    it("still names the models when none of them can answer", async () => {
      // A first run with no keys at all must not get an empty picker: the rows are the evidence that the
      // providers are configured, and the label is what points the user at the Providers screen.
      const engine = fakeEngine({
        models: UNKEYED_FIRST.map((m) => ({ ...m, key_present: false })),
        health: HEALTH,
      });
      connectedTo(engine);
      render(<App />);

      await pickerOffers("llama-3.3-70b-versatile", "gemini-3.5-flash");
      expect(modelSelect().value).toBe("");
    });

    it("never says no key about a provider that does not ask for one", async () => {
      const engine = fakeEngine({ models: KEYLESS_FIRST, health: HEALTH });
      connectedTo(engine);
      render(<App />);

      await pickerOffers("llama3", "llama-3.3-70b-versatile");
      const text = (id: string) =>
        [...modelSelect().options].find((option) => option.value === id)
          ?.textContent ?? "";
      expect(text("llama-3.3-70b-versatile")).toContain("no key");
      expect(text("llama3")).not.toContain("no key");
    });

    it("sends the model the user picks, even when its provider has no key", async () => {
      const engine = fakeEngine({ models: UNKEYED_FIRST, health: HEALTH });
      connectedTo(engine);
      render(<App />);
      await pickerOffers("llama-3.3-70b-versatile", "gemini-3.5-flash");

      fireEvent.change(modelSelect(), {
        target: { value: "llama-3.3-70b-versatile" },
      });
      await waitFor(() =>
        expect(modelSelect().value).toBe("llama-3.3-70b-versatile"),
      );
      fireEvent.click(screen.getByLabelText("refresh"));

      // A deliberate pick survives the re-read: AUTO holds the provider carrying it first, so naming a
      // model is still a preference worth keeping across a refresh.
      await pickerOffers("llama-3.3-70b-versatile", "gemini-3.5-flash");
      await waitFor(() =>
        expect(modelSelect().value).toBe("llama-3.3-70b-versatile"),
      );

      fireEvent.change(screen.getByLabelText("message"), {
        target: { value: "go" },
      });
      fireEvent.click(screen.getByRole("button", { name: "send" }));
      await waitFor(() =>
        expect(
          engine.calls.some(
            (call) => call.url === `${API_PREFIX}/chat/completions`,
          ),
        ).toBe(true),
      );
      const post = engine.calls.find(
        (call) => call.url === `${API_PREFIX}/chat/completions`,
      )!;
      expect(JSON.parse(post.body ?? "{}").model).toBe(
        "llama-3.3-70b-versatile",
      );
    });

    it("drops a pin the catalogue no longer carries", async () => {
      const options = { models: UNKEYED_FIRST as unknown[], health: HEALTH };
      const engine = fakeEngine(options);
      connectedTo(engine);
      render(<App />);
      await pickerOffers("llama-3.3-70b-versatile", "gemini-3.5-flash");

      fireEvent.change(modelSelect(), {
        target: { value: "gemini-3.5-flash" },
      });
      await waitFor(() => expect(modelSelect().value).toBe("gemini-3.5-flash"));
      options.models = [UNKEYED_FIRST[0]!];
      fireEvent.click(screen.getByLabelText("refresh"));

      // A stale id would still be posted, and the engine would refuse it with a 400 the picker cannot
      // explain. Back to Auto is the one landing place the bar can show honestly.
      await pickerOffers("llama-3.3-70b-versatile");
      await waitFor(() => expect(modelSelect().value).toBe(""));
    });
  });

  describe("the model picker", () => {
    // Two providers can serve the same id. The old picker listed the id twice under the same value
    // and labelled each row with one provider — a pin the router never made. It picks by mode,
    // priority, key, budget and cooldown, and fails over between every provider that serves the id.
    const SHARED = [
      {
        id: "llama-3.3-70b-versatile",
        object: "model",
        owned_by: "groq",
        provider: "groq",
        tier: "fast",
        key_present: true,
        needs_key: true,
      },
      {
        id: "llama-3.3-70b-versatile",
        object: "model",
        owned_by: "together",
        provider: "together",
        tier: "powerful",
        key_present: true,
        needs_key: true,
      },
    ];

    it("lists a model once and names every provider that serves it", async () => {
      const engine = fakeEngine({ models: SHARED, health: HEALTH });
      connectedTo(engine);
      render(<App />);
      await pickerOffers("llama-3.3-70b-versatile");

      const options = [...modelSelect().options];
      expect(options[1]!.textContent).toContain("groq");
      expect(options[1]!.textContent).toContain("together");
      expect(options[1]!.textContent).toContain("fast/powerful");
      // Two rows in the catalogue, one id in the picker: Auto plus that one id, not one per provider.
      expect(options).toHaveLength(2);
    });

    it("does not stamp no key on a model another provider can answer", async () => {
      const engine = fakeEngine({
        models: [{ ...SHARED[0]!, key_present: false }, SHARED[1]!],
        health: HEALTH,
      });
      connectedTo(engine);
      render(<App />);
      await pickerOffers("llama-3.3-70b-versatile");
      expect(modelSelect().options[1]!.textContent).not.toContain("no key");
    });
  });

  it("names the budget chain event instead of falling through to the raw code", async () => {
    const chainRecords: ChainRecord[] = [
      {
        provider: "groq",
        event: "skipped_budget",
        reason: "used 1,020,000 of 1,000,000 tokens in 2026-10",
      },
      { provider: "big", event: "served", model: "claude-sonnet-4-5" },
    ];
    const engine = fakeEngine({
      models: MODELS,
      health: HEALTH,
      chunks: [
        chain(chainRecords[0]),
        chain(chainRecords[1]),
        delta("done"),
        done({ provider_chain: chainRecords }),
      ],
    });
    connectedTo(engine);
    render(<App />);
    fireEvent.change(await screen.findByLabelText("message"), {
      target: { value: "go" },
    });
    fireEvent.click(screen.getByRole("button", { name: "send" }));
    const trace = await screen.findByLabelText("provider chain");
    expect(within(trace).getByText("over budget")).toBeTruthy();
    expect(within(trace).getByText(/of 1,000,000 tokens/)).toBeTruthy();
  });

  it("points a budget refusal at the screen that can raise the cap, and shows the chain", async () => {
    const engine = fakeEngine({
      models: MODELS,
      health: HEALTH,
      chatStatus: 429,
      chatJsonError: {
        code: "budget_exhausted",
        message:
          "mode auto: over the monthly cap for 2026-10 (groq) - raise the cap in the dashboard or wait for the reset",
        status: 429,
        retryable: false,
        provider_chain: [
          {
            provider: "groq",
            event: "skipped_budget",
            reason: "used 1,000,000 of 1,000,000 tokens in 2026-10",
          },
        ],
      },
    });
    connectedTo(engine);
    window.location.hash = "#/chat";
    render(<App />);
    await pickerOffers("llama-3.3-70b-versatile", "claude-sonnet-4-5");
    fireEvent.change(screen.getByLabelText("message"), {
      target: { value: "hi Kira" },
    });
    fireEvent.click(screen.getByRole("button", { name: "send" }));

    const link = await screen.findByRole("link", {
      name: "raise a cap in Providers",
    });
    expect(link.getAttribute("href")).toBe("#/providers");
    expect(screen.getByText(/budget_exhausted: mode auto/)).toBeTruthy();
    // Amendment 15: the refusal's chain is part of the turn, so the chip the spec promises is real.
    expect(screen.getByText("over budget")).toBeTruthy();
  });

  it("does not offer a cap link for a refusal that is not about money", async () => {
    const engine = fakeEngine({
      models: MODELS,
      health: HEALTH,
      chatStatus: 503,
      chatJsonError: {
        code: "providers_exhausted",
        message:
          "mode AUTO: nothing left to ask model 'llama-3.3-70b-versatile' - groq: vault ref 'provider/groq' empty",
        status: 503,
        retryable: false,
      },
    });
    connectedTo(engine);
    window.location.hash = "#/chat";
    render(<App />);
    await pickerOffers("llama-3.3-70b-versatile", "claude-sonnet-4-5");
    fireEvent.change(screen.getByLabelText("message"), {
      target: { value: "hi Kira" },
    });
    fireEvent.click(screen.getByRole("button", { name: "send" }));

    expect(
      await screen.findByText(
        /providers_exhausted: mode AUTO: nothing left to ask/,
      ),
    ).toBeTruthy();
    expect(
      screen.queryByRole("link", { name: "raise a cap in Providers" }),
    ).toBeNull();
  });

  it("names the providers the router stood down, and stops promising tokens", async () => {
    const engine = fakeEngine({
      models: MODELS,
      health: HEALTH,
      overview: {
        month: "2026-10",
        turns: 40,
        tokens: { input: 12000, output: 4800 },
        success_rate: 0.925,
        interrupted: 1,
        failed: 2,
        by_provider: [{ provider: "groq", turns: 38, tokens: 1000000 }],
        by_model: [
          {
            provider: "groq",
            model: "llama-3.3-70b-versatile",
            turns: 38,
            tokens: 1000000,
          },
        ],
        daily: [{ date: "2026-10-01", turns: 20, tokens: 9000 }],
        budgets: [
          { provider: "groq", cap: 1000000, used: 1000000, remaining: 0 },
          { provider: "openrouter", cap: null, used: 0, remaining: null },
        ],
        recent_issues: [],
        refusals: { count: 0, by_code: [], recent: [] },
      },
    });
    connectedTo(engine);
    window.location.hash = "#/overview";
    render(<App />);

    expect(await screen.findByText(/used all of 2026-10's cap/)).toBeTruthy();
    expect(
      screen
        .getByRole("link", { name: "raise a cap in Providers" })
        .getAttribute("href"),
    ).toBe("#/providers");
    expect(screen.getByText("1,000,000 / 1,000,000 · at cap")).toBeTruthy();
    // Task 15 rule 4: "N left" is a promise the engine cannot keep while a turn is running.
    expect(screen.queryByText(/[\d,]+ left/)).toBeNull();
    expect(screen.getByText(/Counted from stored turns/)).toBeTruthy();
  });

  it("says nothing about caps when the month still has room", async () => {
    const engine = fakeEngine({ models: MODELS, health: HEALTH });
    connectedTo(engine);
    window.location.hash = "#/overview";
    render(<App />);

    expect(await screen.findByText(/250,000 \/ 1,000,000/)).toBeTruthy();
    expect(
      screen.queryByRole("link", { name: "raise a cap in Providers" }),
    ).toBeNull();
    expect(screen.queryByText(/at cap/)).toBeNull();
  });

  it("use in chat picks the model and moves to the chat pane", async () => {
    const engine = fakeEngine({ models: MODELS, health: HEALTH });
    connectedTo(engine);
    window.location.hash = "#/models";
    render(<App />);
    expect(await screen.findByText("claude-sonnet-4-5")).toBeTruthy();

    fireEvent.click(
      screen.getByRole("button", { name: "use in chat claude-sonnet-4-5" }),
    );
    await waitFor(() => expect(window.location.hash).toBe("#/chat"));
    expect(modelSelect().value).toBe("claude-sonnet-4-5");
  });

  it("starts a turn from the prompts screen", async () => {
    localStorage.setItem("kira.shell", "chat");
    const engine = fakeEngine({ models: MODELS, health: HEALTH });
    connectedTo(engine);
    window.location.hash = "#/prompts";
    render(<App />);

    fireEvent.click(await screen.findByRole("button", { name: "use Summarize" }));
    await waitFor(() => expect(window.location.hash).toBe("#/chat"));
    const box = (await screen.findByLabelText("message")) as HTMLTextAreaElement;
    expect(box.value).toContain("Summarize the following in three sentences");
  });

  it("pins a persona from the skills screen, sends it with the turn, and lets the chip clear it", async () => {
    // A persona is the tab's choice and a method is the model's, so only the persona gets a button here.
    const engine = fakeEngine({
      models: MODELS,
      health: HEALTH,
      skills: {
        skills: [
          {
            name: "concise",
            description: "short answers",
            kind: "persona",
            source: "builtin",
            body_bytes: 40,
          },
          {
            name: "debug",
            description: "bisect a failure",
            kind: "method",
            source: "builtin",
            body_bytes: 90,
          },
        ],
        files: [],
      },
    });
    connectedTo(engine);
    window.location.hash = "#/skills";
    render(<App />);

    expect(await screen.findByText("bisect a failure")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "use debug" })).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "use concise" }));
    await waitFor(() => expect(window.location.hash).toBe("#/chat"));
    expect(
      screen.getByRole("button", { name: "clear skill concise" }),
    ).toBeTruthy();

    fireEvent.change(await screen.findByLabelText("message"), {
      target: { value: "hi" },
    });
    fireEvent.click(screen.getByRole("button", { name: "send" }));
    await waitFor(() =>
      expect(
        engine.calls.some(
          (call) => call.url === `${API_PREFIX}/chat/completions`,
        ),
      ).toBe(true),
    );
    const post = engine.calls.find(
      (call) => call.url === `${API_PREFIX}/chat/completions`,
    )!;
    expect(JSON.parse(post.body ?? "{}").skill).toBe("concise");

    fireEvent.click(
      screen.getByRole("button", { name: "clear skill concise" }),
    );
    expect(
      screen.queryByRole("button", { name: "clear skill concise" }),
    ).toBeNull();
    expect(sessionStorage.getItem("kira.skill")).toBeNull();
  });

  describe("surface switch", () => {
    it("starts on the stored shell and flips the app attribute when clicked", async () => {
      localStorage.setItem("kira.shell", "chat");
      const engine = fakeEngine({ models: MODELS, health: HEALTH });
      connectedTo(engine);
      const view = render(<App />);

      const group = await screen.findByRole("group", { name: "surface" });
      const [chat, agent] = within(group).getAllByRole("button");
      expect(chat!.getAttribute("aria-pressed")).toBe("true");
      expect(agent!.getAttribute("aria-pressed")).toBe("false");
      expect(
        view.container.querySelector(".app")?.getAttribute("data-shell"),
      ).toBe("chat");
      expect(
        view.container.querySelector(".app")?.getAttribute("data-chat-focus"),
      ).toBe("on");

      fireEvent.click(agent!);
      expect(localStorage.getItem("kira.shell")).toBe("agent");
      expect(
        view.container.querySelector(".app")?.getAttribute("data-shell"),
      ).toBe("agent");
      expect(
        view.container.querySelector(".app")?.getAttribute("data-chat-focus"),
      ).toBe("off");
      // The focused chat header unmounts with the shell change; the rail switch is the one now on
      // screen, so read the pressed state from the switch still in the document.
      const switched = screen.getByRole("group", { name: "surface" });
      const [chatNow, agentNow] = within(switched).getAllByRole("button");
      expect(agentNow!.getAttribute("aria-pressed")).toBe("true");
      expect(chatNow!.getAttribute("aria-pressed")).toBe("false");
    });

    it("keeps the connection dot inside the switch", async () => {
      const engine = fakeEngine({ models: MODELS, health: HEALTH });
      connectedTo(engine);
      render(<App />);
      const group = await screen.findByRole("group", { name: "surface" });
      expect(group.querySelector("span.dot.on")).toBeTruthy();
    });

    it("collapses the agent sidebar to a rail and remembers the choice", async () => {
      localStorage.setItem("kira.shell", "agent");
      const engine = fakeEngine({ models: MODELS, health: HEALTH });
      connectedTo(engine);
      const view = render(<App />);
      await screen.findByRole("group", { name: "surface" });

      expect(
        view.container.querySelector(".app")?.getAttribute("data-sidebar"),
      ).toBe("expanded");
      fireEvent.click(screen.getByRole("button", { name: "collapse sidebar" }));
      expect(
        view.container.querySelector(".app")?.getAttribute("data-sidebar"),
      ).toBe("collapsed");
      expect(localStorage.getItem("kira.sidebar")).toBe("collapsed");
      expect(
        screen.getByRole("button", { name: "expand sidebar" }),
      ).toBeTruthy();
    });

    it("names every rail control even when the labels are hidden", async () => {
      localStorage.setItem("kira.shell", "agent");
      localStorage.setItem("kira.sidebar", "collapsed");
      const engine = fakeEngine({ models: MODELS, health: HEALTH });
      connectedTo(engine);
      const view = render(<App />);
      await screen.findByRole("group", { name: "surface" });

      // CSS hides .rail-label in the collapsed rail, so the name has to live on the button itself.
      const rail = view.container.querySelector(".rail") as HTMLElement;
      const named = [...rail.querySelectorAll("button")].map((button) =>
        button.getAttribute("aria-label"),
      );
      for (const name of [
        "Chat",
        "Prompts",
        "Overview",
        "Providers",
        "Models",
        "Sessions",
        "Tools",
        "Skills",
        "Avatar",
        "Remote",
        "refresh",
        "disconnect",
      ]) {
        expect(named, name).toContain(name);
      }
      // The pairing page is a link a phone opens, not a section of this desktop's rail.
      expect(named).not.toContain("Pair a device");
    });

    it("has no collapse control in the chat shell", async () => {
      localStorage.setItem("kira.shell", "chat");
      const engine = fakeEngine({ models: MODELS, health: HEALTH });
      connectedTo(engine);
      render(<App />);
      await screen.findByRole("group", { name: "surface" });
      expect(screen.queryByRole("button", { name: /sidebar/ })).toBeNull();
    });

    it("closes the phone drawer after switching surfaces", async () => {
      localStorage.setItem("kira.shell", "agent");
      const engine = fakeEngine({ models: MODELS, health: HEALTH });
      connectedTo(engine);
      const view = render(<App />);

      await screen.findByRole("group", { name: "surface" });
      fireEvent.click(screen.getByRole("button", { name: "Menu" }));
      const rail = view.container.querySelector(".rail") as HTMLElement;
      expect(rail.getAttribute("data-open")).toBe("on");

      fireEvent.click(
        within(within(rail).getByRole("group", { name: "surface" })).getByRole(
          "button",
          { name: "Chat" },
        ),
      );
      expect(localStorage.getItem("kira.shell")).toBe("chat");
      expect(rail.getAttribute("data-open")).toBe("off");
    });

    it("keeps the conversation header on every section in chat mode", async () => {
      localStorage.setItem("kira.shell", "chat");
      const engine = fakeEngine({ models: MODELS, health: HEALTH });
      connectedTo(engine);
      const view = render(<App />);

      await screen.findByRole("group", { name: "surface" });
      expect(view.container.querySelector(".chat-bar")).toBeTruthy();
      expect(
        screen.getByRole("button", { name: "open sections" }),
      ).toBeTruthy();
      expect(screen.getByText("Kira")).toBeTruthy();

      // Chat mode is a surface, not one route: Providers opens under the same header, with the
      // workspace rail still behind the drawer, instead of silently becoming the agent workspace.
      fireEvent.click(screen.getByRole("button", { name: "Providers" }));
      expect(
        await screen.findByRole("heading", { name: "Providers" }),
      ).toBeTruthy();
      expect(view.container.querySelector(".chat-bar")).toBeTruthy();
      expect(
        view.container.querySelector(".app")?.getAttribute("data-chat-focus"),
      ).toBe("on");
      expect(
        view.container.querySelector(".rail")?.getAttribute("data-open"),
      ).toBe("off");
    });

    it("keeps the agent composer's idle footer", async () => {
      localStorage.setItem("kira.shell", "agent");
      const engine = fakeEngine({ models: MODELS, health: HEALTH });
      connectedTo(engine);
      render(<App />);
      await pickerOffers("llama-3.3-70b-versatile", "claude-sonnet-4-5");
      expect(screen.getByText(/^Enter sends · 2 models · AUTO$/)).toBeTruthy();
    });

    it("starts a new conversation from the sidebar without deleting the old one", async () => {
      localStorage.setItem("kira.shell", "chat");
      sessionStorage.clear();
      const engine = fakeEngine({
        models: MODELS,
        health: HEALTH,
        chunks: [delta("first answer"), done({ session_id: "sess-new" })],
      });
      connectedTo(engine);
      render(<App />);
      await screen.findByRole("group", { name: "surface" });

      fireEvent.change(screen.getByLabelText("message"), {
        target: { value: "hello" },
      });
      fireEvent.click(screen.getByRole("button", { name: "send" }));
      expect(await screen.findByText("first answer")).toBeTruthy();
      expect(sessionStorage.getItem("kira.session")).toBe("sess-new");

      const fresh = await screen.findByRole("button", { name: "New chat" });
      await waitFor(() => expect(fresh.hasAttribute("disabled")).toBe(false));
      fireEvent.click(fresh);

      expect(screen.queryByText("first answer")).toBeNull();
      expect(sessionStorage.getItem("kira.session")).toBeNull();
      expect(await screen.findByText("How can I help?")).toBeTruthy();
      // A pointer change, not a write: the transcript is still in the ledger.
      expect(engine.calls.some((call) => call.method === "DELETE")).toBe(false);
    });
  });

  describe("the rail's refresh", () => {
    it("re-reads the screen on show, not only the engine-wide reads", async () => {
      // Measured in the unit-12 browser pass (2026-10-30): a phone paired while the desktop sat on
      // Remote, and the one button that looks like a re-read changed nothing — it refreshed health
      // and the catalogue, while the device table kept saying nobody had paired.
      const engine = fakeEngine({
        models: MODELS,
        health: HEALTH,
        devices: [],
      });
      connectedTo(engine);
      window.location.hash = "#/remote";
      render(<App />);
      expect(await screen.findByText(/no device has paired yet/)).toBeTruthy();

      const paired = await fetch(`${API_PREFIX}/kira/pair`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ code: "ABCD1234", name: "pixel" }),
      });
      expect(paired.status).toBe(200);

      fireEvent.click(screen.getByLabelText("refresh"));

      expect(await screen.findByText("pixel")).toBeTruthy();
    });
  });
});

describe("the phone bar", () => {
  function rail(): HTMLElement {
    const element = document.querySelector(".rail");
    expect(
      element,
      "the rail is the only copy of the navigation",
    ).not.toBeNull();
    return element as HTMLElement;
  }

  it("reaches the five hot screens without opening the menu", async () => {
    const engine = fakeEngine({ models: MODELS, health: HEALTH, devices: [] });
    connectedTo(engine);
    render(<App />);
    await screen.findByLabelText("model");

    const bar = document.querySelector(".phone-bar") as HTMLElement;
    expect(bar).not.toBeNull();
    fireEvent.click(within(bar).getByLabelText("Sessions"));

    expect(window.location.hash).toBe("#/sessions");

    fireEvent.click(within(bar).getByLabelText("Avatar"));
    expect(window.location.hash).toBe("#/avatar");
  });

  it("keeps every other screen one tap away in the menu, and closes it on a choice", async () => {
    const engine = fakeEngine({ models: MODELS, health: HEALTH, devices: [] });
    connectedTo(engine);
    render(<App />);
    await screen.findByLabelText("model");

    const menu = within(
      document.querySelector(".phone-bar") as HTMLElement,
    ).getByLabelText("Menu");
    expect(menu.getAttribute("aria-expanded")).toBe("false");
    expect(rail().dataset.open).toBe("off");

    fireEvent.click(menu);
    expect(menu.getAttribute("aria-expanded")).toBe("true");
    expect(rail().dataset.open).toBe("on");

    fireEvent.click(within(rail()).getByLabelText("Providers"));
    await waitFor(() => expect(rail().dataset.open).toBe("off"));
    expect(window.location.hash).toBe("#/providers");
  });

  it("says which screen is current, so a thumb and a screen reader agree", async () => {
    const engine = fakeEngine({ models: MODELS, health: HEALTH, devices: [] });
    connectedTo(engine);
    window.location.hash = "#/call";
    render(<App />);
    await screen.findByLabelText("model");

    const bar = document.querySelector(".phone-bar") as HTMLElement;
    expect(
      within(bar).getByLabelText("Call").getAttribute("aria-current"),
    ).toBe("page");
  });

  it("closes the sheet when the page behind it is tapped", async () => {
    const engine = fakeEngine({ models: MODELS, health: HEALTH, devices: [] });
    connectedTo(engine);
    render(<App />);
    await screen.findByLabelText("model");

    fireEvent.click(
      within(
        document.querySelector(".phone-bar") as HTMLElement,
      ).getByLabelText("Menu"),
    );
    expect(rail().dataset.open).toBe("on");

    const scrim = document.querySelector(".rail-scrim") as HTMLElement;
    expect(
      scrim,
      "a sheet with no way out but a choice is a trap",
    ).not.toBeNull();
    fireEvent.click(scrim);

    expect(rail().dataset.open).toBe("off");
    expect(window.location.hash).not.toBe("#/providers");
  });

  it("closes the sheet on Escape, for the keyboard a tablet still has", async () => {
    const engine = fakeEngine({ models: MODELS, health: HEALTH, devices: [] });
    connectedTo(engine);
    render(<App />);
    await screen.findByLabelText("model");

    fireEvent.click(
      within(
        document.querySelector(".phone-bar") as HTMLElement,
      ).getByLabelText("Menu"),
    );
    expect(rail().dataset.open).toBe("on");

    fireEvent.keyDown(window, { key: "Escape" });

    await waitFor(() => expect(rail().dataset.open).toBe("off"));
  });
});
