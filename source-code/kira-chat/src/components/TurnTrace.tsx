import { Check, ChevronDown, Clock, Loader, X } from "lucide-react";
import type { ChainRecord, TurnStatus, WireUsage } from "../contracts.ts";
import { traceRows, traceSummary } from "../trace.ts";
import type { RowStatus } from "../trace.ts";

const GLYPH: Record<RowStatus, typeof Check> = {
  done: Check,
  failed: X,
  denied: X,
  waiting: Clock,
  note: Clock,
};

function Activity({ live, worked }: { live: boolean; worked: boolean }) {
  if (!live) return null;
  return (
    <span className="activity" data-kind={worked ? "bars" : "dots"} aria-hidden="true">
      {worked ? (
        <>
          <i />
          <i />
          <i />
        </>
      ) : (
        <>
          <i />
          <i />
          <i />
          <i />
        </>
      )}
    </span>
  );
}

export interface TurnTraceProps {
  chain: ChainRecord[];
  status: TurnStatus | "streaming";
  provider: string | null;
  usage: WireUsage | null;
}

/**
 * The agent transcript's one object for a turn: a sentence, the steps behind it, and who paid for it.
 * Folding is the normal state at the end of a turn — the answer is the point, the trace is the receipt.
 */
export function TurnTrace({ chain, status, provider, usage }: TurnTraceProps) {
  const live = status === "streaming";
  if (chain.length === 0 && !live) return null;

  const rows = traceRows(chain);
  const summary = traceSummary(chain, status, provider);
  const served = provider ?? [...chain].reverse().find((record) => record.event === "served")?.provider ?? null;
  const foot = [served ? `served by ${served}` : null, usage ? `${usage.prompt_tokens}↑ ${usage.completion_tokens}↓` : null]
    .filter(Boolean)
    .join(" · ");

  return (
    <details className="turn-trace" open data-state={live ? "live" : status}>
      <summary className="trace-head">
        <Activity live={live} worked={rows.length > 0} />
        <span className="trace-sentence">{summary.sentence}</span>
        {summary.failed > 0 && <span className="trace-bad">{summary.failed} failed</span>}
        {summary.steps > 0 && <span className="trace-count">{summary.steps} step{summary.steps === 1 ? "" : "s"}</span>}
        <ChevronDown className="trace-chevron" size={14} aria-hidden="true" />
      </summary>
      {rows.length > 0 && (
        <ol className="trace-rows" aria-label="steps">
          {rows.map((row) => {
            // A pending ask is only pending while the turn is open; once it settles the row is history.
            const state: RowStatus = row.status === "waiting" && !live ? "note" : row.status;
            const Glyph = state === "waiting" ? Loader : GLYPH[state];
            return (
              <li key={row.key} className="trace-row" data-status={state}>
                <Glyph className="trace-glyph" size={12} aria-hidden="true" />
                <span className="trace-verb">{row.verb}</span>
                <span className="trace-object" title={row.object}>
                  {row.object}
                </span>
                {row.meta && <span className="trace-meta">{row.meta}</span>}
              </li>
            );
          })}
        </ol>
      )}
      {foot && <p className="trace-foot">{foot}</p>}
    </details>
  );
}
