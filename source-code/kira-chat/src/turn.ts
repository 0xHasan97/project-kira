import type { ChatChunk, ChainRecord, ToolCallWire, TurnStatus, WireUsage } from "./contracts.ts";

export interface ApprovalChunk {
  id: string;
  tool: string;
  risk: string;
  arguments: Record<string, unknown>;
}

export interface Turn {
  text: string;
  chain: ChainRecord[];
  toolCalls: ToolCallWire[];
  provider: string | null;
  model: string | null;
  usage: WireUsage | null;
  status: TurnStatus | "streaming";
  error: string | null;
  errorCode: string | null;
  sessionId: string | null;
  approvals: ApprovalChunk[];
}

export function emptyTurn(): Turn {
  return {
    text: "",
    chain: [],
    toolCalls: [],
    provider: null,
    model: null,
    usage: null,
    status: "streaming",
    error: null,
    errorCode: null,
    sessionId: null,
    approvals: [],
  };
}

/** Folds one SSE frame into the turn. Pure, so the ordering rules are testable without a DOM. */
export function applyChunk(turn: Turn, chunk: ChatChunk): Turn {
  switch (chunk.type) {
    case "delta":
      return { ...turn, text: turn.text + chunk.text };
    case "chain":
      return { ...turn, chain: [...turn.chain, chunk.record] };
    case "tool_call":
      return {
        ...turn,
        toolCalls: [...turn.toolCalls, { id: chunk.id, name: chunk.name, arguments: chunk.arguments }],
      };
    case "done":
      return {
        ...turn,
        provider: chunk.provider,
        model: chunk.model,
        usage: chunk.usage,
        status: chunk.status,
        sessionId: chunk.session_id,
        chain: chunk.provider_chain?.length ? chunk.provider_chain : turn.chain,
      };
    case "approval":
      return {
        ...turn,
        approvals: [
          ...turn.approvals,
          { id: chunk.id, tool: chunk.tool, risk: chunk.risk, arguments: chunk.arguments ?? {} },
        ],
      };
    case "error":
      return {
        ...turn,
        // The engine's own rule, mirrored: text already on screen makes this an interrupted answer, an
        // error before the first token makes it a failed turn. The chip used to say `interrupted` for a
        // Gemini 503 while the stored row said `failed`, so the same turn changed its name on reload.
        status: turn.text ? "interrupted" : "failed",
        error: `${chunk.error.code}: ${chunk.error.message}`,
        errorCode: chunk.error.code,
        chain: chunk.provider_chain?.length ? chunk.provider_chain : turn.chain,
      };
  }
}

export function chainSummary(turn: Turn): string {
  const served = turn.chain.filter((r) => r.event === "served").length;
  const failed = turn.chain.filter((r) => r.event === "failed" || r.event === "aborted_mid_stream").length;
  // A provider that closes its stream with neither text nor a tool call is recorded as `empty_answer`, and
  // it is not a skip, a failure or a serve — without its own bucket the chip reads five zeroes for a turn
  // that genuinely failed. The segment only appears when there is one to report.
  const empties = turn.chain.filter((r) => r.event === "empty_answer").length;
  const skipped = turn.chain.filter((r) => r.event.startsWith("skipped_")).length;
  const tools = turn.chain.filter((r) => r.event === "tool_executed").length;
  return `${served} served · ${failed} failed${empties ? ` · ${empties} empty` : ""} · ${skipped} skipped · ${tools} tool runs`;
}
