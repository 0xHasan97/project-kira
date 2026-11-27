import { API_PREFIX, API_VERSION, CONTRACT_VERSION } from "./contracts.ts";
import type { ChainRecord, ChatChunk, CharacterProfile, CharacterRow, ErrorBody } from "./contracts.ts";
import { KRM1_FIXTURE_BASE64 } from "./avatar/krm1-fixture.ts";

export interface Recorded {
  url: string;
  method: string;
  headers: Record<string, string>;
  body?: string;
}

interface FakeOptions {
  chunks?: (ChatChunk | Record<string, unknown>)[];
  /** Keep the stream open after the last chunk, so a test can inspect a turn mid-flight. */
  holdOpen?: boolean;
  chatStatus?: number;
  chatJsonError?: ErrorBody;
  models?: unknown[];
  /** The refused-token case: the catalogue is behind the bearer check, so a stale token dies here. */
  modelsError?: ErrorBody;
  health?: unknown;
  healthError?: ErrorBody;
  sessions?: unknown[];
  messages?: Record<string, unknown[]>;
  healthz?: unknown;
  /** A loopback page's cookie mint. False answers the refusal a remote page would see. */
  session?: boolean;
  overview?: unknown;
  providers?: unknown;
  settings?: unknown;
  probe?: unknown;
  deleted?: unknown;
  tools?: unknown;
  voice?: unknown;
  checkpoints?: unknown;
  checkpointDetail?: unknown;
  restored?: unknown;
  approvals?: unknown;
  decided?: unknown;
  memory?: unknown;
  memorySearch?: unknown;
  memorySettings?: unknown;
  memoryError?: boolean;
  exportError?: boolean;
  skills?: unknown;
  skillsError?: boolean;
  devices?: unknown[];
  pairingCode?: unknown;
  paired?: unknown;
  pairError?: ErrorBody;
  /** The whole `GET /kira/characters` answer that seeds the fake's library, rows and pick included. */
  characters?: unknown;
  /** The image workspace: readiness, checkpoints and gallery rows. */
  images?: unknown;
  /** A generation answer. The screen renders what this says the engine drew. */
  generated?: unknown;
  /** A refused generation: no engine, no model, or an engine that failed. */
  imageError?: ErrorBody;
  /** Bytes served at `…/images/file/{name}`, keyed by name. */
  imageFiles?: Record<string, Uint8Array>;
  /** The whole `GET /kira/studio` answer, when a test wants a studio that is missing a piece. */
  studio?: unknown;
  /** What `/studio/llm/start` answers, when the test wants to see the post-start state. */
  studioStarted?: unknown;
  /** What `/studio/download` answers. */
  downloaded?: unknown;
  /** The studio's Node server. `true` answers a running child; a test may pass the whole shape. */
  studioRuntime?: unknown;
  /** Canned answers for the forwarded studio API, keyed by path without its query string. */
  studioProxy?: Record<string, unknown>;
  characterProfile?: unknown;
  /** Bytes served at `…/file?path=…`, keyed by the relative path. */
  characterFiles?: Record<string, Uint8Array>;
  /** Bytes served at `…/mesh`. The engine writes these with `pack_mesh`; the default is one it really wrote. */
  characterMesh?: Uint8Array;
  /** The refused import: a zip bomb, a non-model, or bytes that are already here. */
  importError?: ErrorBody;
  /** Override the pick without restating the rows — `null` means the stage is empty. */
  active?: string | null;
  confirm?: string;
}

/** The secret a fake accepts when the test does not name its own. */
export const FAKE_CONFIRM = "fake-confirm";

const json = (payload: unknown, status = 200) =>
  new Response(JSON.stringify(payload), { status, headers: { "content-type": "application/json" } });

function sse(
  chunks: unknown[],
  hold: boolean,
  onHold: (release: () => void) => void,
  signal?: AbortSignal,
): Response {
  const encoder = new TextEncoder();
  const body = new ReadableStream<Uint8Array>({
    start(controller) {
      for (const chunk of chunks) controller.enqueue(encoder.encode(`data: ${JSON.stringify(chunk)}\n\n`));
      if (hold) onHold(() => controller.close());
      else controller.close();
      // A real fetch rejects the body reader when the caller aborts, which is how "stop" reaches the
      // turn. Without this the fake holds a stream that can never end and the stop path is untestable.
      if (signal) {
        const kill = () => controller.error(new DOMException("The user aborted a request.", "AbortError"));
        if (signal.aborted) kill();
        else signal.addEventListener("abort", kill, { once: true });
      }
    },
  });
  return new Response(body, { status: 200, headers: { "content-type": "text/event-stream" } });
}

/**
 * An in-test stand-in for the engine. Deliberately strict: unknown routes 404 so a client
 * that invents an endpoint fails instead of quietly getting `undefined`.
 */
