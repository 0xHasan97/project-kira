import { useState } from "react";
import type { KiraClient } from "../api.ts";
import type { CheckpointInfo, ToolInfo, ToolPolicy } from "../contracts.ts";
import { useAsync } from "../useAsync.ts";
import { useWrite } from "../useWrite.ts";

const POLICIES: ToolPolicy[] = ["allow", "ask", "deny"];

function messageOf(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

function stamp(seconds: number): string {
  return new Date(seconds * 1000).toLocaleString("en-GB", { hour12: false });
}

const EMPTY_TOOLS = { tools: [] as ToolInfo[], plugins: [] as { file: string; name: string; status: string; reason: string }[] };
const EMPTY_CHECKPOINTS = { checkpoints: [] as CheckpointInfo[] };

export function ToolsScreen({ client, connected, pull = 0 }: { client: KiraClient; connected: boolean; pull?: number }) {
  const registry = useAsync(() => (connected ? client.tools() : Promise.resolve(EMPTY_TOOLS)), [connected, pull]);
  const checkpoints = useAsync(
    () => (connected ? client.checkpoints(20) : Promise.resolve(EMPTY_CHECKPOINTS)),
    [connected, pull],
  );
  const { busy, note, run } = useWrite(() => {
    registry.refresh();
    checkpoints.refresh();
  });
  const [notice, setNotice] = useState<string | null>(null);

  function changePolicy(tool: ToolInfo, next: ToolPolicy | null) {
    void run(
      `set ${tool.name}'s policy to ${next ?? "the config default"}`,
      "This changes what the agent may do without asking.",
      next === "allow",
      (secret) => client.setToolPolicy(tool.name, next, secret),
    );
  }

  function restore(checkpoint: CheckpointInfo) {
    void run(
      `restore checkpoint ${checkpoint.id}`,
      "Every file it lists goes back to its pre-write bytes.",
      true,
      async (secret) => {
        const answer = await client.restoreCheckpoint(checkpoint.id, secret);
        setNotice(
          answer.conflicts.length
            ? `restored with ${answer.conflicts.length} conflict(s)`
            : `restored ${answer.restored.length} file(s)`,
        );
        return answer;
      },
    );
  }

  return (
    <section className="screen" aria-label="tools">
      <h2>Tools</h2>
      {note && <p className="error">{note}</p>}
      {notice && <p className="notice">{notice}</p>}

      {registry.kind === "loading" ? <p className="muted">reading the tool registry…</p> : null}
      {registry.kind === "error" ? (
        <p className="error">cannot read the tool registry: {messageOf(registry.error)}</p>
      ) : null}
      {registry.kind === "ready" && (
        <>
          <table className="grid">
            <thead>
              <tr><th>tool</th><th>risk</th><th>source</th><th>default</th><th>policy</th></tr>
            </thead>
            <tbody>
              {registry.data.tools.map((tool) => (
                <tr key={tool.name}>
                  <td>
                    <div className="mono">{tool.name}</div>
                    <div className="muted small">{tool.description}</div>
                  </td>
                  <td>{tool.risk}</td>
                  <td className="muted mono">{tool.source}</td>
                  <td className="muted">{tool.default_policy}</td>
                  <td>
                    <select
                      aria-label={`policy for ${tool.name}`}
                      value={tool.policy}
                      disabled={busy}
                      onChange={(event) =>
                        changePolicy(tool, event.target.value === "" ? null : (event.target.value as ToolPolicy))
                      }
                    >
                      {POLICIES.map((policy) => <option key={policy} value={policy}>{policy}</option>)}
                      {tool.overridden && <option value="">config default</option>}
                    </select>
                    {tool.overridden && <div className="muted mono small">overridden</div>}
                  </td>
                </tr>
              ))}
              {registry.data.tools.length === 0 && (
                <tr><td colSpan={5} className="empty">no tools registered — the engine builds its workspace tools at startup.</td></tr>
              )}
            </tbody>
          </table>

          <h3>plugins</h3>
          {registry.data.plugins.length === 0 ? (
            <p className="empty">no plugins found — drop a JSON file into data_dir/plugins and restart the engine.</p>
          ) : (
            <ul className="work-list">
              {registry.data.plugins.map((plugin) => (
                <li key={plugin.file}>
                  <span className="mono">{plugin.name}</span> — {plugin.status}
                  {plugin.reason ? `: ${plugin.reason}` : ""}
                </li>
              ))}
            </ul>
          )}
        </>
      )}

      <h3>checkpoints</h3>
      {checkpoints.kind === "loading" ? <p className="muted">reading checkpoints…</p> : null}
      {checkpoints.kind === "error" ? (
        <p className="error">cannot read checkpoints: {messageOf(checkpoints.error)}</p>
      ) : null}
      {checkpoints.kind === "ready" && (
        checkpoints.data.checkpoints.length === 0 ? (
          <p className="empty">no checkpoints yet — one is taken before a tool writes a file.</p>
        ) : (
          <ul className="work-list">
            {checkpoints.data.checkpoints.map((checkpoint) => (
              <li key={checkpoint.id}>
                <code className="mono">{checkpoint.id}</code> — {checkpoint.tool} — {checkpoint.status} —{" "}
                {checkpoint.files.length} file(s) · {stamp(checkpoint.created_at)}{" "}
                <button type="button" disabled={busy} onClick={() => restore(checkpoint)}>
                  {`restore ${checkpoint.id}`}
                </button>
                <div className="muted mono small">{checkpoint.files.map((file) => file.path).join(", ")}</div>
              </li>
            ))}
          </ul>
        )
      )}

      <p className="muted small">
        A policy is what the agent may do without asking. "ask" holds the answer open until you decide here
        in the chat; "deny" refuses the call. Restoring writes the checkpointed bytes back and deletes files
        that did not exist then — it takes a checkpoint of its own first.
      </p>
    </section>
  );
}
