import { describe, expect, it } from "vitest";
import { KiraClient } from "./api.ts";
import { API_PREFIX, API_VERSION, CONTRACT_VERSION, KiraApiError } from "./contracts.ts";
import type { ChatChunk } from "./contracts.ts";
import { chain, delta, done, ELLEN_ID, FAKE_CONFIRM, fakeEngine, KRM1_BYTES, PNG_BYTES, PROPS_ID } from "./fake-engine.ts";
import { KRM1_MAGIC } from "./avatar/krm1.ts";

const clientWith = (engine: ReturnType<typeof fakeEngine>) =>
  new KiraClient({ baseUrl: "http://127.0.0.1:8901", token: "sekret", fetch: engine.fetch });

describe("KiraClient", () => {
  it("does not send the bearer token to /healthz", async () => {
    const engine = fakeEngine();
    const healthz = await clientWith(engine).healthz();
    expect(healthz.contract_version).toBe(CONTRACT_VERSION);
    expect(healthz.api_version).toBe(API_VERSION);
    expect(engine.calls[0].headers.Authorization).toBeUndefined();
  });

  it("authenticates every other call and asks for the live probe explicitly", async () => {
    const engine = fakeEngine({ models: [{ id: "llama", provider: "groq", tier: "fast", object: "model", owned_by: "groq", key_present: true, needs_key: true }] });
    await clientWith(engine).models(true);
    expect(engine.calls[0].url).toBe(`${API_PREFIX}/models?live=true`);
    expect(engine.calls[0].headers.Authorization).toBe("Bearer sekret");
  });

  it("streams every chunk in order", async () => {
    const engine = fakeEngine({
      chunks: [
        chain({ provider: "groq", event: "attempt" }),
        delta("He"),
        delta("llo"),
        done(),
      ],
    });
    const seen: ChatChunk[] = [];
    await clientWith(engine).stream({ messages: [{ role: "user", content: "hi" }] }, (chunk) => seen.push(chunk));
    expect(seen.map((chunk) => chunk.type)).toEqual(["chain", "delta", "delta", "done"]);
    const body = JSON.parse(engine.calls[0].body ?? "{}") as Record<string, unknown>;
    expect(body.stream).toBe(true);
    expect(engine.calls[0].headers.accept).toBe("text/event-stream");
  });

  it("turns an error frame into a KiraApiError that still carries the chain", async () => {
    const engine = fakeEngine({
      chunks: [
        chain({ provider: "groq", event: "attempt" }),
        delta("par"),
        {
          type: "error",
          error: { code: "providers_exhausted", message: "no provider left", status: 503, retryable: true },
          provider_chain: [{ provider: "groq", event: "failed" }],
        },
      ],
    });
    const text: string[] = [];
    await expect(
      clientWith(engine).stream({ messages: [{ role: "user", content: "hi" }] }, (chunk) => {
        if (chunk.type === "delta") text.push(chunk.text);
      }),
    ).rejects.toThrow(/providers_exhausted/);
    expect(text).toEqual(["par"]);
  });

  it("raises a KiraApiError for a JSON error response", async () => {
    const engine = fakeEngine({ chatStatus: 502, chatJsonError: { code: "provider_5xx", message: "boom", status: 502, retryable: true } });
    const client = clientWith(engine);
    const failure = await client.stream({ messages: [{ role: "user", content: "hi" }] }, () => undefined).catch((error) => error);
    expect(failure).toBeInstanceOf(KiraApiError);
    expect((failure as KiraApiError).body.code).toBe("provider_5xx");
    expect((failure as KiraApiError).httpStatus).toBe(502);
  });

  it("surfaces an unknown session instead of an empty thread", async () => {
    const engine = fakeEngine({ messages: { known: [] } });
    await expect(clientWith(engine).messages("nope")).rejects.toBeInstanceOf(KiraApiError);
  });

  it("reads the dashboard endpoints with the bearer token and nothing else", async () => {
    const engine = fakeEngine();
    const client = clientWith(engine);
    await client.overview("2026/10");
    await client.providers();
    expect(engine.calls.map((call) => call.url)).toEqual([
      `${API_PREFIX}/kira/overview?month=2026%2F10`,
      `${API_PREFIX}/kira/providers`,
    ]);
    for (const call of engine.calls) {
      expect(call.headers.Authorization).toBe("Bearer sekret");
      expect(call.headers["X-Kira-Confirm"]).toBeUndefined();
    }
  });

  it("reports the body a route-less response actually returned", async () => {
    // Starlette answers an unknown path with `{"detail":...}`, not the contract shape. It used to be
    // reported as "a non-JSON body" because the client read the stream twice — which is exactly the
    // message a moved or renamed route produced, so the honest text is the point of this test.
    const fetchImpl = (async () =>
      new Response('{"detail":"Not Found"}', { status: 404, headers: { "content-type": "application/json" } })) as unknown as typeof fetch;
    const client = new KiraClient({ token: "sekret", fetch: fetchImpl });
    const failure = (await client.models().catch((error) => error)) as KiraApiError;
    expect(failure).toBeInstanceOf(KiraApiError);
    expect(failure.body.code).toBe("empty_response");
    expect(failure.body.message).toContain("Not Found");
    expect(failure.httpStatus).toBe(404);
  });

  it("types a wrong-namespace rejection instead of hiding it behind the transport", async () => {
    const rejection = {
      error: {
        code: "unsupported_version",
        message: `this engine serves ${API_PREFIX} only; '/v9' is not a version it speaks`,
        status: 404,
        retryable: false,
      },
    };
    const fetchImpl = (async () => new Response(JSON.stringify(rejection), { status: 404 })) as unknown as typeof fetch;
    const client = new KiraClient({ token: "sekret", fetch: fetchImpl });
    const failure = (await client.providers().catch((error) => error)) as KiraApiError;
    expect(failure.body.code).toBe("unsupported_version");
    expect(failure.body.retryable).toBe(false);
    expect(failure.message).toContain(API_PREFIX);
  });

  it("sends a settings write with the engine token and no confirm header", async () => {
    const engine = fakeEngine({ settings: { provider: "gr oq", settings: {} } });
    const client = new KiraClient({ baseUrl: "http://127.0.0.1:8901", token: "sekret", fetch: engine.fetch });
    await client.setSettings("gr oq", { enabled: false });
    const call = engine.calls[engine.calls.length - 1];
    expect(call.method).toBe("PUT");
    expect(call.url).toBe(`${API_PREFIX}/kira/providers/gr%20oq/settings`);
    expect(call.headers["X-Kira-Confirm"]).toBeUndefined();
    expect(JSON.parse(call.body ?? "{}")).toEqual({ enabled: false });
  });

  it("surfaces the engine's refusal instead of hiding it", async () => {
    const refusal = {
      error: { code: "unauthorized", message: "the engine token is missing", status: 401, retryable: false },
    };
    const fetchImpl = (async () => new Response(JSON.stringify(refusal), { status: 401 })) as unknown as typeof fetch;
    const client = new KiraClient({ baseUrl: "", token: "sekret", fetch: fetchImpl });
    await expect(client.setSettings("groq", { priority: 5 })).rejects.toMatchObject({
      body: { code: "unauthorized", status: 401 },
    });
  });

  it("calls the tool registry and policy endpoints", async () => {
    const calls: Array<[string, string, string | undefined]> = [];
    const fake = (async (url: string, init?: RequestInit) => {
      calls.push([init?.method ?? "GET", String(url), (init?.headers as Record<string, string>)["X-Kira-Confirm"]]);
      return new Response(JSON.stringify({ tools: [], plugins: [] }), { status: 200, headers: { "content-type": "application/json" } });
    }) as typeof fetch;
    const client = new KiraClient({ baseUrl: "http://kira", token: "t", fetch: fake });
    await client.tools();
    await client.setToolPolicy("write_file", "deny", "confirm-1");
    expect(calls[0][1]).toBe("http://kira/v1/kira/tools");
    expect(calls[1][0]).toBe("PUT");
    expect(calls[1][2]).toBe("confirm-1");
  });

  it("reads checkpoints and decides approvals through the same gate", async () => {
    const seen: Array<{ method: string; url: string; body: string | undefined; confirm: string | undefined }> = [];
    const fake = (async (url: string, init?: RequestInit) => {
      seen.push({
        method: init?.method ?? "GET",
        url: String(url),
        body: init?.body as string | undefined,
        confirm: (init?.headers as Record<string, string>)["X-Kira-Confirm"],
      });
      return new Response(JSON.stringify({ checkpoints: [] }), { status: 200, headers: { "content-type": "application/json" } });
    }) as typeof fetch;
    const client = new KiraClient({ baseUrl: "http://kira", token: "t", fetch: fake });
    await client.checkpoints(5, "s 1");
    await client.decideApproval("a 1", "allow", "c-2");
    expect(seen[0].url).toBe("http://kira/v1/kira/checkpoints?limit=5&session_id=s+1");
    expect(seen[1]).toMatchObject({ method: "POST", url: "http://kira/v1/kira/approvals/a%201", confirm: "c-2" });
    expect(JSON.parse(seen[1].body ?? "{}")).toEqual({ decision: "allow" });
  });

  it("keeps a provider key out of the URL and in the body only", async () => {
    const engine = fakeEngine({ confirm: "s" });
    const client = new KiraClient({ baseUrl: "", token: "sekret", fetch: engine.fetch });
    await client.putKey("groq", "gsk_pasted");
    const call = engine.calls[engine.calls.length - 1];
    expect(call.url).toBe(`${API_PREFIX}/kira/providers/groq/key`);
    expect(call.url).not.toContain("gsk_pasted");
    expect(JSON.parse(call.body ?? "{}")).toEqual({ key: "gsk_pasted" });
    expect(call.headers["X-Kira-Confirm"]).toBeUndefined();
  });

  it("builds the memory query strings and sends the confirm header only on writes", async () => {
    const engine = fakeEngine();
    const client = new KiraClient({ baseUrl: "http://127.0.0.1:8901", token: "t", fetch: engine.fetch });
    await client.memories("pnpm", "preference", true, 10);
    await client.addMemory("I prefer pnpm", "preference", FAKE_CONFIRM);
    await client.putMemorySettings({ capture: "off" }, FAKE_CONFIRM);
    await client.memories(undefined, undefined, false);
    expect(engine.calls[0].url).toBe(`${API_PREFIX}/kira/memory?query=pnpm&kind=preference&pinned=true&limit=10`);
    expect(engine.calls[0].headers["X-Kira-Confirm"]).toBeUndefined();
    expect(engine.calls[1].method).toBe("POST");
    expect(engine.calls[1].headers["X-Kira-Confirm"]).toBe(FAKE_CONFIRM);
    expect(engine.calls[1].body).toBe(JSON.stringify({ text: "I prefer pnpm", kind: "preference" }));
    expect(engine.calls[2].body).toBe(JSON.stringify({ capture: "off" }));
    // pinned=false must reach the wire as false: an `if (pinned)` guard would drop it and read
    // "unpinned only" as "no filter". Absent stays absent (calls[0] proves the other half).
    expect(engine.calls[3].url).toBe(`${API_PREFIX}/kira/memory?pinned=false&limit=50`);
  });

  it("reads the character library, the pick and one profile", async () => {
    const engine = fakeEngine();
    const client = clientWith(engine);
    const list = await client.characters();
    expect(list.active).toBe(ELLEN_ID);
    expect(list.characters.map((row) => row.id)).toEqual([ELLEN_ID, PROPS_ID]);
    expect(engine.calls[0].url).toBe(`${API_PREFIX}/kira/characters`);
    expect(engine.calls[0].headers["X-Kira-Confirm"]).toBeUndefined();

    const profile = await client.character(ELLEN_ID);
    expect(profile.main?.path).toBe("model.pmx");
    expect(profile.main?.textures[0].relative).toBe("tex/颜.tga");
    expect(profile.files.map((file) => file.path)).toContain("profile.json");
  });

  it("imports with the bearer token alone and keeps the importer's refusal", async () => {
    const engine = fakeEngine();
    const client = clientWith(engine);
    const row = await client.importCharacter("D:/MYRAA/models/Neo.zip");
    expect(engine.calls[0].method).toBe("POST");
    // Supplying a file is not destroying one: this is the key-route gate, so no secret is asked for and
    // a screen that forgot to pass one still works.
    expect(engine.calls[0].headers["X-Kira-Confirm"]).toBeUndefined();
    expect(JSON.parse(engine.calls[0].body ?? "{}")).toEqual({ path: "D:/MYRAA/models/Neo.zip" });
    // The row comes back from the library, so a renamed folder cannot make the answer and the next read
    // disagree about the id.
    expect(row.id).toBe("neo-00000000");
    expect((await client.characters()).characters.map((each) => each.id)).toContain("neo-00000000");

    const failing = clientWith(fakeEngine({ importError: {
      code: "too_large", message: "'big.zip' is 400,000,000 bytes, over the 200,000,000 Kira imports",
      status: 413, retryable: false, entry: "D:/big.zip",
    } }));
    await expect(failing.importCharacter("D:/big.zip")).rejects.toMatchObject({
      body: { code: "too_large", status: 413, entry: "D:/big.zip" },
    });
  });

  it("puts a character on stage and takes everyone off with a real null", async () => {
    const engine = fakeEngine();
    const client = clientWith(engine);
    expect((await client.setActiveCharacter(PROPS_ID)).active).toBe(PROPS_ID);
    expect(engine.calls[0].method).toBe("PUT");
    expect(engine.calls[0].url).toBe(`${API_PREFIX}/kira/characters/active`);
    expect(engine.calls[0].body).toBe(JSON.stringify({ id: PROPS_ID }));
    expect(engine.calls[0].headers["X-Kira-Confirm"]).toBeUndefined();
    expect((await client.setActiveCharacter(null)).active).toBeNull();
    // `"id": null` is the whole difference between "take the stage clear" and a body that said nothing.
    expect(engine.calls[1].body).toBe(JSON.stringify({ id: null }));
    expect((await client.characters()).active).toBeNull();
    await expect(client.setActiveCharacter("nobody-00000000")).rejects.toMatchObject({
      body: { code: "character_not_found", status: 404 },
    });
  });

  it("removes a character only with the confirm secret, and forgets its pick with it", async () => {
    const engine = fakeEngine();
    const client = clientWith(engine);
    await expect(client.removeCharacter(ELLEN_ID, "wrong-one")).rejects.toMatchObject({
      body: { code: "unauthorized", status: 401 },
    });
    expect((await client.removeCharacter(ELLEN_ID, FAKE_CONFIRM)).deleted).toBe(ELLEN_ID);
    const list = await client.characters();
    expect(list.characters.map((row) => row.id)).toEqual([PROPS_ID]);
    expect(list.active).toBeNull();
    await expect(client.removeCharacter(PROPS_ID, FAKE_CONFIRM)).resolves.toMatchObject({ deleted: PROPS_ID });
    await expect(client.character(ELLEN_ID)).rejects.toMatchObject({ body: { code: "character_not_found" } });
  });

  it("fetches a character's bytes with the token in the header and never in the URL", async () => {
    const engine = fakeEngine();
    const client = clientWith(engine);
    const url = client.characterFileUrl(ELLEN_ID, "tex/颜.png");
    expect(url).toBe(`${API_PREFIX}/kira/characters/${ELLEN_ID}/file?path=tex%2F%E9%A2%9C.png`);
    expect(url).not.toContain("sekret");

    const buffer = await client.bytes(url);
    expect(buffer).toBeInstanceOf(ArrayBuffer);
    expect(new Uint8Array(buffer)).toEqual(PNG_BYTES);
    const call = engine.calls[0];
    expect(call.method).toBe("GET");
    expect(call.headers.Authorization).toBe("Bearer sekret");
    expect(call.url).not.toContain("sekret");
  });

  it("answers an escaping file path with the engine's own refusal", async () => {
    const engine = fakeEngine();
    const client = clientWith(engine);
    // The route refuses this; the client's job is to carry the refusal instead of swallowing it, because
    // a stage that gets an empty buffer would show a faceless body rather than a bug it can name.
    await expect(client.bytes(client.characterFileUrl(ELLEN_ID, "../profile.json"))).rejects.toMatchObject({
      body: { code: "unsafe_entry", status: 400, entry: "../profile.json" },
    });
    await expect(client.bytes(client.characterFileUrl(ELLEN_ID, "tex/gone.png"))).rejects.toMatchObject({
      body: { code: "character_file_not_found", status: 404 },
    });
    expect(engine.calls[0].headers.Authorization).toBe("Bearer sekret");
  });

  it("names the mesh route as a path, not as a URL with a secret in it", async () => {
    const engine = fakeEngine();
    const client = clientWith(engine);
    const path = client.characterMeshUrl(ELLEN_ID);
    expect(path).toBe(`${API_PREFIX}/kira/characters/${ELLEN_ID}/mesh`);
    expect(path).not.toContain("sekret");

    // The bytes are the engine's own KRM1 blob, so the client's binary read is what the stage decoder eats.
    const buffer = await client.bytes(path);
    expect(new TextDecoder().decode(new Uint8Array(buffer, 0, 4))).toBe(KRM1_MAGIC);
    expect(new Uint8Array(buffer)).toEqual(KRM1_BYTES);
    expect(engine.calls[0]).toMatchObject({ method: "GET", url: path });
    expect(engine.calls[0].headers.Authorization).toBe("Bearer sekret");
  });

  it("carries the mesh route's refusal instead of handing back an empty body", async () => {
    const engine = fakeEngine();
    const client = clientWith(engine);
    // A prop-only archive has no body, and a stage that received zero bytes would draw nothing and say
    // nothing. The code has to survive the trip so the screen can name the character that has no face.
    await expect(client.bytes(client.characterMeshUrl(PROPS_ID))).rejects.toMatchObject({
      body: { code: "character_file_not_found", status: 404, entry: PROPS_ID },
    });
    await expect(client.bytes(client.characterMeshUrl("nope-00000000"))).rejects.toMatchObject({
      body: { code: "character_not_found", status: 404 },
    });
  });
});
