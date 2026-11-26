import { useState } from "react";
import type { KiraClient } from "../api.ts";
import type { BudgetRow, DailyUsage, OverviewResponse, RefusalSummary } from "../contracts.ts";
import { useAsync } from "../useAsync.ts";

const MONTH_INPUT = /^\d{4}-\d{2}$/;

function num(value: number): string {
  return value.toLocaleString("en-US");
}

function Stat({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="stat">
      <span className="muted">{label}</span>
      <strong className="stat-value">{value}</strong>
      {hint ? <span className="muted mono">{hint}</span> : null}
    </div>
  );
}

function BudgetBar({ row }: { row: BudgetRow }) {
  // An effective cap of 0 is normalised to null by the engine, so these are the only two states.
  if (row.cap === null) {
    return (
      <div className="budget">
        <span className="mono">{row.provider}</span>
        <div className="budget-bar budget-unlimited" aria-label={`${row.provider} has no monthly cap`}>
          <span className="budget-label">{num(row.used)} tokens · no cap</span>
        </div>
      </div>
    );
  }
  const pct = Math.min(100, (row.used / row.cap) * 100);
  // `remaining` is the engine's own clamp, so `remaining === 0` is exactly the state the router acts
  // on. Anything above zero is not a countdown: the turn in flight is not counted (Task 15, rule 4).
  const atCap = row.remaining === 0;
  return (
    <div className="budget">
      <span className="mono">{row.provider}</span>
      <div
        className={`budget-bar ${atCap ? "budget-over" : pct > 80 ? "budget-high" : ""}`}
        aria-label={atCap ? `${row.provider} is at its monthly cap` : `${row.provider} used ${Math.round(pct)}% of its cap`}
      >
        <span className="budget-used" style={{ width: `${pct}%` }} />
        <span className="budget-label">
          {num(row.used)} / {num(row.cap)}
          {atCap ? " · at cap" : ""}
        </span>
      </div>
    </div>
  );
}

function Sparkline({ daily }: { daily: DailyUsage[] }) {
  if (daily.length === 0) return null;
  const peak = Math.max(...daily.map((day) => day.tokens), 1);
  const step = 300 / Math.max(daily.length - 1, 1);
  const points = daily
    .map((day, index) => `${(index * step).toFixed(1)},${(30 - (day.tokens / peak) * 28).toFixed(2)}`)
    .join(" ");
  return (
    <svg className="spark" viewBox="0 0 300 30" preserveAspectRatio="none" role="img" aria-label={`daily tokens, peak ${peak}`}>
      <polyline points={points} fill="none" stroke="currentColor" strokeWidth="1.5" />
    </svg>
  );
}

function Refusals({ summary, month }: { summary: RefusalSummary; month: string }) {
  if (summary.count === 0) return null;
  const plural = summary.count === 1 ? "" : "s";
  return (
    <>
      <h3>Refused before starting</h3>
      {/* Outside the `turns === 0` gate on purpose: this is the month where nothing was spent,
          and a refusal is exactly the thing no turn row can tell you about. */}
      <p>
        {num(summary.count)} turn{plural} in {month} never reached a provider, so{" "}
        {summary.count === 1 ? "it is" : "they are"} not in the counts above — a refusal writes no message
        row. {summary.by_code.map((row) => `${row.code} ×${num(row.count)}`).join(" · ")}.
      </p>
      <ul className="issues" aria-label="recent refusals">
        {summary.recent.map((row, index) => (
          <li key={`${row.created_at}-${index}`}>
            <span className="issue-failed">{row.code}</span>
            <span>{row.message}</span>
          </li>
        ))}
      </ul>
    </>
  );
}

