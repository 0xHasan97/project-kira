import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { FormEvent } from "react";
import {
  chatText,
  downloadMedia,
  loadPuter,
  mediaSrc,
  modelCost,
  puterError,
  transcriptText,
  PUTER_DEVELOPER_URL,
  type PuterChatChunk,
  type PuterChatMessage,
  type PuterModel,
  type PuterRealtimeConversation,
  type PuterSdk,
  type PuterTtsEngine,
  type PuterUser,
  type PuterVoice,
} from "../puter.ts";
import "../puter.css";

type Tab = "chat" | "image" | "speech" | "vision" | "video" | "realtime" | "models";

const TABS: readonly { id: Tab; label: string }[] = [
  { id: "chat", label: "chat" },
  { id: "image", label: "images" },
  { id: "speech", label: "speech" },
  { id: "vision", label: "vision" },
  { id: "video", label: "video" },
  { id: "realtime", label: "realtime" },
  { id: "models", label: "models" },
];

const TTS_PROVIDERS = ["aws-polly", "openai", "elevenlabs", "gemini", "xai", "speechify"] as const;
const STT_PROVIDERS = ["openai", "xai", "gemini"] as const;
const OCR_PROVIDERS = ["aws-textract", "mistral"] as const;
const REALTIME_MODELS = [
  "gpt-realtime-2.1-mini",
  "gpt-realtime-2.1",
  "gpt-realtime-2",
  "gpt-realtime-1.5",
  "gpt-realtime",
  "gpt-realtime-mini",
] as const;

function errorLine(error: string | null): React.ReactNode {
  return error ? (
    <p className="error small" role="alert">
      {error}
    </p>
  ) : null;
}

function TestToggle({
  checked,
  onChange,
  id,
}: {
  checked: boolean;
  onChange: (checked: boolean) => void;
  id: string;
}) {
  return (
    <label className="puter-check" htmlFor={id}>
      <input
        id={id}
        type="checkbox"
        checked={checked}
        onChange={(event) => onChange(event.target.checked)}
      />
      test mode
    </label>
  );
}

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <button
      type="button"
      disabled={!text}
      onClick={() => {
        const clipboard = navigator.clipboard;
        if (!clipboard) return;
        void clipboard.writeText(text).then(
          () => setCopied(true),
          () => setCopied(false),
        );
      }}
    >
      {copied ? "copied" : "copy"}
    </button>
  );
}

function MediaActions({ src, filename }: { src: string; filename: string }) {
  return (
    <div className="puter-actions">
      <a href={src} target="_blank" rel="noreferrer">
        open
      </a>
      <button type="button" onClick={() => downloadMedia(src, filename)}>
        download
      </button>
    </div>
  );
}

function FileChoice({
  label,
  accept,
  file,
  onFile,
}: {
  label: string;
  accept: string;
  file: File | null;
  onFile: (file: File | null) => void;
}) {
  return (
    <label className="puter-field">
      <span>{label}</span>
      <input
        type="file"
        accept={accept}
        onChange={(event) => onFile(event.target.files?.[0] ?? null)}
      />
      {file ? (
        <span className="muted small">
          {file.name} · {Math.max(1, Math.round(file.size / 1024))} KB
        </span>
      ) : null}
    </label>
  );
}

function ModelDatalist({ id, models }: { id: string; models: PuterModel[] }) {
  return (
    <datalist id={id}>
      {models.map((model) => {
        const value = model.puterId || model.id;
        return <option key={value} value={value} label={model.name || model.provider} />;
      })}
    </datalist>
  );
}

function ChatPanel({ puter, models }: { puter: PuterSdk; models: PuterModel[] }) {
  type Turn = { role: "user" | "assistant"; content: string };
  const [turns, setTurns] = useState<Turn[]>([]);
  const [draft, setDraft] = useState("");
  const [model, setModel] = useState("");
  const [testMode, setTestMode] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const abort = useRef<AbortController | null>(null);
  const thread = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    const node = thread.current;
    if (node) node.scrollTop = node.scrollHeight;
  }, [turns]);

  async function send(event: FormEvent) {
    event.preventDefault();
    const text = draft.trim();
    if (!text || busy) return;
    setError(null);
    const history: PuterChatMessage[] = [
      ...turns.map((turn) => ({ role: turn.role, content: turn.content })),
      { role: "user", content: text },
    ];
    setTurns([...turns, { role: "user", content: text }, { role: "assistant", content: "" }]);
    setDraft("");
    setBusy(true);
    const controller = new AbortController();
    abort.current = controller;
    const options: Record<string, unknown> = {
      stream: true,
      signal: controller.signal,
    };
    if (model.trim()) options.model = model.trim();
    try {
      const reply = testMode
        ? await puter.ai.chat(history, true, options)
        : await puter.ai.chat(history, options);
      let answer = "";
      const iterator = reply as AsyncIterable<PuterChatChunk>;
      if (iterator && typeof iterator[Symbol.asyncIterator] === "function") {
        for await (const chunk of iterator) {
          if (chunk.type === "error") throw new Error(puterError(chunk));
          if (chunk.type === "text" && chunk.text) {
            answer += chunk.text;
            const next = answer;
            setTurns((previous) => {
              const copy = [...previous];
              const last = copy[copy.length - 1];
              if (last?.role === "assistant") copy[copy.length - 1] = { ...last, content: next };
              return copy;
            });
          }
        }
      } else {
        answer = chatText(reply as Parameters<typeof chatText>[0]);
        setTurns((previous) => {
          const copy = [...previous];
          const last = copy[copy.length - 1];
          if (last?.role === "assistant") copy[copy.length - 1] = { ...last, content: answer };
          return copy;
        });
      }
      if (!answer.trim()) throw new Error("Puter returned an empty reply.");
    } catch (failure) {
      if (!controller.signal.aborted) setError(puterError(failure));
      setTurns((previous) => {
        const last = previous[previous.length - 1];
        return last?.role === "assistant" && !last.content ? previous.slice(0, -1) : previous;
      });
    } finally {
      abort.current = null;
      setBusy(false);
    }
  }

  return (
    <div className="puter-panel puter-chat-panel">
      <div className="puter-intro">
        <p>
          A direct Puter chat: more than 500 models, streamed through your own Puter account.
          Nothing here is stored by Kira.
        </p>
        <p className="muted small">
          The model is optional; leaving it blank lets Puter choose its current default.
        </p>
      </div>
      <div className="puter-thread" ref={thread} aria-label="Puter chat transcript">
        {turns.length === 0 ? (
          <p className="muted">Ask anything. The reply arrives from Puter, not from Kira's router.</p>
        ) : (
          turns.map((turn, index) => (
            <article className="puter-turn" data-role={turn.role} key={index}>
              <span className="puter-role">{turn.role}</span>
              <p>{turn.content || (busy && index === turns.length - 1 ? "…" : "")}</p>
            </article>
          ))
        )}
      </div>
      {errorLine(error)}
      <form className="puter-composer" onSubmit={send}>
        <textarea
          aria-label="message"
          rows={3}
          placeholder="Write a message for Puter…"
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter" && !event.shiftKey) {
              event.preventDefault();
              event.currentTarget.form?.requestSubmit();
            }
          }}
        />
        <div className="puter-actions">
          <label className="puter-field puter-model-field">
            <span>chat model</span>
            <input
              list="puter-chat-models"
              placeholder="Puter default"
              value={model}
              onChange={(event) => setModel(event.target.value)}
            />
          </label>
          <ModelDatalist id="puter-chat-models" models={models} />
          <TestToggle checked={testMode} onChange={setTestMode} id="puter-chat-test" />
          <span className="spacer" />
          {busy ? (
            <button type="button" onClick={() => abort.current?.abort()}>
              stop
            </button>
          ) : (
            <button type="submit" disabled={!draft.trim()}>
              send
            </button>
          )}
          <button
            type="button"
            disabled={busy || turns.length === 0}
            onClick={() => {
              setTurns([]);
              setError(null);
            }}
          >
            clear
          </button>
        </div>
      </form>
    </div>
  );
}

