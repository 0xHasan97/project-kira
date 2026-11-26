import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { runInNewContext } from "node:vm";
import { beforeEach, describe, expect, it, vi } from "vitest";

// The worker runs in a service-worker scope, not a DOM, so it is loaded into a hand-built one. The
// point is not to mock the browser: it is that a bad worker locks a phone out of the app until the
// cache is cleared by hand, so every branch it owns gets exercised here first.

class FakeResponse {
  readonly status: number;
  readonly ok: boolean;
  readonly headers: Map<string, string>;
  readonly body: string | null;

  constructor(body: string | null = null, init: { status?: number; headers?: Record<string, string> } = {}) {
    this.body = body;
    this.status = init.status ?? 200;
    this.ok = this.status >= 200 && this.status < 300;
    this.headers = new Map(Object.entries(init.headers ?? {}));
  }

  async text(): Promise<string> {
    return this.body ?? "";
  }

  clone(): FakeResponse {
    return new FakeResponse(this.body, { status: this.status });
  }
}

class FakeCache {
  readonly entries = new Map<string, FakeResponse>();

  async put(key: string, value: FakeResponse): Promise<void> {
    this.entries.set(key, value);
  }

  async match(key: string): Promise<FakeResponse | undefined> {
    return this.entries.get(key);
  }
}

class FakeCaches {
  readonly stores = new Map<string, FakeCache>();

  async open(name: string): Promise<FakeCache> {
    let cache = this.stores.get(name);
    if (!cache) {
      cache = new FakeCache();
      this.stores.set(name, cache);
    }
    return cache;
  }

  async keys(): Promise<string[]> {
    return [...this.stores.keys()];
  }

  async delete(name: string): Promise<boolean> {
    return this.stores.delete(name);
  }

  async match(key: string): Promise<FakeResponse | undefined> {
    for (const cache of this.stores.values()) {
      const hit = await cache.match(key);
      if (hit) return hit;
    }
    return undefined;
  }
}

const SHELL_HTML =
  '<html><head><link rel="stylesheet" href="/chat/assets/index-abc.css"><link rel="manifest" href="/chat/manifest.webmanifest">' +
  "</head><body><script src=\"/chat/assets/index-abc.js\"></script>" +
  '<a href="https://example.invalid/x">x</a><a href="/healthz">h</a></body></html>';

interface Worker {
  skipWaiting: ReturnType<typeof vi.fn>;
  claim: ReturnType<typeof vi.fn>;
}

interface Loaded {
  worker: Worker;
  caches: FakeCaches;
  network: Map<string, string | "down">;
  fetched: string[];
  dispatch(type: "install" | "activate", event?: Record<string, unknown>): Promise<void>;
  fetchEvent(request: { url: string; method?: string; mode?: string }): {
    responded: Promise<FakeResponse> | undefined;
    waited: Promise<unknown> | undefined;
  };
}

function loadWorker(): Loaded {
  const source = readFileSync(resolve(process.cwd(), "public/sw.js"), "utf8");
  const caches = new FakeCaches();
  const fetched: string[] = [];
  const network = new Map<string, string | "down">();
  const listeners = new Map<string, (event: Record<string, unknown>) => void>();
  const worker: Worker = { skipWaiting: vi.fn(async () => {}), claim: vi.fn(async () => {}) };
  const self = {
    location: { origin: "http://kira.test" },
    addEventListener: (type: string, fn: (event: Record<string, unknown>) => void) => {
      listeners.set(type, fn);
    },
    skipWaiting: worker.skipWaiting,
    clients: { claim: worker.claim },
  };
  const fetch = vi.fn(async (input: string) => {
    fetched.push(input);
    const body = network.get(input);
    if (body === "down" || body === undefined) throw new TypeError("network down");
    return new FakeResponse(body, { headers: { "content-type": "text/html" } });
  });
  runInNewContext(source, { self, caches, fetch, Response: FakeResponse, URL });
  return {
    worker,
    caches,
    network,
    fetched,
    async dispatch(type, event = {}) {
      const handler = listeners.get(type);
      if (!handler) throw new Error(`worker registered no ${type} listener`);
      const waited: Promise<unknown>[] = [];
      handler({ waitUntil: (p: Promise<unknown>) => waited.push(p), ...event });
      await Promise.all(waited);
    },
    fetchEvent(request) {
      const handler = listeners.get("fetch");
      if (!handler) throw new Error("worker registered no fetch listener");
      let responded: Promise<FakeResponse> | undefined;
      let waited: Promise<unknown> | undefined;
      handler({
        request: { method: "GET", mode: "no-cors", ...request },
        respondWith: (p: Promise<FakeResponse>) => {
          responded = p;
        },
        waitUntil: (p: Promise<unknown>) => {
          waited = p;
        },
      });
      return { responded, waited };
    },
  };
}

