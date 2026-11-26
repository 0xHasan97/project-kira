import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { KiraClient } from "../api.ts";
import type { ModelInfo, OverviewResponse } from "../contracts.ts";
import { fakeEngine, overviewFixture } from "../fake-engine.ts";
import { ModelsScreen } from "./ModelsScreen.tsx";

const MODELS: ModelInfo[] = [
  { id: "llama-3.3-70b-versatile", object: "model", owned_by: "groq", provider: "groq", tier: "fast", key_present: true, needs_key: true, context_window: 131072 },
  { id: "claude-sonnet-4-5", object: "model", owned_by: "anthropic", provider: "anthropic", tier: "powerful", key_present: true, needs_key: true, context_window: 200000 },
];

// The fixtures answer `unknown` on purpose (the fake's options are `unknown`), but this file needs to
// spread one and hand models to a typed prop, so it names the shape it relies on rather than casting
// at each call site.
const OVERVIEW = overviewFixture() as OverviewResponse;

function renderScreen(engine: ReturnType<typeof fakeEngine>, models = MODELS, onUse = vi.fn()) {
  render(
    <ModelsScreen
      client={new KiraClient({ baseUrl: "", token: "sekret", fetch: engine.fetch })}
      models={models}
      onUse={onUse}
    />,
  );
  return onUse;
}

describe("ModelsScreen", () => {
  it("lists every configured model with its tier and its month, including the unused one", async () => {
    const engine = fakeEngine({ overview: overviewFixture() });
    renderScreen(engine);
    expect(await screen.findByText("llama-3.3-70b-versatile")).toBeTruthy();
    expect(screen.getByText("claude-sonnet-4-5")).toBeTruthy();
    expect(screen.getByText("fast")).toBeTruthy();
    expect(screen.getByText("powerful")).toBeTruthy();
    // overviewFixture's by_model has one row: groq/llama-3.3-70b-versatile, 38 turns, 15,000 tokens.
    expect(screen.getByText("38")).toBeTruthy();
    expect(screen.getByText("15,000")).toBeTruthy();
    expect(screen.queryByText("no longer configured")).toBeNull();
  });

  it("shows the zero for a model that was not used, not a blank", async () => {
    const engine = fakeEngine({ overview: overviewFixture() });
    renderScreen(engine);
    await screen.findByText("claude-sonnet-4-5");
    const row = screen.getByRole("row", { name: /claude-sonnet-4-5/ });
    expect(within(row).getAllByText("0")).toHaveLength(2);
  });

  it("keeps a month's history when the config stopped naming the model", async () => {
    const engine = fakeEngine({
      overview: { ...OVERVIEW, by_model: [{ provider: "groq", model: "llama-3.1-8k", turns: 4, tokens: 900 }] },
    });
    renderScreen(engine);
    expect(await screen.findByText("llama-3.1-8k")).toBeTruthy();
    expect(screen.getByText("no longer configured")).toBeTruthy();
    expect(screen.getByText("4")).toBeTruthy();
    expect(screen.getByText("900")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "use in chat llama-3.1-8k" })).toBeNull();
    expect(screen.getByText("groq/llama-3.1-8k")).toBeTruthy();
  });

  it("offers one action per configured model", async () => {
    const engine = fakeEngine({ overview: overviewFixture() });
    const onUse = renderScreen(engine);
    await screen.findByText("llama-3.3-70b-versatile");
    expect(screen.queryByRole("textbox")).toBeNull();
    expect(document.querySelectorAll("table input, table select, table textarea")).toHaveLength(0);
    fireEvent.click(screen.getByRole("button", { name: "use in chat llama-3.3-70b-versatile" }));
    expect(onUse).toHaveBeenCalledWith("llama-3.3-70b-versatile");
  });

  it("leaves the essay off the page and keeps one line of context", async () => {
    const engine = fakeEngine({ overview: overviewFixture() });
    renderScreen(engine);
    expect(await screen.findByText(/Spend for \d{4}-\d{2}/)).toBeTruthy();
    expect(screen.queryByText(/Adding or renaming a model means editing/)).toBeNull();
    expect(screen.queryByText(/interrupted and failed turns are in these numbers/)).toBeNull();
  });

  it("states empty and error as themselves", async () => {
    const empty = fakeEngine({ overview: { ...OVERVIEW, by_model: [] } });
    renderScreen(empty, []);
    expect(await screen.findByText(/Nothing to route to/)).toBeTruthy();

    // A read that rejects, not a read that returns the wrong shape: the fake cannot fail `/v1/kira/overview`
    // with a non-2xx, and useAsync's error state is what a refused or unreachable engine produces.
    const rejects = { overview: async () => { throw new Error("engine went away"); } } as unknown as KiraClient;
    render(<ModelsScreen client={rejects} models={MODELS} onUse={vi.fn()} />);
    await waitFor(() => expect(screen.getByText(/cannot read this month/)).toBeTruthy());
    // A regex, not an exact string: the paragraph is `cannot read this month: ` plus the engine's own
    // words as two text children, and testing-library matches an element's joined direct text.
    expect(screen.getByText(/engine went away/)).toBeTruthy();
  });
});
