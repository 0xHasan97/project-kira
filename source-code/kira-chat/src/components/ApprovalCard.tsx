import { useState } from "react";
import type { ApprovalChunk } from "../turn.ts";

const PREVIEW = 240;

/**
 * The stream is held open while this card is on screen, so the decision has to be sendable
 * here — the confirm dialog would unmount the turn that is waiting on it. Both directions
 * carry the secret because the engine's decision endpoint is a mutating call: a deny sent
 * without it comes back refused and the turn stays open, which is how the browser pass
 * found this.
 */
export function ApprovalCard({
  approval,
  onDecide,
}: {
  approval: ApprovalChunk;
  onDecide: (id: string, decision: "allow" | "deny", secret: string) => Promise<void>;
}) {
  const [secret, setSecret] = useState("");
  const [sent, setSent] = useState<"allow" | "deny" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const preview = JSON.stringify(approval.arguments, null, 2);

  async function decide(decision: "allow" | "deny") {
    try {
      await onDecide(approval.id, decision, secret);
      setSent(decision);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  if (sent) {
    return (
      <p className="approval-note">
        {approval.tool}: {sent === "allow" ? "allowed" : "denied"}
      </p>
    );
  }

  return (
    <div className="approval-card" role="group" aria-label={`approval for ${approval.tool}`}>
      <p className="work-meta">
        {approval.tool} · {approval.risk} · needs permission
      </p>
      <pre className="work-json">{preview.length > PREVIEW ? `${preview.slice(0, PREVIEW)}…` : preview}</pre>
      <input
        aria-label="approval secret"
        type="password"
        value={secret}
        onChange={(event) => setSecret(event.target.value)}
        placeholder="confirm secret"
        autoComplete="off"
      />
      <button type="button" onClick={() => void decide("allow")} disabled={!secret.trim()}>
        allow
      </button>
      <button type="button" onClick={() => void decide("deny")} disabled={!secret.trim()}>
        deny
      </button>
      {error && <p className="error">{error}</p>}
    </div>
  );
}
