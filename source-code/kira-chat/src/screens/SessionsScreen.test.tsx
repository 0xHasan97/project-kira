import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { KiraClient } from "../api.ts";
import { FAKE_CONFIRM, fakeEngine } from "../fake-engine.ts";
import { ConfirmProvider } from "../confirm.tsx";
import { SessionsScreen } from "./SessionsScreen.tsx";

const ROWS = [
  { id: "sess-busy", mode: "AUTO", created_at: 1_700_000_000, message_count: 4, tokens: 1200, last_used_at: 1_700_000_400 },
  { id: "sess-quiet", mode: "POWERFUL", created_at: 1_699_000_000, message_count: 0, tokens: 0, last_used_at: null },
];

const TRANSCRIPT = [
  {
    id: 1, session_id: "sess-busy", role: "user", content: "hi", provider: null, model: null,
    finish_reason: null, status: "complete", created_at: 1_700_000_000, tool_calls: [], usage: {}, chain: [],
  },
  {
    id: 2, session_id: "sess-busy", role: "assistant", content: "hello", provider: "groq", model: "mini",
    finish_reason: "stop", status: "complete", created_at: 1_700_000_400, tool_calls: [],
    usage: { input_tokens: 700, output_tokens: 500 },
    chain: [{ provider: "groq", event: "served", model: "mini" }],
  },
];

function renderScreen(engine: ReturnType<typeof fakeEngine>, props = {}) {
  const onChanged = vi.fn();
  render(
    <ConfirmProvider>
      <SessionsScreen
        client={new KiraClient({ baseUrl: "", token: "sekret", fetch: engine.fetch })}
        focusId={null}
        onChanged={onChanged}
        {...props}
      />
    </ConfirmProvider>,
  );
  return onChanged;
}

async function typeSecret(value = FAKE_CONFIRM) {
  fireEvent.change(await screen.findByLabelText("Confirm secret"), { target: { value } });
  fireEvent.click(screen.getByRole("button", { name: "confirm write" }));
}

