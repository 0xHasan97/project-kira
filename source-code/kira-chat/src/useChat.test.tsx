import { act, renderHook, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { KiraClient } from "./api.ts";
import { delta, done, fakeEngine } from "./fake-engine.ts";
import { useChat } from "./useChat.ts";

const client = () => new KiraClient({ baseUrl: "http://127.0.0.1:8901", token: "t" });

describe("useChat", () => {
  const ROWS = {
    "sess-77": [
      { id: 1, session_id: "sess-77", role: "user", content: "earlier", provider: null, model: null, finish_reason: null, status: "complete", created_at: 1, tool_calls: [], usage: {}, chain: [] },
      { id: 2, session_id: "sess-77", role: "assistant", content: "earlier answer", provider: "groq", model: "mini", finish_reason: "stop", status: "complete", created_at: 2, tool_calls: [], usage: { input_tokens: 3, output_tokens: 4 }, chain: [{ provider: "groq", event: "served" }] },
    ],
  };

  it("remembers the session a turn created, so a reload continues the same sitting", async () => {
    sessionStorage.clear();
    const first = fakeEngine({ chunks: [delta("hi"), done({ session_id: "sess-77" })] });
    vi.stubGlobal("fetch", first.fetch);
    const one = renderHook(() =>
      useChat({ client: client(), model: "mini", mode: "AUTO", connected: true, watching: true }),
    );
    act(() => one.result.current.setPrompt("go"));
    act(() => void one.result.current.send());
    await waitFor(() => expect(one.result.current.busy).toBe(false));
    expect(sessionStorage.getItem("kira.session")).toBe("sess-77");
    one.unmount();

    // A reload: a fresh hook against an engine that still holds the session.
    const second = fakeEngine({ messages: ROWS, chunks: [delta("again"), done({ session_id: "sess-77" })] });
    vi.stubGlobal("fetch", second.fetch);
    const two = renderHook(() =>
      useChat({ client: client(), model: "mini", mode: "AUTO", connected: true, watching: true }),
    );
    await waitFor(() => expect(two.result.current.entries.map((entry) => entry.content)).toEqual(["earlier", "earlier answer"]));
    expect(two.result.current.sessionId).toBe("sess-77");

    act(() => two.result.current.setPrompt("next"));
    act(() => void two.result.current.send());
    await waitFor(() => expect(two.result.current.busy).toBe(false));
    const post = second.calls.filter((call) => call.url === "/v1/chat/completions").at(-1)!;
    expect(JSON.parse(post.body ?? "{}").session_id).toBe("sess-77");
  });

  it("forgets a stored session the engine no longer has", async () => {
    sessionStorage.setItem("kira.session", "sess-gone");
    const engine = fakeEngine({ messages: {} });
    vi.stubGlobal("fetch", engine.fetch);
    const { result } = renderHook(() =>
      useChat({ client: client(), model: "mini", mode: "AUTO", connected: true, watching: true }),
    );
    await waitFor(() => expect(sessionStorage.getItem("kira.session")).toBeNull());
    expect(result.current.sessionId).toBeNull();
  });

  it("remembers the session the rail opened", async () => {
    sessionStorage.clear();
    const engine = fakeEngine({ messages: ROWS });
    vi.stubGlobal("fetch", engine.fetch);
    const { result } = renderHook(() =>
      useChat({ client: client(), model: "mini", mode: "AUTO", connected: true, watching: false }),
    );
    await act(() => result.current.openSession("sess-77"));
    expect(sessionStorage.getItem("kira.session")).toBe("sess-77");
  });

  it("starts a fresh session without deleting the old one", async () => {
    sessionStorage.setItem("kira.session", "sess-77");
    const engine = fakeEngine({ messages: ROWS, chunks: [delta("fresh"), done({ session_id: "sess-new" })] });
    vi.stubGlobal("fetch", engine.fetch);
    const { result } = renderHook(() =>
      useChat({ client: client(), model: "mini", mode: "AUTO", connected: true, watching: true }),
    );
    await waitFor(() => expect(result.current.entries).toHaveLength(2));

    act(() => result.current.newChat());
    expect(result.current.entries).toEqual([]);
    expect(result.current.sessionId).toBeNull();
    expect(sessionStorage.getItem("kira.session")).toBeNull();
    // A new chat is a pointer change, not a delete: the old transcript stays in the ledger.
    expect(engine.calls.some((call) => call.method === "DELETE")).toBe(false);

    act(() => result.current.setPrompt("next"));
    act(() => void result.current.send());
    await waitFor(() => expect(result.current.busy).toBe(false));
    const post = engine.calls.filter((call) => call.url === "/v1/chat/completions").at(-1)!;
    expect(JSON.parse(post.body ?? "{}").session_id).toBeNull();
    expect(sessionStorage.getItem("kira.session")).toBe("sess-new");
  });

  it("keeps the streamed text in one place while a turn is in flight", async () => {
    const engine = fakeEngine({ holdOpen: true, chunks: [delta("half an"), delta("swer"), done()] });
    vi.stubGlobal("fetch", engine.fetch);

    const { result } = renderHook(() =>
      useChat({ client: client(), model: "mini", mode: "AUTO", connected: true, watching: false }),
    );

    act(() => result.current.setPrompt("go"));
    act(() => void result.current.send());

    await waitFor(() => expect(result.current.live?.text).toBe("half answer"));
    expect(result.current.busy).toBe(true);

    act(() => engine.releaseStream());
    await waitFor(() => expect(result.current.busy).toBe(false));
    expect(result.current.live).toBeNull();
    expect(result.current.entries.at(-1)?.content).toBe("half answer");
  });

  it("records a refusal as a failed turn with its chain", async () => {
    const engine = fakeEngine({
      chatStatus: 429,
      chatJsonError: {
        code: "budget_exhausted",
        message: "over the cap",
        status: 429,
        retryable: false,
        provider_chain: [{ provider: "groq", event: "skipped_budget", reason: "used all of it" }],
      },
    });
    vi.stubGlobal("fetch", engine.fetch);

    const { result } = renderHook(() =>
      useChat({ client: client(), model: "mini", mode: "AUTO", connected: true, watching: false }),
    );

    act(() => result.current.setPrompt("go"));
    act(() => void result.current.send());
    await waitFor(() => expect(result.current.busy).toBe(false));

    const turn = result.current.entries.at(-1)?.turn;
    // The engine stores an empty failed turn as `failed`; a bubble that says `interrupted` for the same
    // row changes its own history when the user reloads the session.
    expect(turn?.status).toBe("failed");
    expect(turn?.errorCode).toBe("budget_exhausted");
    expect(turn?.chain[0]?.event).toBe("skipped_budget");
  });

  it("does not file a turn into the session the user switched to mid-answer", async () => {
    sessionStorage.clear();
    const OTHER = {
      "sess-other": [
        { id: 9, session_id: "sess-other", role: "user", content: "a question in B", provider: null, model: null, finish_reason: null, status: "complete", created_at: 1, tool_calls: [], usage: {}, chain: [] },
        { id: 10, session_id: "sess-other", role: "assistant", content: "an answer in B", provider: "groq", model: "mini", finish_reason: "stop", status: "complete", created_at: 2, tool_calls: [], usage: {}, chain: [] },
      ],
    };
    const engine = fakeEngine({
      holdOpen: true,
      messages: { ...ROWS, ...OTHER },
      chunks: [delta("answer for A"), done({ session_id: "sess-77" })],
    });
    vi.stubGlobal("fetch", engine.fetch);

    const { result } = renderHook(() =>
      useChat({ client: client(), model: "mini", mode: "AUTO", connected: true, watching: false }),
    );
    // A is the session this turn was asked in.
    await act(() => result.current.openSession("sess-77"));
    act(() => result.current.setPrompt("go"));
    act(() => void result.current.send());
    await waitFor(() => expect(result.current.busy).toBe(true));

    // The user opens B while A is still streaming — the sidebar is clickable, so this can happen.
    await act(() => result.current.openSession("sess-other"));
    expect(result.current.entries.map((entry) => entry.content)).toEqual(["a question in B", "an answer in B"]);

    act(() => engine.releaseStream());
    await waitFor(() => expect(result.current.busy).toBe(false));

    // B keeps B's transcript, and the hook stays on B; A's answer was never appended to it.
    expect(result.current.sessionId).toBe("sess-other");
    expect(result.current.entries.map((entry) => entry.content)).toEqual(["a question in B", "an answer in B"]);
  });

  it("calls a stop an interruption even when nothing had streamed yet", async () => {
    const engine = fakeEngine({ holdOpen: true, chunks: [delta("half an")] });
    vi.stubGlobal("fetch", engine.fetch);

    const { result } = renderHook(() =>
      useChat({ client: client(), model: "mini", mode: "AUTO", connected: true, watching: false }),
    );
    act(() => result.current.setPrompt("go"));
    act(() => void result.current.send());
    await waitFor(() => expect(result.current.live?.text).toBe("half an"));
    act(() => result.current.stop());
    await waitFor(() => expect(result.current.busy).toBe(false));

    const turn = result.current.entries.at(-1)?.turn;
    expect(turn?.status).toBe("interrupted");
    expect(turn?.text).toBe("half an");
    // The DOMException's own wording ("The user aborted a request.") is not an error the user caused a
    // provider to make; the bubble says what happened instead.
    expect(turn?.error).toBe("you stopped this turn");
  });
});
