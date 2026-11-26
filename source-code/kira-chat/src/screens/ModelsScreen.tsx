import type { KiraClient } from "../api.ts";
import type { ModelInfo, ModelUsage, OverviewResponse } from "../contracts.ts";
import { useAsync } from "../useAsync.ts";

function num(value: number): string {
  return value.toLocaleString("en-US");
}

function key(provider: string, model: string): string {
  return `${provider}/${model}`;
}

export function ModelsScreen({
  client,
  models,
  onUse,
  pull = 0,
}: {
  client: KiraClient;
  models: ModelInfo[];
  onUse: (id: string) => void;
  pull?: number;
}) {
  const state = useAsync(() => client.overview(), [pull]);

  if (state.kind === "loading") return <section className="screen"><p className="muted">reading the month…</p></section>;
  if (state.kind === "error") {
    return (
      <section className="screen">
        <p className="error">cannot read this month: {String((state.error as Error).message ?? state.error)}</p>
      </section>
    );
  }
  const view: OverviewResponse = state.data;
  // A `model: null` row is a turn that failed before any model answered it, so it names no model to
  // join against and cannot be retired — Overview's Top models table is where that row belongs.
  const named = view.by_model.filter((row): row is ModelUsage & { model: string } => row.model !== null);
  const usage = new Map<string, ModelUsage>(named.map((row) => [key(row.provider, row.model), row]));
  const configured = new Set(models.map((model) => key(model.provider, model.id)));
  // Amendment 16: whatever the month spent that the config no longer names still gets a row.
  const retired = named.filter((row) => !configured.has(key(row.provider, row.model)));

  if (models.length === 0 && retired.length === 0) {
    return (
      <section className="screen">
        <h2>Models</h2>
        <p className="empty">
          Nothing to route to — no models in <span className="mono">config.yaml</span>.
        </p>
      </section>
    );
  }

  return (
    <section className="screen">
      <header className="screen-head">
        <div className="screen-title">
          <h2>Models</h2>
          <p className="screen-sub">Spend for {view.month} · read-only, edit <span className="mono">config.yaml</span></p>
        </div>
        <span className="spacer" />
        <button type="button" onClick={state.refresh}>reload</button>
      </header>

      <table className="grid models-table">
        <thead>
          <tr><th>model</th><th>provider</th><th>tier</th><th>turns</th><th>tokens</th><th>chat</th></tr>
        </thead>
        <tbody>
          {models.map((model) => {
            const row = usage.get(key(model.provider, model.id));
            return (
              <tr key={key(model.provider, model.id)}>
                <td className="mono">{model.id}</td>
                <td>{model.provider}</td>
                <td>{model.tier}</td>
                <td>{num(row?.turns ?? 0)}</td>
                <td>{num(row?.tokens ?? 0)}</td>
                <td>
                  <button
                    type="button"
                    aria-label={"use in chat " + model.id}
                    title={"use in chat " + model.id}
                    onClick={() => onUse(model.id)}
                  >
                    Use
                  </button>
                </td>
              </tr>
            );
          })}
          {retired.map((row) => (
            <tr key={key(row.provider, row.model)} className="row-retired">
              <td className="mono">
                {row.model}
                <div className="muted">no longer configured</div>
              </td>
              <td>{row.provider}</td>
              <td className="muted">—</td>
              <td>{num(row.turns)}</td>
              <td>{num(row.tokens)}</td>
              <td className="muted mono">{key(row.provider, row.model)}</td>
            </tr>
          ))}
        </tbody>
      </table>

    </section>
  );
}
