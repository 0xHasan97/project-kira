import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { KiraClient } from "../api.ts";
import type { OverviewResponse } from "../contracts.ts";
import { fakeEngine, overviewFixture } from "../fake-engine.ts";
import { OverviewScreen } from "./OverviewScreen.tsx";

const client = (engine: ReturnType<typeof fakeEngine>) =>
  new KiraClient({ baseUrl: "", token: "sekret", fetch: engine.fetch });

function renderScreen(overview: OverviewResponse) {
  const engine = fakeEngine({ overview });
  render(<OverviewScreen client={client(engine)} onOpenSession={vi.fn()} />);
}

const EMPTY: OverviewResponse = {
  ...(overviewFixture() as OverviewResponse),
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
};

describe("OverviewScreen refusals", () => {
  it("reports a refusal in a month that spent nothing, because no row could hold it", async () => {
    renderScreen({
      ...EMPTY,
      refusals: {
        count: 2,
        by_code: [{ code: "budget_exhausted", count: 2 }],
        recent: [
          {
            code: "budget_exhausted",
            message: "mode AUTO: over the monthly cap for 2026-10 (groq) - raise the cap in the dashboard",
            mode: "AUTO",
            model: null,
            created_at: 1,
          },
        ],
      },
    });
    expect(await screen.findByText("nothing spent in 2026-10 yet — the month is empty, not broken.")).toBeTruthy();
    expect(screen.getByText("Refused before starting")).toBeTruthy();
    expect(screen.getByText(/2 turns in 2026-10 never reached a provider/)).toBeTruthy();
    expect(screen.getByText(/budget_exhausted ×2/)).toBeTruthy();
    expect(screen.getByText(/over the monthly cap for 2026-10 \(groq\)/)).toBeTruthy();
  });

  it("says nothing about refusals when the engine had someone to ask every time", async () => {
    renderScreen(EMPTY);
    await screen.findByText("nothing spent in 2026-10 yet — the month is empty, not broken.");
    expect(screen.queryByText("Refused before starting")).toBeNull();
  });
});