export function fakeEngine(options: FakeOptions = {}) {
  const calls: Recorded[] = [];
  let release: (() => void) | null = null;
  // The switches a `PUT /kira/memory/settings` actually moves. A fake that answered a write from a
  // frozen fixture would let the screen show yesterday's state and the test still call it a pass.
  let memorySettings = options.memorySettings ?? memoryFixture().settings;
  // Revoking has to move the list, or a screen that never re-read would look correct anyway.
  let devices = [...((options.devices ?? []) as { id: string; name: string; created_at: number; last_seen_at: number }[])];
  // The character library is state for the same reason: importing adds a row, removing takes it - and the
  // stage pick - away. A fake that answered a frozen list would let a screen that never re-reads pass.
  const seed = (options.characters ?? charactersFixture()) as { characters: CharacterRow[]; active: string | null };
  let rows = [...seed.characters];
  let pick: string | null = options.active === undefined ? seed.active : options.active;
  const files = options.characterFiles ?? characterFilesFixture();
  const meshBytes = options.characterMesh ?? KRM1_BYTES;
  const wanted = options.confirm ?? FAKE_CONFIRM;
  // Starting the local model flips this, so a re-read after the write sees a running server.
  let studioRunning = false;
  // The studio server is state too: start must be visible on the next read, or a screen that never
  // refreshed would look correct.
  const studioBase = (options.studioRuntime ?? studioRuntimeFixture(false)) as Record<string, unknown>;
  let studioAppRunning = Boolean(studioBase.running);
  const studioAppNow = () => ({
    ...studioBase,
    running: studioAppRunning,
    managed: studioAppRunning,
    url: studioAppRunning ? (studioBase.url ?? "http://127.0.0.1:1420") : null,
    pid: studioAppRunning ? 4242 : null,
    health: studioAppRunning ? { build: "text-image-v1", issues: [] } : null,
    error: null,
  });
  // Both spellings are read because the client sends an object literal, so the key is exactly as
  // written - a test that lowercases it must still be refused, not accidentally match.
  const refused = json(
    { error: { code: "unauthorized", message: "this write needs the confirm secret", status: 401, retryable: false } },
    401,
  );
  const fetchImpl = async (input: RequestInfo | URL, init: RequestInit = {}) => {
    const url = new URL(String(input), "http://127.0.0.1:8901");
    const headers = (init.headers ?? {}) as Record<string, string>;
    const method = init.method ?? "GET";
    const confirmHeader = headers["X-Kira-Confirm"] ?? headers["x-kira-confirm"] ?? "";
    calls.push({
      url: `${url.pathname}${url.search}`,
      method,
      headers,
      body: typeof init.body === "string" ? init.body : undefined,
    });

    // Same rule as the engine's middleware: a namespace this fake does not speak is answered before
    // anything else about the request is looked at.
    const namespace = url.pathname.match(/^\/(v\d+)(?:\/|$)/);
    if (namespace && `/${namespace[1]}` !== API_PREFIX) {
      return json(
        {
          error: {
            code: "unsupported_version",
            message: `this engine serves ${API_PREFIX} only; '/${namespace[1]}' is not a version it speaks`,
            status: 404,
            retryable: false,
          },
        },
        404,
      );
    }

    const at = (suffix: string) => url.pathname === `${API_PREFIX}${suffix}`;

    if (url.pathname === "/healthz") {
      return json(
        options.healthz ?? {
          ok: true,
          api_version: API_VERSION,
          contract_version: CONTRACT_VERSION,
          providers_configured: 2,
          default_mode: "AUTO",
        },
      );
    }
    if (at("/kira/session")) {
      if (method === "DELETE") return json({ connected: false });
      if (method === "POST" && options.session) return json({ connected: true });
      return json(
        {
          error: {
            code: "unauthorized",
            message: "a browser session is only available to a page on this machine; use the launcher or pair a device",
            status: 401,
            retryable: false,
          },
        },
        401,
      );
    }
    if (at("/models"))
      return options.modelsError
        ? json({ error: options.modelsError }, options.modelsError.status)
        : json({ object: "list", data: options.models ?? [] });
    if (at("/kira/health"))
      return options.healthError
        ? json({ error: options.healthError }, options.healthError.status)
        : json(options.health ?? { providers: {}, configured: [] });
    if (at("/kira/overview")) return json(options.overview ?? overviewFixture());
    if (at("/kira/providers")) return json(options.providers ?? providersFixture());
    if (at("/kira/sessions") && method === "GET") return json({ sessions: options.sessions ?? [] });
    if (at("/kira/tools") && method === "GET") return json(options.tools ?? { tools: [], plugins: [] });
    if (at("/kira/voice") && method === "GET") return json(options.voice ?? voiceFixture());
    if (at("/kira/checkpoints") && method === "GET") return json(options.checkpoints ?? { checkpoints: [] });
    if (at("/kira/approvals") && method === "GET") return json(options.approvals ?? { approvals: [] });
    const history = url.pathname.match(new RegExp(`^${API_PREFIX}/kira/sessions/([^/]+)/messages$`));
    if (history) {
      if (options.messages && !(history[1] in options.messages)) {
        return json({ error: { code: "session_not_found", message: `unknown session ${history[1]}`, status: 404, retryable: false } }, 404);
      }
      return json({ session_id: history[1], messages: options.messages?.[history[1]] ?? [] });
    }
    if (at("/kira/skills") && method === "GET") {
      if (options.skillsError) {
        return json({ error: { code: "internal_error", message: "the skill pack could not be read", status: 500, retryable: false } }, 500);
      }
      return json(options.skills ?? { skills: [], files: [], discovery: "inline" });
    }
    if (at("/kira/pairing-code") && method === "POST") {
      if (confirmHeader !== wanted) return refused;
      return json(options.pairingCode ?? { code: "ABCD1234", expires_at: 1_700_000_120 });
    }
    if (at("/kira/pair") && method === "POST") {
      if (options.pairError) return json({ error: options.pairError }, options.pairError.status ?? 400);
      const body = JSON.parse(String(init.body ?? "{}")) as { code: string; name: string };
      const device = { id: "dev-paired", name: body.name, created_at: 1_700_000_000, last_seen_at: 1_700_000_000 };
      devices = [...devices, device];
      return json(options.paired ?? { token: "kd_test_token", device });
    }
    if (at("/kira/devices") && method === "GET") return json({ devices });
    const deviceRow = url.pathname.match(new RegExp(`^${API_PREFIX}/kira/devices/([^/]+)$`));
    if (deviceRow && method === "DELETE") {
      if (confirmHeader !== wanted) return refused;
      if (!devices.some((device) => device.id === deviceRow[1])) {
        return json({ error: { code: "not_found", message: "unknown device", status: 404, retryable: false } }, 404);
      }
      devices = devices.filter((device) => device.id !== deviceRow[1]);
      return json({ deleted: deviceRow[1] });
    }
    if (at("/kira/memory") && method === "GET") {
      if (options.memoryError) {
        return json({ error: { code: "internal_error", message: "the index is not open", status: 500, retryable: false } }, 500);
      }
      return json({ ...(options.memory ?? memoryFixture()), settings: memorySettings });
    }
    if (at("/kira/memory") && method === "POST") {
      if (confirmHeader !== wanted) return refused;
      const body = JSON.parse(String(init.body ?? "{}")) as { text: string; kind?: string };
      return json({ ...memoryFixture().memories[0], id: "m3", text: body.text, kind: body.kind ?? "fact", origin: "user" });
    }
    if (at("/kira/memory/search") && method === "GET") return json(options.memorySearch ?? memoryHitsFixture());
    if (at("/kira/memory/settings") && method === "GET") return json(memorySettings);
    if (at("/kira/memory/settings") && method === "PUT") {
      if (confirmHeader !== wanted) return refused;
      const body = JSON.parse(String(init.body ?? "{}")) as Partial<typeof memorySettings>;
      memorySettings = { ...memorySettings, ...body };
      return json(memorySettings);
    }
    if (at("/kira/memory/export") && method === "GET") {
      if (options.exportError) {
        return json({ error: { code: "internal_error", message: "the export could not be built", status: 500, retryable: false } }, 500);
      }
      // `memory` is `unknown` on purpose - a test may hand any payload - so the one field this branch
      // mirrors, the list's own `memories`, is read through a narrow cast and answered with an empty
      // page rather than a missing field: `MemoryExport` requires `memories`.
      const list = (options.memory ?? memoryFixture()) as { memories?: unknown[] };
      return json({ version: 1, exported_at: 6, memories: list.memories ?? [] });
    }
    const memoryItem = url.pathname.match(new RegExp(`^${API_PREFIX}/kira/memory/([^/]+)$`));
    if (memoryItem && (method === "PATCH" || method === "DELETE")) {
      if (confirmHeader !== wanted) return refused;
      if (memoryItem[1] === "gone") {
        return json({ error: { code: "not_found", message: "unknown memory", status: 404, retryable: false } }, 404);
      }
      if (method === "DELETE") return json({ deleted: memoryItem[1] });
      return json({ ...memoryFixture().memories[0], id: memoryItem[1], ...JSON.parse(String(init.body ?? "{}")) });
    }

    // The studio: one read, then the one child process Kira starts itself. Starting it is a write
    // (an exec), so the fake demands the confirm header exactly like the engine's route does.
    if (at("/kira/studio") && method === "GET") {
      return json(options.studio ?? (studioRunning ? studioFixtureRunning() : studioFixture()));
    }
    if (at("/kira/studio/llm/start") && method === "POST") {
      if (confirmHeader !== wanted) return refused;
      studioRunning = true;
      return json(options.studioStarted ?? studioFixtureRunning());
    }
    if (at("/kira/studio/llm/stop") && method === "POST") {
      if (confirmHeader !== wanted) return refused;
      studioRunning = false;
      return json(options.studio ?? studioFixture());
    }
    if (at("/kira/studio/download") && method === "POST") {
      if (confirmHeader !== wanted) return refused;
      return json(options.downloaded ?? studioDownloadFixture());
    }
    if (at("/kira/studio/app") && method === "GET") {
      return json(studioAppNow());
    }
    if (at("/kira/studio/app/start") && method === "POST") {
      if (confirmHeader !== wanted) return refused;
      studioAppRunning = true;
      return json(studioAppNow());
    }
    if (at("/kira/studio/app/stop") && method === "POST") {
      if (confirmHeader !== wanted) return refused;
      studioAppRunning = false;
      return json(studioAppNow());
    }
    if (at("/kira/studio/proxy")) {
      const target = url.searchParams.get("path") ?? "";
      // The engine asks for the typed secret only where a forwarded call deletes or stops something.
      if (method === "POST" && /delete|stop/.test(target) && confirmHeader !== wanted) return refused;
      const table = { ...studioProxyFixture(), ...(options.studioProxy ?? {}) };
      if (target.startsWith("/tts-outputs/")) {
        return new Response(new Blob([new Uint8Array([82, 73, 70, 70])]), { headers: { "content-type": "audio/wav" } });
      }
      const key = target.split("?")[0];
      const answer = table[key];
      return answer ? json(answer) : json({ ok: false, error: `no fake for ${target}` }, 404);
    }

    // The image workspace. `file` is a literal before `{name}` for the same reason the engine
    // registers it first: `/images/file/foo.png` must never be read as an image called "file".
    if (at("/kira/images") && method === "GET") return json(options.images ?? imagesFixture());
    if (at("/kira/images/generate") && method === "POST") {
      if (confirmHeader !== wanted) return refused;
      if (options.imageError) return json({ error: options.imageError }, options.imageError.status);
      return json(options.generated ?? imageOutputFixture());
    }
    const imageFile = url.pathname.match(new RegExp(`^${API_PREFIX}/kira/images/file/([^/]+)$`));
    if (imageFile && method === "GET") {
      const bytes = (options.imageFiles ?? {})[imageFile[1]] ?? IMAGE_PNG_BYTES;
      return new Response(new Blob([bytes as unknown as BlobPart]), { status: 200, headers: { "content-type": "image/png" } });
    }
    const imageRow = url.pathname.match(new RegExp(`^${API_PREFIX}/kira/images/([^/]+)$`));
    if (imageRow && method === "DELETE") {
      if (confirmHeader !== wanted) return refused;
      return json({ deleted: imageRow[1] });
    }

    // The character library. `/kira/characters/active` is matched before `([^/]+)` because that is the
    // order the engine registers them in: a pick is a literal, not a folder called "active".
    if (at("/kira/characters") && method === "POST") {
      // Owner-token-only, like the key routes: no confirm header is asked for here, and one would be
      // ignored. A device token never reaches this fake, because the client that has one cannot be the
      // desktop that imports.
      if (options.importError) {
        return json({ error: options.importError }, options.importError.status ?? 400);
      }
      const body = JSON.parse(String(init.body ?? "{}")) as { path: string };
      const row = importedRow(body.path);
      if (rows.some((each) => each.sha256 === row.sha256)) {
        return json(
          {
            error: {
              code: "already_imported",
              message: `those bytes are already in the library as '${row.id}'`,
              status: 409,
              retryable: false,
              entry: row.id,
            },
          },
          409,
        );
      }
      rows = [...rows, row];
      return json(row, 201);
    }
    if (at("/kira/characters") && method === "GET") return json({ characters: rows, active: pick });
    if (at("/kira/characters/active") && method === "PUT") {
      const body = JSON.parse(String(init.body ?? "{}")) as { id: string | null };
      if (body.id !== null && !rows.some((each) => each.id === body.id)) {
        return json(
          { error: { code: "character_not_found", message: `the library has no character '${body.id}'`, status: 404, retryable: false } },
          404,
        );
      }
      pick = body.id;
      return json({ active: pick });
    }
    const characterFile = url.pathname.match(new RegExp(`^${API_PREFIX}/kira/characters/([^/]+)/file$`));
    if (characterFile && method === "GET") {
      const id = decodeURIComponent(characterFile[1]);
      const relative = url.searchParams.get("path") ?? "";
      if (!rows.some((each) => each.id === id)) return missingCharacter(id);
      // The engine's real check is `resolve()` against the folder; a fake has no folder, so the shape it
      // can reproduce is the one that matters to a client: the dot-dot path is refused, and refused with
      // the code the route uses.
      if (relative.split(/[\\/]/).includes("..") || relative.startsWith("/")) {
        return json(
          {
            error: {
              code: "unsafe_entry",
              message: `'${relative}' climbs out of the folder of character '${id}'`,
              status: 400,
              retryable: false,
              entry: relative,
            },
          },
          400,
        );
      }
      const bytes = files[relative];
      if (bytes === undefined) {
        return json(
          {
            error: {
              code: "character_file_not_found",
              message: `character '${id}' has no file '${relative}'`,
              status: 404,
              retryable: false,
              entry: relative,
            },
          },
          404,
        );
      }
      return new Response(bytes as unknown as BodyInit, {
        status: 200,
        headers: { "content-type": fileMediaType(relative), "content-length": String(bytes.byteLength) },
      });
    }
    const characterMesh = url.pathname.match(new RegExp(`^${API_PREFIX}/kira/characters/([^/]+)/mesh$`));
    if (characterMesh && method === "GET") {
      const id = decodeURIComponent(characterMesh[1]);
      const row = rows.find((each) => each.id === id);
      if (!row) return missingCharacter(id);
      // A prop-only archive has no body to export, and the engine answers that with its own code rather
      // than an empty blob — the stage has to be able to tell "nothing to draw" from "draw nothing".
      if (!row.is_character) {
        return json(
          {
            error: {
              code: "character_file_not_found",
              message: `character '${id}' has no body to put on the stage`,
              status: 404,
              retryable: false,
              entry: id,
            },
          },
          404,
        );
      }
      const bytes = meshBytes;
      return new Response(bytes as unknown as BodyInit, {
        status: 200,
        headers: { "content-type": "application/octet-stream", "content-length": String(bytes.byteLength) },
      });
    }
    const characterRow = url.pathname.match(new RegExp(`^${API_PREFIX}/kira/characters/([^/]+)$`));
    if (characterRow) {
      const id = decodeURIComponent(characterRow[1]);
      const row = rows.find((each) => each.id === id);
      if (!row) return missingCharacter(id);
      if (method === "GET") return json(options.characterProfile ?? characterProfileFixture(row));
      if (method === "DELETE") {
        if (confirmHeader !== wanted) return refused;
        rows = rows.filter((each) => each.id !== id);
        // Taking it off stage in the same call is the engine's rule, and the one a screen cannot see if
        // the fake leaves a pick pointing at a row it just deleted.
        if (pick === id) pick = null;
        return json({ deleted: id });
      }
    }

    if (at("/chat/completions")) {
      if (options.chatJsonError) return json({ error: options.chatJsonError }, options.chatStatus ?? 503);
      return sse(options.chunks ?? [], options.holdOpen ?? false, (close) => {
        release = close;
      }, init.signal ?? undefined);
    }

    // Writes. The exact `/kira/sessions` check comes before the `([^/]+)` matcher so
    // `…/sessions/{id}/messages` still reaches the read branch above.
    const settings = url.pathname.match(new RegExp(`^${API_PREFIX}/kira/providers/([^/]+)/settings$`));
    if (settings && method === "PUT") {
      // Owner-token-only, like the key routes: provider controls ask for no confirm header.
      const name = decodeURIComponent(settings[1]);
      return json(options.settings ?? { provider: name, settings: settingsFixture(name) });
    }
    const key = url.pathname.match(new RegExp(`^${API_PREFIX}/kira/providers/([^/]+)/key$`));
    if (key && (method === "PUT" || method === "DELETE")) {
      // The engine gates keys on the bearer token, not the confirm header (app.py: owner).
      const name = decodeURIComponent(key[1]);
      return json({ provider: name, key_ref: `provider/${name}`, key_present: method === "PUT" });
    }
    const cooldown = url.pathname.match(new RegExp(`^${API_PREFIX}/kira/providers/([^/]+)/cooldown$`));
    if (cooldown && method === "DELETE") {
      return json(options.providers ?? providersFixture());
    }
    const probe = url.pathname.match(new RegExp(`^${API_PREFIX}/kira/providers/([^/]+)/probe$`));
    if (probe && method === "POST") {
      const name = decodeURIComponent(probe[1]);
      return json(
        options.probe ?? { provider: name, ok: true, model_count: 3, sample: ["mini"], latency_ms: 120, error: null },
      );
    }
    const tool = url.pathname.match(new RegExp(`^${API_PREFIX}/kira/tools/([^/]+)$`));
    if (tool && method === "PUT") {
      if (confirmHeader !== wanted) return refused;
      const name = decodeURIComponent(tool[1]);
      const body = JSON.parse(String(init.body ?? "{}")) as { policy?: string | null };
      return json({ tool: { name, policy: body.policy ?? "allow", overridden: body.policy !== null } });
    }
    const restore = url.pathname.match(new RegExp(`^${API_PREFIX}/kira/checkpoints/([^/]+)/restore$`));
    if (restore && method === "POST") {
      if (confirmHeader !== wanted) return refused;
      return json(options.restored ?? { restored: [], conflicts: [], checkpoint_id: "cp-next" });
    }
    const checkpoint = url.pathname.match(new RegExp(`^${API_PREFIX}/kira/checkpoints/([^/]+)$`));
    if (checkpoint && method === "GET") {
      if (!options.checkpointDetail) {
        return json({ error: { code: "not_found", message: "unknown checkpoint", status: 404, retryable: false } }, 404);
      }
      return json(options.checkpointDetail);
    }
    const approval = url.pathname.match(new RegExp(`^${API_PREFIX}/kira/approvals/([^/]+)$`));
    if (approval && method === "POST") {
      if (confirmHeader !== wanted) return refused;
      const id = decodeURIComponent(approval[1]);
      const body = JSON.parse(String(init.body ?? "{}")) as { decision?: string };
      return json(
        options.decided ?? {
          approval: { id, tool: "write_file", arguments: {}, risk: "write", status: body.decision === "allow" ? "allowed" : "denied", created_at: 1, expires_at: 2 },
        },
      );
    }
    if (at("/kira/sessions") && method === "DELETE") {
      if (confirmHeader !== wanted) return refused;
      return json(options.deleted ?? { deleted: 2, messages: 5 });
    }
    const session = url.pathname.match(new RegExp(`^${API_PREFIX}/kira/sessions/([^/]+)$`));
    if (session && method === "DELETE") {
      if (confirmHeader !== wanted) return refused;
      return json(options.deleted ?? { deleted: 1, messages: 3 });
    }
    return json({ detail: "Not Found" }, 404);
  };
  return { fetch: fetchImpl as unknown as typeof fetch, calls, releaseStream: () => release?.() };
}

