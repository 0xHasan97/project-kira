import { API_PREFIX, KiraApiError } from "./contracts.ts";
import type {
  ApprovalResponse,
  ApprovalsResponse,
  ChatChunk,
  ChatRequest,
  CheckpointDiff,
  CheckpointRestore,
  CheckpointsResponse,
  CharacterActiveResponse,
  CharacterDeleted,
  CharacterList,
  CharacterProfile,
  CharacterRow,
  DeletedResponse,
  DeviceDeleted,
  DevicesResponse,
  ErrorBody,
  HealthResponse,
  HealthzResponse,
  ImageDeleted,
  ImageGenerateRequest,
  ImageOutput,
  ImagesStatus,
  KeyResponse,
  MemoryDeleted,
  MemoryExport,
  MemoryItem,
  MemoryKind,
  MemoryList,
  MemoryPatch,
  MemorySearch,
  MemorySettings,
  MemorySettingsPatch,
  MessagesResponse,
  ModelsResponse,
  OverviewResponse,
  PairResponse,
  PairingCodeResponse,
  ProbeResponse,
  ProvidersResponse,
  SettingsRequest,
  SettingsResponse,
  SessionsResponse,
  SkillsResponse,
  StudioDownloadRequest,
  StudioDownloadResult,
  StudioRuntime,
  StudioStatus,
  ToolPolicyResponse,
  ToolsResponse,
  VoiceStatus,
} from "./contracts.ts";
import { SseBuffer } from "./sse.ts";

export interface KiraClientOptions {
  baseUrl?: string;
  token: string;
  fetch?: typeof fetch;
}

/**
 * Any subset of the four tunable fields; `null` clears that override back to config.yaml.
 * The name the screens use — the shape and its meaning live in the published contract.
 */
export type SettingPatch = SettingsRequest;

/** Every engine call goes through here; nothing else in the UI talks to HTTP. */
export class KiraClient {
  readonly baseUrl: string;
  private token: string;
  private fetchImpl: typeof fetch;

  constructor(options: KiraClientOptions) {
    this.baseUrl = (options.baseUrl ?? "").replace(/\/$/, "");
    this.token = options.token;
    this.fetchImpl = options.fetch ?? globalThis.fetch.bind(globalThis);
  }

  private headers(extra: Record<string, string> = {}): HeadersInit {
    return { Authorization: `Bearer ${this.token}`, ...extra };
  }

  private async request<T>(path: string, init: RequestInit = {}): Promise<T> {
    const response = await this.fetchImpl(this.url(path), {
      ...init,
      headers: this.headers((init.headers as Record<string, string>) ?? {}),
    });
    if (!response.ok) throw await this.asError(response, 0);
    return (await response.json()) as T;
  }

  private url(path: string): string {
    return `${this.baseUrl}${path}`;
  }

  private async asError(response: Response, httpStatus: number): Promise<KiraApiError> {
    // One read of the body. Calling `response.text()` after `response.json()` can only throw, which used to
    // turn a shaped JSON error — a renamed route, a wrong namespace — into "HTTP 404 with a non-JSON body".
    const text = await response.text();
    let body: ErrorBody;
    try {
      const parsed = JSON.parse(text) as { error?: ErrorBody };
      body = parsed.error ?? {
        code: "empty_response",
        message: text.slice(0, 200) || `HTTP ${response.status} returned no body`,
        status: response.status,
        retryable: false,
      };
    } catch {
      body = { code: "non_json_error", message: `HTTP ${response.status} with a non-JSON body`, status: response.status, retryable: false };
    }
    return new KiraApiError(body, response.status || httpStatus);
  }

  /** /healthz deliberately needs no token, so a wrong token still shows the engine is alive. */
  async healthz(): Promise<HealthzResponse> {
    const response = await this.fetchImpl(this.url("/healthz"));
    if (!response.ok) throw await this.asError(response, 0);
    return (await response.json()) as HealthzResponse;
  }

  models(live = false): Promise<ModelsResponse> {
    return this.request<ModelsResponse>(`${API_PREFIX}/models${live ? "?live=true" : ""}`);
  }

  health(): Promise<HealthResponse> {
    return this.request<HealthResponse>(`${API_PREFIX}/kira/health`);
  }

