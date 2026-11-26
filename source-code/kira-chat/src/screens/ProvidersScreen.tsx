import { useEffect, useState } from "react";
import type { KiraClient, SettingPatch } from "../api.ts";
import type { FieldStateBool, FieldStateCap, FieldStateInt, FieldStateStr, ProbeResponse, ProviderView } from "../contracts.ts";
import { keyBadge } from "../keying.ts";
import { useAsync } from "../useAsync.ts";
import { useWrite } from "../useWrite.ts";

type AnyState = FieldStateBool | FieldStateCap | FieldStateInt | FieldStateStr;

function show(value: unknown): string {
  if (value === null) return "unlimited";
  if (typeof value === "number") return value.toLocaleString("en-US");
  if (typeof value === "boolean") return value ? "on" : "off";
  return String(value);
}

function Was({ state }: { state: AnyState }) {
  return state.override === null ? null : <span className="was">was {show(state.base)}</span>;
}

interface FieldProps<State> {
  provider: string;
  state: State;
  busy: boolean;
  commit: (patch: SettingPatch) => void;
}

function PriorityField({ provider, state, busy, commit }: FieldProps<FieldStateInt>) {
  const [raw, setRaw] = useState(String(state.effective));
  // A re-read that changes the value wins over what is in the box; the box only holds a draft.
  useEffect(() => setRaw(String(state.effective)), [state.effective]);
  return (
    <label className="p-field">
      <span className="p-label">Priority</span>
      <input
        aria-label={"priority " + provider}
        name={"priority_" + provider}
        type="number"
        min={0}
        max={1000}
        value={raw}
        disabled={busy}
        onChange={(event) => setRaw(event.target.value)}
        onBlur={() => {
          const next = Number(raw);
          if (!Number.isInteger(next) || next === state.effective) return;
          commit({ priority: next });
        }}
      />
      <Was state={state} />
    </label>
  );
}

function CapField({ provider, state, busy, commit }: FieldProps<FieldStateCap>) {
  const [raw, setRaw] = useState(state.effective === null ? "" : String(state.effective));
  useEffect(() => setRaw(state.effective === null ? "" : String(state.effective)), [state.effective]);
  return (
    <div className="p-field p-cap">
      <label className="p-label" htmlFor={"cap_" + provider}>Monthly cap</label>
      <div className="p-cap-row">
        <input
          id={"cap_" + provider}
          aria-label={"monthly cap " + provider}
          name={"cap_" + provider}
          type="number"
          min={0}
          value={raw}
          placeholder="unlimited"
          disabled={busy}
          onChange={(event) => setRaw(event.target.value)}
        />
        <button
          type="button"
          aria-label={"set cap " + provider}
          disabled={busy || raw === ""}
          onClick={() => commit({ monthly_cap: Number(raw) })}
        >
          Set
        </button>
        <button
          type="button"
          aria-label={"clear override " + provider}
          disabled={busy || state.override === null}
          onClick={() => commit({ monthly_cap: null })}
        >
          Clear
        </button>
      </div>
      <Was state={state} />
    </div>
  );
}

