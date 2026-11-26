import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { AgentPanel, PANEL_TABS } from "./AgentPanel.tsx";
import { API_PREFIX, CONTRACT_VERSION } from "../contracts.ts";
import type { ChainRecord } from "../contracts.ts";
import { emptyTurn } from "../turn.ts";
import type { ChatState } from "../useChat.ts";

function chatWith(overrides: Partial<ChatState> = {}): ChatState {
  return {
    entries: [], sessionId: null, sessions: [], health: null, prompt: "", setPrompt: () => {},
    skill: null, setSkill: () => {},
    busy: false, live: null, ledgerError: null, connected: true, send: () => {}, stop: () => {},
    openSession: async () => {}, newChat: () => {}, pullLedger: () => {}, decideApproval: async () => {},
    ...overrides,
  };
}

function quietClient() {
  return {
    tools: vi.fn().mockResolvedValue({ tools: [], plugins: [] }),
    checkpoints: vi.fn().mockResolvedValue({ checkpoints: [] }),
  } as never;
}

function mount(chat: ChatState = chatWith(), client: ReturnType<typeof quietClient> = quietClient(), modelChoices: { id: string; contextWindowText: string }[] = []) {
  return render(<AgentPanel chat={chat} model="mini" mode="AUTO" client={client} modelChoices={modelChoices} />);
}

describe("AgentPanel", () => {
  it("shows ALTREX's eight tabs in the donor's order", () => {
    mount(undefined, undefined, [{ id: "mini", contextWindowText: "8k" }]);
    expect(screen.getAllByRole("tab").map((tab) => tab.textContent)).toEqual([...PANEL_TABS]);
    expect([...PANEL_TABS]).toEqual([
      "Changes", "Terminal", "Tests", "Problems", "Agents", "Checkpoints", "Context", "Developer",
    ]);
  });

  it.each([
    ["Changes", "no file writes this turn"],
    ["Terminal", "no commands this turn"],
    ["Tests", "no test runs this turn"],
    ["Problems", "no problems this turn"],
    ["Checkpoints", "no session yet"],
  ])("the %s tab says nothing happened yet instead of dressing an empty list", (tab, text) => {
    mount(undefined, undefined, [{ id: "mini", contextWindowText: "8k" }]);
    fireEvent.click(screen.getByRole("tab", { name: tab }));
    expect(screen.getByRole("tabpanel").textContent).toContain(text);
  });

  it("fills the harness tabs from chain records", async () => {
    const chain: ChainRecord[] = [
      { event: "checkpoint_created", tool: "write_file", checkpoint_id: "cp1", files: 1 },
      { event: "tool_executed", tool: "write_file", ok: true, chars: 40, risk: "write", summary: "a.txt" },
      {
        event: "tool_executed",
        tool: "run_command",
        ok: false,
        chars: 20,
        risk: "exec",
        summary: "python -m pytest",
        kind: "test",
        exit_code: 1,
        duration_ms: 12,
      },
      { event: "tool_denied", tool: "write_file", reason: "tool is denied by policy" },
    ];
    const turn = { ...emptyTurn(), chain };
    const chat = chatWith({ entries: [{ id: 1, role: "assistant", content: "", turn }] });
    const client = {
      tools: vi.fn().mockResolvedValue({
        tools: [
          { name: "write_file", risk: "write", policy: "ask", source: "builtin", description: "", parameters: {}, default_policy: "ask", overridden: false },
        ],
        plugins: [],
      }),
      checkpoints: vi.fn().mockResolvedValue({ checkpoints: [] }),
    } as never;

    mount(chat, client, [{ id: "mini", contextWindowText: "8k" }]);
    fireEvent.click(screen.getByRole("tab", { name: /Changes/ }));
    expect(screen.getByText(/a\.txt/)).toBeTruthy();
    fireEvent.click(screen.getByRole("tab", { name: /Terminal/ }));
    expect(screen.getByText(/python -m pytest/)).toBeTruthy();
    fireEvent.click(screen.getByRole("tab", { name: /Tests/ }));
    expect(screen.getByText(/exit 1/)).toBeTruthy();
    fireEvent.click(screen.getByRole("tab", { name: /Problems/ }));
    expect(screen.getByText(/denied by policy/)).toBeTruthy();
    fireEvent.click(screen.getByRole("tab", { name: /Agents/ }));
    expect(await screen.findByText("write_file")).toBeTruthy();
  });

  it("the Agents tab shows the turn's chain as a step timeline", () => {
    const turn = { ...emptyTurn(), status: "complete" as const, chain: [
      { provider: "groq", event: "attempt" as const, model: "mini" },
      { provider: "groq", event: "served" as const, model: "mini" },
      { provider: "kira", event: "tool_executed" as const, tool: "echo", ok: true, chars: 3 },
    ] };
    mount(chatWith({ entries: [{ id: 1, role: "assistant", content: "hi", turn }] }), undefined, [{ id: "mini", contextWindowText: "8k" }]);
    fireEvent.click(screen.getByRole("tab", { name: "Agents" }));
    const panel = screen.getByRole("tabpanel");
    expect(within(panel).getByText("trying")).toBeTruthy();
    expect(within(panel).getByText("answered")).toBeTruthy();
    expect(within(panel).getByText("tool ran")).toBeTruthy();
    expect(panel.textContent).toContain("echo");
  });

  it("the Context tab reads the session, model, mode and usage", () => {
    const turn = { ...emptyTurn(), status: "complete" as const, usage: { prompt_tokens: 12, completion_tokens: 7 } };
    mount(chatWith({ sessionId: "sess-abcdef12", entries: [{ id: 1, role: "assistant", content: "hi", turn }] }), undefined, [{ id: "mini", contextWindowText: "8k" }]);
    fireEvent.click(screen.getByRole("tab", { name: "Context" }));
    const panel = screen.getByRole("tabpanel");
    expect(panel.textContent).toContain("sess-abc");
    expect(panel.textContent).toContain("mini");
    expect(panel.textContent).toContain("AUTO");
    expect(panel.textContent).toContain("12↑ / 7↓");
  });

  it("the Developer tab names the provenance contract", () => {
    mount(undefined, undefined, [{ id: "mini", contextWindowText: "8k" }]);
    fireEvent.click(screen.getByRole("tab", { name: "Developer" }));
    const panel = screen.getByRole("tabpanel");
    expect(panel.textContent).toContain(API_PREFIX);
    expect(panel.textContent).toContain(`v${CONTRACT_VERSION}`);
    expect(panel.textContent).toContain("provider_chain");
  });

  it("says when there is no turn yet, instead of an empty timeline", () => {
    mount(undefined, undefined, [{ id: "mini", contextWindowText: "8k" }]);
    fireEvent.click(screen.getByRole("tab", { name: "Agents" }));
    expect(screen.getByRole("tabpanel").textContent).toContain("no turn yet");
  });
});
