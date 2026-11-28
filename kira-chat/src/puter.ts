/**
 * Puter.js is loaded from Puter's own CDN at runtime, never bundled. It is the only way to reach
 * the user-pays AI surface without putting an API key in this app: Puter signs the browser in and
 * bills the signed-in account, while Kira only ever holds the media URL or text that comes back.
 *
 * The SDK is a third-party global with a large, moving surface. The types here cover the calls the
 * Puter screen makes, and every helper treats a shape it does not recognise as an error rather than
 * guessing at a field. The docs for each call are linked from the screen.
 */

export const PUTER_SCRIPT_URL = "https://js.puter.com/v2/";
export const PUTER_DEVELOPER_URL = "https://developer.puter.com/";

export interface PuterUser {
  username?: string;
  email?: string;
  [key: string]: unknown;
}

export interface PuterErrorBody {
  message?: string;
  msg?: string;
  error?: string;
  code?: string;
  errorCode?: string;
  status?: number;
  [key: string]: unknown;
}

export interface PuterModel {
  id: string;
  puterId?: string;
  provider: string;
  name?: string;
  aliases?: string[];
  context?: number;
  max_tokens?: number;
  cost?: {
    currency?: string;
    tokens?: number;
    input?: number;
    output?: number;
  };
  [key: string]: unknown;
}

export interface PuterChatMessage {
  role: "system" | "user" | "assistant";
  content: string;
}

export interface PuterChatResult {
  message?: {
    role?: string;
    content?: string | Array<{ type?: string; text?: string }> | null;
    reasoning?: string;
    [key: string]: unknown;
  };
  [key: string]: unknown;
}

export interface PuterChatChunk {
  type: string;
  text?: string;
  message?: string;
  code?: string;
  status?: number;
  reasoning?: string;
  image?: { type?: string; image_url?: { url?: string } };
  [key: string]: unknown;
}

export interface PuterMedia {
  src?: string;
  toString(): string;
}

export interface PuterTranscription {
  text?: string;
  model?: string;
  language?: string;
  duration?: number;
  [key: string]: unknown;
}

export interface PuterTtsEngine {
  id: string;
  name?: string;
  provider?: string;
  pricing_per_million_chars?: number;
  [key: string]: unknown;
}

export interface PuterVoice {
  id: string;
  name?: string;
  provider?: string;
  language?: { name?: string; code?: string };
  supported_engines?: string[];
  [key: string]: unknown;
}

export interface PuterRealtimeEvent {
  type?: string;
  delta?: string;
  role?: string;
  text?: string;
  final?: boolean;
  message?: string;
  code?: string;
  status?: number;
  [key: string]: unknown;
}

export interface PuterRealtimeConversation {
  state: string;
  model?: string;
  connect(): Promise<void>;
  close(): void;
  sendText(text: string): void;
  configure?(options: Record<string, unknown>): Promise<void>;
  interrupt?(): Promise<void>;
  on(type: string, handler: (event: PuterRealtimeEvent) => void): () => void;
  off?(type: string, handler: (event: PuterRealtimeEvent) => void): void;
  microphone?: {
    start(): Promise<void>;
    stop(): void;
    mute?(): void;
    unmute?(): void;
  };
  speaker?: {
    start(options?: { bargeIn?: boolean }): Promise<void>;
    stop(): void;
  };
}

export interface PuterTextToSpeech {
  (text: string, options?: Record<string, unknown>): Promise<PuterMedia>;
  (
    text: string,
    language: string,
    voice?: string,
    engine?: string,
    testMode?: boolean,
  ): Promise<PuterMedia>;
  listEngines(provider?: string | { provider?: string }): Promise<PuterTtsEngine[]>;
  listVoices(options?: string | { provider?: string; engine?: string }): Promise<PuterVoice[]>;
}

export interface PuterAi {
  chat(
    prompt: string | PuterChatMessage[],
    optionsOrTest?: Record<string, unknown> | boolean,
    options?: Record<string, unknown>,
  ): Promise<PuterChatResult | AsyncIterable<PuterChatChunk>>;
  txt2img(prompt: string, options?: Record<string, unknown>): Promise<PuterMedia>;
  txt2speech: PuterTextToSpeech;
  speech2txt(
    source: File | Blob | string,
    options?: Record<string, unknown>,
    testMode?: boolean,
  ): Promise<string | PuterTranscription>;
  img2txt(
    source: File | Blob | string,
    options?: Record<string, unknown>,
    testMode?: boolean,
  ): Promise<string>;
  txt2vid(prompt: string, options?: Record<string, unknown>): Promise<PuterMedia>;
  speech2speech(
    source: File | Blob | string,
    options?: Record<string, unknown>,
    testMode?: boolean,
  ): Promise<PuterMedia>;
  realtime(options?: Record<string, unknown>): Promise<PuterRealtimeConversation>;
  listModels(provider?: string): Promise<PuterModel[]>;
  listModelProviders(): Promise<string[]>;
}