export const delta = (text: string): ChatChunk => ({ type: "delta", text });
export const chain = (record: ChainRecord): ChatChunk => ({ type: "chain", record });
export const done = (overrides: Record<string, unknown> = {}): ChatChunk =>
  ({
    type: "done",
    id: "chatcmpl-test",
    session_id: "sess-1",
    provider: "groq",
    model: "llama-3.3-70b-versatile",
    finish_reason: "stop",
    status: "complete",
    usage: { prompt_tokens: 12, completion_tokens: 7 },
    provider_chain: [
      { provider: "openrouter", event: "failed", reason: "rate limited", cooldown_s: 5 },
      { provider: "groq", event: "served", model: "llama-3.3-70b-versatile" },
    ],
    ...overrides,
  }) as unknown as ChatChunk;

/**
 * What a personal machine reports: configured for local speech, missing both installs.
 * The wording is the engine's own, copied from `voice/stt.py` and `voice/tts.py`, because this screen
 * exists to show the user the exact sentence that tells them what to install.
 */
export function voiceFixture(): unknown {
  return {
    stt: { mode: "local", available: false, detail: 'faster-whisper is not installed — pip install -e ".[voice]"' },
    tts: {
      mode: "local",
      available: false,
      detail: "piper is not installed — put piper.exe and a voice .onnx under <data>/voice/piper (README §Voice)",
    },
    vision: null,
    limits: { max_utterance_s: 30, silence_ms: 700 },
  };
}

