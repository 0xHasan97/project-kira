import { useState } from "react";
import type { KiraClient } from "../api.ts";
import { useConfirm } from "../confirm.tsx";
import type { DeviceInfo, PairingCodeResponse } from "../contracts.ts";
import { useAsync } from "../useAsync.ts";

const PUBLIC_KEY = "kira.public";
const EMPTY = { devices: [] as DeviceInfo[] };

function messageOf(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

/** Unix seconds as a stable local stamp — the row says when, not "a while ago". */
function when(seconds: number): string {
  return new Date(seconds * 1000).toISOString().slice(0, 16).replace("T", " ");
}

export function RemoteScreen({
  client,
  connected,
  pull = 0,
}: {
  client: KiraClient;
  connected: boolean;
  /** Rises when the rail's refresh is pressed; a phone's pairing cannot call back into this tab. */
  pull?: number;
}) {
  const confirm = useConfirm();
  const devices = useAsync(() => (connected ? client.devices() : Promise.resolve(EMPTY)), [connected, pull]);
  const [publicBase, setPublicBase] = useState(() => localStorage.getItem(PUBLIC_KEY) ?? "");
  const [code, setCode] = useState<PairingCodeResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  const linkBase = (publicBase.trim() || window.location.origin).replace(/\/$/, "");
  const link = code ? `${linkBase}/chat/#/pair?code=${code.code}` : "";

  function rememberPublic(value: string) {
    setPublicBase(value);
    if (value.trim()) localStorage.setItem(PUBLIC_KEY, value.trim());
    else localStorage.removeItem(PUBLIC_KEY);
  }

  async function mint() {
    setError(null);
    const secret = await confirm({
      summary: "make a pairing code",
      detail: "a phone with this code can read and chat for 120 seconds; every write still needs this secret",
    });
    if (!secret) return;
    try {
      setCode(await client.pairingCode(secret));
      setCopied(false);
    } catch (caught) {
      setError(messageOf(caught));
    }
  }

  async function revoke(device: DeviceInfo) {
    const secret = await confirm({
      summary: `revoke ${device.name}`,
      detail: "its token stops authenticating on the next request",
      danger: true,
    });
    if (!secret) return;
    try {
      await client.revokeDevice(device.id, secret);
      devices.refresh();
    } catch (caught) {
      setError(messageOf(caught));
    }
  }

  async function copy() {
    if (!navigator.clipboard) return;
    await navigator.clipboard.writeText(link);
    setCopied(true);
  }

  return (
    <section className="screen" aria-label="remote">
      <h2>Remote</h2>
      <p className="muted">
        The engine listens on 127.0.0.1 only — nothing here opens a port. Run a tunnel on this machine
        (Tailscale Serve or <span className="mono">cloudflared</span>), point it at 127.0.0.1:8901, and put the
        address it gives you below. A phone needs HTTPS before it will hand out a microphone, which is why the
        call screen stays desktop-only otherwise.
      </p>

      <label>
        public address
        <input
          name="public_address"
          value={publicBase}
          onChange={(event) => rememberPublic(event.target.value)}
          placeholder={window.location.origin}
          spellCheck={false}
        />
      </label>

      <div className="remote-actions">
        <button type="button" onClick={() => void mint()}>
          make a pairing code
        </button>
        {code && (
          <>
            <output className="pairing-code mono">{code.code}</output>
            <span className="muted small">good until {when(code.expires_at)}</span>
          </>
        )}
      </div>

      {code && (
        <p className="pairing-link">
          <a className="mono" href={link}>
            {link}
          </a>{" "}
          <button type="button" onClick={() => void copy()}>
            {copied ? "copied" : "copy link"}
          </button>
        </p>
      )}

      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}

      <h3>paired devices</h3>
      {devices.kind === "loading" ? <p className="muted">reading the device list…</p> : null}
      {devices.kind === "error" ? (
        <p className="error" role="alert">
          cannot read the device list: {messageOf(devices.error)}
        </p>
      ) : null}
      {devices.kind === "ready" &&
        (devices.data.devices.length === 0 ? (
          <p className="empty">no device has paired yet — a code above is how one joins.</p>
        ) : (
          <table className="grid">
            <thead>
              <tr>
                <th>device</th>
                <th>paired</th>
                <th>last seen</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {devices.data.devices.map((device) => (
                <tr key={device.id}>
                  <td className="mono">{device.name}</td>
                  <td className="muted mono">{when(device.created_at)}</td>
                  <td className="muted mono">{when(device.last_seen_at)}</td>
                  <td>
                    <button type="button" onClick={() => void revoke(device)}>
                      {`revoke ${device.name}`}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        ))}

      <p className="muted small">
        A paired device gets its own token — it reads and chats, and the engine stores only a hash of it.
        Changes (keys, memory, deletions, tool policies) still ask for the confirm secret, which never leaves
        this desktop.
      </p>
    </section>
  );
}
