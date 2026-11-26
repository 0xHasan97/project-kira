import { useEffect, useState } from "react";
import { FileDiff, Terminal, FlaskConical, CircleAlert, Bot, History, Layers, Code } from "lucide-react";
import type { KiraClient } from "../api.ts";
import { ChainTrace } from "../components/ChainTrace.tsx";
import { API_PREFIX, CONTRACT_VERSION } from "../contracts.ts";
import type { CheckpointInfo, Mode, ToolsResponse } from "../contracts.ts";
import { chainSummary } from "../turn.ts";
import type { Turn } from "../turn.ts";
import type { ChatState } from "../useChat.ts";

export const PANEL_TABS = [
  "Changes",
  "Terminal",
  "Tests",
  "Problems",
  "Agents",
  "Checkpoints",
  "Context",
  "Developer",
] as const; // ALTREX WorkPanel.tsx:16-25, same order
export type PanelTab = (typeof PANEL_TABS)[number];

const ICONS: Record<PanelTab, typeof Code> = {
  Changes: FileDiff,
  Terminal,
  Tests: FlaskConical,
  Problems: CircleAlert,
  Agents: Bot,
  Checkpoints: History,
  Context: Layers,
  Developer: Code,
};

const executed = (turn: Turn | null) => (turn?.chain ?? []).filter((r) => r.event === "tool_executed");
// `risk` is the tool's declaration, not the model's opinion of its arguments.
const writes = (turn: Turn | null) => executed(turn).filter((r) => r.risk === "write");
const commands = (turn: Turn | null) => executed(turn).filter((r) => r.risk === "exec");
const tests = (turn: Turn | null) => commands(turn).filter((r) => r.kind === "test");
const failures = (turn: Turn | null) =>
  (turn?.chain ?? []).filter((r) => r.event === "tool_denied" || (r.event === "tool_executed" && r.ok === false));

function lastTurn(chat: ChatState): Turn | null {
  if (chat.live) return chat.live;
  for (let i = chat.entries.length - 1; i >= 0; i -= 1) {
    const turn = chat.entries[i]?.turn;
    if (turn) return turn;
  }
  return null;
}