/** The smallest bytes a browser will call a PNG; the screen never decodes them, it only needs a blob. */
export const IMAGE_PNG_BYTES = new Uint8Array([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a, 0, 0, 0, 0]);

export function imageOutputFixture(): unknown {
  return {
    name: "img-20260101-120000-abc123.png",
    url: `/v1/kira/images/file/img-20260101-120000-abc123.png`,
    prompt: "a lantern-lit street after rain",
    negative_prompt: "blurry",
    model: "sd15.safetensors",
    steps: 24,
    cfg_scale: 7,
    width: 512,
    height: 512,
    seed: 1234,
    sampler: "euler_a",
    created_at: "2026-01-01T12:00:00+00:00",
    duration_ms: 4200,
    backend: "local",
  };
}

/** One studio with every component present; tests override a piece to make it missing. */
export function studioFixture(): unknown {
  return {
    root: "C:/Portable-Local-Studio-main",
    available: true,
    image: {
      available: true,
      engine: "C:/Portable-Local-Studio-main/app/backend/win/vulkan/sd-vulkan.exe",
      detail: "stable-diffusion.cpp (vulkan)",
      models: [{ name: "sd15", filename: "sd15.safetensors", size_bytes: 2_100_000_000, kind: "safetensors" }],
    },
    llm: {
      available: true,
      engine: "C:/Portable-Local-Studio-main/app/llm-backend/win/vulkan/llama-server.exe",
      detail: "llama.cpp (vulkan)",
      models: [{ name: "qwen", filename: "qwen2.5-3b-instruct-q4_k_m.gguf", size_bytes: 2_000_000_000, kind: "gguf" }],
      running: false,
      model: null,
      url: null,
      model_dir: "C:/Portable-Local-Studio-main/app/llm-models",
      engine_dir: "C:/Portable-Local-Studio-main/app/llm-backend/win/vulkan",
      reason: null,
    },
    stt: {
      available: true,
      engine: "C:/Portable-Local-Studio-main/app/speech-backend/win/cpu/whisper-cli.exe",
      detail: "whisper.cpp",
      models: [{ name: "ggml-base.en", filename: "ggml-base.en.bin", size_bytes: 148_000_000, kind: "bin" }],
    },
    tts: {
      available: true,
      engine: "C:/Portable-Local-Studio-main/app/tools/node-win/node.exe",
      detail: "Kokoro via kokoro-js (q8)",
      models: [],
    },
  };
}

