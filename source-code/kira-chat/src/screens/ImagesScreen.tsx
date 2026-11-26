import { useEffect, useState } from "react";
import type { FormEvent } from "react";
import type { KiraClient } from "../api.ts";
import type { ImageOutput, ImagesStatus } from "../contracts.ts";
import { useAsync } from "../useAsync.ts";
import { useWrite } from "../useWrite.ts";

function messageOf(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

function when(iso: string): string {
  if (!iso) return "—";
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? iso : date.toLocaleString();
}

function size(bytes: number): string {
  const gb = bytes / (1024 * 1024 * 1024);
  return gb >= 1 ? `${gb.toFixed(1)} GB` : `${Math.max(1, Math.round(bytes / (1024 * 1024)))} MB`;
}

/**
 * A PNG under the bearer header. An `<img src>` cannot carry a token and a token in a URL is a
 * token in a log, so the bytes are fetched through the client and handed to the browser as a blob.
 * The object URL is revoked on unmount or when the name changes; a gallery that leaked one per
 * render would hold every image in memory for as long as the tab is open.
 */
function GalleryImage({ client, path, alt }: { client: KiraClient; path: string; alt: string }) {
  const [url, setUrl] = useState<string | null>(null);
  const [failure, setFailure] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    let objectUrl: string | null = null;
    setUrl(null);
    setFailure(null);
    client.bytes(path).then(
      (buffer) => {
        if (cancelled) return;
        objectUrl = URL.createObjectURL(new Blob([buffer], { type: "image/png" }));
        setUrl(objectUrl);
      },
      (error: unknown) => {
        if (!cancelled) setFailure(messageOf(error));
      },
    );
    return () => {
      cancelled = true;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [client, path]);

  if (failure) return <p className="error small">{failure}</p>;
  if (!url) return <p className="muted small">loading the image…</p>;
  return <img src={url} alt={alt} loading="lazy" />;
}

export function ImagesScreen({
  client,
  connected,
  pull = 0,
}: {
  client: KiraClient;
  connected: boolean;
  pull?: number;
}) {
  const status = useAsync(() => (connected ? client.images() : Promise.resolve(null)), [connected, pull]);
  const [prompt, setPrompt] = useState("");
  const [negative, setNegative] = useState("");
  const [model, setModel] = useState("");
  const [steps, setSteps] = useState(24);
  const [cfg, setCfg] = useState(7);
  const [width, setWidth] = useState(512);
  const [height, setHeight] = useState(512);
  const [seed, setSeed] = useState(-1);
  const [sampler, setSampler] = useState("euler_a");
  const [latest, setLatest] = useState<ImageOutput | null>(null);
  const { busy, note, run } = useWrite(status.refresh);

  const view: ImagesStatus | null = status.kind === "ready" ? status.data : null;
  const models = view?.models ?? [];
  const outputs = view?.outputs ?? [];
  const chosen = model || models[0]?.name || "";
  const ready = view?.ready === true;

  function generate(event: FormEvent) {
    event.preventDefault();
    const text = prompt.trim();
    if (!text) return;
    // A generation is a file written into the gallery, so it carries the same typed-secret gate as
    // every other bearer write. The dialog is also where a missing confirm secret is explained.
    void run(
      "draw this image",
      "The engine runs locally and adds the PNG and its settings to the Images gallery.",
      false,
      async (secret) => {
        const record = await client.generateImage(
          {
            prompt: text,
            negative_prompt: negative,
            model: chosen || null,
            steps,
            cfg_scale: cfg,
            width,
            height,
            seed,
            sampler,
          },
          secret,
        );
        setLatest(record);
      },
    );
  }

  if (status.kind === "loading") return <section className="screen"><p className="muted">reading the image workspace…</p></section>;
  if (status.kind === "error") {
    return (
      <section className="screen" aria-label="images">
        <h2>Images</h2>
        <p className="error">cannot read the image workspace: {messageOf(status.error)}</p>
      </section>
    );
  }

  return (
    <section className="screen" aria-label="images">
      <header className="screen-head">
        <h2>Images</h2>
        <span className="spacer" />
        <span className="muted small">{models.length} models · {outputs.length} in the gallery</span>
        <button type="button" onClick={status.refresh}>reload</button>
      </header>

      {!ready && (
        <div className="image-setup">
          <p className="empty">{view?.reason ?? "the image workspace is not configured"}</p>
          <p className="muted small">
            This is local only: nothing here downloads a model or calls a cloud service. Drop the
            stable-diffusion.cpp executable in <span className="mono">{view?.engine_dir}</span> and a
            checkpoint in <span className="mono">{view?.model_dir}</span>, or set{" "}
            <span className="mono">KIRA_SD_BACKEND</span> / <span className="mono">KIRA_SD_MODEL</span>.
            <span className="mono"> KIRA_SD_URL</span> points at a server you already run.
          </p>
          {models.length > 0 && (
            <table className="grid">
              <thead><tr><th>checkpoint</th><th>kind</th><th>size</th></tr></thead>
              <tbody>
                {models.map((entry) => (
                  <tr key={entry.filename}>
                    <td className="mono">{entry.filename}</td>
                    <td>{entry.kind}</td>
                    <td>{size(entry.size_bytes)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}

      {ready && (
        <form className="image-form" onSubmit={generate}>
          <label>
            prompt
            <textarea
              name="prompt"
              value={prompt}
              onChange={(event) => setPrompt(event.target.value)}
              rows={3}
              placeholder="a lantern-lit street after rain, 35mm"
            />
          </label>
          <label>
            negative
            <input
              name="negative_prompt"
              value={negative}
              onChange={(event) => setNegative(event.target.value)}
              placeholder="blurry, watermark"
            />
          </label>
          <div className="image-row">
            <label>
              checkpoint
              <select name="model" value={chosen} onChange={(event) => setModel(event.target.value)}>
                {models.map((entry) => (
                  <option key={entry.filename} value={entry.name}>
                    {entry.filename} · {size(entry.size_bytes)}
                  </option>
                ))}
              </select>
            </label>
            <label>
              sampler
              <input name="sampler" value={sampler} onChange={(event) => setSampler(event.target.value)} />
            </label>
            <label>
              seed
              <input name="seed" type="number" value={seed} onChange={(event) => setSeed(Number(event.target.value))} />
            </label>
          </div>
          <div className="image-row">
            <label>
              width
              <input name="width" type="number" min={64} max={2048} step={8} value={width} onChange={(event) => setWidth(Number(event.target.value))} />
            </label>
            <label>
              height
              <input name="height" type="number" min={64} max={2048} step={8} value={height} onChange={(event) => setHeight(Number(event.target.value))} />
            </label>
            <label>
              steps
              <input name="steps" type="number" min={1} max={150} value={steps} onChange={(event) => setSteps(Number(event.target.value))} />
            </label>
            <label>
              cfg
              <input name="cfg_scale" type="number" min={0} max={30} step={0.5} value={cfg} onChange={(event) => setCfg(Number(event.target.value))} />
            </label>
          </div>
          <p className="muted small">
            {view?.backend === "remote"
              ? <>drawing on the server at <span className="mono">{view.remote_url}</span></>
              : <>drawing with <span className="mono">{view?.backend_path}</span></>}
            {" · "}the picture is saved next to a JSON sidecar in <span className="mono">{view?.output_dir}</span>
          </p>
          <button type="submit" disabled={busy || !prompt.trim()}>
            {busy ? "drawing (this can take minutes)…" : "generate"}
          </button>
          {note && <p className="error">{note}</p>}
        </form>
      )}

      {latest && (
        <figure className="image-latest">
          <GalleryImage client={client} path={latest.url} alt={latest.prompt} />
          <figcaption>
            <span className="mono">{latest.name}</span> · {latest.width}×{latest.height} · {latest.steps} steps · cfg{" "}
            {latest.cfg_scale} · seed <span className="mono">{latest.seed}</span> · {latest.sampler} ·{" "}
            {(latest.duration_ms / 1000).toFixed(1)}s
          </figcaption>
        </figure>
      )}

      <h3>Gallery</h3>
      {outputs.length === 0 ? (
        <p className="empty">nothing drawn yet — every generation lands here, with the settings that made it.</p>
      ) : (
        <div className="image-grid">
          {outputs.map((output) => (
            <figure key={output.name} className="image-card">
              <GalleryImage client={client} path={output.url} alt={output.prompt || output.name} />
              <figcaption>
                <span className="mono">{output.name}</span>
                <div className="muted small">
                  {output.width}×{output.height} · seed {output.seed} · {when(output.created_at)}
                </div>
                <p className="small">{output.prompt}</p>
                <button
                  type="button"
                  disabled={busy}
                  onClick={() =>
                    void run(
                      `delete ${output.name}`,
                      "The PNG and its sidecar are removed from the gallery. This cannot be undone.",
                      true,
                      (secret) => client.deleteImage(output.name, secret),
                    )
                  }
                >
                  delete
                </button>
              </figcaption>
            </figure>
          ))}
        </div>
      )}
    </section>
  );
}