function messageOf(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

export function AgentPanel({ chat, model, mode, client, modelChoices }: { chat: ChatState; model: string; mode: Mode; client: KiraClient; modelChoices: { id: string; contextWindowText: string }[] }) {
  const [tab, setTab] = useState<PanelTab>("Changes");
  const [registry, setRegistry] = useState<ToolsResponse | null>(null);
  const [registryError, setRegistryError] = useState<string | null>(null);
  const [checkpoints, setCheckpoints] = useState<CheckpointInfo[]>([]);
  const [checkpointError, setCheckpointError] = useState<string | null>(null);
  const turn = lastTurn(chat);

  useEffect(() => {
    if (tab !== "Agents") return;
    let cancelled = false;
    client
      .tools()
      .then((answer) => {
        if (cancelled) return;
        setRegistry(answer);
        setRegistryError(null);
      })
      .catch((error) => {
        if (cancelled) return;
        setRegistry(null);
        setRegistryError(messageOf(error));
      });
    return () => {
      cancelled = true;
    };
  }, [tab, client]);

  useEffect(() => {
    if (tab !== "Checkpoints" || !chat.sessionId) return;
    let cancelled = false;
    client
      .checkpoints(20, chat.sessionId)
      .then((answer) => {
        if (cancelled) return;
        setCheckpoints(answer.checkpoints);
        setCheckpointError(null);
      })
      .catch((error) => {
        if (cancelled) return;
        setCheckpoints([]);
        setCheckpointError(messageOf(error));
      });
    return () => {
      cancelled = true;
    };
  }, [tab, chat.sessionId, client]);

  return (
    <aside className="work-panel" aria-label="work panel">
      <div className="work-tabs" role="tablist" aria-label="work panel tabs">
        {PANEL_TABS.map((name) => {
          const Icon = ICONS[name];
          return (
            <button
              key={name}
              type="button"
              role="tab"
              aria-label={name}
              title={name}
              aria-selected={tab === name}
              className={tab === name ? "active" : ""}
              onClick={() => setTab(name)}
            >
              <Icon size={16} />
              <span className="work-tab-label">{name}</span>
            </button>
          );
        })}
      </div>
      <div className="work-head">
        <span className="work-kicker">Inspector</span>
        <h3>{tab}</h3>
      </div>
      <div className="work-body" role="tabpanel" aria-label={tab}>
        {tab === "Changes" &&
          (writes(turn).length ? (
            <ul className="work-list">
              {writes(turn).map((record) => (
                <li key={record.call_id ?? record.summary} className="mono">
                  {record.summary ?? record.tool}
                  {record.checkpoint_id ? ` · checkpoint ${record.checkpoint_id}` : ""}
                </li>
              ))}
            </ul>
          ) : (
            <p className="empty">no file writes this turn</p>
          ))}

        {tab === "Terminal" &&
          (commands(turn).length ? (
            <ul className="work-list">
              {commands(turn).map((record) => (
                <li key={record.call_id ?? record.summary} className="mono">
                  {record.summary} · exit {record.exit_code ?? "—"} · {record.duration_ms ?? 0} ms
                </li>
              ))}
            </ul>
          ) : (
            <p className="empty">no commands this turn</p>
          ))}

        {tab === "Tests" &&
          (tests(turn).length ? (
            <ul className="work-list">
              {tests(turn).map((record) => (
                <li key={record.call_id ?? record.summary} className="mono">
                  {record.summary} · exit {record.exit_code}
                </li>
              ))}
            </ul>
          ) : (
            <p className="empty">no test runs this turn — argv decides what counts as a test</p>
          ))}

        {tab === "Problems" &&
          (failures(turn).length ? (
            <ul className="work-list">
              {failures(turn).map((record) => (
                <li key={`${record.event}-${record.call_id}`} className="mono">
                  {record.event === "tool_denied"
                    ? `${record.tool}: ${record.reason}`
                    : `${record.tool}: exit ${record.exit_code ?? "—"}`}
                </li>
              ))}
            </ul>
          ) : (
            <p className="empty">no problems this turn</p>
          ))}

        {tab === "Agents" && (
          <>
            {!turn && <p className="empty">no turn yet — ask something and the chain will appear here</p>}
            {turn && (
              <>
                <p className="work-meta">{chainSummary(turn)}</p>
                <ChainTrace chain={turn.chain} />
              </>
            )}
            <h4>registry</h4>
            {registryError && <p className="error">{registryError}</p>}
            {registry ? (
              <>
                {registry.tools.length === 0 ? (
                  <p className="empty">no tools registered</p>
                ) : (
                  <ul className="work-list">
                    {registry.tools.map((tool) => (
                      <li key={tool.name}>
                        <span className="mono">{tool.name}</span> · {tool.risk} · {tool.policy}
                      </li>
                    ))}
                  </ul>
                )}
                <h4>plugins</h4>
                {registry.plugins.length === 0 ? (
                  <p className="empty">no plugins found</p>
                ) : (
                  <ul className="work-list">
                    {registry.plugins.map((plugin) => (
                      <li key={plugin.file}>
                        {plugin.name} — {plugin.status}
                        {plugin.reason ? `: ${plugin.reason}` : ""}
                      </li>
                    ))}
                  </ul>
                )}
              </>
            ) : (
              !registryError && <p className="muted">reading the registry…</p>
            )}
          </>
        )}

        {tab === "Checkpoints" && (
          <>
            {!chat.sessionId ? (
              <p className="empty">no session yet — checkpoints are listed once a turn has one</p>
            ) : checkpointError ? (
              <p className="error">{checkpointError}</p>
            ) : checkpoints.length === 0 ? (
              <p className="empty">no checkpoints in this session</p>
            ) : (
              <ul className="work-list">
                {checkpoints.map((checkpoint) => (
                  <li key={checkpoint.id} className="mono">
                    {checkpoint.id} · {checkpoint.tool} · {checkpoint.status} · {checkpoint.files.length} file(s)
                  </li>
                ))}
              </ul>
            )}
          </>
        )}

        {tab === "Context" && (
          <dl className="work-facts">
            <dt>session</dt><dd className="mono">{chat.sessionId ? chat.sessionId.slice(0, 8) : "none yet"}</dd>
            <dt>model</dt><dd className="mono">{model || "—"}</dd>
            <dt>mode</dt><dd className="mono">{mode}</dd>
            <dt>usage</dt><dd className="mono">{turn?.usage ? `${turn.usage.prompt_tokens}↑ / ${turn.usage.completion_tokens}↓` : "—"}</dd>
            <dt>status</dt><dd className="mono">{turn?.status ?? "—"}</dd>
            <dt>context window</dt><dd className="mono">{model && modelChoices.length > 0 ? `${(modelChoices.find(c => c.id === model)?.contextWindowText ?? "—")}` : "—"}</dd>
          </dl>
        )}
        {tab === "Developer" && (
          <dl className="work-facts">
            <dt>namespace</dt><dd className="mono">{API_PREFIX}</dd>
            <dt>contract</dt><dd className="mono">v{CONTRACT_VERSION}</dd>
            <dt>provider_chain</dt>
            <dd className="mono work-json">{JSON.stringify(turn?.chain ?? [], null, 2)}</dd>
          </dl>
        )}
      </div>
    </aside>
  );
}
