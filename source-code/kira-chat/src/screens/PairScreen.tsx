import { useMemo, useState } from "react";
import type { FormEvent } from "react";
import { KiraClient } from "../api.ts";

function messageOf(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

/** The code rides in the hash so it never reaches a server log: `#/pair?code=AB12CD34`. */
function clean(raw: string): string {
  return raw.toUpperCase().replace(/[^0-9A-Z]/g, "");
}

function codeFromHash(): string {
  const query = window.location.hash.split("?")[1] ?? "";
  return clean(new URLSearchParams(query).get("code") ?? "");
}

export function PairScreen({ onPaired }: { onPaired: (token: string) => void }) {
  // No token yet, by definition. The route ignores the bearer header this client still sends.
  const client = useMemo(
    () => new KiraClient({ baseUrl: localStorage.getItem("kira.base") ?? "", token: "" }),
    [],
  );
  const [code, setCode] = useState(codeFromHash);
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function pair(event: FormEvent) {
    event.preventDefault();
    const device = name.trim();
    if (!device) {
      setError("name this device, so the desktop can tell it apart from the others");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const answer = await client.pair(clean(code), device);
      onPaired(answer.token);
    } catch (caught) {
      setError(messageOf(caught));
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="gate">
      <form className="gate-card" onSubmit={(event) => void pair(event)}>
        <h1>Pair this device</h1>
        <p className="muted">
          Type the name you want this phone to have. The desktop shows the code; it works once and dies after
          two minutes.
        </p>
        <label>
          pairing code
          <input
            name="pairing_code"
            value={code}
            onChange={(event) => setCode(clean(event.target.value))}
            autoComplete="one-time-code"
            spellCheck={false}
            autoFocus
          />
        </label>
        <label>
          device name
          <input
            name="device_name"
            value={name}
            onChange={(event) => setName(event.target.value)}
            placeholder="phone"
            maxLength={40}
          />
        </label>
        <button type="submit" disabled={busy}>
          {busy ? "pairing…" : "pair"}
        </button>
        {error && (
          <p className="error" role="alert">
            {error}
          </p>
        )}
        <p className="muted small">
          The token this returns stays in this browser. Every change — keys, memory, deletions — still needs
          the confirm secret, which only exists on the desktop.
        </p>
      </form>
    </main>
  );
}
