import { useEffect, useRef, useState } from "react";
import { Plus } from "lucide-react";
import { ApprovalCard } from "../components/ApprovalCard.tsx";
import { ChainTrace } from "../components/ChainTrace.tsx";
import { TurnTrace } from "../components/TurnTrace.tsx";
import { useFollow } from "../follow.ts";
import { autosize, elapsed, wantsSend } from "../composer.ts";
import type { ModelInfo, Mode } from "../contracts.ts";
import type { Shell } from "../shell.ts";
import { answersToday, keyBadge } from "../keying.ts";
import { chainSummary } from "../turn.ts";
import type { ChatState } from "../useChat.ts";

export interface ChatScreenProps {
  chat: ChatState;
  shell: Shell;
  models: ModelInfo[];
  mode: Mode;
  model: string;
  modelChoices: {
    id: string;
    contextWindow: number | null;
    contextWindowText: string;
  }[];
}

export function ChatScreen({
  chat,
  shell,
  models,
  mode,
  model,
  modelChoices,
}: ChatScreenProps) {
  const {
    entries,
    live,
    busy,
    prompt,
    setPrompt,
    send,
    stop,
    openSession,
    newChat,
    sessions,
    health,
    ledgerError,
    sessionId,
  } = chat;
  // The meter is about the conversation, not the stream: keep the finished turn's usage on screen
  // once `live` is cleared, or every answer would reset the bar to zero the moment it completed.
  const lastDone = [...entries].reverse().find((entry) => entry.turn?.usage);
  const contextUsage = live?.usage ?? lastDone?.turn?.usage ?? null;

  // The composer is sticky inside the thread, so a turn that arrives while the reader sits at the
  // bottom must drag that bottom down with it — otherwise the newest answer hides under the composer.
  const thread = useRef<HTMLElement>(null);
  const follow = useFollow(
    thread,
    `${entries.length}:${live?.text.length ?? 0}`,
  );
  const box = useRef<HTMLTextAreaElement>(null);

  // The prompt grows with its text: a long paste must not become a four-line window onto itself.
  useEffect(() => {
    if (box.current) autosize(box.current);
  }, [prompt]);

  // A working turn has no ending to show, so the footer counts instead: "Working for 12s · 2 steps".
  const [startedAt, setStartedAt] = useState<number | null>(null);
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!busy) {
      setStartedAt(null);
      return;
    }
    setStartedAt((prev) => prev ?? Date.now());
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [busy]);

  const steps =
    live?.chain.filter((record) => record.event === "tool_executed").length ??
    0;
  // The composer says nothing when it is idle: the model and routing pickers already sit in the
  // header, and repeating them under the box was a third place to read the same fact. A working turn
  // is the one status the header cannot show, so that is the only sentence left here.
  // The picker lists ids once, so the count beside it has to count ids too — two providers serving
  // the same model are one choice, not two.
  const choices = new Set(models.map((entry) => entry.id)).size;
  const footer =
    shell === "agent"
      ? busy
        ? `Working for ${elapsed(startedAt ?? now, now)} · ${steps} step${steps === 1 ? "" : "s"}`
        : `Enter sends · ${choices} model${choices === 1 ? "" : "s"} · ${mode}`
      : busy
        ? `Working for ${elapsed(startedAt ?? now, now)} · ${steps} step${steps === 1 ? "" : "s"}`
        : "";

  const cooling = health
    ? Object.entries(health.providers).filter(
        ([, state]) => state.cooling_s > 0,
      )
    : [];
  // A first run with no provider able to answer should say what to do next, not sit on a sentence
  // over an empty box. A provider with `needs_key: false` already answers, so it rules setup out.
  const configured = health?.configured ?? [];
  const missingKeys = configured.filter((provider) => !answersToday(provider));
  const needsSetup = health !== null && !configured.some(answersToday);
  const recentSessions = sessions.slice(0, 8);

  return (
    <div className="body">
      <aside className="side">
        {ledgerError && (
          <p className="error" role="alert">
            {ledgerError}
          </p>
        )}
        <div className="side-head">
          <h2>{shell === "agent" ? "Sessions" : "Conversations"}</h2>
          {shell !== "agent" && (
            <button
              type="button"
              className="new-chat"
              onClick={newChat}
              disabled={busy}
              title="start a new conversation"
            >
              <Plus size={14} aria-hidden="true" />
              New chat
            </button>
          )}
        </div>
        {sessions.length === 0 && (
          <p className="muted side-empty">
            {shell === "agent" ? "none yet" : "No conversations yet"}
          </p>
        )}
        <ul>
          {recentSessions.map((row) => (
            <li key={row.id}>
              <button
                type="button"
                className={row.id === sessionId ? "active" : ""}
                // Switching mid-turn would leave the answer streaming into a conversation that is no
                // longer on screen. The hook refuses the write too, but the button should not offer it.
                disabled={busy}
                onClick={() => void openSession(row.id)}
              >
                <span className="mono">{row.id.slice(0, 8)}</span>
                <span className="muted">{row.mode}</span>
              </button>
            </li>
          ))}
        </ul>
        {sessions.length > recentSessions.length && (
          <a className="side-more" href="#/sessions">
            All {sessions.length}{" "}
            {shell === "agent" ? "sessions" : "conversations"}
          </a>
        )}
        {health && (
          <>
            <h2>Providers</h2>
            <ul className="providers">
              {health.configured.map((provider) => {
                const state = health.providers[provider.name];
                const badge = keyBadge(provider);
                return (
                  <li key={provider.name}>
                    <span className="mono">{provider.name}</span>
                    <span
                      className={
                        badge.ok ? "badge badge-ok" : "badge badge-none"
                      }
                    >
                      {badge.text}
                    </span>
                    <span className="muted provider-state">
                      {state
                        ? `${state.successes}✓ ${state.failures}✗${state.cooling_s ? ` ${state.cooling_s}s` : ""}`
                        : "idle"}
                    </span>
                  </li>
                );
              })}
            </ul>
            {cooling.length > 0 && (
              <p className="warn">{cooling.length} provider(s) cooling down</p>
            )}
          </>
        )}
      </aside>

      <section className="thread" ref={thread}>
        {entries.length === 0 && !live && shell === "agent" && (
          <div className="empty-state">
            <p className="empty-eyebrow">Agent mode</p>
            <h1>What are we building?</h1>
            <p className="empty-sub">
              Ask a question, plan a change, or run a tool. Every answer keeps
              its provider chain and every write waits for your confirmation.
            </p>
            <div className="empty-hints">
              {[
                [
                  "Review the working tree",
                  "Review the working tree and list anything worth fixing.",
                ],
                [
                  "Run the test suite",
                  "Run the full test suite and explain any failures.",
                ],
                [
                  "Explain this project",
                  "Explain how this project is structured and where to start.",
                ],
              ].map(([label, prompt]) => (
                <button
                  key={label}
                  type="button"
                  onClick={() => {
                    setPrompt(prompt);
                    box.current?.focus();
                  }}
                >
                  {label}
                </button>
              ))}
            </div>
          </div>
        )}
        {entries.length === 0 && !live && shell !== "agent" && (
          <div className="empty-state chat-empty">
            <p className="empty-eyebrow">{needsSetup ? "Setup" : "Chat"}</p>
            <h1>{needsSetup ? "Connect a provider" : "How can I help?"}</h1>
            <p className="empty-sub">
              {needsSetup
                ? configured.length === 0
                  ? "No provider configured yet."
                  : `${missingKeys.map((provider) => provider.name).join(", ")} ${missingKeys.length === 1 ? "needs" : "need"} a key.`
                : "Ask anything. The reply names the model that served it."}
            </p>
            {needsSetup ? (
              <a className="empty-action" href="#/providers">
                Open Providers
              </a>
            ) : (
              <div className="empty-hints">
                {[
                  [
                    "Summarize this project",
                    "Summarize this project and its main components.",
                  ],
                  [
                    "Plan a change",
                    "Plan a small change to this project and list the files it would touch.",
                  ],
                  [
                    "Explain a concept",
                    "Explain how the Kira engine routes a request to a provider.",
                  ],
                ].map(([label, prompt]) => (
                  <button
                    key={label}
                    type="button"
                    onClick={() => {
                      setPrompt(prompt);
                      box.current?.focus();
                    }}
                  >
                    {label}
                  </button>
                ))}
              </div>
            )}
          </div>
        )}
        {entries.map((entry) => (
          <article key={entry.id} className={`msg ${entry.role}`}>
            <div className="who">
              {entry.role === "user" ? "you" : shell === "agent" ? (entry.turn?.provider ?? "kira") : "Kira"}
            </div>
            <div className="content">
              {entry.content || (
                <em className="muted">
                  {shell === "agent" ? "no text returned" : "No text in this reply."}
                </em>
              )}
            </div>
            {entry.turn && (
              <>
                <div className="meta">
                  {shell === "agent" ? (
                    <>
                      <span>{entry.turn.status}</span>
                      {entry.turn.model && (
                        <span className="mono">{entry.turn.model}</span>
                      )}
                      {entry.turn.usage && (
                        <span>
                          {entry.turn.usage.prompt_tokens}↑ /{" "}
                          {entry.turn.usage.completion_tokens}↓
                        </span>
                      )}
                      <span>{chainSummary(entry.turn)}</span>
                    </>
                  ) : (
                    // Chat keeps the line to what a reader can act on: who answered, with which
                    // model, and what it cost. The skipped/failed counts live in the routing trace.
                    <>
                      {entry.turn.provider && <span>{entry.turn.provider}</span>}
                      {entry.turn.model && (
                        <span className="mono">{entry.turn.model}</span>
                      )}
                      {entry.turn.usage && (
                        <span>
                          {entry.turn.usage.prompt_tokens} in ·{" "}
                          {entry.turn.usage.completion_tokens} out
                        </span>
                      )}
                    </>
                  )}
                </div>
                {entry.turn.error && (
                  // The engine's failure text names every provider it tried. That is evidence, not the
                  // headline: a collapsed one-line label keeps the thread readable and the sentence one
                  // click away.
                  <details className="turn-error">
                    <summary>
                      {entry.turn.errorCode === "budget_exhausted" ? "monthly cap reached" : "this turn failed"}
                    </summary>
                    <p>{entry.turn.error}</p>
                    {entry.turn.errorCode === "budget_exhausted" && (
                      <a href="#/providers">raise a cap in Providers</a>
                    )}
                  </details>
                )}
                {shell === "agent" ? (
                  <TurnTrace
                    chain={entry.turn.chain}
                    status={entry.turn.status}
                    provider={entry.turn.provider}
                    usage={entry.turn.usage}
                  />
                ) : (
                  entry.turn.chain.length > 0 && (
                    <details className="why">
                      <summary>How this answer was routed</summary>
                      <ChainTrace chain={entry.turn.chain} />
                    </details>
                  )
                )}
              </>
            )}
          </article>
        ))}
        {live && (
          <article className="msg assistant streaming">
            <div className="who">
              {shell === "agent" ? (live.provider ?? "…") : "Kira"}
            </div>
            <div className="content">
              {live.text || (
                <em className="muted">
                  {shell === "agent" ? "waiting for the first token" : "Thinking…"}
                </em>
              )}
            </div>
            {shell === "agent" ? (
              <TurnTrace
                chain={live.chain}
                status={live.status}
                provider={live.provider}
                usage={live.usage}
              />
            ) : (
              live.chain.length > 0 && (
                <details className="why" open>
                  <summary>Routing</summary>
                  <ChainTrace chain={live.chain} />
                </details>
              )
            )}
            {live.approvals.map((approval) => (
              <ApprovalCard
                key={approval.id}
                approval={approval}
                onDecide={chat.decideApproval}
              />
            ))}
          </article>
        )}

        <form
          className="composer"
          onSubmit={(e) => {
            follow();
            void send(e);
          }}
        >
          <textarea
            ref={box}
            name="message"
            value={prompt}
            onChange={(e) => setPrompt(e.target.value)}
            onKeyDown={(e) => {
              const composing = (e.nativeEvent as KeyboardEvent).isComposing;
              if (
                !wantsSend({
                  key: e.key,
                  shiftKey: e.shiftKey,
                  ctrlKey: e.ctrlKey,
                  metaKey: e.metaKey,
                  isComposing: composing,
                })
              )
                return;
              e.preventDefault();
              follow();
              void send();
            }}
            rows={shell === "agent" ? 3 : 1}
            placeholder={shell === "agent" ? "message the engine" : "Message Kira…"}
            aria-label="message"
          />
          <div className="composer-actions">
            {footer && (
              <span className="muted composer-status" aria-live="polite">
                {footer}
              </span>
            )}
            {chat.skill && (
              <button
                type="button"
                className="skill-chip"
                aria-label={`clear skill ${chat.skill}`}
                title="the persona pinned to the next turn"
                onClick={() => chat.setSkill(null)}
              >
                skill: {chat.skill} · clear
              </button>
            )}
            <span className="spacer" />
            {/* Context meter — shows estimated tokens used vs context window for the selected model.
                A provider with no declared window gets no bar: measuring it against a made-up 8k
                would be a number that looks measured and is not. */}
            {model &&
              modelChoices.length > 0 &&
              (() => {
                const choice = modelChoices.find((c) => c.id === model);
                if (!choice || !choice.contextWindow) return null;
                const cw = choice.contextWindow;
                const used = contextUsage
                  ? contextUsage.prompt_tokens + contextUsage.completion_tokens
                  : 0;
                return (
                  <div className="context-meter" title="context window usage">
                    <div className="context-meter-bar">
                      <div
                        className="context-meter-fill"
                        style={{
                          width: `${Math.min(100, Math.max(0, (used / cw) * 100))}%`,
                        }}
                      />
                    </div>
                    <span className="context-meter-text">
                      {used} / {choice.contextWindowText}
                    </span>
                  </div>
                );
              })()}
            {/* One tile that is the next action, whichever it is: send the draft, or stop the turn. */}
            {busy ? (
              <button type="button" className="composer-stop" onClick={stop}>
                stop
              </button>
            ) : (
              <button type="submit" disabled={!chat.connected}>
                send
              </button>
            )}
          </div>
        </form>
      </section>
    </div>
  );
}