function ImagePanel({ puter }: { puter: PuterSdk }) {
  const [prompt, setPrompt] = useState("");
  const [model, setModel] = useState("");
  const [ratio, setRatio] = useState("1:1");
  const [testMode, setTestMode] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [src, setSrc] = useState<string | null>(null);
  const [alt, setAlt] = useState("");

  async function draw(event: FormEvent) {
    event.preventDefault();
    const text = prompt.trim();
    if (!text || busy) return;
    setBusy(true);
    setError(null);
    try {
      const options: Record<string, unknown> = {
        aspect_ratio: ratio,
        test_mode: testMode,
      };
      if (model.trim()) options.model = model.trim();
      const image = await puter.ai.txt2img(text, options);
      setSrc(mediaSrc(image));
      setAlt(text);
    } catch (failure) {
      setError(puterError(failure));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="puter-panel">
      <div className="puter-intro">
        <p>
          Text to image through Puter's image providers. The default model is Puter's current
          image model; test mode returns a sample without spending credits.
        </p>
      </div>
      <form className="puter-form" onSubmit={draw}>
        <label className="puter-field">
          <span>image prompt</span>
          <textarea
            aria-label="image prompt"
            rows={3}
            placeholder="A quiet greenhouse at dusk, soft rain on the glass…"
            value={prompt}
            onChange={(event) => setPrompt(event.target.value)}
          />
        </label>
        <div className="puter-grid">
          <label className="puter-field">
            <span>model (optional)</span>
            <input
              value={model}
              placeholder="Puter default"
              onChange={(event) => setModel(event.target.value)}
            />
          </label>
          <label className="puter-field">
            <span>aspect ratio</span>
            <select value={ratio} onChange={(event) => setRatio(event.target.value)}>
              <option value="1:1">1:1 square</option>
              <option value="16:9">16:9 landscape</option>
              <option value="9:16">9:16 portrait</option>
              <option value="4:3">4:3 landscape</option>
              <option value="3:4">3:4 portrait</option>
            </select>
          </label>
        </div>
        <div className="puter-actions">
          <TestToggle checked={testMode} onChange={setTestMode} id="puter-image-test" />
          <span className="spacer" />
          <button type="submit" disabled={busy || !prompt.trim()}>
            {busy ? "drawing…" : "generate"}
          </button>
        </div>
      </form>
      {errorLine(error)}
      {src ? (
        <figure className="puter-result puter-image-result">
          <img src={src} alt={alt} />
          <figcaption>
            <span className="muted small">Puter image · hosted URLs may expire</span>
            <MediaActions src={src} filename="puter-image.png" />
          </figcaption>
        </figure>
      ) : null}
    </div>
  );
}

function TextToSpeechPanel({ puter }: { puter: PuterSdk }) {
  const [text, setText] = useState("");
  const [provider, setProvider] = useState<string>("aws-polly");
  const [voice, setVoice] = useState("");
  const [model, setModel] = useState("");
  const [engine, setEngine] = useState("");
  const [language, setLanguage] = useState("en-US");
  const [format, setFormat] = useState("");
  const [instructions, setInstructions] = useState("");
  const [ssml, setSsml] = useState(false);
  const [testMode, setTestMode] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [src, setSrc] = useState<string | null>(null);
  const [voices, setVoices] = useState<PuterVoice[]>([]);
  const [models, setModels] = useState<PuterTtsEngine[]>([]);
  const [catalogNote, setCatalogNote] = useState<string | null>(null);

  async function loadCatalog() {
    setCatalogNote(null);
    const [voiceResult, engineResult] = await Promise.allSettled([
      puter.ai.txt2speech.listVoices({ provider }),
      puter.ai.txt2speech.listEngines(provider),
    ]);
    const nextVoices = voiceResult.status === "fulfilled" ? voiceResult.value : [];
    const nextModels = engineResult.status === "fulfilled" ? engineResult.value : [];
    setVoices(nextVoices);
    setModels(nextModels);
    const failure =
      voiceResult.status === "rejected"
        ? voiceResult.reason
        : engineResult.status === "rejected"
          ? engineResult.reason
          : null;
    setCatalogNote(
      failure
        ? puterError(failure)
        : nextVoices.length + " voices · " + nextModels.length + " models",
    );
  }

  async function speak(event: FormEvent) {
    event.preventDefault();
    const value = text.trim();
    if (!value || busy) return;
    setBusy(true);
    setError(null);
    try {
      const options: Record<string, unknown> = {
        provider,
        test_mode: testMode,
      };
      if (voice.trim()) options.voice = voice.trim();
      if (provider === "aws-polly") {
        if (engine.trim()) options.engine = engine.trim();
        if (language.trim()) options.language = language.trim();
        if (ssml) options.ssml = true;
      } else {
        if (model.trim()) options.model = model.trim();
        if (format.trim()) {
          options[provider === "openai" ? "response_format" : "output_format"] = format.trim();
        }
        if (instructions.trim() && (provider === "openai" || provider === "gemini")) {
          options.instructions = instructions.trim();
        }
        if (language.trim() && provider === "xai") options.language = language.trim();
      }
      const audio = await puter.ai.txt2speech(value, options);
      setSrc(mediaSrc(audio));
    } catch (failure) {
      setError(puterError(failure));
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="puter-form" onSubmit={speak}>
      <label className="puter-field">
        <span>words to speak</span>
        <textarea
          aria-label="words to speak"
          rows={4}
          maxLength={3000}
          placeholder="The evening train was late, and nobody minded."
          value={text}
          onChange={(event) => setText(event.target.value)}
        />
        <span className="muted small">{text.length} / 3,000 characters</span>
      </label>
      <div className="puter-grid">
        <label className="puter-field">
          <span>provider</span>
          <select
            value={provider}
            onChange={(event) => {
              setProvider(event.target.value);
              setVoice("");
              setModel("");
              setEngine("");
              setFormat("");
              setInstructions("");
              setSsml(false);
              setVoices([]);
              setModels([]);
              setCatalogNote(null);
            }}
          >
            {TTS_PROVIDERS.map((name) => (
              <option key={name} value={name}>
                {name}
              </option>
            ))}
          </select>
        </label>
        <label className="puter-field">
          <span>voice (optional)</span>
          <input
            list="puter-tts-voices"
            placeholder="provider default"
            value={voice}
            onChange={(event) => setVoice(event.target.value)}
          />
          <datalist id="puter-tts-voices">
            {voices.map((item) => (
              <option
                key={item.provider + ":" + item.id}
                value={item.id}
                label={item.name || item.provider || item.id}
              />
            ))}
          </datalist>
        </label>
        <label className="puter-field">
          <span>model (optional)</span>
          <input
            list="puter-tts-models"
            placeholder={provider === "openai" ? "gpt-4o-mini-tts" : "provider default"}
            value={model}
            disabled={provider === "aws-polly"}
            onChange={(event) => setModel(event.target.value)}
          />
          <datalist id="puter-tts-models">
            {models.map((item) => (
              <option key={item.id} value={item.id} label={item.name || item.id} />
            ))}
          </datalist>
        </label>
        <label className="puter-field">
          <span>AWS engine</span>
          <select
            value={engine}
            disabled={provider !== "aws-polly"}
            onChange={(event) => setEngine(event.target.value)}
          >
            <option value="">provider default</option>
            <option value="standard">standard</option>
            <option value="neural">neural</option>
            <option value="long-form">long-form</option>
            <option value="generative">generative</option>
          </select>
        </label>
        <label className="puter-field">
          <span>language</span>
          <input
            value={language}
            disabled={provider !== "aws-polly" && provider !== "xai"}
            onChange={(event) => setLanguage(event.target.value)}
          />
        </label>
        <label className="puter-field">
          <span>format (optional)</span>
          <input
            placeholder={
              provider === "aws-polly"
                ? "mp3 only"
                : provider === "openai"
                  ? "mp3, wav, opus, aac…"
                  : provider === "elevenlabs"
                    ? "mp3_44100_128"
                    : "mp3"
            }
            value={format}
            disabled={provider === "aws-polly"}
            onChange={(event) => setFormat(event.target.value)}
          />
        </label>
      </div>
      <label className="puter-field">
        <span>delivery instructions (OpenAI, Gemini)</span>
        <textarea
          rows={2}
          maxLength={3000}
          placeholder="Sound cheerful but not overly fast."
          value={instructions}
          disabled={provider !== "openai" && provider !== "gemini"}
          onChange={(event) => setInstructions(event.target.value)}
        />
      </label>
      <div className="puter-actions">
        <button type="button" onClick={() => void loadCatalog()}>
          list voices
        </button>
        {catalogNote ? <span className="muted small">{catalogNote}</span> : null}
        {provider === "aws-polly" ? (
          <label className="puter-check">
            <input
              type="checkbox"
              checked={ssml}
              onChange={(event) => setSsml(event.target.checked)}
            />
            SSML markup
          </label>
        ) : null}
        <TestToggle checked={testMode} onChange={setTestMode} id="puter-tts-test" />
        <span className="spacer" />
        <button type="submit" disabled={busy || !text.trim()}>
          {busy ? "speaking…" : "speak"}
        </button>
      </div>
      {errorLine(error)}
      {src ? (
        <div className="puter-result">
          <audio controls src={src} aria-label="Puter speech result" />
          <MediaActions src={src} filename="puter-speech.mp3" />
        </div>
      ) : null}
    </form>
  );
}

function TranscribePanel({ puter }: { puter: PuterSdk }) {
  const [file, setFile] = useState<File | null>(null);
  const [provider, setProvider] = useState<string>("openai");
  const [model, setModel] = useState("");
  const [language, setLanguage] = useState("");
  const [format, setFormat] = useState("");
  const [testMode, setTestMode] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [text, setText] = useState("");
  const [meta, setMeta] = useState("");

  async function transcribe(event: FormEvent) {
    event.preventDefault();
    if (!file || busy) return;
    setBusy(true);
    setError(null);
    setText("");
    setMeta("");
    try {
      const options: Record<string, unknown> = { provider, test_mode: testMode };
      if (model.trim()) options.model = model.trim();
      if (language.trim()) options.language = language.trim();
      if (format) options.response_format = format;
      const result = await puter.ai.speech2txt(file, options);
      setText(transcriptText(result));
      if (typeof result === "object" && result) {
        const facts = [result.model, result.language, result.duration ? result.duration + "s" : ""].filter(
          Boolean,
        );
        setMeta(facts.join(" · "));
      }
    } catch (failure) {
      setError(puterError(failure));
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="puter-form" onSubmit={transcribe}>
      <FileChoice label="audio file" accept="audio/*" file={file} onFile={setFile} />
      <div className="puter-grid">
        <label className="puter-field">
          <span>provider</span>
          <select value={provider} onChange={(event) => setProvider(event.target.value)}>
            {STT_PROVIDERS.map((name) => (
              <option key={name} value={name}>
                {name}
              </option>
            ))}
          </select>
        </label>
        <label className="puter-field">
          <span>model (optional)</span>
          <input
            placeholder="provider default"
            value={model}
            onChange={(event) => setModel(event.target.value)}
          />
        </label>
        <label className="puter-field">
          <span>language hint (optional)</span>
          <input
            placeholder="en"
            value={language}
            onChange={(event) => setLanguage(event.target.value)}
          />
        </label>
        <label className="puter-field">
          <span>response format</span>
          <select value={format} onChange={(event) => setFormat(event.target.value)}>
            <option value="">provider default</option>
            <option value="json">json</option>
            <option value="text">text</option>
            <option value="verbose_json">verbose json</option>
            <option value="srt">srt</option>
            <option value="vtt">vtt</option>
          </select>
        </label>
      </div>
      <div className="puter-actions">
        <TestToggle checked={testMode} onChange={setTestMode} id="puter-stt-test" />
        <span className="spacer" />
        <button type="submit" disabled={busy || !file}>
          {busy ? "transcribing…" : "transcribe"}
        </button>
      </div>
      {errorLine(error)}
      {text ? (
        <div className="puter-result">
          <div className="puter-result-head">
            <span className="muted small">transcript{meta ? " · " + meta : ""}</span>
            <CopyButton text={text} />
          </div>
          <pre className="puter-text">{text}</pre>
        </div>
      ) : null}
    </form>
  );
}

function RevoicePanel({ puter }: { puter: PuterSdk }) {
  const [file, setFile] = useState<File | null>(null);
  const [voice, setVoice] = useState("21m00Tcm4TlvDq8ikWAM");
  const [model, setModel] = useState("eleven_multilingual_sts_v2");
  const [noise, setNoise] = useState(false);
  const [testMode, setTestMode] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [src, setSrc] = useState<string | null>(null);

  async function revoice(event: FormEvent) {
    event.preventDefault();
    if (!file || busy) return;
    setBusy(true);
    setError(null);
    try {
      const options: Record<string, unknown> = {
        voice: voice.trim() || undefined,
        model,
        remove_background_noise: noise,
        test_mode: testMode,
      };
      const audio = await puter.ai.speech2speech(file, options);
      setSrc(mediaSrc(audio));
    } catch (failure) {
      setError(puterError(failure));
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="puter-form" onSubmit={revoice}>
      <FileChoice label="audio to revoice" accept="audio/*" file={file} onFile={setFile} />
      <div className="puter-grid">
        <label className="puter-field">
          <span>target voice</span>
          <input value={voice} onChange={(event) => setVoice(event.target.value)} />
        </label>
        <label className="puter-field">
          <span>model</span>
          <select value={model} onChange={(event) => setModel(event.target.value)}>
            <option value="eleven_multilingual_sts_v2">eleven_multilingual_sts_v2</option>
            <option value="eleven_english_sts_v2">eleven_english_sts_v2</option>
          </select>
        </label>
      </div>
      <div className="puter-actions">
        <label className="puter-check">
          <input
            type="checkbox"
            checked={noise}
            onChange={(event) => setNoise(event.target.checked)}
          />
          remove background noise
        </label>
        <TestToggle checked={testMode} onChange={setTestMode} id="puter-sts-test" />
        <span className="spacer" />
        <button type="submit" disabled={busy || !file}>
          {busy ? "revoicing…" : "revoice"}
        </button>
      </div>
      {errorLine(error)}
      {src ? (
        <div className="puter-result">
          <audio controls src={src} aria-label="Puter revoice result" />
          <MediaActions src={src} filename="puter-revoice.mp3" />
        </div>
      ) : null}
    </form>
  );
}

function SpeechPanel({ puter }: { puter: PuterSdk }) {
  const [mode, setMode] = useState<"tts" | "stt" | "revoice">("tts");
  return (
    <div className="puter-panel">
      <div className="puter-intro">
        <p>
          Speech synthesis, transcription and voice conversion. Each call uses Puter's provider
          selection and is billed to the signed-in account.
        </p>
      </div>
      <div className="segmented" role="tablist" aria-label="speech tool">
        <button
          type="button"
          role="tab"
          aria-selected={mode === "tts"}
          onClick={() => setMode("tts")}
        >
          text to speech
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={mode === "stt"}
          onClick={() => setMode("stt")}
        >
          transcribe
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={mode === "revoice"}
          onClick={() => setMode("revoice")}
        >
          revoice
        </button>
      </div>
      {mode === "tts" ? <TextToSpeechPanel puter={puter} /> : null}
      {mode === "stt" ? <TranscribePanel puter={puter} /> : null}
      {mode === "revoice" ? <RevoicePanel puter={puter} /> : null}
    </div>
  );
}

function VisionPanel({ puter }: { puter: PuterSdk }) {
  const [file, setFile] = useState<File | null>(null);
  const [url, setUrl] = useState("");
  const [provider, setProvider] = useState<string>("aws-textract");
  const [model, setModel] = useState("");
  const [testMode, setTestMode] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [text, setText] = useState("");
  const [preview, setPreview] = useState<string | null>(null);

  useEffect(() => {
    if (!file || !file.type.startsWith("image/") || typeof URL.createObjectURL !== "function") {
      setPreview(null);
      return;
    }
    const next = URL.createObjectURL(file);
    setPreview(next);
    return () => URL.revokeObjectURL(next);
  }, [file]);

  async function read(event: FormEvent) {
    event.preventDefault();
    const source = file || url.trim();
    if (!source || busy) return;
    setBusy(true);
    setError(null);
    setText("");
    try {
      const options: Record<string, unknown> = { provider, test_mode: testMode };
      if (model.trim()) options.model = model.trim();
      const result = await puter.ai.img2txt(source, options);
      setText(result);
    } catch (failure) {
      setError(puterError(failure));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="puter-panel">
      <div className="puter-intro">
        <p>
          Read an image or a document into text with Puter OCR. AWS Textract handles a single page;
          Mistral models also read PDFs, Office files and EPUB.
        </p>
      </div>
      <form className="puter-form" onSubmit={read}>
        <FileChoice
          label="image or document"
          accept="image/*,.pdf,.docx,.pptx,.xlsx,.epub,.rtf,.tif,.tiff"
          file={file}
          onFile={setFile}
        />
        <label className="puter-field">
          <span>or a URL</span>
          <input
            placeholder="https://…"
            value={url}
            onChange={(event) => setUrl(event.target.value)}
            disabled={Boolean(file)}
          />
        </label>
        {preview ? <img className="puter-preview" src={preview} alt="source preview" /> : null}
        <div className="puter-grid">
          <label className="puter-field">
            <span>provider</span>
            <select value={provider} onChange={(event) => setProvider(event.target.value)}>
              {OCR_PROVIDERS.map((name) => (
                <option key={name} value={name}>
                  {name}
                </option>
              ))}
            </select>
          </label>
          <label className="puter-field">
            <span>model (optional)</span>
            <input
              placeholder="provider default"
              value={model}
              onChange={(event) => setModel(event.target.value)}
            />
          </label>
        </div>
        <div className="puter-actions">
          <TestToggle checked={testMode} onChange={setTestMode} id="puter-ocr-test" />
          <span className="spacer" />
          <button type="submit" disabled={busy || (!file && !url.trim())}>
            {busy ? "reading…" : "read text"}
          </button>
        </div>
      </form>
      {errorLine(error)}
      {text ? (
        <div className="puter-result">
          <div className="puter-result-head">
            <span className="muted small">recognised text</span>
            <CopyButton text={text} />
          </div>
          <pre className="puter-text">{text}</pre>
        </div>
      ) : null}
    </div>
  );
}

function VideoPanel({ puter }: { puter: PuterSdk }) {
  const [prompt, setPrompt] = useState("");
  const [model, setModel] = useState("");
  const [seconds, setSeconds] = useState("5");
  const [size, setSize] = useState("1280x720");
  const [testMode, setTestMode] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [src, setSrc] = useState<string | null>(null);
  const [alt, setAlt] = useState("");

  async function make(event: FormEvent) {
    event.preventDefault();
    const text = prompt.trim();
    if (!text || busy) return;
    setBusy(true);
    setError(null);
    try {
      const options: Record<string, unknown> = { test_mode: testMode };
      if (model.trim()) options.model = model.trim();
      const length = Number(seconds);
      if (Number.isFinite(length) && length > 0) options.seconds = length;
      if (size !== "default") options.size = size;
      const video = await puter.ai.txt2vid(text, options);
      setSrc(mediaSrc(video));
      setAlt(text);
    } catch (failure) {
      setError(puterError(failure));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="puter-panel">
      <div className="puter-intro">
        <p>
          Text to video. Puter may wait up to 14 minutes for a provider, so leave this tab open
          while a clip renders; test mode returns a short sample instead.
        </p>
      </div>
      <form className="puter-form" onSubmit={make}>
        <label className="puter-field">
          <span>video prompt</span>
          <textarea
            aria-label="video prompt"
            rows={3}
            placeholder="A paper boat crossing a rain puddle, slow tracking shot, overcast light…"
            value={prompt}
            onChange={(event) => setPrompt(event.target.value)}
          />
        </label>
        <div className="puter-grid">
          <label className="puter-field">
            <span>model (optional)</span>
            <input
              placeholder="Puter default"
              value={model}
              onChange={(event) => setModel(event.target.value)}
            />
          </label>
          <label className="puter-field">
            <span>seconds</span>
            <input
              type="number"
              min={1}
              max={30}
              value={seconds}
              onChange={(event) => setSeconds(event.target.value)}
            />
          </label>
          <label className="puter-field">
            <span>size</span>
            <select value={size} onChange={(event) => setSize(event.target.value)}>
              <option value="default">model default</option>
              <option value="1280x720">1280 × 720</option>
              <option value="720x1280">720 × 1280</option>
              <option value="1024x1024">1024 × 1024</option>
            </select>
          </label>
        </div>
        <div className="puter-actions">
          <TestToggle checked={testMode} onChange={setTestMode} id="puter-video-test" />
          <span className="spacer" />
          <button type="submit" disabled={busy || !prompt.trim()}>
            {busy ? "rendering…" : "generate video"}
          </button>
        </div>
      </form>
      {errorLine(error)}
      {src ? (
        <figure className="puter-result">
          <video controls src={src} aria-label={alt} />
          <figcaption>
            <span className="muted small">Puter video · hosted URLs may expire</span>
            <MediaActions src={src} filename="puter-video.mp4" />
          </figcaption>
        </figure>
      ) : null}
    </div>
  );
}

function RealtimePanel({ puter }: { puter: PuterSdk }) {
  type Line = { role: string; text: string };
  const [mode, setMode] = useState<"text" | "voice">("text");
  const [instructions, setInstructions] = useState("You are Kira, a concise and warm assistant.");
  const [model, setModel] = useState("gpt-realtime-2.1-mini");
  const [voice, setVoice] = useState("");
  const [active, setActive] = useState(false);
  const [connecting, setConnecting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [lines, setLines] = useState<Line[]>([]);
  const [live, setLive] = useState("");
  const [draft, setDraft] = useState("");
  const conversation = useRef<PuterRealtimeConversation | null>(null);
  const liveText = useRef("");
  const thread = useRef<HTMLDivElement | null>(null);

  const append = useCallback((role: string, text: string) => {
    const clean = text.trim();
    if (!clean) return;
    setLines((previous) => [...previous, { role, text: clean }]);
  }, []);

  const clearLive = useCallback(() => {
    liveText.current = "";
    setLive("");
  }, []);

  useEffect(() => {
    const node = thread.current;
    if (node) node.scrollTop = node.scrollHeight;
  }, [lines, live]);

  useEffect(
    () => () => {
      conversation.current?.close();
      conversation.current = null;
    },
    [],
  );

  async function start() {
    if (connecting || active) return;
    setError(null);
    setConnecting(true);
    try {
      const options: Record<string, unknown> = {
        model,
        instructions,
        output: mode === "voice" ? ["audio"] : ["text"],
      };
      if (voice.trim()) options.voice = voice.trim();
      const next = await puter.ai.realtime(options);
      conversation.current = next;
      next.on("text", (event) => {
        if (mode !== "text") return;
        liveText.current += event.delta ?? "";
        setLive(liveText.current);
      });
      next.on("transcript", (event) => {
        if (mode !== "voice") return;
        if (event.final) {
          append(event.role || "assistant", event.text || "");
          if (event.role === "assistant") clearLive();
        } else if (event.role === "assistant") {
          setLive(event.text || "");
        }
      });
      next.on("turn.done", () => {
        if (mode !== "text") return;
        const text = liveText.current.trim();
        if (text) append("assistant", text);
        clearLive();
      });
      next.on("error", (event) => setError(puterError(event)));
      next.on("close", () => setActive(false));
      await next.connect();
      if (mode === "voice") {
        await next.speaker?.start({ bargeIn: true });
        await next.microphone?.start();
      }
      setActive(true);
    } catch (failure) {
      try {
        conversation.current?.close();
      } catch {
        // The failed session has nothing left to release.
      }
      conversation.current = null;
      setError(puterError(failure));
    } finally {
      setConnecting(false);
    }
  }

  function stop() {
    try {
      conversation.current?.microphone?.stop();
      conversation.current?.speaker?.stop();
      conversation.current?.close();
    } catch {
      // close() is best effort; the UI still drops the session below.
    }
    conversation.current = null;
    setActive(false);
    clearLive();
  }

  function sendText(event: FormEvent) {
    event.preventDefault();
    const text = draft.trim();
    if (!text || !active || mode !== "text") return;
    try {
      append("user", text);
      setDraft("");
      clearLive();
      conversation.current?.sendText(text);
    } catch (failure) {
      setError(puterError(failure));
    }
  }

  return (
    <div className="puter-panel">
      <div className="puter-intro">
        <p>
          A live OpenAI realtime session through Puter. Text mode streams a reply; voice mode opens
          the microphone and speaker. Realtime is beta and requires a paid Puter plan.
        </p>
      </div>
      <div className="puter-grid">
        <label className="puter-field">
          <span>mode</span>
          <select
            value={mode}
            disabled={active || connecting}
            onChange={(event) => setMode(event.target.value as "text" | "voice")}
          >
            <option value="text">text</option>
            <option value="voice">voice (microphone)</option>
          </select>
        </label>
        <label className="puter-field">
          <span>realtime model</span>
          <select value={model} disabled={active || connecting} onChange={(event) => setModel(event.target.value)}>
            {REALTIME_MODELS.map((name) => (
              <option key={name} value={name}>
                {name}
              </option>
            ))}
          </select>
        </label>
        <label className="puter-field">
          <span>voice (optional)</span>
          <input
            value={voice}
            disabled={active || connecting}
            placeholder="OpenAI default"
            onChange={(event) => setVoice(event.target.value)}
          />
        </label>
      </div>
      <label className="puter-field">
        <span>instructions</span>
        <textarea
          rows={2}
          maxLength={8192}
          value={instructions}
          disabled={active || connecting}
          onChange={(event) => setInstructions(event.target.value)}
        />
      </label>
      <div className="puter-actions">
        {active ? (
          <>
            <span className="badge-ok">live</span>
            <button type="button" onClick={stop}>
              end session
            </button>
            {mode === "voice" ? (
              <button
                type="button"
                onClick={() => {
                  void conversation.current?.interrupt?.().catch((failure: unknown) => {
                    setError(puterError(failure));
                  });
                }}
              >
                interrupt
              </button>
            ) : null}
            <button
              type="button"
              onClick={() => {
                setLines([]);
                clearLive();
              }}
            >
              clear transcript
            </button>
          </>
        ) : (
          <button type="button" disabled={connecting} onClick={() => void start()}>
            {connecting ? "connecting…" : mode === "voice" ? "start voice session" : "start text session"}
          </button>
        )}
      </div>
      {errorLine(error)}
      <div className="puter-thread" ref={thread} aria-label="Puter realtime transcript">
        {lines.length === 0 && !live ? (
          <p className="muted">
            {mode === "voice"
              ? "Start the session, allow the microphone, then speak."
              : "Start the session, then send a line below."}
          </p>
        ) : (
          lines.map((line, index) => (
            <article className="puter-turn" data-role={line.role} key={index}>
              <span className="puter-role">{line.role}</span>
              <p>{line.text}</p>
            </article>
          ))
        )}
        {live ? (
          <article className="puter-turn" data-role="assistant">
            <span className="puter-role">assistant · live</span>
            <p>{live}</p>
          </article>
        ) : null}
      </div>
      {mode === "text" ? (
        <form className="puter-composer" onSubmit={sendText}>
          <textarea
            aria-label="realtime message"
            rows={2}
            placeholder={active ? "Send a line into the session…" : "Start the session first"}
            disabled={!active}
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
          />
          <div className="puter-actions">
            <span className="spacer" />
            <button type="submit" disabled={!active || !draft.trim()}>
              send
            </button>
          </div>
        </form>
      ) : null}
    </div>
  );
}

function ModelsPanel({
  models,
  providers,
  loading,
  error,
  refresh,
}: {
  models: PuterModel[];
  providers: string[];
  loading: boolean;
  error: string | null;
  refresh: () => void;
}) {
  const [query, setQuery] = useState("");
  const [provider, setProvider] = useState("all");
  const filtered = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return models.filter((model) => {
      if (provider !== "all" && model.provider !== provider) return false;
      if (!needle) return true;
      return (
        model.id.toLowerCase().includes(needle) ||
        (model.name || "").toLowerCase().includes(needle) ||
        (model.puterId || "").toLowerCase().includes(needle) ||
        model.provider.toLowerCase().includes(needle)
      );
    });
  }, [models, provider, query]);
  const shown = filtered.slice(0, 200);

  return (
    <div className="puter-panel">
      <div className="puter-intro">
        <p>
          The live Puter catalogue. It is the same list the chat model box suggests, with provider,
          context window and the per-token price Puter reports.
        </p>
      </div>
      <div className="filters puter-filters">
        <input
          aria-label="search models"
          placeholder="search models"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
        />
        <select aria-label="provider filter" value={provider} onChange={(event) => setProvider(event.target.value)}>
          <option value="all">all providers ({providers.length})</option>
          {providers.map((name) => (
            <option key={name} value={name}>
              {name}
            </option>
          ))}
        </select>
        <button type="button" onClick={refresh} disabled={loading}>
          {loading ? "refreshing…" : "refresh"}
        </button>
      </div>
      {error ? <p className="error small">{error}</p> : null}
      {!models.length && loading ? <p className="muted">reading the Puter catalogue…</p> : null}
      {!models.length && !loading && !error ? (
        <p className="muted">Puter reported no models for this account.</p>
      ) : null}
      {models.length > 0 ? (
        <>
          <p className="muted small">
            {filtered.length} model{filtered.length === 1 ? "" : "s"} match
            {filtered.length > shown.length ? " · showing the first " + shown.length : ""}
          </p>
          <div className="puter-table-wrap">
            <table className="puter-models">
              <thead>
                <tr>
                  <th>model</th>
                  <th>provider</th>
                  <th>context</th>
                  <th>max out</th>
                  <th>price</th>
                </tr>
              </thead>
              <tbody>
                {shown.map((model) => (
                  <tr key={model.puterId || model.provider + ":" + model.id}>
                    <td>
                      <span className="puter-model-name">{model.name || model.id}</span>
                      <span className="mono small muted">{model.puterId || model.id}</span>
                    </td>
                    <td>{model.provider}</td>
                    <td className="mono">{model.context ? model.context.toLocaleString() : "—"}</td>
                    <td className="mono">{model.max_tokens ? model.max_tokens.toLocaleString() : "—"}</td>
                    <td className="small">{modelCost(model)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      ) : null}
    </div>
  );
}

export function PuterScreen() {
  const [sdk, setSdk] = useState<PuterSdk | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [signedIn, setSignedIn] = useState(false);
  const [user, setUser] = useState<PuterUser | null>(null);
  const [authBusy, setAuthBusy] = useState(false);
  const [authError, setAuthError] = useState<string | null>(null);
  const [tab, setTab] = useState<Tab>("chat");
  const [models, setModels] = useState<PuterModel[]>([]);
  const [providers, setProviders] = useState<string[]>([]);
  const [catalogLoading, setCatalogLoading] = useState(false);
  const [catalogError, setCatalogError] = useState<string | null>(null);

  const refreshCatalog = useCallback(async () => {
    if (!sdk) return;
    setCatalogLoading(true);
    setCatalogError(null);
    const [catalog, names] = await Promise.allSettled([
      sdk.ai.listModels(),
      sdk.ai.listModelProviders(),
    ]);
    if (catalog.status === "fulfilled") setModels(catalog.value);
    else setCatalogError(puterError(catalog.reason));
    if (names.status === "fulfilled") setProviders(names.value);
    setCatalogLoading(false);
  }, [sdk]);

  useEffect(() => {
    if (signedIn && sdk) void refreshCatalog();
  }, [signedIn, sdk, refreshCatalog]);

  /**
   * The SDK is a third-party script, so it is fetched only after an explicit click and not when the
   * route opens. The loopback engine session is an HttpOnly cookie; the screen never hands a bearer
   * token to Puter. On a paired device that keeps a typed token in localStorage, that token is still
   * same-origin data, which is why this workspace is described as local-first.
   */
  async function connect() {
    if (authBusy) return;
    setAuthBusy(true);
    setAuthError(null);
    setLoadError(null);
    let loaded = sdk;
    try {
      if (!loaded) {
        loaded = await loadPuter();
        setSdk(loaded);
        const already = await Promise.resolve(loaded.auth.isSignedIn());
        // The SDK fetch is async, and a popup opened after it would lose the click's user
        // activation. Leave the hero up with a Continue button so signIn() runs on a fresh click.
        if (!already) return;
      } else {
        // Call signIn before any await so the popup still has this click's user activation.
        await loaded.auth.signIn();
      }
      const yes = await Promise.resolve(loaded.auth.isSignedIn());
      if (!yes) throw new Error("Puter did not finish signing in. Try again.");
      setSignedIn(true);
      try {
        setUser(await loaded.auth.getUser());
      } catch {
        setUser(null);
      }
    } catch (failure) {
      const message = puterError(failure);
      if (loaded) setAuthError(message);
      else setLoadError(message);
    } finally {
      setAuthBusy(false);
    }
  }

  async function signOut() {
    if (!sdk) return;
    try {
      await sdk.auth.signOut();
    } catch (failure) {
      setAuthError(puterError(failure));
    }
    setSignedIn(false);
    setUser(null);
    setModels([]);
    setProviders([]);
    setCatalogError(null);
    setTab("chat");
  }

  return (
    <section className="screen puter-screen" aria-label="Puter AI">
      <header className="screen-head">
        <h2>Puter AI</h2>
        <span className="puter-kicker">user-pays</span>
        <span className="spacer" />
        <a className="puter-doc-link" href={PUTER_DEVELOPER_URL} target="_blank" rel="noreferrer">
          developer.puter.com ↗
        </a>
      </header>

      {loadError ? (
        <div className="puter-hero" role="alert">
          <h3>Puter.js could not load</h3>
          <p>{loadError}</p>
          <p className="muted small">
            The SDK is fetched from js.puter.com only when you press Connect. Kira's own engine still
            works without it.
          </p>
          <button type="button" disabled={authBusy} onClick={() => void connect()}>
            {authBusy ? "opening Puter…" : "try again"}
          </button>
        </div>
      ) : signedIn && sdk ? (
        <>
          <div className="puter-account">
            <span className="badge-ok">connected</span>
            <strong>{user?.username || user?.email || "Puter account"}</strong>
            <span className="muted small">calls are billed by Puter to this account</span>
            <span className="spacer" />
            <button type="button" onClick={() => void signOut()}>
              sign out
            </button>
          </div>
          {authError ? <p className="error small">{authError}</p> : null}
          <div className="segmented puter-tabs" role="tablist" aria-label="Puter tools">
            {TABS.map((item) => (
              <button
                key={item.id}
                type="button"
                role="tab"
                aria-selected={tab === item.id}
                onClick={() => setTab(item.id)}
              >
                {item.label}
              </button>
            ))}
          </div>
          {catalogError && tab !== "models" ? (
            <p className="muted small">
              model catalogue unavailable: {catalogError} · chat still accepts a typed model name
            </p>
          ) : null}
          {tab === "chat" ? <ChatPanel puter={sdk} models={models} /> : null}
          {tab === "image" ? <ImagePanel puter={sdk} /> : null}
          {tab === "speech" ? <SpeechPanel puter={sdk} /> : null}
          {tab === "vision" ? <VisionPanel puter={sdk} /> : null}
          {tab === "video" ? <VideoPanel puter={sdk} /> : null}
          {tab === "realtime" ? <RealtimePanel puter={sdk} /> : null}
          {tab === "models" ? (
            <ModelsPanel
              models={models}
              providers={providers}
              loading={catalogLoading}
              error={catalogError}
              refresh={() => void refreshCatalog()}
            />
          ) : null}
        </>
      ) : (
        <div className="puter-hero">
          <h3>Connect Puter</h3>
          <p>
            Puter is a user-pays AI platform: you sign in with a Puter account, and the calls you
            make here are billed to that account. Kira never asks for an API key and never stores
            one.
          </p>
          <ul>
            <li>chat with hundreds of models, including image-capable models</li>
            <li>text to image and text to video</li>
            <li>text to speech, transcription and voice conversion</li>
            <li>OCR for images, PDFs and office documents</li>
            <li>live text or voice realtime sessions (paid plan)</li>
          </ul>
          <div className="puter-actions">
            <button type="button" disabled={authBusy} onClick={() => void connect()}>
              {authBusy
                ? sdk
                  ? "opening Puter…"
                  : "loading Puter…"
                : sdk
                  ? "Continue to Puter"
                  : "Connect Puter"}
            </button>
            <a href="https://docs.puter.com/AI/" target="_blank" rel="noreferrer">
              read the AI docs
            </a>
          </div>
          {sdk ? (
            <p className="muted small">
              Puter.js is ready. Press Continue to open Puter's sign-in popup.
            </p>
          ) : null}
          {errorLine(authError)}
          <p className="muted small">
            Connect loads Puter's official browser SDK from js.puter.com. It then runs in this page
            as third-party code, so connect only in a browser profile you trust. Kira never asks
            Puter for, or stores, an AI API key.
          </p>
          <p className="muted small">
            A popup opens on puter.com for the sign-in. If this browser blocks it, allow popups for
            this page and try again.
          </p>
        </div>
      )}

      <footer className="puter-footer">
        <span>
          AI and media by <a href={PUTER_DEVELOPER_URL} target="_blank" rel="noreferrer">Puter</a> ·
          Powered by Puter
        </span>
        <a href="https://docs.puter.com/AI/" target="_blank" rel="noreferrer">
          API docs
        </a>
        <a href="https://docs.puter.com/user-pays-model/" target="_blank" rel="noreferrer">
          user-pays model
        </a>
      </footer>
    </section>
  );
}