describe("the shell worker", () => {
  let loaded: Loaded;

  beforeEach(async () => {
    loaded = loadWorker();
    loaded.network.set("/chat/", SHELL_HTML);
    loaded.network.set("/chat/assets/index-abc.js", "console.log(1)");
    loaded.network.set("/chat/assets/index-abc.css", "body{}");
    loaded.network.set("/chat/manifest.webmanifest", "{}");
    await loaded.dispatch("install");
  });

  it("caches the shell and every asset the shell names, under one versioned cache", async () => {
    const names = await loaded.caches.keys();
    expect(names).toHaveLength(1);
    expect(names[0]).toMatch(/^kira-shell-/);
    const entries = loaded.caches.stores.get(names[0]!)!.entries;
    expect([...entries.keys()].sort()).toEqual([
      "/chat/",
      "/chat/assets/index-abc.css",
      "/chat/assets/index-abc.js",
      "/chat/manifest.webmanifest",
    ]);
  });

  it("does not try to cache another origin, the API, or a health probe", async () => {
    expect(loaded.fetched).not.toContain("https://example.invalid/x");
    expect(loaded.fetched).not.toContain("/healthz");
    expect(loaded.fetched.some((url) => url.startsWith("/v1/"))).toBe(false);
  });

  it("takes over at once instead of waiting for every tab to close", () => {
    expect(loaded.worker.skipWaiting).toHaveBeenCalled();
  });

  it("serves a navigation from the network while the engine is up", async () => {
    const { responded } = loaded.fetchEvent({ url: "http://kira.test/chat/#/chat", mode: "navigate" });
    expect((await responded!)!.body).toBe(SHELL_HTML);
  });

  it("falls back to the cached shell when the engine is unreachable", async () => {
    loaded.network.set("/chat/", "down");
    const { responded } = loaded.fetchEvent({ url: "http://kira.test/chat/#/chat", mode: "navigate" });
    const response = await responded!;
    expect(response.body).toBe(SHELL_HTML);
  });

  it("says the engine is unreachable rather than showing the browser's own error page", async () => {
    loaded.caches.stores.clear();
    loaded.network.set("/chat/", "down");
    const { responded } = loaded.fetchEvent({ url: "http://kira.test/chat/#/chat", mode: "navigate" });
    const response = await responded!;
    expect(response.body).toContain("Kira is unreachable");
    expect(response.status).toBe(503);
  });

  it("answers an asset from the cache without touching the network", async () => {
    const before = loaded.fetched.length;
    const { responded } = loaded.fetchEvent({ url: "http://kira.test/chat/assets/index-abc.js" });
    const response = await responded!;
    expect(response.body).toBe("console.log(1)");
    expect(loaded.fetched.length).toBe(before);
  });

  it("never intercepts the API — a cached answer would be a cached lie", () => {
    for (const url of ["/v1/kira/overview", "/v1/chat/completions", "/healthz"]) {
      const { responded } = loaded.fetchEvent({ url: `http://kira.test${url}` });
      expect(responded).toBeUndefined();
    }
  });

  it("never intercepts a write", () => {
    const { responded } = loaded.fetchEvent({ url: "http://kira.test/chat/", method: "POST" });
    expect(responded).toBeUndefined();
  });

  it("caches a route chunk on first load so it survives a dead engine", async () => {
    const path = "/chat/assets/avatar-xyz.js";
    loaded.network.set(path, "console.log(\"three\")");
    const first = await loaded.fetchEvent({ url: `http://kira.test${path}` }).responded!;
    expect(first.body).toBe("console.log(\"three\")");
    const names = await loaded.caches.keys();
    expect(loaded.caches.stores.get(names[0]!)!.entries.has(path)).toBe(true);

    loaded.network.set(path, "down");
    const second = await loaded.fetchEvent({ url: `http://kira.test${path}` }).responded!;
    expect(second.body).toBe("console.log(\"three\")");
  });

  it("drops caches from an older build and claims the open pages", async () => {
    await loaded.caches.open("kira-shell-stale");
    await loaded.dispatch("activate");
    expect(await loaded.caches.keys()).toEqual([expect.stringMatching(/^kira-shell-/)]);
    expect(loaded.worker.claim).toHaveBeenCalled();
  });
});
