import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";
import { KiraClient } from "../api.ts";
import { ConfirmProvider } from "../confirm.tsx";
import { FAKE_CONFIRM, fakeEngine } from "../fake-engine.ts";
import { MemoryScreen } from "./MemoryScreen.tsx";

function mount(engine: ReturnType<typeof fakeEngine>) {
  const client = new KiraClient({ baseUrl: "http://127.0.0.1:8901", token: "t", fetch: engine.fetch });
  render(
    <ConfirmProvider>
      <MemoryScreen client={client} connected />
    </ConfirmProvider>,
  );
}

async function signIn() {
  // The one confirm dialog every screen shares: its label and its submit button's name, verbatim.
  fireEvent.change(await screen.findByLabelText(/confirm secret/i), { target: { value: FAKE_CONFIRM } });
  fireEvent.click(screen.getByRole("button", { name: /confirm write/i }));
}

beforeEach(() => localStorage.clear());

describe("MemoryScreen", () => {
  it("lists facts with their kind, origin and pin state", async () => {
    mount(fakeEngine());
    expect(await screen.findByText("I prefer pnpm")).toBeTruthy();
    expect(screen.getAllByText("preference").length).toBeGreaterThan(0); // the chip and the kind menu
    expect(screen.getByText(/auto · 42 tokens/)).toBeTruthy();
    expect(screen.getByLabelText("search facts")).toBeTruthy();
  });

  it("adds a fact after the confirm secret is typed", async () => {
    const engine = fakeEngine();
    mount(engine);
    await screen.findByText("I prefer pnpm");
    fireEvent.change(screen.getByLabelText("new fact"), { target: { value: "I am on Windows" } });
    fireEvent.click(screen.getByRole("button", { name: "keep" }));
    await signIn();
    await waitFor(() =>
      expect(engine.calls.some((call) => call.method === "POST" && call.url === "/v1/kira/memory")).toBe(true),
    );
    const post = engine.calls.find((call) => call.method === "POST")!;
    expect(post.headers["X-Kira-Confirm"]).toBe(FAKE_CONFIRM);
    expect(post.body).toBe(JSON.stringify({ text: "I am on Windows", kind: "fact" }));
  });

  it("forgets one fact behind a danger confirm and re-reads the list", async () => {
    const engine = fakeEngine();
    mount(engine);
    await screen.findByText("I prefer pnpm");
    fireEvent.click(screen.getByRole("button", { name: /forget m1/ }));
    await signIn();
    await waitFor(() =>
      expect(engine.calls.some((call) => call.method === "DELETE" && call.url === "/v1/kira/memory/m1")).toBe(true),
    );
  });

  it("switches to history and shows bracketed snippets", async () => {
    mount(fakeEngine());
    fireEvent.click(screen.getByRole("tab", { name: "history" }));
    fireEvent.change(screen.getByLabelText("search history"), { target: { value: "vector" } });
    expect(await screen.findByText(/\[vector\]/)).toBeTruthy();
    expect(screen.getByText(/session sess-9/)).toBeTruthy();
  });

  it("turns capture off through the switch and says what that removes", async () => {
    const engine = fakeEngine();
    mount(engine);
    await screen.findByText("I prefer pnpm");
    fireEvent.click(screen.getByLabelText("capture"));
    await signIn();
    await waitFor(() =>
      expect(
        engine.calls.some((call) => call.method === "PUT" && call.url === "/v1/kira/memory/settings"),
      ).toBe(true),
    );
    expect(await screen.findByText(/remember is hidden from the model/i)).toBeTruthy();
  });

  it("names the tokenizer when it is not trigram", async () => {
    mount(
      fakeEngine({
        memorySettings: { inject: true, capture: "explicit", extract: false, tokenizer: "unicode61" },
      }),
    );
    expect(await screen.findByText("unicode61")).toBeTruthy();
    expect(screen.getByText(/CJK/)).toBeTruthy();
  });

  it("shows the engine's refusal instead of an empty table", async () => {
    mount(fakeEngine({ memoryError: true }));
    expect((await screen.findByRole("alert")).textContent).toContain("cannot read memory");
    // The switches are the engine's settings, not this screen's defaults: a failed read must not
    // render three checkboxes that claim to know what the engine thinks.
    expect(screen.queryByLabelText("inject")).toBeNull();
  });

  it("says so when the export fails instead of dropping the rejection", async () => {
    mount(fakeEngine({ exportError: true }));
    await screen.findByText("I prefer pnpm");
    fireEvent.click(screen.getByRole("button", { name: "export" }));
    expect((await screen.findByRole("alert")).textContent).toContain("cannot export memory");
  });
});