export function studioFixtureRunning(): unknown {
  const base = studioFixture() as { llm: Record<string, unknown> };
  return {
    ...base,
    llm: { ...base.llm, running: true, model: "qwen", url: "http://127.0.0.1:8123/v1" },
  };
}

/** The studio's Node server: stopped by default, managed by Kira while it runs. */
export function studioRuntimeFixture(running = false): unknown {
  return {
    found: true,
    running,
    managed: running,
    external: false,
    url: running ? "http://127.0.0.1:1420" : null,
    root: "C:/Portable-Local-Studio-main",
    pid: running ? 4242 : null,
    error: null,
    health: running ? { build: "text-image-v1", issues: [] } : null,
  };
}

/** The forwarded studio API, small enough to read: one of each shape the panels render. */
export function studioProxyFixture(): Record<string, unknown> {
  return {
    "/api/speech/models": { ok: true, models: [{ filename: "ggml-base.bin", size: "142 MB", installed: true }] },
    "/api/speech/transcriptions": {
      ok: true,
      transcriptions: [
        { filename: "t1.json", displayName: "hello.wav", text: "hello there", url: "/transcriptions/t1.json", createdAt: "2026-01-01" },
      ],
    },
    "/api/speech/delete-model": { ok: true },
    "/api/tts/status": {
      ok: true,
      voices: [
        { id: "af_heart", name: "Heart", language: "en-us", gender: "Female" },
        { id: "am_michael", name: "Michael", language: "en-us", gender: "Male" },
      ],
    },
    "/api/tts/outputs": {
      ok: true,
      outputs: [{ filename: "a.json", text: "hi there", url: "/tts-outputs/a.wav", displayName: "Heart", size: "120 KB" }],
    },
    "/api/tts/speak": { ok: true, output: { filename: "a.json", url: "/tts-outputs/a.wav", text: "hi there" } },
    "/api/tts/delete-output": { ok: true },
    "/api/models": { ok: true, models: [{ filename: "dream.safetensors", size: "6.5 GB", installed: true }] },
    "/api/llm/models": { ok: true, models: [{ filename: "qwen.gguf", size: "2.0 GB", installed: true }] },
    "/api/tts/models": { ok: true, models: [{ filename: "kokoro-onnx-q8.json", size: "107 KB", installed: true }] },
    "/api/delete-model": { ok: true },
    "/api/llm/delete-model": { ok: true },
    "/api/tts/delete-model": { ok: true },
    "/api/health": {
      ok: true,
      build: "text-image-v1",
      issues: [],
      checks: [{ label: "Models folder", ok: true, path: "C:/studio/app/models" }],
      models: { count: 3, totalSize: "18.2 GB" },
    },
    "/api/backend-status": { ready: false, running: false, error: null, settings: { backendType: "auto", model: null } },
  };
}

