import { describe, expect, it } from "vitest";
import type { ChainRecord } from "./contracts.ts";
import { traceRows, traceSummary } from "./trace.ts";

const read: ChainRecord = {
  event: "tool_executed",
  tool: "read_file",
  call_id: "c1",
  ok: true,
  risk: "read",
  summary: "src/app.ts",
  chars: 812,
};
const exec: ChainRecord = {
  event: "tool_executed",
  tool: "run_command",
  call_id: "c2",
  ok: true,
  risk: "exec",
  kind: "command",
  summary: "npm test",
  duration_ms: 2410,
  exit_code: 0,
};
const write: ChainRecord = {
  event: "tool_executed",
  tool: "write_file",
  call_id: "c3",
  ok: true,
  risk: "write",
  summary: "src/b.ts",
};
const failed: ChainRecord = {
  event: "tool_executed",
  tool: "run_command",
  call_id: "c4",
  ok: false,
  risk: "exec",
  summary: "pnpm build",
  exit_code: 2,
};

describe("traceRows", () => {
  it("reads a tool call as a past-tense line with the detail on the right", () => {
    const [row] = traceRows([read]);
    expect(row).toMatchObject({ verb: "Read", object: "src/app.ts", status: "done" });
    expect(row?.meta).toBe("812 chars");
  });

  it("puts a command's duration on the right, exit code when it failed", () => {
    expect(traceRows([exec])[0]).toMatchObject({ verb: "Ran", object: "npm test", meta: "2.4 s", status: "done" });
    expect(traceRows([failed])[0]).toMatchObject({ verb: "Couldn't run", object: "pnpm build", status: "failed" });
    expect(traceRows([failed])[0]?.meta).toBe("exit 2");
  });

  it("keeps the reason a tool was denied", () => {
    const row = traceRows([
      { event: "tool_denied", tool: "run_command", call_id: "c5", risk: "exec", reason: "policy says ask" },
    ])[0];
    expect(row).toMatchObject({ verb: "Couldn't run", meta: "policy says ask", status: "denied" });
  });

  it("shows an approval request as waiting, not as work already done", () => {
    const row = traceRows([{ event: "tool_approval_requested", tool: "run_command", risk: "exec", approval_id: "a1" }])[0];
    expect(row).toMatchObject({ verb: "Asked to run", object: "run_command", meta: "exec", status: "waiting" });
  });

  it("does not turn provider hops into tool rows", () => {
    const rows = traceRows([
      { provider: "groq", event: "attempt", model: "m" },
      { provider: "groq", event: "served", model: "m" },
    ]);
    expect(rows).toEqual([]);
  });
});

describe("traceSummary", () => {
  it("folds a turn into one sentence, in a fixed order", () => {
    const summary = traceSummary([read, exec, write, read], "complete");
    expect(summary.sentence).toBe("Read 2 files, ran 1 command and edited 1 file");
    expect(summary.steps).toBe(4);
    expect(summary.failed).toBe(0);
  });

  it("names the failures beside the count instead of hiding them in the list", () => {
    const summary = traceSummary([read, failed], "complete");
    expect(summary.failed).toBe(1);
    expect(summary.sentence).toBe("Read 1 file");
  });

  it("falls back to who answered when no tool ran", () => {
    const summary = traceSummary(
      [
        { provider: "groq", event: "failed", reason: "rate limited" },
        { provider: "gemini", event: "served", model: "gemini-3.5-flash" },
      ],
      "complete",
    );
    expect(summary.sentence).toBe("Answered by gemini after 1 provider failed");
    expect(summary.steps).toBe(0);
  });

  it("says a skip is a skip, not a failure", () => {
    const summary = traceSummary(
      [
        { provider: "openrouter", event: "skipped_missing_key" },
        { provider: "gemini", event: "served" },
      ],
      "complete",
      "gemini",
    );
    expect(summary.sentence).toBe("Answered by gemini after 1 provider was skipped");
  });

  it("is still working when no step has landed", () => {
    expect(traceSummary([], "streaming").sentence).toBe("Working");
  });

  it("does not claim an answer when the turn was refused", () => {
    const summary = traceSummary([{ provider: "groq", event: "failed", reason: "down" }], "failed");
    expect(summary.sentence).toBe("No provider could answer");
  });
});