export interface PuterSdk {
  auth: {
    isSignedIn(): boolean | Promise<boolean>;
    signIn(): Promise<unknown>;
    signOut(): void | Promise<void>;
    getUser(): Promise<PuterUser>;
  };
  ai: PuterAi;
}

declare global {
  interface Window {
    puter?: PuterSdk;
  }
}

let loading: Promise<PuterSdk> | null = null;

/** The one place the SDK is fetched. A second screen, or StrictMode's second effect, shares it. */
export function loadPuter(): Promise<PuterSdk> {
  if (typeof window === "undefined") {
    return Promise.reject(new Error("Puter.js needs a browser."));
  }
  if (window.puter) return Promise.resolve(window.puter);
  if (loading) return loading;

  loading = new Promise<PuterSdk>((resolve, reject) => {
    const script = document.createElement("script");
    script.src = PUTER_SCRIPT_URL;
    script.async = true;
    script.dataset.kiraPuter = "on";
    const fail = (message: string) => {
      script.remove();
      loading = null;
      reject(new Error(message));
    };
    script.addEventListener("load", () => {
      if (window.puter) resolve(window.puter);
      else fail("Puter.js loaded but did not expose the Puter API. Try again.");
    });
    script.addEventListener("error", () => {
      fail("Puter.js could not be loaded. Check this machine's network connection and try again.");
    });
    document.head.append(script);
  });
  return loading;
}

/** SDK rejections are usually { message, code }, not Error instances. Keep both facts. */
export function puterError(error: unknown): string {
  if (error instanceof Error && error.message) return error.message;
  if (error && typeof error === "object") {
    const body = error as PuterErrorBody;
    const message =
      typeof body.message === "string"
        ? body.message.trim()
        : typeof body.msg === "string"
          ? body.msg.trim()
          : "";
    const code =
      typeof body.code === "string"
        ? body.code
        : typeof body.errorCode === "string"
          ? body.errorCode
          : typeof body.error === "string"
            ? body.error
            : "";
    if (message && code) return message + " (" + code + ")";
    if (message) return message;
    if (code) return code;
    try {
      const encoded = JSON.stringify(error);
      if (encoded && encoded !== "{}") return encoded;
    } catch {
      // A circular rejection object is still not a reason to hide the fact that it failed.
    }
  }
  return String(error) || "Puter returned an unknown error.";
}

/** txt2img returns an HTMLImageElement, txt2speech an HTMLAudioElement, and so on. */
export function mediaSrc(value: PuterMedia | string | null | undefined): string {
  if (typeof value === "string" && value) return value;
  if (value && typeof value === "object" && typeof value.src === "string" && value.src) {
    return value.src;
  }
  const text = value === null || value === undefined ? "" : String(value);
  if (/^(https?:|blob:|data:)/.test(text)) return text;
  throw new Error("Puter returned no media URL.");
}

/** A chat result's content is a string on normalized models and a block array on older ones. */
export function chatText(result: PuterChatResult | string | null | undefined): string {
  if (typeof result === "string") return result;
  const content = result?.message?.content;
  if (typeof content === "string") return content;
  if (Array.isArray(content)) {
    return content
      .map((block) => (block && typeof block === "object" && typeof block.text === "string" ? block.text : ""))
      .join("");
  }
  return "";
}

/** speech2txt returns a string in text mode and an object by default. */
export function transcriptText(result: string | PuterTranscription | null | undefined): string {
  if (typeof result === "string") return result;
  if (result && typeof result === "object" && typeof result.text === "string") return result.text;
  return "";
}

/** Human-readable price from the catalogue's cents-per-token fields, or an em dash. */
export function modelCost(model: PuterModel): string {
  const cost = model.cost;
  if (!cost || typeof cost.tokens !== "number" || cost.tokens <= 0) return "—";
  const dollars = (cents: number | undefined) =>
    typeof cents === "number" ? "$" + (cents / 100).toFixed(2) : "—";
  return dollars(cost.input) + " in / " + dollars(cost.output) + " out per " + cost.tokens.toLocaleString() + " tokens";
}

/** One anchor click; a remote URL may open in a tab when the browser ignores download. */
export function downloadMedia(src: string, filename: string): void {
  const link = document.createElement("a");
  link.href = src;
  link.download = filename;
  link.target = "_blank";
  link.rel = "noreferrer";
  document.body.append(link);
  link.click();
  link.remove();
}