export function studioDownloadFixture(): unknown {
  return {
    name: "qwen",
    filename: "qwen2.5-3b-instruct-q4_k_m.gguf",
    kind: "llm",
    bytes: 2_000_000_000,
    path: "C:/kira-data/llm/models/qwen2.5-3b-instruct-q4_k_m.gguf",
  };
}

/** A ready workspace with one checkpoint and one picture already on disk. */
export function imagesFixture(): unknown {
  return {
    ready: true,
    reason: null,
    backend: "local",
    backend_path: "C:/kira/images/engines/sd.exe",
    remote_url: null,
    engine_dir: "C:/kira/images/engines",
    model_dir: "C:/kira/images/models",
    output_dir: "C:/kira/images/outputs",
    models: [{ name: "sd15", filename: "sd15.safetensors", size_bytes: 2_100_000_000, kind: "safetensors" }],
    outputs: [imageOutputFixture()],
  };
}

/**
 * Two facts as the store returns them: one pinned preference the user typed, one auto-extracted
 * fact carrying the session it came from and the 42 tokens it cost.
 */
export function memoryFixture() {
  return {
    memories: [
      { id: "m1", kind: "preference", text: "I prefer pnpm", pinned: true, origin: "user",
        session_id: null, tokens_spent: 0, created_at: 1, updated_at: 2, last_used_at: null, use_count: 3 },
      { id: "m2", kind: "fact", text: "works on Windows", pinned: false, origin: "auto",
        session_id: "sess-9", tokens_spent: 42, created_at: 3, updated_at: 3, last_used_at: 4, use_count: 1 },
    ],
    total: 2,
    settings: { inject: true, capture: "explicit", extract: false, tokenizer: "trigram" },
  };
}

