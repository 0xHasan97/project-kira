import { useEffect, useState } from "react";
import type { FormEvent } from "react";
import type { KiraClient } from "../api.ts";
import type { StudioFile, StudioModelRow, StudioRuntime, StudioVoice } from "../contracts.ts";
import { useAsync } from "../useAsync.ts";
import { useWrite } from "../useWrite.ts";

function messageOf(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

/** The studio server: what is running, whose process it is, and the one button that changes it. */
export function StudioRuntimeCard({
  client,
  runtime,
  loading,
  refresh,
  onChanged,
}: {
  client: KiraClient;
  runtime: StudioRuntime | null;
  loading: boolean;
  refresh: () => void;
  onChanged?: () => void;
}) {
  const { busy, note, run } = useWrite(refresh);

  function start() {
    void run(
      "start the Portable AI Studio server",
      "It runs on loopback only and is stopped when Kira exits. Transcription, voice and the model manager are its routes.",
      false,
      async (secret) => {
        await client.startStudioApp(secret);
        onChanged?.();
      },
    );
  }

  function stop() {
    void run(
      "stop the studio server",
      "The child process ends. A studio you started yourself is left alone.",
      true,
      async (secret) => {
        await client.stopStudioApp(secret);
        onChanged?.();
      },
    );
  }

  return (
    <section className="studio-card" aria-label="Studio server">
      <header>
        <h3>Studio server</h3>
        <span className={runtime?.running ? "badge-ok" : "badge-off"}>
          {loading ? "…" : runtime?.running ? "running" : "stopped"}
        </span>
      </header>
      {loading ? (
        <p className="muted small">reading the studio server…</p>
      ) : runtime?.running ? (
        <>
          <p>
            Whisper, Kokoro and the four model folders answer at{" "}
            <span className="mono">{runtime.url}</span>.
            {runtime.managed ? " Kira started this process and stops it when the engine exits." : " This process belongs to another launcher."}
          </p>
          {runtime.health && (
            <p className="muted small">
              build <span className="mono">{runtime.health.build ?? "unknown"}</span>
              {runtime.health.issues.length > 0 && <> · {runtime.health.issues.length} issue(s)</>}
            </p>
          )}
          {runtime.managed && <button type="button" disabled={busy} onClick={stop}>stop studio server</button>}
        </>
      ) : (
        <>
          <p className="muted small">
            The studio server is the local API behind transcription, voice, downloads and the hardware report.
            Kira only starts it when you ask.
          </p>
          <button type="button" disabled={busy || !runtime?.found} onClick={start}>start studio server</button>
          {runtime && !runtime.found && (
            <p className="muted small">No studio folder was found; set <span className="mono">KIRA_STUDIO_DIR</span>.</p>
          )}
        </>
      )}
      {runtime?.error && <p className="error">{runtime.error}</p>}
      {note && <p className="error">{note}</p>}
    </section>
  );
}

type Panel = "transcribe" | "voice" | "models" | "diagnostics";

/** Every studio tool the chat app does not already own: whisper, Kokoro, the folders, the report. */
export function StudioTools({ client, running }: { client: KiraClient; running: boolean }) {
  const [panel, setPanel] = useState<Panel>("transcribe");
  if (!running) {
    return (
      <p className="muted">
        Start the studio server above to transcribe audio, speak with Kokoro, manage models or read the hardware report.
      </p>
    );
  }
  return (
    <section aria-label="Studio tools">
      <div className="segmented" role="tablist">
        {(["transcribe", "voice", "models", "diagnostics"] as Panel[]).map((name) => (
          <button
            key={name}
            type="button"
            role="tab"
            aria-selected={panel === name}
            onClick={() => setPanel(name)}
          >
            {name}
          </button>
        ))}
      </div>
      {panel === "transcribe" && <TranscribePanel client={client} />}
      {panel === "voice" && <VoicePanel client={client} />}
      {panel === "models" && <ModelsPanel client={client} />}
      {panel === "diagnostics" && <DiagnosticsPanel client={client} />}
    </section>
  );
}

function TranscribePanel({ client }: { client: KiraClient }) {
  const [file, setFile] = useState<File | null>(null);
  const [model, setModel] = useState("");
  const [text, setText] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const models = useAsync(() => client.studioGet<{ models: StudioModelRow[] }>("/api/speech/models"), []);
  const history = useAsync(
    () => client.studioGet<{ transcriptions: StudioFile[] }>("/api/speech/transcriptions"),
    [text],
  );
  const installed = models.kind === "ready" ? models.data.models.filter((row) => row.installed !== false) : [];
  const chosen = model || installed[0]?.filename || "";

  async function transcribe(event: FormEvent) {
    event.preventDefault();
    if (!file) return;
    setBusy(true);
    setError(null);
    try {
      const query = new URLSearchParams({ filename: file.name, language: "auto", model: chosen });
      const answer = await client.studioUpload<{ transcription: { text: string } }>(
        `/api/speech/transcribe?${query}`,
        file,
      );
      setText(answer.transcription.text);
    } catch (failure) {
      setError(messageOf(failure));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="studio-card" aria-label="Transcribe">
      <h3>Transcribe audio</h3>
      <p className="muted small">whisper.cpp takes a 16 kHz WAV. The transcript is saved in the studio, and every word stays on this machine.</p>
      <form className="image-form" onSubmit={transcribe}>
        <div className="image-row">
          <label>
            WAV file
            <input type="file" accept=".wav,audio/wav" onChange={(event) => setFile(event.target.files?.[0] ?? null)} />
          </label>
          <label>
            model
            <select value={chosen} onChange={(event) => setModel(event.target.value)}>
              {installed.map((row) => (
                <option key={row.filename} value={row.filename}>{row.filename} · {row.size ?? ""}</option>
              ))}
            </select>
          </label>
        </div>
        <button type="submit" disabled={busy || !file || !chosen}>transcribe</button>
      </form>
      {models.kind === "ready" && installed.length === 0 && (
        <p className="muted small">No whisper model is installed; the studio's models tab and the download form below can fetch one.</p>
      )}
      {error && <p className="error">{error}</p>}
      {text !== null && (
        <div className="studio-transcript">
          <h4>Transcript</h4>
          <p>{text || "(silence)"}</p>
        </div>
      )}
      {history.kind === "ready" && history.data.transcriptions.length > 0 && (
        <>
          <h4>Recent transcripts</h4>
          <table className="grid">
            <thead><tr><th>file</th><th>text</th></tr></thead>
            <tbody>
              {history.data.transcriptions.slice(0, 6).map((row) => (
                <tr key={row.filename}>
                  <td className="mono">{row.displayName ?? row.filename}</td>
                  <td>{row.text?.slice(0, 90) ?? ""}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}
    </section>
  );
}

function VoicePanel({ client }: { client: KiraClient }) {
  const [text, setText] = useState("");
  const [voice, setVoice] = useState("");
  const [audioUrl, setAudioUrl] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const voices = useAsync(() => client.studioGet<{ voices: StudioVoice[] }>("/api/tts/status"), []);
  const outputs = useAsync(() => client.studioGet<{ outputs: StudioFile[] }>("/api/tts/outputs"), [audioUrl]);
  const { note, run } = useWrite(outputs.refresh);
  const available = voices.kind === "ready" ? voices.data.voices : [];
  const chosen = voice || available[0]?.id || "";

  useEffect(() => {
    return () => {
      if (audioUrl) URL.revokeObjectURL(audioUrl);
    };
  }, [audioUrl]);

  async function speak(event: FormEvent) {
    event.preventDefault();
    if (!text.trim()) return;
    setBusy(true);
    setError(null);
    try {
      const answer = await client.studioPost<{ output: StudioFile }>("/api/tts/speak", {
        text: text.trim(),
        voice: chosen,
        speed: 1,
      });
      const blob = await client.studioBlob(answer.output.url);
      setAudioUrl(URL.createObjectURL(blob));
    } catch (failure) {
      setError(messageOf(failure));
    } finally {
      setBusy(false);
    }
  }

  function forget(filename: string) {
    void run(
      "delete this clip",
      "The WAV and its metadata leave the studio outputs folder.",
      true,
      async (secret) => {
        await client.studioPost("/api/tts/delete-output", { filename }, secret);
      },
    );
  }

  return (
    <section className="studio-card" aria-label="Voice">
      <h3>Speak with Kokoro</h3>
      <form className="image-form" onSubmit={speak}>
        <label>
          text
          <textarea value={text} onChange={(event) => setText(event.target.value)} rows={4} />
        </label>
        <div className="image-row">
          <label>
            voice
            <select value={chosen} onChange={(event) => setVoice(event.target.value)}>
              {available.map((row) => (
                <option key={row.id} value={row.id}>{row.name} · {row.language} · {row.gender}</option>
              ))}
            </select>
          </label>
        </div>
        <button type="submit" disabled={busy || !text.trim() || !chosen}>speak</button>
      </form>
      {voices.kind === "ready" && available.length === 0 && (
        <p className="muted small">No Kokoro voice answered; the first run downloads its ONNX model into the studio's tts-cache.</p>
      )}
      {audioUrl && <audio controls src={audioUrl} />}
      {error && <p className="error">{error}</p>}
      {outputs.kind === "ready" && outputs.data.outputs.length > 0 && (
        <>
          <h4>Recent clips</h4>
          <table className="grid">
            <thead><tr><th>clip</th><th>text</th><th /></tr></thead>
            <tbody>
              {outputs.data.outputs.slice(0, 6).map((row) => (
                <tr key={row.filename}>
                  <td className="mono">{row.displayName ?? row.filename}</td>
                  <td>{row.text?.slice(0, 70) ?? ""}</td>
                  <td><button type="button" onClick={() => forget(row.filename)}>delete</button></td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}
      {note && <p className="error">{note}</p>}
    </section>
  );
}

function ModelsPanel({ client }: { client: KiraClient }) {
  const images = useAsync(() => client.studioGet<{ models: StudioModelRow[] }>("/api/models"), []);
  const llm = useAsync(() => client.studioGet<{ models: StudioModelRow[] }>("/api/llm/models"), []);
  const speech = useAsync(() => client.studioGet<{ models: StudioModelRow[] }>("/api/speech/models"), []);
  const tts = useAsync(() => client.studioGet<{ models: StudioModelRow[] }>("/api/tts/models"), []);
  const refreshAll = () => {
    images.refresh();
    llm.refresh();
    speech.refresh();
    tts.refresh();
  };
  const { busy, note, run } = useWrite(refreshAll);

  function remove(target: string, filename: string) {
    void run(
      `delete ${filename}`,
      "The file leaves the studio folder. A running engine that holds it is stopped first.",
      true,
      async (secret) => {
        await client.studioPost(target, { filename }, secret);
      },
    );
  }

  const groups: { title: string; target: string; state: typeof images }[] = [
    { title: "Image checkpoints", target: "/api/delete-model", state: images },
    { title: "Chat models", target: "/api/llm/delete-model", state: llm },
    { title: "Whisper models", target: "/api/speech/delete-model", state: speech },
    { title: "Kokoro manifests", target: "/api/tts/delete-model", state: tts },
  ];

  return (
    <section className="studio-card" aria-label="Models">
      <h3>Installed models</h3>
      <p className="muted small">What the studio loads. The download card below writes into Kira, not here.</p>
      {groups.map(({ title, target, state }) => (
        <div key={title}>
          <h4>{title}</h4>
          {state.kind === "loading" && <p className="muted small">reading…</p>}
          {state.kind === "error" && <p className="error">{messageOf(state.error)}</p>}
          {state.kind === "ready" && state.data.models.length === 0 && <p className="empty">none</p>}
          {state.kind === "ready" && state.data.models.length > 0 && (
            <table className="grid">
              <thead><tr><th>file</th><th>size</th><th /></tr></thead>
              <tbody>
                {state.data.models.map((row) => (
                  <tr key={row.filename}>
                    <td className="mono">{row.filename}</td>
                    <td>{row.size ?? (row.sizeBytes ? `${Math.round(row.sizeBytes / 1048576)} MB` : "")}</td>
                    <td>
                      <button type="button" disabled={busy} onClick={() => remove(target, row.filename)}>
                        delete
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      ))}
      {note && <p className="error">{note}</p>}
    </section>
  );
}

function DiagnosticsPanel({ client }: { client: KiraClient }) {
  const health = useAsync(
    () => client.studioGet<{
      build?: string;
      issues?: string[];
      checks?: { label: string; ok: boolean; path?: string }[];
      models?: { count: number; totalSize: string };
    }>("/api/health"),
    [],
  );
  const backend = useAsync(
    () => client.studioGet<{ ready: boolean; running: boolean; error?: string | null; settings?: { backendType?: string; model?: string | null } }>("/api/backend-status"),
    [],
  );
  return (
    <section className="studio-card" aria-label="Diagnostics">
      <h3>Hardware and readiness</h3>
      {health.kind === "error" && <p className="error">{messageOf(health.error)}</p>}
      {health.kind === "ready" && (
        <>
          <p>
            build <span className="mono">{health.data.build ?? "unknown"}</span>
            {health.data.models && <> · {health.data.models.count} checkpoints · {health.data.models.totalSize}</>}
          </p>
          {health.data.issues && health.data.issues.length > 0 ? (
            <ul className="error">{health.data.issues.map((issue) => <li key={issue}>{issue}</li>)}</ul>
          ) : <p className="muted small">No issues reported.</p>}
          {health.data.checks && (
            <table className="grid">
              <thead><tr><th>check</th><th>state</th><th>path</th></tr></thead>
              <tbody>
                {health.data.checks.map((row) => (
                  <tr key={row.label}>
                    <td>{row.label}</td>
                    <td>{row.ok ? "ok" : "missing"}</td>
                    <td className="mono small">{row.path ?? ""}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </>
      )}
      <h4>Image backend</h4>
      {backend.kind === "error" && <p className="error">{messageOf(backend.error)}</p>}
      {backend.kind === "ready" && (
        <p>
          {backend.data.running ? "running" : "stopped"} · backend{" "}
          <span className="mono">{backend.data.settings?.backendType ?? "auto"}</span>
          {backend.data.settings?.model && <> · model <span className="mono">{backend.data.settings.model}</span></>}
        </p>
      )}
      {backend.kind === "ready" && backend.data.error && <p className="error">{backend.data.error}</p>}
    </section>
  );
}