export function OverviewScreen({
  client,
  onOpenSession,
  pull = 0,
}: {
  client: KiraClient;
  onOpenSession: (sessionId: string) => void;
  pull?: number;
}) {
  const [month, setMonth] = useState<string | undefined>(undefined);
  const state = useAsync(() => client.overview(month), [month, pull]);

  if (state.kind === "loading") return <section className="screen"><p className="muted">loading the month…</p></section>;
  if (state.kind === "error") {
    return (
      <section className="screen">
        <p className="error">cannot read the overview: {String((state.error as Error).message ?? state.error)}</p>
      </section>
    );
  }
  const view: OverviewResponse = state.data;
  const served = view.turns - view.interrupted - view.failed;
  const capped = view.budgets.filter((row) => row.remaining === 0);

  return (
    <section className="screen">
      <header className="screen-head">
        <h2>Overview</h2>
        <label className="muted">
          month
          <input
            type="month"
            aria-label="month"
            value={month ?? view.month}
            onChange={(event) => {
              const next = event.target.value;
              setMonth(MONTH_INPUT.test(next) ? next : undefined);
            }}
          />
        </label>
        <span className="spacer" />
        <button type="button" onClick={state.refresh}>
          reload
        </button>
      </header>

      {view.turns === 0 ? (
        <p className="empty">nothing spent in {view.month} yet — the month is empty, not broken.</p>
      ) : (
        <>
          <div className="stats">
            <Stat label="turns" value={num(view.turns)} hint={`${num(served)} served`} />
            <Stat label="tokens" value={num(view.tokens.input + view.tokens.output)} hint={`${num(view.tokens.input)} in · ${num(view.tokens.output)} out`} />
            <Stat label="success rate" value={view.success_rate === null ? "no data" : `${(view.success_rate * 100).toFixed(1)}%`} />
            <Stat label="interrupted" value={num(view.interrupted)} />
            <Stat label="failed" value={num(view.failed)} />
          </div>

          <h3>Budgets</h3>
          {view.budgets.map((row) => (
            <BudgetBar key={row.provider} row={row} />
          ))}
          {capped.length > 0 ? (
            <p className="at-cap">
              <strong>{capped.map((row) => row.provider).join(", ")}</strong>{" "}
              {capped.length === 1 ? "has" : "have"} used all of {view.month}'s cap, so no turn will route
              through {capped.length === 1 ? "it" : "them"} until the cap is raised or the month resets.{" "}
              <a href="#/providers">raise a cap in Providers</a>
            </p>
          ) : null}
          <p className="muted small">
            Counted from stored turns, so the one in flight is not in these numbers yet — a bar can sit just
            under a cap the router is about to reach.
          </p>

          <h3>By day</h3>
          <Sparkline daily={view.daily} />

          <h3>Top models</h3>
          <table className="grid">
            <thead><tr><th>model</th><th>provider</th><th>turns</th><th>tokens</th></tr></thead>
            <tbody>
              {view.by_model.map((row) => (
                <tr key={`${row.provider}/${row.model}`}>
                  <td className="mono">{row.model ?? "no model reached"}</td>
                  <td>{row.provider}</td>
                  <td>{num(row.turns)}</td>
                  <td>{num(row.tokens)}</td>
                </tr>
              ))}
            </tbody>
          </table>

          <h3>Recent trouble</h3>
          {view.recent_issues.length === 0 ? (
            <p className="empty">no interrupted or failed turns this month.</p>
          ) : (
            <ul className="issues" aria-label="recent trouble">
              {view.recent_issues.map((issue) => (
                <li key={issue.id}>
                  <span className={`issue-${issue.status}`}>{issue.status}</span>
                  {/* A button, not an anchor: a transcript is React state, and the route parser knows
                      five names only, so `#/sessions/sess-9` would parse to `chat`. */}
                  <button type="button" className="link" onClick={() => onOpenSession(issue.session_id)}>
                    {issue.session_id}
                  </button>
                  <span>{issue.provider ?? "no provider"} · {issue.reason}</span>
                </li>
              ))}
            </ul>
          )}
        </>
      )}
      <Refusals summary={view.refusals} month={view.month} />
      <p className="muted">
        {view.by_provider.length} provider{view.by_provider.length === 1 ? "" : "s"} served this month. Adding a provider
        or a model means editing <span className="mono">config.yaml</span>.
      </p>
    </section>
  );
}