/** One history hit, with the engine's own `[ ]` around the match. */
export function memoryHitsFixture() {
  return {
    hits: [
      { session_id: "sess-9", message_id: 12, role: "user", snippet: "we talked about the [vector] database", created_at: 5 },
    ],
  };
}

// --- the character library ------------------------------------------------------------------------------

/** The body a real import produced: 26 798 vertices, and one texture that did not ship with it. */
export const ELLEN_ID = "ellen-9f3a2b1c";
/** A props-only archive, so a screen has to render a row that cannot be put on stage. */
export const PROPS_ID = "props-11223344";

const bytesOf = (text: string) => new TextEncoder().encode(text);
/** The four magic bytes plus the version and encoding counts a PMX header opens with. */
export const PMX_BYTES = new Uint8Array([...bytesOf("PMX "), 0x08, 0x00, 0x01, 0x01]);
export const PNG_BYTES = new Uint8Array([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]);
export const PROFILE_BYTES = bytesOf('{"schema":1}');

/**
 * The bytes `kira-engine`'s `pack_mesh` writes for the fixture in `tests/test_mesh_export.py`, kept in
 * `avatar/krm1-fixture.ts` and cross-checked from the Python side by `tests/test_krm1_fixture.py`. The fake
 * serves them at `…/mesh` so a client test exercises the real route shape against real engine output
 * instead of a blob this file invented — which is the only way the loader's tests mean anything.
 */
export const KRM1_BYTES = (() => {
  const raw = atob(KRM1_FIXTURE_BASE64);
  const bytes = new Uint8Array(raw.length);
  for (let at = 0; at < raw.length; at += 1) bytes[at] = raw.charCodeAt(at);
  return bytes;
})();

const fakeSha = (text: string): string => {
  let hash = 5381;
  for (const char of text) hash = ((hash << 5) + hash + char.charCodeAt(0)) >>> 0;
  return hash.toString(16).padStart(8, "0").repeat(8);
};

const fileMediaType = (relative: string): string => {
  const suffix = relative.slice(relative.lastIndexOf(".")).toLowerCase();
  if (suffix === ".png") return "image/png";
  if (suffix === ".json") return "application/json";
  // The two formats the engine says a browser cannot open on its own. The fake has to answer them the same
  // way because the loader's `.tga` path is a decoder of its own, and a fake that refused the request would
  // hide that.
  if (suffix === ".tga") return "image/x-tga";
  if (suffix === ".bmp") return "image/bmp";
  return "application/octet-stream";
};

function characterRow(overrides: Partial<CharacterRow> & { id: string }): CharacterRow {
  return {
    display_name: "ellen",
    english_name: "Ellen",
    source_file_name: "Ellen.zip",
    sha256: fakeSha("Ellen.zip"),
    imported_at: "2026-10-31T10:00:00+00:00",
    is_character: true,
    main_name: "ellen",
    path: "model.pmx",
    vertices: 26_798,
    bones: 101,
    has_physics: true,
    texture_status: "7/8 — hair.bmp absent",
    companion_count: 1,
    license_note: "redistribution not permitted — see LICENSE.txt in the archive",
    reason: "the only model in the archive with a face and a skeleton",
    ...overrides,
  };
}

/** Two rows because one is not enough: a library screen needs the props-only case in front of it. */
export function charactersFixture(): { characters: CharacterRow[]; active: string | null } {
  return {
    characters: [
      characterRow({ id: ELLEN_ID }),
      characterRow({
        id: PROPS_ID,
        display_name: "小道具",
        english_name: "props",
        source_file_name: "props.zip",
        sha256: fakeSha("props.zip"),
        is_character: false,
        main_name: null,
        path: null,
        vertices: 0,
        bones: 0,
        has_physics: false,
        texture_status: "no textures",
        companion_count: 0,
        license_note: null,
        reason: "no model in the archive passed the body test",
      }),
    ],
    active: ELLEN_ID,
  };
}

/**
 * One measured PMX, in the fields the contract publishes. The texture list is the interesting part: a
 * declared windows path, the posix name the stage fetches, and a `hair.bmp` that is simply not there.
 */
export function characterProfileFixture(row: CharacterRow): CharacterProfile {
  const capability = {
    path: row.path ?? "model.pmx",
    name: row.display_name,
    english_name: row.english_name,
    file_name: row.path ?? "model.pmx",
    version: 2.1,
    count_framing: "header" as const,
    material_framing: "draw_and_memos" as const,
    counts: {
      vertex_count: row.vertices, face_index_count: row.vertices * 6, texture_count: 8, material_count: 6,
      bone_count: row.bones, morph_count: 52, frame_count: 9, rigid_body_count: 42, constraint_count: 21,
    },
    vertices: row.vertices,
    bones: row.bones,
    triangles: Math.floor((row.vertices * 6) / 3),
    has_physics: row.has_physics,
    is_character: row.is_character,
    texture_status: row.texture_status ?? "no textures",
    standard_groups: ["両目", "左腕", "右腕"],
    finger_bone_count: 14,
    morph_names: ["あ", "い", "う", "え", "お", "笑い", "怒り", "悲しむ", "びっくり", "まばたき"],
    morph_kinds: [1, 1, 1, 1, 1],
    frame_names: ["表情", "腕"],
    textures: [
      { declared: "tex\\颜.tga", relative: "tex/颜.tga", exists: true, size: 4_096, format: "tga", escapes: false },
      { declared: "hair.bmp", relative: "hair.bmp", exists: false, size: null, format: "", escapes: false },
    ],
    texture_resolved: 7,
    missing_textures: ["hair.bmp"],
    sphere_texture_refs: 0,
    shared_toon_refs: 3,
    ik_bone_count: 2,
    trailing_bytes: 0,
    findings: ["hair.bmp is declared and absent"],
    license_note: row.license_note,
    unreadable: null,
  };
  return {
    schema: 1,
    id: row.id,
    display_name: row.display_name,
    english_name: row.english_name,
    imported_at: row.imported_at,
    source: { file_name: row.source_file_name, sha256: row.sha256, bytes: 45_000_000, archive: true },
    reason: row.reason,
    license_note: row.license_note,
    main: row.is_character ? capability : null,
    companions: row.is_character ? [] : [capability],
    files: [
      { path: "model.pmx", bytes: 44_000_000 },
      { path: "tex/颜.png", bytes: PNG_BYTES.byteLength },
      { path: "profile.json", bytes: PROFILE_BYTES.byteLength },
    ],
  };
}

