import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { ChainRecord } from "../contracts.ts";
import { TurnTrace } from "./TurnTrace.tsx";

const read: ChainRecord = {
  event: "tool_executed",
  tool: "read_file",
  call_id: "c1",
  ok: true,
  risk: "read",
  summary: "src/app.ts",
  chars: 812,
};
const ran: ChainRecord = {
  event: "tool_executed",
  tool: "run_command",
  call_id: "c2",
  ok: true,
  risk: "exec",
  summary: "npm test",
  duration_ms: 2410,
};
const broke: ChainRecord = {
  event: "tool_executed",
  tool: "run_command",
  call_id: "c3",
  ok: false,
  risk: "exec",
  summary: "pnpm build",
  exit_code: 2,
};

describe("TurnTrace", () => {
  it("folds the steps into one sentence a human can read", () => {
    render(<TurnTrace chain={[read, ran]} status="complete" provider="gemini" usage={null} />);
    expect(screen.getByText("Read 1 file and ran 1 command")).toBeTruthy();
    expect(screen.getByText("2 steps")).toBeTruthy();
    expect(screen.getByText("Read")).toBeTruthy();
    expect(screen.getByText("2.4 s")).toBeTruthy();
  });

  it("names what broke beside the count, and marks the row", () => {
    const { container } = render(<TurnTrace chain={[read, broke]} status="complete" provider="gemini" usage={null} />);
    expect(screen.getByText("Couldn't run")).toBeTruthy();
    expect(screen.getByText("1 failed")).toBeTruthy();
    expect(container.querySelector('[data-status="failed"]')?.textContent).toContain("pnpm build");
  });

  it("pulses before the first step, and shows a live bar once work is happening", () => {
    const { container, rerender } = render(<TurnTrace chain={[]} status="streaming" provider={null} usage={null} />);
    expect(screen.getByText("Working")).toBeTruthy();
    expect(container.querySelector(".activity")?.getAttribute("data-kind")).toBe("dots");
    rerender(<TurnTrace chain={[read]} status="streaming" provider={null} usage={null} />);
    expect(container.querySelector(".activity")?.getAttribute("data-kind")).toBe("bars");
  });

  it("stops counting an ask as pending once the turn settles", () => {
    // Measured live 2026-10-31: after the command ran, the transcript still showed the ask row with a
    // clock. The decision is history by then — only a turn that is still open can be waiting on one.
    const asked: ChainRecord = {
      event: "tool_approval_requested",
      tool: "run_command",
      call_id: "c4",
      risk: "exec",
      summary: "npm test",
      approval_id: "ap1",
    };
    const { container } = render(<TurnTrace chain={[asked, ran]} status="complete" provider="gemini" usage={null} />);
    expect(screen.getByText("Asked to run")).toBeTruthy();
    expect(container.querySelector('[data-status="waiting"]')).toBeNull();
    expect(container.querySelector(".trace-row")?.getAttribute("data-status")).toBe("note");
  });

  it("says who answered, and what it cost, under the work", () => {
    render(
      <TurnTrace
        chain={[{ provider: "groq", event: "served", model: "llama" }]}
        status="complete"
        provider="groq"
        usage={{ prompt_tokens: 704, completion_tokens: 21 }}
      />,
    );
    expect(screen.getByText("Answered by groq")).toBeTruthy();
    expect(screen.getByText("served by groq · 704↑ 21↓")).toBeTruthy();
  });

  it("draws nothing for a turn with no chain yet", () => {
    const { container } = render(<TurnTrace chain={[]} status="complete" provider={null} usage={null} />);
    expect(container.firstChild).toBeNull();
  });
});
