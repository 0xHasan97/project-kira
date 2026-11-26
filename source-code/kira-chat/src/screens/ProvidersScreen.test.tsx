import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { KiraClient } from "../api.ts";
import type { ProviderView } from "../contracts.ts";
import { fakeEngine, providersFixture } from "../fake-engine.ts";
import { ConfirmProvider } from "../confirm.tsx";
import { ProvidersScreen } from "./ProvidersScreen.tsx";

const client = (engine: ReturnType<typeof fakeEngine>) =>
  new KiraClient({ baseUrl: "", token: "sekret", fetch: engine.fetch });

function renderScreen(engine: ReturnType<typeof fakeEngine>, onChanged = vi.fn()) {
  render(
    <ConfirmProvider>
      <ProvidersScreen client={client(engine)} onChanged={onChanged} />
    </ConfirmProvider>,
  );
  return onChanged;
}

describe("ProvidersScreen writes", () => {
  it("renders every provider before anything is clicked", async () => {
    const engine = fakeEngine({ providers: providersFixture() });
    renderScreen(engine);
    expect(await screen.findByText("groq")).toBeTruthy();
    // Amendment 36 again: a `was …` line only appears for an overridden field, so groq's tuned
    // priority (base 50) reads `was 50` and openrouter's untouched base 100 stays silent.
    expect(screen.getByText(/was 50/)).toBeTruthy();
    expect(screen.queryByText(/was 100/)).toBeNull();
    expect(engine.calls.filter((call) => call.method === "PUT").length).toBe(0);
  });

  it("does not report a missing key for a provider that asks for none", async () => {
    // The sandbox engine's only provider was a loopback server with no credential, and this table told
    // the user "no key" — the wording of a problem to fix. A keyless stanza has nothing to store.
    const base = providersFixture() as { month: string; orphan_settings: string[]; providers: ProviderView[] };
    const local: ProviderView = {
      ...base.providers[0],
      name: "local",
      base_url: "http://127.0.0.1:11434/v1",
      models: ["llama3"],
      key_ref: "",
      key_present: false,
      needs_key: false,
    };
    const engine = fakeEngine({ providers: { ...base, providers: [...base.providers, local] } });
    renderScreen(engine);

    const row = (await screen.findByText("local")).closest("[data-provider]");
    expect(row?.textContent).toContain("no key needed");
    expect(within(row as HTMLElement).queryByText("no key")).toBeNull();
    expect(within(row as HTMLElement).getByRole("button", { name: "forget key local" }).hasAttribute("disabled")).toBe(true);
  });

  it("toggling a provider applies immediately, with no confirm dialog", async () => {
    const engine = fakeEngine({ providers: providersFixture() });
    const onChanged = renderScreen(engine);
    fireEvent.click(await screen.findByLabelText("enabled groq"));
    await waitFor(() =>
      expect(
        engine.calls.some(
          (call) =>
            call.method === "PUT" &&
            call.url === "/v1/kira/providers/groq/settings" &&
            call.headers["X-Kira-Confirm"] === undefined &&
            call.body === JSON.stringify({ enabled: false }),
        ),
      ).toBe(true),
    );
    expect(screen.queryByLabelText("Confirm secret")).toBeNull();
    await waitFor(() => expect(onChanged).toHaveBeenCalled());
  });

  it("cap 0 means unlimited and the clear button means back to config.yaml", async () => {
    const engine = fakeEngine({ providers: providersFixture() });
    renderScreen(engine);
    // groq is the provider whose cap has an override, so both buttons are meaningful on it: `0`
    // stores unlimited, `clear override` only exists while an override is there to clear.
    const cap = await screen.findByLabelText("monthly cap groq");
    fireEvent.change(cap, { target: { value: "0" } });
    // Wait for the controlled field to commit before clicking: the suite runs files in parallel,
    // and a click dispatched in the same task as the change can still read the old render.
    await waitFor(() => expect((cap as HTMLInputElement).value).toBe("0"));
    fireEvent.click(screen.getByRole("button", { name: "set cap groq" }));
    await waitFor(() =>
      expect(engine.calls.some((call) => call.body === JSON.stringify({ monthly_cap: 0 }))).toBe(true),
    );
    fireEvent.click(await screen.findByRole("button", { name: /clear override groq/ }));
    await waitFor(() =>
      expect(engine.calls.some((call) => call.body === JSON.stringify({ monthly_cap: null }))).toBe(true),
    );
    expect(screen.queryByLabelText("Confirm secret")).toBeNull();
  });

  it("test spends one probe, renders the answer inline, and forget never echoes the key", async () => {
    const engine = fakeEngine({ providers: providersFixture() });
    renderScreen(engine);
    fireEvent.click(await screen.findByRole("button", { name: "test groq" }));
    expect(await screen.findByText(/3 models · 120ms/)).toBeTruthy();
    expect(screen.queryByLabelText("Confirm secret")).toBeNull();

    fireEvent.change(screen.getByLabelText("new key groq"), { target: { value: "gsk_pasted" } });
    fireEvent.click(screen.getByRole("button", { name: "store key groq" }));
    // Pasting a key is not authorised by a second secret: no dialog, the write goes straight out.
    expect(screen.queryByLabelText("Confirm secret")).toBeNull();
    await waitFor(() =>
      expect(
        engine.calls.some(
          (call) => call.url === "/v1/kira/providers/groq/key" && call.body === JSON.stringify({ key: "gsk_pasted" }),
        ),
      ).toBe(true),
    );
    expect(engine.calls.every((call) => !call.url.includes("gsk_pasted"))).toBe(true);
    // The store write re-read the table, so the row has to be found again before the next click.
    fireEvent.click(await screen.findByRole("button", { name: "forget key groq" }));
    expect(screen.queryByLabelText("Confirm secret")).toBeNull();
    await waitFor(() =>
      expect(
        engine.calls.some((call) => call.method === "DELETE" && call.url === "/v1/kira/providers/groq/key"),
      ).toBe(true),
    );
  });

  it("marks the provider the router is standing down, and only that one", async () => {
    // The router filters `cap is not None and used >= cap` (router.py:107). The table used to show
    // two numbers and leave the subtraction to the reader, so the one row that no longer answers
    // looked exactly like the ones that still did.
    const base = providersFixture() as { month: string; orphan_settings: string[]; providers: ProviderView[] };
    const withSpend = (name: string, spend: number, cap: number | null): ProviderView => ({
      ...base.providers[0],
      name,
      monthly_cap: { base: null, override: cap, effective: cap },
      spend_this_month: spend,
    });
    const engine = fakeEngine({
      providers: { ...base, providers: [...base.providers, withSpend("at-cap", 300_000, 300_000), withSpend("unlimited", 900_000, null)] },
    });
    renderScreen(engine);

    const atCap = (await screen.findByText("at-cap")).closest("[data-provider]") as HTMLElement;
    expect(within(atCap).getByText("at cap")).toBeTruthy();
    const groq = (await screen.findByText("groq")).closest("[data-provider]") as HTMLElement;
    expect(within(groq).queryByText("at cap")).toBeNull();
    const unlimited = screen.getByLabelText("monthly cap unlimited").closest("[data-provider]") as HTMLElement;
    expect(within(unlimited).queryByText("at cap")).toBeNull();
  });

  it("keeps each provider's controls on its own card, with no page-level essay", async () => {
    const engine = fakeEngine({ providers: providersFixture() });
    renderScreen(engine);
    const card = (await screen.findByText("groq")).closest("[data-provider]") as HTMLElement;
    expect(within(card).getByLabelText("monthly cap groq")).toBeTruthy();
    expect(within(card).getByRole("button", { name: "test groq" })).toBeTruthy();
    expect(screen.queryByText(/the router reads it before the health ledger/)).toBeNull();
  });
});
