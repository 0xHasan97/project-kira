import { createContext, useCallback, useContext, useEffect, useRef, useState } from "react";
import type { FormEvent, ReactNode } from "react";

export interface ConfirmRequest {
  /** What the human is approving, in their words: "turn groq off", not "PUT /settings". */
  summary: string;
  detail?: string;
  danger?: boolean;
  /** When set, the submit button stays dead until this exact string is typed. Not sent anywhere. */
  phrase?: string;
}

/** Resolves to the typed secret, or null when the human cancelled. */
export type Ask = (request: ConfirmRequest) => Promise<string | null>;

const ConfirmContext = createContext<Ask | null>(null);

export function useConfirm(): Ask {
  const ask = useContext(ConfirmContext);
  if (!ask) throw new Error("useConfirm needs a <ConfirmProvider> above it");
  return ask;
}

interface Open {
  request: ConfirmRequest;
  resolve: (answer: string | null) => void;
}

export function ConfirmProvider({ children }: { children: ReactNode }) {
  const [open, setOpen] = useState<Open | null>(null);
  const [typed, setTyped] = useState("");
  const [typedPhrase, setTypedPhrase] = useState("");
  const [error, setError] = useState<string | null>(null);
  // The state mirror is not enough to answer "is a dialog up right now" inside a synchronous
  // click handler, so keep one authoritative flag that never lags a render.
  const openRef = useRef<Open | null>(null);

  const close = useCallback(() => {
    openRef.current = null;
    setOpen(null);
    setTyped("");
    setTypedPhrase("");
    setError(null);
  }, []);

  const ask = useCallback<Ask>(
    (request) =>
      new Promise<string | null>((resolve) => {
        if (openRef.current) {
          resolve(null);
          return;
        }
        setTyped("");
        setTypedPhrase("");
        setError(null);
        const next = { request, resolve };
        openRef.current = next;
        setOpen(next);
      }),
    [],
  );

  function submit(event: FormEvent) {
    event.preventDefault();
    const current = openRef.current;
    // Enter in the secret box submits this form with the button still disabled, so the words are
    // checked here too: a paste that carries whitespace is not typing them, and neither is a keystroke.
    if (current?.request.phrase !== undefined && typedPhrase !== current.request.phrase) {
      setError(`type ${current.request.phrase} exactly, or cancel`);
      return;
    }
    if (!typed) {
      setError("type the confirm secret, or cancel");
      return;
    }
    close();
    current?.resolve(typed);
  }

  function cancel() {
    const current = openRef.current;
    close();
    current?.resolve(null);
  }

  useEffect(() => {
    if (!open) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") cancel();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
    // `cancel` is re-created each render on purpose: the listener is re-bound with it, so
    // memoising it would only serve a lint rule. See Task 14 Step 3.
  }, [open]);

  return (
    <ConfirmContext.Provider value={ask}>
      {children}
      {open && (
        <div className="confirm-backdrop" role="dialog" aria-modal="true" aria-labelledby="confirm-title">
          <form className="confirm-card" onSubmit={submit}>
            <h3 id="confirm-title">{open.request.summary}</h3>
            {open.request.detail && <p className="muted mono">{open.request.detail}</p>}
            {open.request.danger && <p className="warn">This cannot be undone from the browser.</p>}
            {/* The destruction is named first, then the credential that authorises it. */}
            {open.request.phrase && (
              <label>
                {`Type ${open.request.phrase} to allow this`}
                <input
                  name="confirm_phrase"
                  type="text"
                  value={typedPhrase}
                  onChange={(event) => setTypedPhrase(event.target.value)}
                  autoComplete="off"
                  spellCheck={false}
                />
              </label>
            )}
            <label>
              Confirm secret
              <input
                name="confirm_secret"
                type="password"
                value={typed}
                onChange={(event) => setTyped(event.target.value)}
                autoComplete="off"
                spellCheck={false}
                autoFocus
              />
            </label>
            <p className="muted">
              The engine/confirm value, printed on its first run and by kira-engine token. It goes out
              once, in the X-Kira-Confirm header, and this page keeps no copy of it.
            </p>
            {error && <p className="error">{error}</p>}
            <div className="confirm-actions">
              <button type="button" onClick={cancel}>
                cancel
              </button>
              <button
                type="submit"
                disabled={open.request.phrase !== undefined && typedPhrase !== open.request.phrase}
                className={open.request.danger ? "danger" : undefined}
              >
                confirm write
              </button>
            </div>
          </form>
        </div>
      )}
    </ConfirmContext.Provider>
  );
}