describe("SessionsScreen", () => {
  it("lists what each session cost, newest first", async () => {
    const engine = fakeEngine({ sessions: ROWS });
    renderScreen(engine);
    const rows = await screen.findAllByRole("row");
    expect(within(rows[1]).getByText("sess-busy")).toBeTruthy();
    expect(within(rows[2]).getByText("sess-quiet")).toBeTruthy();
    expect(within(rows[2]).getByText("never")).toBeTruthy();
    expect(within(rows[1]).getByText("1,200")).toBeTruthy();
  });

  it("filters by id or mode and says what the filter hid", async () => {
    const engine = fakeEngine({ sessions: ROWS });
    renderScreen(engine);
    await screen.findByText("sess-busy");
    fireEvent.change(screen.getByLabelText("filter sessions"), { target: { value: "powerful" } });
    expect(screen.queryByText("sess-busy")).toBeNull();
    expect(screen.getByText("sess-quiet")).toBeTruthy();
    expect(screen.getByText("1 of 2 stored")).toBeTruthy();
    fireEvent.change(screen.getByLabelText("filter sessions"), { target: { value: "zzz" } });
    expect(screen.getByText(/No session matches/)).toBeTruthy();
  });

  it("says empty in the engine's words, not a dash", async () => {
    const engine = fakeEngine({ sessions: [] });
    renderScreen(engine);
    expect(await screen.findByText("No sessions yet.")).toBeTruthy();
  });

  it("opens a transcript that shows the turn the engine stored", async () => {
    const engine = fakeEngine({ sessions: ROWS, messages: { "sess-busy": TRANSCRIPT } });
    renderScreen(engine);
    fireEvent.click(await screen.findByRole("button", { name: "transcript sess-busy" }));
    expect(await screen.findByText("hi")).toBeTruthy();
    expect(screen.getByText("hello")).toBeTruthy();
    expect(screen.getByText("answered")).toBeTruthy();
    expect(engine.calls.some((call) => call.url === "/v1/kira/sessions/sess-busy/messages")).toBe(true);
  });

  it("gives a user row only what a user row has — no status word and no token count", async () => {
    const engine = fakeEngine({ sessions: ROWS, messages: { "sess-busy": TRANSCRIPT } });
    renderScreen(engine);
    fireEvent.click(await screen.findByRole("button", { name: "transcript sess-busy" }));
    await screen.findByText("hi");
    const items = screen.getAllByRole("listitem");
    const user = items.find((item) => item.className.includes("turn-user"))!;
    const assistant = items.find((item) => item.className.includes("turn-assistant"))!;
    expect(within(user).queryByText("complete")).toBeNull();
    expect(within(user).queryByText(/tokens/)).toBeNull();
    expect(within(assistant).getByText("complete")).toBeTruthy();
    expect(within(assistant).getByText("1,200 tokens")).toBeTruthy();
  });

  it("offers a Markdown export once the transcript has turns", async () => {
    const engine = fakeEngine({ sessions: ROWS, messages: { "sess-busy": TRANSCRIPT } });
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
    renderScreen(engine);
    fireEvent.click(await screen.findByRole("button", { name: "transcript sess-busy" }));
    await screen.findByText("hello");
    const button = screen.getByRole("button", { name: "export .md" }) as HTMLButtonElement;
    expect(button.disabled).toBe(false);
    fireEvent.click(button);
    expect(click).toHaveBeenCalledOnce();
  });

  it("renders the transcript the engine was already pointing at", async () => {
    const engine = fakeEngine({ sessions: ROWS, messages: { "sess-busy": TRANSCRIPT } });
    renderScreen(engine, { focusId: "sess-busy" });
    expect(await screen.findByText("hello")).toBeTruthy();
  });

  it("deletes one after naming it and its message count", async () => {
    const engine = fakeEngine({ sessions: ROWS, deleted: { deleted: 1, messages: 4 } });
    const onChanged = renderScreen(engine);
    fireEvent.click(await screen.findByRole("button", { name: "delete sess-busy" }));
    expect(await screen.findByText(/delete sess-busy and its 4 messages/)).toBeTruthy();
    await typeSecret();
    await waitFor(() =>
      expect(
        engine.calls.some(
          (call) =>
            call.method === "DELETE" &&
            call.url === "/v1/kira/sessions/sess-busy" &&
            call.headers["X-Kira-Confirm"] === FAKE_CONFIRM,
        ),
      ).toBe(true),
    );
    await waitFor(() => expect(onChanged).toHaveBeenCalled());
  });

  it("sends nothing when the delete is cancelled", async () => {
    const engine = fakeEngine({ sessions: ROWS });
    renderScreen(engine);
    fireEvent.click(await screen.findByRole("button", { name: "delete sess-quiet" }));
    fireEvent.click(await screen.findByRole("button", { name: "cancel" }));
    await waitFor(() => expect(engine.calls.filter((call) => call.method !== "GET").length).toBe(0));
  });

  it("closes the transcript of the session it just deleted", async () => {
    const engine = fakeEngine({
      sessions: ROWS,
      messages: { "sess-busy": TRANSCRIPT },
      deleted: { deleted: 1, messages: 2 },
    });
    renderScreen(engine);
    fireEvent.click(await screen.findByRole("button", { name: "transcript sess-busy" }));
    await screen.findByText("hello");
    fireEvent.click(screen.getByRole("button", { name: "delete sess-busy" }));
    await typeSecret();
    // A panel left open over a gone session could only say "it was never answered", which is a
    // different truth than "you deleted it a second ago".
    await waitFor(() =>
      expect(screen.queryByRole("region", { name: "transcript sess-busy" })).toBeNull(),
    );
  });

  it("clears all after the secret, with no extra words to type", async () => {
    const engine = fakeEngine({ sessions: ROWS, deleted: { deleted: 2, messages: 4 } });
    renderScreen(engine);
    fireEvent.click(await screen.findByRole("button", { name: "delete every session" }));

    // Deleting the whole history is one destructive write, so it asks for the secret like any other.
    // An extra phrase on top of that was friction without a second guarantee: the engine only ever
    // checks the secret, and the words never left this dialog.
    expect(screen.queryByLabelText(/to allow this/)).toBeNull();
    fireEvent.change(await screen.findByLabelText("Confirm secret"), { target: { value: FAKE_CONFIRM } });
    fireEvent.click(screen.getByRole("button", { name: "confirm write" }));
    await waitFor(() =>
      expect(
        engine.calls.some(
          (call) =>
            call.method === "DELETE" && call.url === "/v1/kira/sessions" && !call.body,
        ),
      ).toBe(true),
    );
    expect(engine.calls.some((call) => JSON.stringify(call.body ?? "").includes("DELETE ALL"))).toBe(false);
  });
});
