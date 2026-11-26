import { useState } from "react";
import type { KiraClient } from "../api.ts";
import type {
  MemoryHit,
  MemoryItem,
  MemoryKind,
  MemoryList,
  MemorySearch,
  MemorySettings,
  MemorySettingsPatch,
} from "../contracts.ts";
import { useAsync } from "../useAsync.ts";
import { useWrite } from "../useWrite.ts";

const KINDS: MemoryKind[] = ["fact", "preference", "note"];

const EMPTY: MemoryList = {
  memories: [],
  total: 0,
  settings: { inject: true, capture: "explicit", extract: false, tokenizer: "trigram" },
};

const EMPTY_HITS: MemorySearch = { hits: [] };

function messageOf(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

function stamp(seconds: number): string {
  return new Date(seconds * 1000).toLocaleDateString("en-GB");
}

export function MemoryScreen({ client, connected, pull = 0 }: { client: KiraClient; connected: boolean; pull?: number }) {
  const [tab, setTab] = useState<"facts" | "history">("facts");
  const [query, setQuery] = useState("");
  const [historyQuery, setHistoryQuery] = useState("");
  const [draft, setDraft] = useState("");
  const [kind, setKind] = useState<MemoryKind>("fact");
  const [editing, setEditing] = useState<{ id: string; text: string } | null>(null);
  const [exportError, setExportError] = useState<string | null>(null);

  const facts = useAsync(
    () => (connected ? client.memories(query || undefined) : Promise.resolve(EMPTY)),
    [connected, query, pull],
  );
  const hits = useAsync(
    () => (connected && historyQuery ? client.memorySearch(historyQuery) : Promise.resolve(EMPTY_HITS)),
    [connected, historyQuery, pull],
  );
  const { busy, note, run } = useWrite(() => {
    facts.refresh();
    hits.refresh();
  });

  const settings: MemorySettings = facts.kind === "ready" ? facts.data.settings : EMPTY.settings;

  function keep() {
    const text = draft.trim();
    if (!text) return;
    void run("keep this fact", "It will be injected into future turns until you forget it.", false, async (secret) => {
      await client.addMemory(text, kind, secret);
      setDraft("");
    });
  }

  function forget(item: MemoryItem) {
    void run(`forget "${item.text.slice(0, 60)}"`, "This cannot be undone; export first if unsure.", true, (secret) =>
      client.deleteMemory(item.id, secret),
    );
  }

  function togglePin(item: MemoryItem) {
    void run(
      item.pinned ? "unpin this fact" : "pin this fact",
      "Pinned facts are the first ones injected into every turn.",
      false,
      (secret) => client.updateMemory(item.id, { pinned: !item.pinned }, secret),
    );
  }

  function saveEdit() {
    if (!editing) return;
    void run("save this edit", "The indexed text changes with it.", false, async (secret) => {
      await client.updateMemory(editing.id, { text: editing.text }, secret);
      setEditing(null);
    });
  }

  function switchSetting(key: "inject" | "capture" | "extract", value: boolean) {
    // Written as literals, not a computed key: `{ [key]: value }` widens to an index signature and
    // stops being the patch the client's type promises.
    const patch: MemorySettingsPatch =
      key === "capture" ? { capture: value ? "explicit" : "off" } : key === "inject" ? { inject: value } : { extract: value };
    void run(`set ${key}`, "This changes what every future turn carries.", false, (secret) =>
      client.putMemorySettings(patch, secret),
    );
  }

  function exportAll() {
    setExportError(null);
    void client
      .exportMemory()
      .then((data) => {
        const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
        const url = URL.createObjectURL(blob);
        const link = document.createElement("a");
        link.href = url;
        link.download = `kira-memory-${new Date().toISOString().slice(0, 10)}.json`;
        link.click();
        URL.revokeObjectURL(url);
      })
      // A backup that silently did not happen is worse than one that says why it did not.
      .catch((error: unknown) => setExportError(messageOf(error)));
  }

  return (
    <section className="screen" aria-label="memory">
      <header className="screen-head">
        <h2>Memory</h2>
        <div className="segmented" role="tablist" aria-label="memory views">
          <button type="button" role="tab" aria-selected={tab === "facts"} onClick={() => setTab("facts")}>
            facts
          </button>
          <button type="button" role="tab" aria-selected={tab === "history"} onClick={() => setTab("history")}>
            history
          </button>
        </div>
        <span className="spacer" />
        <button type="button" onClick={exportAll}>
          export
        </button>
      </header>
      {note && <p className="error">{note}</p>}
      {exportError ? (
        <p className="error" role="alert">
          cannot export memory: {exportError}
        </p>
      ) : null}

      {tab === "facts" && (
        <>
          <div className="filters">
            <input
              aria-label="search facts"
              placeholder="search facts"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
            />
            <input
              aria-label="new fact"
              placeholder="something worth keeping"
              value={draft}
              onChange={(event) => setDraft(event.target.value)}
            />
            <select aria-label="kind" value={kind} onChange={(event) => setKind(event.target.value as MemoryKind)}>
              {KINDS.map((option) => (
                <option key={option} value={option}>
                  {option}
                </option>
              ))}
            </select>
            <button type="button" disabled={busy || !draft.trim()} onClick={keep}>
              keep
            </button>
          </div>

          {facts.kind === "loading" ? <p className="muted">reading memory…</p> : null}
          {facts.kind === "error" ? (
            <p className="error" role="alert">
              cannot read memory: {messageOf(facts.error)}
            </p>
          ) : null}
          {facts.kind === "ready" && (
            <table className="grid">
              <thead>
                <tr>
                  <th>fact</th>
                  <th>kind</th>
                  <th>origin</th>
                  <th>used</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {facts.data.memories.map((item) => (
                  <tr key={item.id}>
                    <td>
                      {editing?.id === item.id ? (
                        <input
                          aria-label={`edit ${item.id}`}
                          value={editing.text}
                          onChange={(event) => setEditing({ id: item.id, text: event.target.value })}
                        />
                      ) : (
                        <div>{item.text}</div>
                      )}
                      <div className="muted small">{stamp(item.created_at)}</div>
                    </td>
                    <td>
                      <span className="badge">{item.kind}</span>
                    </td>
                    <td className="muted">
                      {item.origin}
                      {item.origin === "auto" ? ` · ${item.tokens_spent ?? 0} tokens` : ""}
                    </td>
                    <td className="muted">{`${item.use_count}×`}</td>
                    <td>
                      <div className="cell-actions">
                        <button type="button" disabled={busy} onClick={() => togglePin(item)}>
                          {item.pinned ? "unpin" : "pin"}
                        </button>
                        {editing?.id === item.id ? (
                          <>
                            <button type="button" disabled={busy} onClick={saveEdit}>
                              save
                            </button>
                            <button type="button" onClick={() => setEditing(null)}>
                              cancel
                            </button>
                          </>
                        ) : (
                          <button
                            type="button"
                            disabled={busy}
                            onClick={() => setEditing({ id: item.id, text: item.text })}
                          >
                            edit
                          </button>
                        )}
                        <button type="button" disabled={busy} onClick={() => forget(item)}>
                          {`forget ${item.id}`}
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
                {facts.data.memories.length === 0 && (
                  <tr>
                    <td colSpan={5} className="empty">
                      nothing kept yet — say "remember that …" in chat, or type a fact above.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          )}

          {facts.kind === "ready" && (
            <>
              <div className="switches">
                <label>
                  <input
                    type="checkbox"
                    aria-label="inject"
                    checked={settings.inject}
                    disabled={busy}
                    onChange={(event) => switchSetting("inject", event.target.checked)}
                  />
                  inject into every turn
                </label>
                <label>
                  <input
                    type="checkbox"
                    aria-label="capture"
                    checked={settings.capture !== "off"}
                    disabled={busy}
                    onChange={(event) => switchSetting("capture", event.target.checked)}
                  />
                  let the model keep facts
                </label>
                <label>
                  <input
                    type="checkbox"
                    aria-label="extract"
                    checked={settings.extract}
                    disabled={busy}
                    onChange={(event) => switchSetting("extract", event.target.checked)}
                  />
                  extract after each turn (one extra call)
                </label>
              </div>
              {settings.capture === "off" ? (
                <p className="muted small">remember is hidden from the model while capture is off.</p>
              ) : null}
              {settings.tokenizer !== "trigram" ? (
                <p className="muted small">
                  this build fell back to the <strong>{settings.tokenizer}</strong> tokenizer — CJK search
                  is served by the slower LIKE tier.
                </p>
              ) : null}
            </>
          )}
        </>
      )}

      {tab === "history" && (
        <>
          <div className="filters">
            <input
              aria-label="search history"
              placeholder="search past conversations"
              value={historyQuery}
              onChange={(event) => setHistoryQuery(event.target.value)}
            />
          </div>
          {hits.kind === "error" ? (
            <p className="error" role="alert">
              cannot search history: {messageOf(hits.error)}
            </p>
          ) : null}
          {hits.kind === "ready" && hits.data.hits.length === 0 ? (
            <p className="empty">no stored message matches that yet.</p>
          ) : null}
          {hits.kind === "ready" && hits.data.hits.length > 0 && (
            <ul className="work-list">
              {hits.data.hits.map((hit: MemoryHit) => (
                <li key={`${hit.session_id}-${hit.message_id}`}>
                  <span className="muted small">
                    {hit.role} · session {hit.session_id} · {stamp(hit.created_at)}
                  </span>
                  <div>{hit.snippet}</div>
                </li>
              ))}
            </ul>
          )}
        </>
      )}
    </section>
  );
}
