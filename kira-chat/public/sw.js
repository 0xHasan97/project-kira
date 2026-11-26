/*
 * Kira's shell worker.
 *
 * Its whole job is to keep the app openable when the engine is not: the bundle is cached under a name
 * derived from the shell document itself, which changes whenever a rebuild renames its assets. Nothing
 * from the API is ever cached — a stored chat answer, model list or overview would be yesterday's
 * truth served as today's — and nothing outside `/chat/` is touched at all.
 *
 * Written as plain script on purpose: it is served as-is, with no build step and no framework.
 */

const SHELL = "/chat/";
const PREFIX = "kira-shell-";
const VERSIONED = /\.(?:css|js|mjs|png|svg|ico|webmanifest|woff2?)$/;
const OFFLINE = `<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Kira is unreachable</title>
<style>body{margin:0;min-height:100vh;display:grid;place-items:center;background:#0f1113;color:#e9ecef;
font:16px/1.5 system-ui,sans-serif;text-align:center}h1{font-size:1.1rem;font-weight:500}
p{color:#97a1ab;max-width:22rem;margin:.4rem auto}</style></head>
<body><main><h1>Kira is unreachable</h1>
<p>The bundle is here, but the engine on your desktop is not answering. Start it there, then reload.</p>
</main></body></html>`;

let current = null;

function stamp(text) {
  // FNV-1a: a cache name, not a security boundary — but it has to change with the document.
  let hash = 0x811c9dc5;
  for (let i = 0; i < text.length; i += 1) {
    hash ^= text.charCodeAt(i);
    hash = Math.imul(hash, 0x01000193) >>> 0;
  }
  return hash.toString(36);
}

function shellAssets(document, base) {
  const found = new Set();
  const pattern = /(?:src|href)="([^"]+)"/g;
  let match = pattern.exec(document);
  while (match !== null) {
    let url;
    try {
      url = new URL(match[1], base);
    } catch {
      match = pattern.exec(document);
      continue;
    }
    if (url.origin === self.location.origin && url.pathname.startsWith(SHELL) && VERSIONED.test(url.pathname)) {
      found.add(url.pathname);
    }
    match = pattern.exec(document);
  }
  return [...found];
}

async function install() {
  const response = await fetch(SHELL, { cache: "reload" });
  const document = await response.text();
  current = PREFIX + stamp(document);
  const cache = await caches.open(current);
  await cache.put(SHELL, new Response(document, { headers: { "content-type": "text/html; charset=utf-8" } }));
  await Promise.all(
    shellAssets(document, self.location.origin + SHELL).map(async (path) => {
      try {
        const asset = await fetch(path, { cache: "reload" });
        if (asset && asset.ok) await cache.put(path, asset);
      } catch {
        // One missing asset is not a reason to keep the previous shell installed.
      }
    }),
  );
  await self.skipWaiting();
}

async function activate() {
  const names = await caches.keys();
  await Promise.all(
    names
      .filter((name) => name.startsWith(PREFIX) && name !== current)
      .map((name) => caches.delete(name)),
  );
  await self.clients.claim();
}

async function navigation(request) {
  try {
    return await fetch(request);
  } catch {
    const cached = await caches.match(SHELL);
    if (cached) return cached;
    return new Response(OFFLINE, {
      status: 503,
      headers: { "content-type": "text/html; charset=utf-8" },
    });
  }
}

async function asset(path) {
  const cached = await caches.match(path);
  if (cached) return cached;
  const response = await fetch(path);
  // A route chunk is not named by index.html, so the install list cannot know it. Cache it after the
  // first online visit and the same route still opens when the engine is gone; the versioned cache is
  // dropped on the next build, so a rename cannot leave stale code behind.
  if (current && response && response.ok && VERSIONED.test(path)) {
    try {
      const cache = await caches.open(current);
      await cache.put(path, response.clone());
    } catch {
      // Storage quota or a read-only cache: serving the response is still the right answer.
    }
  }
  return response;
}

self.addEventListener("install", (event) => {
  event.waitUntil(install());
});

self.addEventListener("activate", (event) => {
  event.waitUntil(activate());
});

self.addEventListener("fetch", (event) => {
  const request = event.request;
  if (request.method !== "GET") return;
  let url;
  try {
    url = new URL(request.url);
  } catch {
    return;
  }
  if (url.origin !== self.location.origin || !url.pathname.startsWith(SHELL)) return;
  event.respondWith(request.mode === "navigate" ? navigation(request) : asset(url.pathname));
});
