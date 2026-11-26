import { useEffect, useState } from "react";
import type { KiraClient } from "../api.ts";
import type { MessageRow, SessionRow } from "../contracts.ts";
import { ChainTrace } from "../components/ChainTrace.tsx";
import { useAsync } from "../useAsync.ts";
import { useWrite } from "../useWrite.ts";
import { downloadTranscript } from "../export.ts";

function num(value: number): string {
  return value.toLocaleString("en-US");
}

function stamp(seconds: number | null): string {
  if (seconds === null) return "never";
  return new Date(seconds * 1000).toLocaleString("en-GB", { hour12: false });
}

export function SessionsScreen({
  client,
  focusId,
  onChanged,
  pull = 0,
}: {
  client: KiraClient;
  focusId: string | null;
  onChanged: () => void;
  /** Rises on the rail's refresh — a call or a paired phone writes turns this tab never saw. */
  pull?: number;
}) {
  const [open, setOpen] = useState<string | null>(focusId);
  const [query, setQuery] = useState("");
  useEffect(() => setOpen(focusId), [focusId]);

  const list = useAsync(() => client.sessions(200), [pull]);
  const transcript = useAsync(
    () => (open === null ? Promise.resolve(null) : client.messages(open)),
    [open, pull],
  );
  const { busy, note, run } = useWrite(() => {
    list.refresh();
    transcript.refresh();
    onChanged();
  });

  if (list.kind === "loading") return <section className="screen"><p className="muted">reading sessions…</p></section>;
  if (list.kind === "error") {
    return (
      <section className="screen">
        <p className="error">cannot read sessions: {String((list.error as Error).message ?? list.error)}</p>
      </section>
    );
  }
  const rows = list.data.sessions;
  const needle = query.trim().toLowerCase();
  const visible = needle
    ? rows.filter((row) => `${row.id} ${row.mode}`.toLowerCase().includes(needle))
    : rows;

  return (
    <section className="screen">
      <header className="screen-head">
        <div className="screen-title">
          <h2>Sessions</h2>
          <p className="screen-sub">
            {needle ? `${visible.length} of ${rows.length} stored` : `${rows.length} stored`}
          </p>
        </div>
        <span className="spacer" />
        <input
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          aria-label="filter sessions"
          placeholder="filter sessions…"
          spellCheck={false}
        />
        <button type="button" onClick={list.refresh}>reload</button>
        <button
          type="button"
          className="danger"
          disabled={busy || rows.length === 0}
          onClick={() =>
            void run(
              "delete every session",
              "DELETE /v1/kira/sessions",
              true,
              async (secret) => {
                const answer = await client.clearSessions(secret);
                setOpen(null);
                return answer;
              },
            )
          }
        >
          delete every session
        </button>
      </header>
      {note && <p className="error">{note}</p>}

      {rows.length === 0 ? (
        <p className="empty">No sessions yet.</p>
      ) : visible.length === 0 ? (
        <p className="empty">No session matches “{query.trim()}”.</p>
      ) : (
        <table className="grid">
          <thead>
            <tr><th>session</th><th>mode</th><th>messages</th><th>tokens</th><th>last used</th><th>actions</th></tr>
          </thead>
          <tbody>
            {visible.map((row: SessionRow) => (
              <tr key={row.id} className={open === row.id ? "row-open" : undefined}>
                <td className="mono">{row.id}</td>
                <td>{row.mode}</td>
                <td>{row.message_count}</td>
                <td className="mono">{num(row.tokens)}</td>
                <td className="mono">{stamp(row.last_used_at)}</td>
                <td>
                  <div className="cell-actions">
                    <button
                      type="button"
                      aria-label={`transcript ${row.id}`}
                      title={`transcript ${row.id}`}
                      onClick={() => setOpen(row.id)}
                    >
                      transcript
                    </button>
                    <button
                      type="button"
                      aria-label={`delete ${row.id}`}
                      disabled={busy}
                      onClick={() =>
                        void run(
                          `delete ${row.id} and its ${row.message_count} message${row.message_count === 1 ? "" : "s"}`,
                          `DELETE /v1/kira/sessions/${row.id}`,
                          true,
                          // Closing the transcript that was just deleted is part of the write: an open
                          // panel over a gone session can only say "it was never answered", which is a
                          // different truth than "you deleted it a second ago".
                          async (secret) => {
                            const answer = await client.deleteSession(row.id, secret);
                            setOpen((current) => (current === row.id ? null : current));
                            return answer;
                          },
                        )
                      }
                    >
                      delete
                    </button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {open !== null && (
        <section className="transcript" aria-label={`transcript ${open}`}>
          <header className="screen-head">
            <h3 className="mono">{open}</h3>
            <span className="spacer" />
            <button
              type="button"
              disabled={
                transcript.kind !== "ready" ||
                transcript.data === null ||
                transcript.data.messages.length === 0
              }
              onClick={() => {
                if (open && transcript.kind === "ready" && transcript.data) {
                  downloadTranscript(open, transcript.data.messages);
                }
              }}
            >
              export .md
            </button>
            <button type="button" onClick={() => setOpen(null)}>close</button>
          </header>
          {transcript.kind === "loading" ? <p className="muted">reading the turns…</p> : null}
          {transcript.kind === "error" ? (
            <p className="error">cannot read this session: {String((transcript.error as Error).message ?? transcript.error)}</p>
          ) : null}
          {transcript.kind === "ready" && transcript.data !== null && (
            transcript.data.messages.length === 0 ? (
              <p className="empty">the engine has no rows for {open}: it was created and never answered.</p>
            ) : (
              <ol className="turns">
                {transcript.data.messages.map((message: MessageRow) => (
                  <li key={message.id} className={`turn turn-${message.role}`}>
                    <div className="meta">
                      <span>{message.role}</span>
                      {/* A user row was never given a status by anyone and spent nothing; "complete" and
                          "0 tokens" beside it are the assistant's vocabulary wearing the wrong label. */}
                      {message.role === "assistant" && (
                        <>
                          <span className="mono">{message.status}</span>
                          {message.provider && <span className="mono">{message.provider}/{message.model}</span>}
                          {message.usage && (
                            <span className="mono">
                              {num((message.usage.input_tokens ?? 0) + (message.usage.output_tokens ?? 0))} tokens
                            </span>
                          )}
                        </>
                      )}
                    </div>
                    <div className="content">{message.content || <em className="muted">no text stored</em>}</div>
                    <ChainTrace chain={message.chain} />
                  </li>
                ))}
              </ol>
            )
          )}
        </section>
      )}

      <p className="muted small">
        Deleting is final: the engine removes the session and every message under it in one statement, and
        there is no undo in the browser. A delete that finds nothing still answers as a success, because the
        row you clicked is a snapshot of a list someone else may have already cleared.
      </p>
    </section>
  );
}
