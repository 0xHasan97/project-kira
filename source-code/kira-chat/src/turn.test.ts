import { describe, expect, it } from "vitest";
import type { ChainRecord, ChatChunk, TurnStatus } from "./contracts.ts";
import { applyChunk, chainSummary, emptyTurn } from "./turn.ts";

const served: ChainRecord = { provider: "groq", event: "served", model: "llama-3.3-70b-versatile" };
const failed: ChainRecord = { provider: "openrouter", event: "failed", reason: "rate limited", cooldown_s: 5 };

describe("applyChunk", () => {
  it("accumulates deltas in arrival order", () => {
    let turn = emptyTurn();
    for (const text of ["Hel", "lo", " there"]) {
      turn = applyChunk(turn, { type: "delta", text } as ChatChunk);
    }
    expect(turn.text).toBe("Hello there");
    expect(turn.status).toBe("streaming");
  });

  it("keeps every chain record the engine sent while streaming", () => {
    let turn = emptyTurn();
    turn = applyChunk(turn, { type: "chain", record: failed } as ChatChunk);
    turn = applyChunk(turn, { type: "chain", record: served } as ChatChunk);
    expect(turn.chain.map((r) => r.event)).toEqual(["failed", "served"]);
  });

  it("prefers the authoritative chain from the done frame", () => {
    const done = {
      type: "done",
      id: "chatcmpl-1",
      session_id: "abc",
      provider: "groq",
      model: "llama",
      finish_reason: "stop",
      status: "complete" as TurnStatus,
      usage: { prompt_tokens: 9, completion_tokens: 4 },
      provider_chain: [failed, served],
    } as unknown as ChatChunk;
    const turn = applyChunk(applyChunk(emptyTurn(), { type: "chain", record: failed } as ChatChunk), done);
    expect(turn.provider).toBe("groq");
    expect(turn.sessionId).toBe("abc");
    expect(turn.usage?.completion_tokens).toBe(4);
    expect(turn.chain).toHaveLength(2);
    expect(turn.status).toBe("complete");
  });

  it("records tool calls as they arrive", () => {
    const turn = applyChunk(emptyTurn(), {
      type: "tool_call",
      id: "call_1",
      name: "echo",
      arguments: { text: "pong" },
    } as unknown as ChatChunk);
    expect(turn.toolCalls).toEqual([{ id: "call_1", name: "echo", arguments: { text: "pong" } }]);
  });

  it("marks an error frame that left nothing to show as failed, the way the engine stores it", () => {
    const turn = applyChunk(emptyTurn(), {
      type: "error",
      error: { code: "providers_exhausted", message: "every provider was filtered out", status: 503, retryable: true },
      provider_chain: [failed],
    } as unknown as ChatChunk);
    // Measured live: Gemini 503'd `high demand` on the first token, the engine stored the row as
    // `failed`, and the bubble said `interrupted` — two words for one turn, and the reload changed it.
    expect(turn.status).toBe("failed");
    expect(turn.error).toBe("providers_exhausted: every provider was filtered out");
    expect(turn.chain).toHaveLength(1);
  });

  it("keeps a partial answer interrupted when the error frame arrives after text", () => {
    let turn = applyChunk(emptyTurn(), { type: "delta", text: "half an" } as ChatChunk);
    turn = applyChunk(turn, { type: "delta", text: "swer" } as ChatChunk);
    turn = applyChunk(turn, {
      type: "error",
      error: { code: "providers_exhausted", message: "every provider was filtered out", status: 503, retryable: true },
      provider_chain: [{ provider: "groq", event: "aborted_mid_stream", reason: "client already saw text" }],
    } as unknown as ChatChunk);
    expect(turn.status).toBe("interrupted");
    expect(turn.text).toBe("half answer");
  });

  it("summarises a failover turn for the meta line", () => {
    let turn = emptyTurn();
    for (const record of [failed, served, { provider: "groq", event: "tool_executed", tool: "echo", ok: true, chars: 4 }]) {
      turn = applyChunk(turn, { type: "chain", record } as ChatChunk);
    }
    expect(chainSummary(turn)).toBe("1 served · 1 failed · 0 skipped · 1 tool runs");
  });

  it("counts a turn that providers answered with nothing, because the chip would hide it", () => {
    let turn = emptyTurn();
    // The router records `empty_answer` when a provider opens a stream and closes it with no text and no
    // tool call (see `kira-engine/src/kira/router.py`, measured live on Gemini 3.5 Flash spending its whole
    // output budget on hidden thinking). The summary counted served/failed/skipped/tools, so such a turn
    // read `0 served · 0 failed · 0 skipped · 0 tool runs`: five zeroes for a turn that did fail. The live
    // quota failure this run hit was different — a 429 the router recorded as a skip, which the chip did
    // report — and that honesty is what this bucket extends.
    for (const record of [
      { provider: "gemini", model: "gemini-3.5-flash", event: "attempt" },
      { provider: "gemini", model: "gemini-3.5-flash", event: "empty_answer", reason: "completed with no text" },
    ]) {
      turn = applyChunk(turn, { type: "chain", record } as ChatChunk);
    }
    expect(chainSummary(turn)).toBe("0 served · 0 failed · 1 empty · 0 skipped · 0 tool runs");
  });

  it("collects approval chunks", () => {
    let turn = emptyTurn();
    turn = applyChunk(turn, {
      type: "approval",
      id: "a1",
      tool: "write_file",
      risk: "write",
      arguments: { path: "a.txt" },
    } as ChatChunk);
    expect(turn.approvals).toEqual([{ id: "a1", tool: "write_file", risk: "write", arguments: { path: "a.txt" } }]);
  });

  it("keeps the engine's code as a field, not only inside the message", () => {
    const turn = applyChunk(emptyTurn(), {
      type: "error",
      error: { code: "budget_exhausted", message: "over the monthly cap for 2026-10 (fast_one)", status: 429, retryable: false },
    } as unknown as ChatChunk);
    expect(turn.status).toBe("failed");
    expect(turn.error).toBe("budget_exhausted: over the monthly cap for 2026-10 (fast_one)");
    expect(turn.errorCode).toBe("budget_exhausted");
    expect(emptyTurn().errorCode).toBeNull();
  });
});
