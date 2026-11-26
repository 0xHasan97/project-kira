import type { ChainRecord, TurnStatus } from "./contracts.ts";

export type RowStatus = "done" | "failed" | "denied" | "waiting" | "note";

export interface TraceRow {
  key: string;
  verb: string;
  object: string;
  meta: string;
  status: RowStatus;
}

export interface TraceSummary {
  sentence: string;
  steps: number;
  failed: number;
}

/** `streaming` is the live turn's own status, before `done` names what it was. */
type SummaryState = TurnStatus | "streaming";

const PAST: Record<string, [string, string]> = {
  read: ["Read", "Couldn't read"],
  write: ["Edited", "Couldn't edit"],
  exec: ["Ran", "Couldn't run"],
  network: ["Fetched", "Couldn't fetch"],
};

/** Verb, then the singular and plural noun it counts. */
const CLAUSE: Record<string, [string, string, string]> = {
  read: ["Read", "file", "files"],
  exec: ["ran", "command", "commands"],
  write: ["edited", "file", "files"],
  network: ["fetched", "URL", "URLs"],
};

const ORDER = ["read", "exec", "write", "network"] as const;

function verbFor(risk: string | undefined): [string, string] {
  return PAST[risk ?? ""] ?? ["Called", "Couldn't call"];
}

function ms(value: number): string {
  return value < 1000 ? `${value} ms` : `${(value / 1000).toFixed(1)} s`;
}

function metaFor(record: ChainRecord): string {
  // A failed command's number is its exit status; a successful one's is how long it took.
  if (record.ok === false && record.exit_code !== undefined) return `exit ${record.exit_code}`;
  if (record.duration_ms !== undefined) return ms(record.duration_ms);
  if (record.exit_code !== undefined) return `exit ${record.exit_code}`;
  if (record.chars !== undefined) return `${record.chars} chars`;
  return "";
}

/**
 * One row per step a human can read: past tense when it happened, "Couldn't …" when it did not.
 * Provider hops are not rows — who answered belongs to the summary sentence, not the work list.
 */
export function traceRows(chain: ChainRecord[]): TraceRow[] {
  const rows: TraceRow[] = [];
  chain.forEach((record, index) => {
    const key = record.call_id ?? `${record.event}-${index}`;
    if (record.event === "tool_executed") {
      const [past, broke] = verbFor(record.risk);
      rows.push({
        key,
        verb: record.ok === false ? broke : past,
        object: record.summary ?? record.tool ?? "a tool",
        meta: metaFor(record),
        status: record.ok === false ? "failed" : "done",
      });
      return;
    }
    if (record.event === "tool_approval_requested") {
      const [, broke] = verbFor(record.risk);
      rows.push({
        key,
        verb: broke.replace("Couldn't ", "Asked to "),
        object: record.tool ?? "a tool",
        meta: record.risk ?? "",
        status: "waiting",
      });
      return;
    }
    if (record.event === "tool_denied") {
      const [, broke] = verbFor(record.risk);
      rows.push({
        key,
        verb: broke,
        object: record.tool ?? "a tool",
        meta: record.reason ?? "denied",
        status: "denied",
      });
      return;
    }
    if (record.event === "checkpoint_created") {
      const files = record.files ?? 0;
      rows.push({
        key,
        verb: "Saved a checkpoint",
        object: `${files} file${files === 1 ? "" : "s"}`,
        meta: record.checkpoint_id ?? "",
        status: "note",
      });
    }
  });
  return rows;
}

function clauses(chain: ChainRecord[]): string[] {
  const counts = new Map<string, number>();
  for (const record of chain) {
    if (record.event !== "tool_executed" || record.ok === false) continue;
    const risk = record.risk && CLAUSE[record.risk] ? record.risk : "exec";
    counts.set(risk, (counts.get(risk) ?? 0) + 1);
  }
  return ORDER.filter((risk) => counts.has(risk)).map((risk) => {
    const [verb, one, many] = CLAUSE[risk]!;
    const n = counts.get(risk)!;
    return `${verb} ${n} ${n === 1 ? one : many}`;
  });
}

function lastServed(chain: ChainRecord[]): string | null {
  for (let i = chain.length - 1; i >= 0; i -= 1) {
    const record = chain[i]!;
    if (record.event === "served" && record.provider) return record.provider;
  }
  return null;
}

function join(parts: string[]): string {
  if (parts.length <= 1) return parts[0] ?? "";
  return `${parts.slice(0, -1).join(", ")} and ${parts[parts.length - 1]}`;
}

/** What the turn should say when folded: its work in prose, or who answered when there was none. */
export function traceSummary(
  chain: ChainRecord[],
  state: SummaryState,
  servedProvider?: string | null,
): TraceSummary {
  const rows = traceRows(chain);
  const steps = rows.filter((row) => row.status !== "note").length;
  const failed = rows.filter((row) => row.status === "failed" || row.status === "denied").length;
  const parts = clauses(chain);

  if (parts.length > 0) return { sentence: join(parts), steps, failed };
  if (state === "streaming") return { sentence: "Working", steps, failed };

  const served = servedProvider ?? lastServed(chain);
  if (served) {
    const failedProviders = chain.filter((record) => record.event === "failed" || record.event === "aborted_mid_stream").length;
    const skipped = chain.filter((record) => record.event.startsWith("skipped_")).length;
    const after: string[] = [];
    if (failedProviders > 0) after.push(`${failedProviders} provider${failedProviders === 1 ? "" : "s"} failed`);
    if (skipped > 0) after.push(`${skipped} provider${skipped === 1 ? " was" : "s were"} skipped`);
    return {
      sentence: `Answered by ${served}${after.length ? ` after ${join(after)}` : ""}`,
      steps,
      failed,
    };
  }
  if (state === "failed" || state === "interrupted") {
    return { sentence: "No provider could answer", steps, failed };
  }
  return { sentence: "No step recorded", steps, failed };
}
