import { useCallback, useEffect, useRef, useState } from "react";
import type { FormEvent } from "react";
import type { KiraClient } from "./api.ts";
import type { ChatChunk, HealthResponse, Mode, SessionRow } from "./contracts.ts";
import { KiraApiError } from "./contracts.ts";
import { applyChunk, emptyTurn } from "./turn.ts";
import type { Turn } from "./turn.ts";

export interface Entry {
  id: number;
  role: "user" | "assistant";
  content: string;
  turn?: Turn;
}

const SESSION_KEY = "kira.session";
const SKILL_KEY = "kira.skill";

/** The session this tab is in. sessionStorage, not local: two tabs are two sittings, and a
 * browser restart is a new one — but a reload or a route change is the same conversation. */
function storedSession(): string | null {
  return sessionStorage.getItem(SESSION_KEY);
}

function rememberSession(id: string | null): void {
  if (id === null) sessionStorage.removeItem(SESSION_KEY);
  else sessionStorage.setItem(SESSION_KEY, id);
}

/** The persona this tab pinned, for the same reason: a route change is the same sitting. */
function storedSkill(): string | null {
  return sessionStorage.getItem(SKILL_KEY);
}

function rememberSkill(name: string | null): void {
  if (name === null) sessionStorage.removeItem(SKILL_KEY);
  else sessionStorage.setItem(SKILL_KEY, name);
}

export interface UseChatOptions {
  client: KiraClient;
  model: string;
  mode: Mode;
  connected: boolean;
  /** True when a surface that shows the ledger is mounted (the chat screen, or the agent shell). */
  watching: boolean;
}

export interface ChatState {
  entries: Entry[];
  sessionId: string | null;
  sessions: SessionRow[];
  health: HealthResponse | null;
  prompt: string;
  setPrompt(prompt: string): void;
  /** The persona pinned to the next turns, or null. Methods are the model's to load, not the tab's. */
  skill: string | null;
  setSkill(name: string | null): void;
  busy: boolean;
  live: Turn | null;
  ledgerError: string | null;
  /** The screen still gates the composer on this, so the hook owns the same boolean the ledger reads. */
  connected: boolean;
  send(event?: FormEvent): void;
  stop(): void;
  openSession(id: string): Promise<void>;
  /** Forget the current sitting and start the next send in a fresh engine session. */
  newChat(): void;
  pullLedger(): void;
  decideApproval(id: string, decision: "allow" | "deny", secret: string): Promise<void>;
}