  overview(month?: string): Promise<OverviewResponse> {
    const query = month ? `?month=${encodeURIComponent(month)}` : "";
    return this.request<OverviewResponse>(`${API_PREFIX}/kira/overview${query}`);
  }

  providers(): Promise<ProvidersResponse> {
    return this.request<ProvidersResponse>(`${API_PREFIX}/kira/providers`);
  }

  sessions(limit = 30): Promise<SessionsResponse> {
    return this.request<SessionsResponse>(`${API_PREFIX}/kira/sessions?limit=${limit}`);
  }

  messages(sessionId: string): Promise<MessagesResponse> {
    return this.request<MessagesResponse>(`${API_PREFIX}/kira/sessions/${encodeURIComponent(sessionId)}/messages`);
  }

  /** Provider controls are desktop-only: the engine token is the whole gate, no typed secret. */
  setSettings(name: string, patch: SettingPatch): Promise<SettingsResponse> {
    return this.request<SettingsResponse>(`${API_PREFIX}/kira/providers/${encodeURIComponent(name)}/settings`, {
      method: "PUT",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(patch),
    });
  }

  /** Keys are the one write a human pastes, so they ask for the bearer token and nothing typed. */
  putKey(name: string, key: string): Promise<KeyResponse> {
    return this.request<KeyResponse>(`${API_PREFIX}/kira/providers/${encodeURIComponent(name)}/key`, {
      method: "PUT",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ key }),
    });
  }

  deleteKey(name: string): Promise<KeyResponse> {
    return this.request<KeyResponse>(`${API_PREFIX}/kira/providers/${encodeURIComponent(name)}/key`, {
      method: "DELETE",
    });
  }

  clearCooldown(name: string): Promise<ProvidersResponse> {
    return this.request<ProvidersResponse>(`${API_PREFIX}/kira/providers/${encodeURIComponent(name)}/cooldown`, {
      method: "DELETE",
    });
  }

  probe(name: string): Promise<ProbeResponse> {
    return this.request<ProbeResponse>(`${API_PREFIX}/kira/providers/${encodeURIComponent(name)}/probe`, {
      method: "POST",
    });
  }

  deleteSession(sessionId: string, secret: string): Promise<DeletedResponse> {
    return this.write(`${API_PREFIX}/kira/sessions/${encodeURIComponent(sessionId)}`, "DELETE", secret);
  }

  clearSessions(secret: string): Promise<DeletedResponse> {
    return this.write(`${API_PREFIX}/kira/sessions`, "DELETE", secret);
  }

  tools(): Promise<ToolsResponse> {
    return this.request<ToolsResponse>(`${API_PREFIX}/kira/tools`);
  }

  skills(): Promise<SkillsResponse> {
    return this.request<SkillsResponse>(`${API_PREFIX}/kira/skills`);
  }

  /** Mint a pairing code. Confirm-gated, so the phone can never mint one for itself. */
  pairingCode(secret: string): Promise<PairingCodeResponse> {
    return this.write(`${API_PREFIX}/kira/pairing-code`, "POST", secret);
  }

  /**
   * The one call a device makes before it has a token. The client always sends a bearer header;
   * this route ignores it, which is why pairing works from a browser that has never connected.
   */
  pair(code: string, name: string): Promise<PairResponse> {
    return this.request<PairResponse>(`${API_PREFIX}/kira/pair`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ code, name }),
    });
  }

  devices(): Promise<DevicesResponse> {
    return this.request<DevicesResponse>(`${API_PREFIX}/kira/devices`);
  }

  revokeDevice(id: string, secret: string): Promise<DeviceDeleted> {
    return this.write(`${API_PREFIX}/kira/devices/${encodeURIComponent(id)}`, "DELETE", secret);
  }

  /** The library, and who is on stage. A pick at a folder that is gone reads `null`, never the stale id. */
  characters(): Promise<CharacterList> {
    return this.request<CharacterList>(`${API_PREFIX}/kira/characters`);
  }

  /** One character whole: the measured body, the models that came with it, and its files. */
  character(id: string): Promise<CharacterProfile> {
    return this.request<CharacterProfile>(`${API_PREFIX}/kira/characters/${encodeURIComponent(id)}`);
  }

  /**
   * Import a `.pmx` or `.zip` already on this machine. No secret: like a pasted key, the caller is
   * supplying a file, not destroying one - and the refusal, when there is one, is the importer's own
   * code and status, so a zip bomb reads as `too_large` rather than as a generic bad request.
   */
  importCharacter(path: string): Promise<CharacterRow> {
    return this.request<CharacterRow>(`${API_PREFIX}/kira/characters`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ path }),
    });
  }

  /** Put a character on stage, or take everyone off with a real `null` in the body. */
  setActiveCharacter(id: string | null): Promise<CharacterActiveResponse> {
    return this.request<CharacterActiveResponse>(`${API_PREFIX}/kira/characters/active`, {
      method: "PUT",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ id }),
    });
  }

  removeCharacter(id: string, secret: string): Promise<CharacterDeleted> {
    return this.write(`${API_PREFIX}/kira/characters/${encodeURIComponent(id)}`, "DELETE", secret);
  }

  /**
   * The path a character's file is fetched from - deliberately a path, not a URL, and never a URL with a
   * token in it. `bytes()` puts the bearer in the header, so nothing that ends up in an access log, a
   * `<img>` element, or a loader's `resourcePath` carries a secret.
   */
  characterFileUrl(id: string, relative: string): string {
    return `${API_PREFIX}/kira/characters/${encodeURIComponent(id)}/file?${new URLSearchParams({ path: relative })}`;
  }

  /**
   * The KRM1 mesh route, as a path for the same reason: the stage asks for a body by its character id and
   * nothing else, so there is no filename to smuggle and no token to put in a query string.
   */
  characterMeshUrl(id: string): string {
    return `${API_PREFIX}/kira/characters/${encodeURIComponent(id)}/mesh`;
  }

  /**
   * Fetch raw bytes - a 45 MB model or one texture - with the bearer header and no body parsing.
   * Everything else in this client decodes JSON; a stage needs the ArrayBuffer itself, and the engine's
   * refusal still has to arrive as a `KiraApiError` so a missing texture is a named finding, not a blank.
   */
  async bytes(path: string): Promise<ArrayBuffer> {
    const response = await this.fetchImpl(this.url(path), { headers: this.headers() });
    if (!response.ok) throw await this.asError(response, 0);
    return response.arrayBuffer();
  }

  memories(query?: string, kind?: MemoryKind, pinned?: boolean, limit = 50): Promise<MemoryList> {
    // Built in this order so the wire URL is stable enough to assert on, and so a filter that is
    // absent reads as absent rather than as "false".
    const params = new URLSearchParams();
    if (query) params.set("query", query);
    if (kind) params.set("kind", kind);
    if (pinned !== undefined) params.set("pinned", String(pinned));
    params.set("limit", String(limit));
    return this.request<MemoryList>(`${API_PREFIX}/kira/memory?${params}`);
  }

  memorySearch(q: string, limit = 20): Promise<MemorySearch> {
    return this.request<MemorySearch>(
      `${API_PREFIX}/kira/memory/search?${new URLSearchParams({ q, limit: String(limit) })}`,
    );
  }

  memorySettings(): Promise<MemorySettings> {
    return this.request<MemorySettings>(`${API_PREFIX}/kira/memory/settings`);
  }

  exportMemory(): Promise<MemoryExport> {
    return this.request<MemoryExport>(`${API_PREFIX}/kira/memory/export`);
  }

  addMemory(text: string, kind: MemoryKind, secret: string): Promise<MemoryItem> {
    return this.write(`${API_PREFIX}/kira/memory`, "POST", secret, { text, kind });
  }

  updateMemory(id: string, patch: MemoryPatch, secret: string): Promise<MemoryItem> {
    return this.write(`${API_PREFIX}/kira/memory/${encodeURIComponent(id)}`, "PATCH", secret, patch);
  }

  deleteMemory(id: string, secret: string): Promise<MemoryDeleted> {
    return this.write(`${API_PREFIX}/kira/memory/${encodeURIComponent(id)}`, "DELETE", secret);
  }

  putMemorySettings(patch: MemorySettingsPatch, secret: string): Promise<MemorySettings> {
    return this.write(`${API_PREFIX}/kira/memory/settings`, "PUT", secret, patch);
  }

  /** What a call would get: listen / speak / see, each with the reason a stage is missing. */
  voice(): Promise<VoiceStatus> {
    return this.request<VoiceStatus>(`${API_PREFIX}/kira/voice`);
  }

  /** The local image workspace: the engine, the checkpoints it can see, and the gallery. */
  images(): Promise<ImagesStatus> {
    return this.request<ImagesStatus>(`${API_PREFIX}/kira/images`);
  }

  /** One generation. Minutes on a CPU, so the route runs it off the event loop. */
  generateImage(request: ImageGenerateRequest, secret: string): Promise<ImageOutput> {
    return this.write(`${API_PREFIX}/kira/images/generate`, "POST", secret, request);
  }

  /**
   * Forgetting an image is a delete like any other: owner token plus the typed confirm secret. The
   * gallery fetches the bytes through `bytes()` with the bearer header, never a token in a URL.
   */
  deleteImage(name: string, secret: string): Promise<ImageDeleted> {
    return this.write(`${API_PREFIX}/kira/images/${encodeURIComponent(name)}`, "DELETE", secret);
  }

  /** The Portable AI Studio components Kira can see, and whether the local chat server is up. */
  studio(): Promise<StudioStatus> {
    return this.request<StudioStatus>(`${API_PREFIX}/kira/studio`);
  }

  /** Start llama.cpp on one GGUF; the engine adds it as a keyless provider while it runs. */
  startStudioLlm(model: string | null, secret: string): Promise<StudioStatus> {
    return this.write(`${API_PREFIX}/kira/studio/llm/start`, "POST", secret, { model });
  }

  stopStudioLlm(secret: string): Promise<StudioStatus> {
    return this.write(`${API_PREFIX}/kira/studio/llm/stop`, "POST", secret);
  }

  /** One Hugging Face file into the folder its loader scans. The ceiling and host check are server-side. */
  downloadStudioModel(request: StudioDownloadRequest, secret: string): Promise<StudioDownloadResult> {
    return this.write(`${API_PREFIX}/kira/studio/download`, "POST", secret, request);
  }

  /** The studio's own Node server: found, running, and whether this engine owns the process. */
  studioRuntime(): Promise<StudioRuntime> {
    return this.request<StudioRuntime>(`${API_PREFIX}/kira/studio/app`);
  }

  /** Starting it is an exec-shaped write, like the llama child: the typed secret is the gate. */
  startStudioApp(secret: string): Promise<StudioRuntime> {
    return this.write(`${API_PREFIX}/kira/studio/app/start`, "POST", secret);
  }

  stopStudioApp(secret: string): Promise<StudioRuntime> {
    return this.write(`${API_PREFIX}/kira/studio/app/stop`, "POST", secret);
  }

  /**
   * One forwarded studio call. The studio speaks its own JSON, so its refusal keeps that sentence as a
   * plain Error. Kira's own refusal (a wrong confirm secret) stays a KiraApiError, because `useWrite`
   * only re-opens the dialog for that shape.
   */
  private async studioFetch(target: string, init: RequestInit): Promise<Response> {
    const query = new URLSearchParams({ path: target });
    const response = await this.fetchImpl(this.url(`${API_PREFIX}/kira/studio/proxy?${query}`), {
      ...init,
      headers: this.headers((init.headers as Record<string, string>) ?? {}),
    });
    if (!response.ok) {
      const text = await response.text();
      let message = `HTTP ${response.status}`;
      try {
        const parsed = JSON.parse(text) as {
          error?: string | { code?: string; message?: string; status?: number };
        };
        if (typeof parsed.error === "string") {
          message = parsed.error;
        } else if (parsed.error?.code && parsed.error.message) {
          // Kira's own refusal, not the studio's: a mistyped confirm secret arrives as the shaped
          // envelope, and `useWrite` only re-opens the dialog for a `KiraApiError`.
          throw new KiraApiError(
            { ...parsed.error, status: parsed.error.status ?? response.status, retryable: false } as ErrorBody,
            response.status,
          );
        } else if (parsed.error?.message) {
          message = parsed.error.message;
        }
      } catch (error) {
        if (error instanceof KiraApiError) throw error;
        // A binary or empty refusal: the status is the only honest sentence there is.
      }
      throw new Error(message);
    }
    return response;
  }

  async studioGet<T>(target: string): Promise<T> {
    return (await (await this.studioFetch(target, { method: "GET" })).json()) as T;
  }

  /** A write the studio performs itself; `secret` is only needed where the engine asks for it (deletes). */
  async studioPost<T>(target: string, body: unknown = {}, secret?: string): Promise<T> {
    const headers: Record<string, string> = { "content-type": "application/json" };
    if (secret?.trim()) headers["X-Kira-Confirm"] = secret.trim();
    const response = await this.studioFetch(target, { method: "POST", headers, body: JSON.stringify(body) });
    return (await response.json()) as T;
  }

  /** Raw bytes up: whisper takes a WAV body, not a multipart form. */
  async studioUpload<T>(target: string, audio: Blob, contentType = "audio/wav"): Promise<T> {
    return (await (await this.studioFetch(target, {
      method: "POST",
      headers: { "content-type": contentType },
      body: audio,
    })).json()) as T;
  }

  /** Bytes down, through the bearer header: audio and images never carry a token in the URL. */
  async studioBlob(target: string): Promise<Blob> {
    return (await this.studioFetch(target, { method: "GET" })).blob();
  }

  setToolPolicy(name: string, policy: "allow" | "ask" | "deny" | null, secret: string): Promise<ToolPolicyResponse> {
    return this.write(`${API_PREFIX}/kira/tools/${encodeURIComponent(name)}`, "PUT", secret, { policy });
  }

  checkpoints(limit = 20, sessionId?: string): Promise<CheckpointsResponse> {
    const query = new URLSearchParams({ limit: String(limit) });
    if (sessionId) query.set("session_id", sessionId);
    return this.request<CheckpointsResponse>(`${API_PREFIX}/kira/checkpoints?${query}`);
  }

  checkpoint(id: string): Promise<CheckpointDiff> {
    return this.request<CheckpointDiff>(`${API_PREFIX}/kira/checkpoints/${encodeURIComponent(id)}`);
  }

  restoreCheckpoint(id: string, secret: string, force = false): Promise<CheckpointRestore> {
    return this.write(`${API_PREFIX}/kira/checkpoints/${encodeURIComponent(id)}/restore`, "POST", secret, { force });
  }

  approvals(): Promise<ApprovalsResponse> {
    return this.request<ApprovalsResponse>(`${API_PREFIX}/kira/approvals`);
  }

  decideApproval(id: string, decision: "allow" | "deny", secret: string): Promise<ApprovalResponse> {
    return this.write(`${API_PREFIX}/kira/approvals/${encodeURIComponent(id)}`, "POST", secret, { decision });
  }

  /**
   * Every mutating call. The secret comes straight from the dialog: it is trimmed, checked, sent in
   * one header and never stored - not in a field on this client, not in storage, not in a URL.
   */
  private async write<T>(path: string, method: string, secret: string, body?: unknown): Promise<T> {
    const value = secret.trim();
    if (!value) throw new Error("no confirm secret - the dialog was cancelled before it could answer");
    return this.request<T>(path, {
      method,
      headers: {
        "X-Kira-Confirm": value,
        ...(body === undefined ? {} : { "content-type": "application/json" }),
      },
      ...(body === undefined ? {} : { body: JSON.stringify(body) }),
    });
  }

  /**
   * Streams one turn. `onChunk` sees every frame as it lands, including chain records,
   * so the UI can show which provider is answering instead of guessing after the fact.
   */
  async stream(
    request: ChatRequest,
    onChunk: (chunk: ChatChunk) => void,
    signal?: AbortSignal,
  ): Promise<void> {
    const response = await this.fetchImpl(this.url(`${API_PREFIX}/chat/completions`), {
      method: "POST",
      headers: this.headers({ "content-type": "application/json", accept: "text/event-stream" }),
      body: JSON.stringify({ ...request, stream: true }),
      signal,
    });
    const contentType = response.headers.get("content-type") ?? "";
    if (!response.ok && !contentType.includes("text/event-stream")) {
      throw await this.asError(response, 500);
    }
    if (!response.body) throw new Error("engine returned no response body");

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    const buffer = new SseBuffer();
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      for (const data of buffer.push(decoder.decode(value, { stream: true }))) {
        const chunk = JSON.parse(data) as ChatChunk;
        onChunk(chunk);
        if (chunk.type === "error") throw new KiraApiError(chunk.error, response.status || 200);
      }
    }
    const trailing = buffer.remainder().trim();
    if (trailing) throw new Error(`stream ended inside an event frame: ${trailing.slice(0, 120)}`);
  }
}