function Row({ provider, client, refresh }: { provider: ProviderView; client: KiraClient; refresh: () => void }) {
  const { busy, note, quick } = useWrite(refresh);
  const [probe, setProbe] = useState<ProbeResponse | null>(null);
  const [draftKey, setDraftKey] = useState("");
  const badge = keyBadge(provider);
  // The router's own filter, with 0 already folded to null by overrides.py, so this is the exact
  // moment the provider stops being a candidate.
  const atCap = provider.monthly_cap.effective !== null && provider.spend_this_month >= provider.monthly_cap.effective;

  // Provider controls are a desktop convenience, not a destructive write: the engine gates them on
  // its own token, so turning a provider off or tuning its cap applies straight away.
  const save = (patch: SettingPatch) =>
    void quick(() => client.setSettings(provider.name, patch));

  return (
    <article className={provider.enabled.effective ? "provider-card" : "provider-card is-off"} data-provider={provider.name}>
      <header className="p-head">
        <div className="p-name">
          <h3>{provider.name}</h3>
          <span className={badge.ok ? "badge badge-ok" : "badge badge-none"}>{badge.text}</span>
          {/* A call's webcam frame can only go to a provider whose config stanza says it takes
              images, so the card says whether the camera has anywhere to go. */}
          <span className={provider.vision ? "badge badge-ok" : "badge badge-none"}>
            {provider.vision ? "vision" : "text"}
          </span>
        </div>
        <label className="p-switch">
          <input
            aria-label={"enabled " + provider.name}
            name={"enabled_" + provider.name}
            type="checkbox"
            checked={provider.enabled.effective}
            disabled={busy}
            onChange={(event) => save({ enabled: event.target.checked })}
          />
          <span>{provider.enabled.effective ? "On" : "Off"}</span>
        </label>
      </header>

      <p className="p-meta mono">{provider.kind} · {provider.base_url}</p>
      <p className="p-models mono">{provider.models.join(", ")}</p>
      <Was state={provider.enabled} />

      <div className="p-key">
        <input
          aria-label={"new key " + provider.name}
          name={"key_" + provider.name}
          type="password"
          value={draftKey}
          placeholder="Paste API key"
          disabled={busy}
          onChange={(event) => setDraftKey(event.target.value)}
        />
        <button
          type="button"
          aria-label={"store key " + provider.name}
          disabled={busy || draftKey.trim() === ""}
          onClick={() =>
            // Pasting a key is not a destructive act, and the human is already at the keyboard on
            // the machine that holds the token: no second secret, no dialog in the way.
            void quick(async () => {
              await client.putKey(provider.name, draftKey.trim());
              setDraftKey("");
            })
          }
        >
          Save
        </button>
        <button
          type="button"
          className="ghost"
          aria-label={"forget key " + provider.name}
          disabled={busy || !provider.key_present}
          onClick={() => void quick(() => client.deleteKey(provider.name))}
        >
          Forget
        </button>
      </div>
      <p className="p-keyref mono">{provider.key_ref || "no credential"} · {provider.key_present ? "stored" : "empty"}</p>

      <div className="p-fields">
        <PriorityField provider={provider.name} state={provider.priority} busy={busy} commit={save} />
        <label className="p-field">
          <span className="p-label">Tier</span>
          <select
            aria-label={"tier " + provider.name}
            name={"tier_" + provider.name}
            value={provider.tier.effective}
            disabled={busy}
            onChange={(event) => save({ tier: event.target.value })}
          >
            <option value="fast">fast</option>
            <option value="powerful">powerful</option>
          </select>
          <Was state={provider.tier} />
        </label>
        <CapField provider={provider.name} state={provider.monthly_cap} busy={busy} commit={save} />
        <div className="p-field">
          <span className="p-label">Spent</span>
          <strong className="p-spend">{show(provider.spend_this_month)}</strong>
          {atCap ? <span className="badge badge-none">at cap</span> : null}
        </div>
      </div>

      <div className="p-health">
        <span className="p-label">Health</span>
        <span className="mono">{provider.health.successes}✓ {provider.health.failures}✗</span>
        {provider.health.cooling_s > 0 ? (
          <>
            <span className="warn mono">cooling {provider.health.cooling_s}s · {provider.health.last_reason}</span>
            <button
              type="button"
              aria-label={"clear cooldown " + provider.name}
              disabled={busy}
              onClick={() => void quick(() => client.clearCooldown(provider.name))}
            >
              Resume
            </button>
          </>
        ) : null}
        {/* A probe writes nothing, so re-reading here would unmount the card and throw away the
            answer this click produced. */}
        <button
          type="button"
          aria-label={"test " + provider.name}
          disabled={busy}
          onClick={() =>
            void quick(
              async () => setProbe(await client.probe(provider.name)),
              { reread: false },
            )
          }
        >
          Test
        </button>
        {probe && (
          <span className="probe-result mono" data-ok={probe.ok}>
            {probe.ok ? probe.model_count + " models · " + probe.latency_ms + "ms" : "failed: " + probe.error}
          </span>
        )}
      </div>
      {note && <p className="error">{note}</p>}
    </article>
  );
}

export function ProvidersScreen({
  client,
  onChanged,
  pull = 0,
}: {
  client: KiraClient;
  onChanged: () => void;
  pull?: number;
}) {
  const state = useAsync(() => client.providers(), [pull]);
  // Both reads: the cards, and the chat sidebar's key/tier facts, which /v1/kira/health derives
  // from the same merged view.
  const refresh = () => {
    state.refresh();
    onChanged();
  };

  if (state.kind === "loading") return <section className="screen"><p className="muted">reading providers…</p></section>;
  if (state.kind === "error") {
    return (
      <section className="screen">
        <p className="error">cannot read providers: {String((state.error as Error).message ?? state.error)}</p>
      </section>
    );
  }
  const body = state.data;

  return (
    <section className="screen providers-screen">
      <header className="screen-head">
        <div className="screen-title">
          <h2>Providers</h2>
          <p className="screen-sub">Spend for {body.month} · {body.providers.length} configured</p>
        </div>
        <span className="spacer" />
        <button type="button" onClick={state.refresh}>reload</button>
      </header>

      {body.providers.length === 0 ? (
        <p className="empty">No providers in <span className="mono">config.yaml</span> yet.</p>
      ) : (
        <div className="provider-grid">
          {body.providers.map((provider) => (
            <Row key={provider.name} provider={provider} client={client} refresh={refresh} />
          ))}
        </div>
      )}

      {body.orphan_settings.length > 0 ? (
        <p className="warn mono">
          settings rows nothing uses: {body.orphan_settings.join(", ")}
        </p>
      ) : null}
    </section>
  );
}
