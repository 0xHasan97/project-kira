import { useState } from "react";
import type { FormEvent } from "react";
import type { KiraClient } from "../api.ts";
import type { StudioDownloadResult, StudioPart, StudioStatus } from "../contracts.ts";
import { useAsync } from "../useAsync.ts";
import { useWrite } from "../useWrite.ts";
import { StudioRuntimeCard, StudioTools } from "./StudioTools.tsx";

function messageOf(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

function size(bytes: number): string {
  const gb = bytes / (1024 * 1024 * 1024);
  if (gb >= 1) return `${gb.toFixed(1)} GB`;
  return `${Math.max(1, Math.round(bytes / (1024 * 1024)))} MB`;
}

function PartCard({ title, part, empty }: { title: string; part: StudioPart; empty: string }) {
  return (
    <section className="studio-card" aria-label={title}>
      <header>
        <h3>{title}</h3>
        <span className={part.available ? "badge-ok" : "badge-off"}>{part.available ? "ready" : "missing"}</span>
      </header>
      <p className="muted small">{part.detail || empty}</p>
      {part.engine && <p className="mono small">{part.engine}</p>}
      {part.models.length > 0 && (
        <table className="grid">
          <thead><tr><th>model</th><th>size</th></tr></thead>
          <tbody>
            {part.models.slice(0, 12).map((model) => (
              <tr key={`${model.kind}:${model.filename}`}>
                <td className="mono"><span className="studio-model" title={model.filename}>{model.filename}</span></td>
                <td>{size(model.size_bytes)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {part.models.length > 12 && <p className="muted small">{part.models.length - 12} more…</p>}
    </section>
  );
}

export function StudioScreen({
  client,
  connected,
  pull = 0,
  onChanged,
}: {
  client: KiraClient;
  connected: boolean;
  pull?: number;
  onChanged?: () => void;
}) {
  const state = useAsync(() => (connected ? client.studio() : Promise.resolve(null)), [connected, pull]);
  // The studio's own Node server is a separate read: it can be down while the folders are present.
  const runtime = useAsync(() => (connected ? client.studioRuntime() : Promise.resolve(null)), [connected, pull]);
  const [llmModel, setLlmModel] = useState("");
  const [kind, setKind] = useState<"llm" | "image" | "stt">("llm");
  const [url, setUrl] = useState("");
  const [downloaded, setDownloaded] = useState<StudioDownloadResult | null>(null);
  const { busy, note, run } = useWrite(state.refresh);

  const view: StudioStatus | null = state.kind === "ready" ? state.data : null;
  const llm = view?.llm;
  const chosen = llmModel || llm?.models[0]?.name || "";

  function startLlm(event: FormEvent) {
    event.preventDefault();
    void run(
      "start the local model",
      "llama-server runs on loopback and joins the router as a keyless provider until you stop it.",
      false,
      async (secret) => {
        await client.startStudioLlm(chosen || null, secret);
        onChanged?.();
      },
    );
  }

  function stopLlm() {
    void run(
      "stop the local model",
      "The child process ends and its models leave the picker. Chat falls back to the other providers.",
      true,
      async (secret) => {
        await client.stopStudioLlm(secret);
        onChanged?.();
      },
    );
  }

  function download(event: FormEvent) {
    event.preventDefault();
    if (!url.trim()) return;
    setDownloaded(null);
    void run(
      "download this model",
      "The file is written into Kira's data folder, not into the studio. A partial download leaves no file.",
      false,
      async (secret) => {
        const result = await client.downloadStudioModel({ kind, url: url.trim(), filename: null }, secret);
        setDownloaded(result);
        onChanged?.();
      },
    );
  }

  if (state.kind === "loading") return <section className="screen"><p className="muted">reading the local studio…</p></section>;
  if (state.kind === "error") {
    return (
      <section className="screen" aria-label="studio">
        <h2>Studio</h2>
        <p className="error">cannot read the studio: {messageOf(state.error)}</p>
      </section>
    );
  }

  return (
    <section className="screen" aria-label="studio">
      <header className="screen-head">
        <h2>Studio</h2>
        <span className="spacer" />
        <span className="muted small">{view?.available ? "Portable AI Studio found" : "Kira folders only"}</span>
        <button type="button" onClick={state.refresh}>reload</button>
      </header>

      <p className="muted">
        {view?.root ? (
          <>The local runtimes come from <span className="mono">{view.root}</span>. Nothing here downloads
          a model on its own, and none of it leaves this machine.</>
        ) : (
          <>No Portable AI Studio folder was found. Kira still reads its own <span className="mono">images</span>,{" "}
          <span className="mono">llm</span> and <span className="mono">voice</span> folders; put a studio beside
          the project, or set <span className="mono">KIRA_STUDIO_DIR</span>.</>
        )}
      </p>

      <StudioRuntimeCard
        client={client}
        runtime={runtime.kind === "ready" ? runtime.data : null}
        loading={runtime.kind === "loading"}
        refresh={runtime.refresh}
        onChanged={onChanged}
      />

      <StudioTools client={client} running={runtime.kind === "ready" && runtime.data?.running === true} />

      <section className="studio-card" aria-label="Local chat">
        <header>
          <h3>Local chat</h3>
          <span className={llm?.running ? "badge-ok" : "badge-off"}>{llm?.running ? "running" : "stopped"}</span>
        </header>
        {llm?.running ? (
          <>
            <p>
              <span className="mono">{llm.model}</span> is serving at <span className="mono">{llm.url}</span>.
              It is in the model picker as <span className="mono">local_llama</span>; press refresh in the rail
              if the list predates this start.
            </p>
            <button type="button" disabled={busy} onClick={stopLlm}>stop local model</button>
          </>
        ) : (
          <form className="image-form" onSubmit={startLlm}>
            {llm && llm.models.length > 0 ? (
              <label>
                GGUF model
                <select name="llm_model" value={chosen} onChange={(event) => setLlmModel(event.target.value)}>
                  {llm.models.map((model) => (
                    <option key={model.filename} value={model.name}>
                      {model.filename} · {size(model.size_bytes)}
                    </option>
                  ))}
                </select>
              </label>
            ) : (
              <p className="empty">{llm?.reason ?? "no GGUF model is installed"}</p>
            )}
            <p className="muted small">
              Engine: <span className="mono">{llm?.engine ?? "none"}</span> · models:{" "}
              <span className="mono">{llm?.model_dir}</span>
            </p>
            <button type="submit" disabled={busy || !chosen}>start local model</button>
          </form>
        )}
      </section>

      <div className="studio-grid">
        {view && <PartCard title="Images" part={view.image} empty="no stable-diffusion.cpp engine" />}
        {view && <PartCard title="Speech to text" part={view.stt} empty="no whisper.cpp engine" />}
        {view && <PartCard title="Text to speech" part={view.tts} empty="no Kokoro runtime" />}
      </div>

      <section className="studio-card" aria-label="Model download">
        <h3>Download a model</h3>
        <p className="muted small">
          Paste a Hugging Face file link. Only <span className="mono">llm</span> (GGUF),{" "}
          <span className="mono">image</span> (safetensors, ckpt, gguf) and <span className="mono">stt</span>{" "}
          (bin) files are accepted, and the server enforces a byte ceiling.
        </p>
        <form className="image-form" onSubmit={download}>
          <div className="image-row">
            <label>
              kind
              <select name="kind" value={kind} onChange={(event) => setKind(event.target.value as typeof kind)}>
                <option value="llm">llm</option>
                <option value="image">image</option>
                <option value="stt">stt</option>
              </select>
            </label>
            <label>
              file URL
              <input
                name="url"
                value={url}
                onChange={(event) => setUrl(event.target.value)}
                placeholder="https://huggingface.co/…/model.gguf"
              />
            </label>
          </div>
          <button type="submit" disabled={busy || !url.trim()}>download</button>
          {downloaded && (
            <p className="muted small">
              saved <span className="mono">{downloaded.filename}</span> · {size(downloaded.bytes)} ·{" "}
              <span className="mono">{downloaded.path}</span>
            </p>
          )}
        </form>
      </section>

      {note && <p className="error">{note}</p>}
    </section>
  );
}