export function useChat({ client, model, mode, connected, watching }: UseChatOptions): ChatState {
  const [entries, setEntries] = useState<Entry[]>([]);
  const [sessionId, setSessionId] = useState<string | null>(() => storedSession());
  const [sessions, setSessions] = useState<SessionRow[]>([]);
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [prompt, setPrompt] = useState("");
  const [skill, setSkillState] = useState<string | null>(() => storedSkill());
  const [busy, setBusy] = useState(false);
  const [live, setLive] = useState<Turn | null>(null);
  const [ledgerError, setLedgerError] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const nextId = useRef(1);
  const restored = useRef(false);
  // The current session, readable from the closure a long-running `send` already captured. The state
  // variable in that closure is the one from the render that started the turn, so it cannot tell the
  // turn whether the user has since opened another conversation — this ref can.
  const sessionIdRef = useRef<string | null>(sessionId);
  useEffect(() => {
    sessionIdRef.current = sessionId;
  }, [sessionId]);

  // Chat only re-reads the engine when it is actually on screen. A failure is shown, not swallowed: a dead
  // token or a refused namespace used to look exactly like an engine that has never served a turn.
  const pullLedger = useCallback(() => {
    if (!connected) return;
    void Promise.all([client.health(), client.sessions()])
      .then(([snapshot, rows]) => {
        setHealth(snapshot);
        setSessions(rows.sessions);
        setLedgerError(null);
      })
      .catch((error) => setLedgerError(messageOf(error)));
  }, [client, connected]);

  useEffect(() => {
    if (watching) pullLedger();
  }, [watching, pullLedger]);

  // A remount — a reload, a route change, the shell switching — is the same sitting, so the
  // conversation the tab remembers is what comes back. A session the engine has since dropped
  // (a wiped ledger, a deleted row) is forgotten instead of replayed as an error the user never caused.
  useEffect(() => {
    const stored = storedSession();
    if (restored.current || !watching || !connected || !stored) return;
    restored.current = true;
    void openSession(stored).catch(() => {
      rememberSession(null);
      setSessionId(null);
    });
  }, [watching, connected, client]);

  async function send(event?: FormEvent) {
    event?.preventDefault();
    const text = prompt.trim();
    if (!text || busy) return;
    setPrompt("");
    setEntries((prev) => [...prev, { id: nextId.current++, role: "user", content: text }]);
    setBusy(true);
    setLive(emptyTurn());
    // The session this turn belongs to, captured before the first await. A turn that answers into
    // whatever session happened to be current when the stream ended is the bug this guards: the
    // sidebar stays clickable while a stream is running, so `openSession` can land mid-turn and the
    // `finally` below would otherwise rename the file the answer went into — and append A's answer to
    // B's transcript.
    const startedIn = sessionId;

    const history = entries.map((entry) => ({ role: entry.role, content: entry.content }));
    let turn = emptyTurn();
    const onChunk = (chunk: ChatChunk) => {
      turn = applyChunk(turn, chunk);
      setLive(turn);
    };
    const controller = new AbortController();
    abortRef.current = controller;
    try {
      await client.stream({ messages: [...history, { role: "user", content: text }], model: model || null, mode, session_id: sessionId, skill }, onChunk, controller.signal);
    } catch (error) {
      if (!turn.error) {
        const refusal = error instanceof KiraApiError ? error : null;
        const stopped = controller.signal.aborted;
        turn = {
          ...turn,
          // The engine's rule, mirrored: text that survived makes this an interrupted turn, nothing on
          // screen makes it a failed one — and the bubble has to say the word the stored row says, or the
          // same turn renames itself when the user reloads the session.
          status: turn.text ? "interrupted" : "failed",
          error: stopped ? "you stopped this turn" : messageOf(error),
          errorCode: refusal?.body.code ?? null,
          chain: refusal && refusal.chain.length > 0 ? refusal.chain : turn.chain,
        };
      }
    } finally {
      abortRef.current = null;
      // The user moved to another session while this one was still streaming. The engine has already
      // stored the answer against `turn.sessionId`, so the transcript on screen will be right again
      // the next time that session is opened; writing it into the session they are now reading would
      // be the wrong answer in the wrong conversation.
      if (sessionIdRef.current !== startedIn) {
        setLive(null);
        setBusy(false);
        pullLedger();
        return;
      }
      // A turn the engine accepted names the session the next one belongs to — including the very
      // first turn, which is also the session the tab has to remember.
      const nextSession = turn.sessionId ?? sessionId;
      setSessionId(nextSession);
      rememberSession(nextSession);
      setEntries((prev) => [...prev, { id: nextId.current++, role: "assistant", content: turn.text, turn }]);
      setLive(null);
      setBusy(false);
      // The engine owns history, so pull both the ledger and the session list after a turn.
      pullLedger();
    }
  }

  function setSkill(name: string | null) {
    setSkillState(name);
    rememberSkill(name);
  }

  function stop() {
    abortRef.current?.abort();
  }

  async function openSession(id: string) {
    const rows = await client.messages(id);
    setSessionId(id);
    rememberSession(id);
    setEntries(
      rows.messages
        .filter((row) => row.role === "user" || row.role === "assistant")
        .map((row) => ({
          id: nextId.current++,
          role: row.role as "user" | "assistant",
          content: row.content,
          turn:
            row.role === "assistant"
              ? {
                  ...emptyTurn(),
                  text: row.content,
                  provider: row.provider,
                  model: row.model,
                  status: row.status,
                  // History is stored with internal token names; the live stream speaks OpenAI names.
                  usage: row.usage
                    ? { prompt_tokens: row.usage.input_tokens, completion_tokens: row.usage.output_tokens }
                    : null,
                  chain: row.chain ?? [],
                  toolCalls: row.tool_calls ?? [],
                  sessionId: id,
                }
              : undefined,
        })),
    );
  }

  // A new chat is not a delete: the previous session stays in the ledger and in the sidebar, and this
  // tab simply stops pointing at it. A null session id is how the client says "let the engine mint
  // the next one", so no empty session is written just because someone pressed the button.
  function newChat() {
    if (busy) return;
    setEntries([]);
    setLive(null);
    setSessionId(null);
    sessionIdRef.current = null;
    rememberSession(null);
    setPrompt("");
  }

  async function decideApproval(id: string, decision: "allow" | "deny", secret: string) {
    await client.decideApproval(id, decision, secret);
  }

  return {
    entries,
    sessionId,
    sessions,
    health,
    prompt,
    setPrompt,
    skill,
    setSkill,
    busy,
    live,
    ledgerError,
    connected,
    send,
    stop,
    openSession,
    newChat,
    pullLedger,
    decideApproval,
  };
}

function messageOf(error: unknown): string {
  if (error instanceof Error) return error.message;
  return String(error);
}