export function characterFilesFixture(): Record<string, Uint8Array> {
  return {
    "model.pmx": PMX_BYTES,
    "tex/颜.png": PNG_BYTES,
    "profile.json": PROFILE_BYTES,
  };
}

/** The row a fresh import would answer with — same name, same suffix-free id, a hash of its own. */
function importedRow(path: string): CharacterRow {
  const name = path.split(/[\\/]/).pop() ?? path;
  const stem = name.replace(/\.(zip|pmx)$/i, "");
  const slug = (stem.toLowerCase().replace(/[^a-z0-9]+/g, "").slice(0, 24) || "character") + "-00000000";
  return characterRow({
    id: slug,
    display_name: stem,
    english_name: stem,
    source_file_name: name,
    sha256: fakeSha(name),
    main_name: stem,
  });
}

const missingCharacter = (id: string) =>
  json(
    { error: { code: "character_not_found", message: `no character in the library has that id: '${id}'`, status: 404, retryable: false } },
    404,
  );

/** The state a personal install is actually in: one override, one no-cap provider, one orphan. */
export function providersFixture(): unknown {
  const state = (base: unknown, override: unknown, effective: unknown) => ({ base, override, effective });
  return {
    month: "2026-10",
    orphan_settings: ["ghost.enabled"],
    providers: [
      {
        name: "groq",
        kind: "openai_compat",
        base_url: "https://api.groq.com/openai/v1",
        models: ["llama-3.3-70b-versatile"],
        key_ref: "provider/groq",
        key_present: true,
        needs_key: true,
        vision: false,
        enabled: state(true, null, true),
        priority: state(50, 5, 5),
        tier: state("fast", null, "fast"),
        monthly_cap: state(null, 1000000, 1000000),
        spend_this_month: 250000,
        health: { failures: 0, successes: 12, cooling_s: 0, last_reason: "" },
      },
      {
        name: "openrouter",
        kind: "openai_compat",
        base_url: "https://openrouter.ai/api/v1",
        models: ["claude-sonnet-4-5"],
        key_ref: "provider/openrouter",
        key_present: false,
        needs_key: true,
        vision: true,
        enabled: state(true, false, false),
        priority: state(100, null, 100),
        tier: state("powerful", null, "powerful"),
        monthly_cap: state(null, null, null),
        spend_this_month: 0,
        health: { failures: 3, successes: 0, cooling_s: 42.5, last_reason: "rate_limited status=429 too many" },
      },
    ],
  };
}

/** After a write: enabled overridden off, the other three still at baseline. */
export function settingsFixture(name = "groq"): unknown {
  const state = (base: unknown, override: unknown, effective: unknown) => ({ base, override, effective });
  return {
    provider: name,
    settings: {
      enabled: state(true, false, false),
      priority: state(50, null, 50),
      tier: state("fast", null, "fast"),
      monthly_cap: state(null, null, null),
    },
  };
}

export function overviewFixture(): unknown {
  return {
    month: "2026-10",
    turns: 40,
    tokens: { input: 12000, output: 4800 },
    success_rate: 0.925,
    interrupted: 1,
    failed: 2,
    by_provider: [
      { provider: "groq", turns: 38, tokens: 15000 },
      { provider: "openrouter", turns: 2, tokens: 1800 },
    ],
    by_model: [
      { provider: "groq", model: "llama-3.3-70b-versatile", turns: 38, tokens: 15000 },
      // The two failed turns never reached a model, and they still count in `turns`.
      { provider: "openrouter", model: null, turns: 2, tokens: 1800 },
    ],
    daily: [
      { date: "2026-10-01", turns: 20, tokens: 9000 },
      { date: "2026-10-02", turns: 20, tokens: 7800 },
    ],
    budgets: [
      { provider: "groq", cap: 1000000, used: 250000, remaining: 750000 },
      { provider: "openrouter", cap: null, used: 0, remaining: null },
    ],
    recent_issues: [
      { id: 9, session_id: "sess-9", status: "failed", provider: "openrouter", model: null, created_at: 1, reason: "provider_5xx status=503 down" },
      { id: 8, session_id: "sess-8", status: "interrupted", provider: "groq", model: "llama-3.3-70b-versatile", created_at: 2, reason: "client saw text" },
    ],
    refusals: {
      count: 1,
      by_code: [{ code: "budget_exhausted", count: 1 }],
      recent: [
        {
          code: "budget_exhausted",
          message: "mode FAST: over the monthly cap for 2026-10 (groq) - raise the cap in the dashboard",
          mode: "FAST",
          model: null,
          created_at: 3,
        },
      ],
    },
  };
}
