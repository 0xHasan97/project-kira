import type { ChainRecord } from "../contracts.ts";

const LABELS: Record<string, string> = {
  attempt: "trying",
  served: "answered",
  failed: "failed",
  skipped_cooling: "cooling down",
  skipped_missing_key: "no key",
  skipped_config: "filtered by mode",
  skipped_budget: "over budget",
  aborted_mid_stream: "cut off mid-stream",
  empty_answer: "answered with nothing",
  tool_executed: "tool ran",
  tool_approval_requested: "asked permission",
  tool_denied: "tool denied",
  checkpoint_created: "checkpoint saved",
  usage_estimated: "usage estimated",
  images_attached: "frame sent",
  images_dropped: "frame kept locally",
};

const TONE: Record<string, string> = {
  served: "good",
  attempt: "neutral",
  tool_executed: "neutral",
  tool_approval_requested: "warn",
  checkpoint_created: "neutral",
  usage_estimated: "warn",
  failed: "bad",
  aborted_mid_stream: "bad",
  empty_answer: "bad",
  tool_denied: "bad",
  skipped_cooling: "warn",
  skipped_missing_key: "warn",
  skipped_config: "warn",
  skipped_budget: "warn",
  images_attached: "neutral",
  // A frame that stayed on the device is not an error, but it is the reason the answer did not look.
  images_dropped: "warn",
};

function detail(record: ChainRecord): string {
  if (record.event === "tool_executed") {
    return `${record.tool}(${JSON.stringify(record.call_id ?? "")}) → ${record.ok ? "ok" : "error"}, ${record.chars ?? 0} chars`;
  }
  if (record.event === "tool_approval_requested") return `${record.tool ?? "tool"} · ${record.risk ?? "?"}`;
  if (record.event === "tool_denied") return `${record.tool ?? "tool"} · ${record.reason ?? "denied"}`;
  if (record.event === "checkpoint_created") return `${record.files ?? 0} file(s)`;
  if (record.event === "skipped_cooling") return record.reason ?? `ready in ${record.retry_in_s ?? 0}s`;
  if (record.event === "failed") return `${record.reason ?? ""}${record.cooldown_s ? ` · cooling ${record.cooldown_s}s` : ""}`;
  return record.reason ?? record.model ?? "";
}

/** The point of the spine: show which provider answered, and who it had to go through. */
export function ChainTrace({ chain, collapsible = false }: { chain: ChainRecord[]; collapsible?: boolean }) {
  if (chain.length === 0) return null;
  const steps = (
    <ol className="chain" aria-label="provider chain">
      {chain.map((record, index) => (
        <li key={`${record.provider ?? "kira"}-${record.event}-${index}`} className={`chain-${TONE[record.event] ?? "neutral"}`}>
          <span className="chain-provider">{record.provider ?? "kira"}</span>
          <span className="chain-event">{LABELS[record.event] ?? record.event}</span>
          {detail(record) && <span className="chain-detail">{detail(record)}</span>}
        </li>
      ))}
    </ol>
  );
  // The agent shell trades vertical room for a step count; the chat shell keeps the plain list.
  if (!collapsible) return steps;
  return (
    <details className="chain-steps" open>
      <summary>
        {chain.length} step{chain.length === 1 ? "" : "s"}
      </summary>
      {steps}
    </details>
  );
}
